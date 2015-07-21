import time
import urllib
import logging
import datetime
import re
import functools
import json
import cgi
from cStringIO import StringIO
from collections import defaultdict
from pprint import pprint
from django.contrib.sites.models import Site
from django.core.urlresolvers import reverse
from django.template import Context, loader
from django import http
from django.core.cache import cache
from django.views.decorators.cache import cache_page
from django.db import transaction
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.template import Template
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.core.files import File
from django.contrib.sites.models import RequestSite
from django.views.decorators.cache import cache_control

from postmark_inbound import PostmarkInbound
from .models import BlogItem, BlogItemHits, BlogComment, Category, BlogFile
from .utils import render_comment_text, valid_email, utc_now
from peterbecom.apps.redisutils import get_redis_connection
from peterbecom.apps.rediscounter import redis_increment
from fancy_cache import cache_page
from peterbecom.apps.mincss_response import mincss_response
from . import tasks
from . import utils
from .utils import json_view
from .forms import BlogForm, BlogFileUpload


ONE_HOUR = 60 * 60
ONE_DAY = ONE_HOUR * 24
ONE_WEEK = ONE_DAY * 7
ONE_MONTH = ONE_WEEK * 4
ONE_YEAR = ONE_WEEK * 52


def _blog_post_key_prefixer(request):
    if request.method != 'GET':
        return None
    if request.user.is_authenticated():
        return None
    prefix = utils.make_prefix(request.GET)
    if request.path.endswith('/'):
        oid = request.path.split('/')[-2]
    else:
        oid = request.path.split('/')[-1]

    cache_key = 'latest_comment_add_date:%s' % oid
    latest_date = cache.get(cache_key)
    if latest_date is None:
        try:
            blogitem = (
                BlogItem.objects.filter(oid=oid)
                .values('pk', 'modify_date')[0]
            )
        except IndexError:
            # don't bother, something's really wrong
            return None
        latest_date = blogitem['modify_date']
        blogitem_pk = blogitem['pk']
        for c in (BlogComment.objects
                  .filter(blogitem=blogitem_pk,
                          add_date__gt=latest_date)
                  .values('add_date')
                  .order_by('-add_date')[:1]):
            latest_date = c['add_date']
        latest_date = latest_date.strftime('%f')
        cache.set(cache_key, latest_date, ONE_MONTH)
    prefix += str(latest_date)

    try:
        redis_increment('plog:hits', request)
    except Exception:
        logging.error('Unable to redis.zincrby', exc_info=True)

    # temporary solution because I can't get Google Analytics API to work
    ua = request.META.get('HTTP_USER_AGENT', '')
    if 'bot' not in ua:
        # because not so important exactly how many hits each post gets,
        # just that some posts are more popular than other, therefore
        # we don't need to record this every week.
        if datetime.datetime.utcnow().strftime('%A') == 'Tuesday':
            # so we only do this once a week
            hits, __ = BlogItemHits.objects.get_or_create(oid=oid)
            hits.hits += 1
            hits.save()

    return prefix


@cache_control(public=True, max_age=60 * 60)
@cache_page(
    ONE_WEEK,
    _blog_post_key_prefixer,
    post_process_response=mincss_response
)
def blog_post(request, oid):
    if oid.endswith('/'):
        oid = oid[:-1]
    try:
        post = BlogItem.objects.get(oid=oid)
    except BlogItem.DoesNotExist:
        try:
            post = BlogItem.objects.get(oid__iexact=oid)
        except BlogItem.DoesNotExist:
            if oid == 'add':
                return redirect(reverse('add_post'))
            raise http.Http404(oid)

    ## Reasons for not being here
    if request.method == 'HEAD':
        return http.HttpResponse('')
    elif (request.method == 'GET' and
        (request.GET.get('replypath') or request.GET.get('show-comments'))):
        return http.HttpResponsePermanentRedirect(request.path)

    try:
        redis_increment('plog:misses', request)
    except Exception:
        logging.error('Unable to redis.zincrby', exc_info=True)

    # attach a field called `_absolute_url` which depends on the request
    base_url = 'https://' if request.is_secure() else 'http://'
    base_url += RequestSite(request).domain
    post._absolute_url = base_url + reverse('blog_post', args=(post.oid,))

    data = {
      'post': post,
    }
    try:
        data['previous_post'] = post.get_previous_by_pub_date()
    except BlogItem.DoesNotExist:
        data['previous_post'] = None
    try:
        data['next_post'] = post.get_next_by_pub_date(pub_date__lt=utc_now())
    except BlogItem.DoesNotExist:
        data['next_post'] = None

    comments = (
        BlogComment.objects
        .filter(blogitem=post)
        .order_by('add_date')
    )
    if not request.user.is_staff:
        comments = comments.filter(approved=True)

    comments_truncated = False
    if request.GET.get('comments') != 'all':
        comments = comments[:100]
        if post.count_comments() > 100:
            comments_truncated = 100

    all_comments = defaultdict(list)
    for comment in comments:
        all_comments[comment.parent_id].append(comment)
    data['comments_truncated'] = comments_truncated
    data['all_comments'] = all_comments
    data['related'] = get_related_posts(post)
    data['show_buttons'] = not settings.DEBUG
    data['show_fusion_ad'] = not settings.DEBUG
    data['home_url'] = request.build_absolute_uri('/')
    return render(request, 'plog/post.html', data)


def get_related_posts(post):
    cache_key = 'related_ids:%s' % post.pk
    related_pks = cache.get(cache_key)
    if related_pks is None:
        related_pks = _get_related_pks(post)
        cache.set(cache_key, related_pks, ONE_DAY)

    return (
        BlogItem.objects.filter(pk__in=related_pks)
        .exclude(plogrank__isnull=True)
        .order_by('-plogrank')[:12]
    )

def _get_related_pks(post):
    redis = get_redis_connection(reconnection_wrapped=True)
    count_keywords = redis.get('kwcount')
    if not count_keywords:
        for p in (BlogItem.objects
                  .filter(pub_date__lt=utc_now())):
            for keyword in p.keywords:
                redis.sadd('kw:%s' % keyword, p.pk)
                redis.incr('kwcount')

    _keywords = post.keywords
    _related = defaultdict(int)
    for i, keyword in enumerate(_keywords):
        ids = redis.smembers('kw:%s' % keyword)
        for pk in ids:
            pk = int(pk)
            if pk != post.pk:
                _related[pk] += (len(_keywords) - i)
    items = sorted(((v, k) for (k, v) in _related.items()), reverse=True)
    return [y for (x, y) in items]


def _render_comment(comment):
    return render_to_string('plog/comment.html', {'comment': comment})


@json_view
def prepare_json(request):
    data = {
      'csrf_token': request.META["CSRF_COOKIE"],
      'name': request.COOKIES.get('name',
        request.COOKIES.get('__blogcomment_name')),
      'email': request.COOKIES.get('email',
        request.COOKIES.get('__blogcomment_email')),
    }
    # http://stackoverflow.com/a/7503362/205832
    request.META['CSRF_COOKIE_USED'] = True
    return data


@require_POST
@json_view
def preview_json(request):
    comment = request.POST.get('comment', u'').strip()
    name = request.POST.get('name', u'').strip()
    email = request.POST.get('email', u'').strip()
    if not comment:
        return {}

    html = render_comment_text(comment.strip())
    comment = {
      'oid': 'preview-oid',
      'name': name,
      'email': email,
      'rendered': html,
      'add_date': utc_now(),
      }
    html = render_to_string('plog/comment.html', {
      'comment': comment,
      'preview': True,
    })
    return {'html': html}


# Not using @json_view so I can use response.set_cookie first
@require_POST
@transaction.atomic
def submit_json(request, oid):
    post = get_object_or_404(BlogItem, oid=oid)
    if post.disallow_comments:
        return http.HttpResponseBadRequest("No comments please")
    comment = request.POST['comment'].strip()
    if not comment:
        return http.HttpResponseBadRequest("Missing comment")
    name = request.POST.get('name', u'').strip()
    email = request.POST.get('email', u'').strip()
    parent = request.POST.get('parent')
    if parent:
        parent = get_object_or_404(BlogComment, oid=parent)
    else:
        parent = None  # in case it was u''

    search = {'comment': comment}
    if name:
        search['name'] = name
    if email:
        search['email'] = email
    if parent:
        search['parent'] = parent

    for blog_comment in BlogComment.objects.filter(**search):
        break
    else:
        blog_comment = BlogComment.objects.create(
          oid=BlogComment.next_oid(),
          blogitem=post,
          parent=parent,
          approved=False,
          comment=comment,
          name=name,
          email=email,
          ip_address=request.META.get('REMOTE_ADDR'),
          user_agent=request.META.get('HTTP_USER_AGENT')
        )

        if request.user.is_authenticated():
            _approve_comment(blog_comment)
            assert blog_comment.approved
        else:
            tos = [x[1] for x in settings.ADMINS]
            from_ = ['%s <%s>' % x for x in settings.ADMINS][0]
            body = _get_comment_body(post, blog_comment)
            send_mail("Peterbe.com: New comment on '%s'" % post.title,
                      body, from_, tos)

    html = render_to_string('plog/comment.html', {
      'comment': blog_comment,
      'preview': True,
    })
    _comments = BlogComment.objects.filter(approved=True, blogitem=post)
    comment_count = _comments.count() + 1
    data = {
        'html': html,
        'parent': parent and parent.oid or None,
        'comment_count': comment_count,
    }

    response = http.JsonResponse(data)
    if name:
        if isinstance(name, unicode):
            name = name.encode('utf-8')
        response.set_cookie('name', name)
    if email:
        response.set_cookie('email', email)
    return response


@login_required
def approve_comment(request, oid, comment_oid):
    blogitem = get_object_or_404(BlogItem, oid=oid)
    blogcomment = get_object_or_404(BlogComment, oid=comment_oid)
    if blogcomment.blogitem != blogitem:
        raise http.Http404("bad rel")

    _approve_comment(blogcomment)

    if request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        return http.HttpResponse('OK')
    else:
        url = blogitem.get_absolute_url()
        if blogcomment.blogitem:
            url += '#%s' % blogcomment.oid
        return http.HttpResponse('''<html>Comment approved<br>
        <a href="%s">%s</a>
        </html>
        ''' % (url, blogitem.title))

def _approve_comment(blogcomment):
    blogcomment.approved = True
    blogcomment.save()

    if (blogcomment.parent and blogcomment.parent.email
        and valid_email(blogcomment.parent.email)
        and blogcomment.email != blogcomment.parent.email):
        parent = blogcomment.parent
        tos = [parent.email]
        from_ = 'Peterbe.com <noreply+%s@peterbe.com>' % blogcomment.oid
        body = _get_comment_reply_body(blogcomment.blogitem, blogcomment, parent)
        subject = 'Peterbe.com: Reply to your comment'
        send_mail(subject, body, from_, tos)


def _get_comment_body(blogitem, blogcomment):
    base_url = 'http://%s' % Site.objects.get(pk=settings.SITE_ID).domain
    approve_url = reverse('approve_comment', args=[blogitem.oid, blogcomment.oid])
    delete_url = reverse('delete_comment', args=[blogitem.oid, blogcomment.oid])
    message = template = loader.get_template('plog/comment_body.txt')
    context = {
      'post': blogitem,
      'comment': blogcomment,
      'approve_url': approve_url,
      'delete_url': delete_url,
      'base_url': base_url,
    }
    return template.render(Context(context)).strip()


def _get_comment_reply_body(blogitem, blogcomment, parent):
    base_url = 'http://%s' % Site.objects.get(pk=settings.SITE_ID).domain
    approve_url = reverse('approve_comment', args=[blogitem.oid, blogcomment.oid])
    delete_url = reverse('delete_comment', args=[blogitem.oid, blogcomment.oid])
    message = template = loader.get_template('plog/comment_reply_body.txt')
    context = {
      'post': blogitem,
      'comment': blogcomment,
      'parent': parent,
      'base_url': base_url,
    }
    return template.render(Context(context)).strip()


@login_required
def delete_comment(request, oid, comment_oid):
    user = request.user
    assert user.is_staff or user.is_superuser
    blogitem = get_object_or_404(BlogItem, oid=oid)
    blogcomment = get_object_or_404(BlogComment, oid=comment_oid)
    if blogcomment.blogitem != blogitem:
        raise http.Http404("bad rel")

    blogcomment.delete()

    return http.HttpResponse("Comment deleted")


def _plog_index_key_prefixer(request):
    if request.method != 'GET':
        return None
    if request.user.is_authenticated():
        return None
    prefix = utils.make_prefix(request.GET)
    cache_key = 'latest_post_modify_date'
    latest_date = cache.get(cache_key)
    if latest_date is None:
        latest, = (BlogItem.objects
                   .order_by('-modify_date')
                   .values('modify_date')[:1])
        latest_date = latest['modify_date'].strftime('%f')
        cache.set(cache_key, latest_date, ONE_DAY)
    prefix += str(latest_date)
    return prefix


@cache_control(public=True, max_age=60 * 60)
@cache_page(
    ONE_DAY,
    _plog_index_key_prefixer,
    post_process_response=mincss_response
)
def plog_index(request):
    groups = defaultdict(list)
    now = utc_now()
    group_dates = []

    _categories = dict((x.pk, x.name) for x in
                        Category.objects.all())
    blogitem_categories = defaultdict(list)
    for cat_item in BlogItem.categories.through.objects.all():
        blogitem_categories[cat_item.blogitem_id].append(
          _categories[cat_item.category_id]
        )
    for item in (BlogItem.objects
                 .filter(pub_date__lt=now)
                 .values('pub_date', 'oid', 'title', 'pk')
                 .order_by('-pub_date')):
        group = item['pub_date'].strftime('%Y.%m')
        item['categories'] = blogitem_categories[item['pk']]
        groups[group].append(item)
        tup = (group, item['pub_date'].strftime('%B, %Y'))
        if tup not in group_dates:
            group_dates.append(tup)

    data = {
      'groups': groups,
      'group_dates': group_dates,
    }
    return render(request, 'plog/index.html', data)


def _new_comment_key_prefixer(request):
    if request.method != 'GET':
        return None
    if request.user.is_authenticated():
        return None
    prefix = utils.make_prefix(request.GET)
    cache_key = 'latest_comment_add_date'
    latest_date = cache.get(cache_key)
    if latest_date is None:
        latest, = (BlogItem.objects
                   .order_by('-modify_date')
                   .values('modify_date')[:1])
        latest_date = latest['modify_date'].strftime('%f')
        cache.set(cache_key, latest_date, 60 * 60)
    prefix += str(latest_date)
    return prefix


@cache_page(ONE_HOUR, _new_comment_key_prefixer)
def new_comments(request):
    data = {}
    comments = BlogComment.objects.all()
    if not request.user.is_authenticated():
        comments = comments.filter(approved=True)

    # legacy stuff that can be removed in march 2012
    for c in comments.filter(blogitem__isnull=True):
        if not c.parent:
            c.delete()
        else:
            c.correct_blogitem_parent()

    data['comments'] = (comments
                        .order_by('-add_date')
                        .select_related('blogitem')[:50])
    return render(request, 'plog/new-comments.html', data)


@login_required
@transaction.atomic
def add_post(request):
    data = {}
    user = request.user
    assert user.is_staff or user.is_superuser
    if request.method == 'POST':
        form = BlogForm(data=request.POST)
        if form.is_valid():
            keywords = [x.strip() for x
                        in form.cleaned_data['keywords'].splitlines()
                        if x.strip()]
            blogitem = BlogItem.objects.create(
              oid=form.cleaned_data['oid'],
              title=form.cleaned_data['title'],
              text=form.cleaned_data['text'],
              summary=form.cleaned_data['summary'],
              display_format=form.cleaned_data['display_format'],
              codesyntax=form.cleaned_data['codesyntax'],
              url=form.cleaned_data['url'],
              pub_date=form.cleaned_data['pub_date'],
              keywords=keywords,
            )
            for category in form.cleaned_data['categories']:
                blogitem.categories.add(category)
            blogitem.save()

            redis = get_redis_connection(reconnection_wrapped=True)
            for keyword in keywords:
                if not redis.smembers('kw:%s' % keyword):
                    redis.sadd('kw:%s' % keyword, blogitem.pk)
                    redis.incr('kwcount')

            url = reverse('edit_post', args=[blogitem.oid])
            return redirect(url)
    else:
        initial = {
          'pub_date': utc_now() + datetime.timedelta(seconds=60 * 60),
          'display_format': 'markdown',
        }
        form = BlogForm(initial=initial)
    data['form'] = form
    data['page_title'] = 'Add post'
    data['blogitem'] = None
    return render(request, 'plog/edit.html', data)


@login_required
@transaction.atomic
def edit_post(request, oid):
    blogitem = get_object_or_404(BlogItem, oid=oid)
    data = {}
    user = request.user
    assert user.is_staff or user.is_superuser
    if request.method == 'POST':
        form = BlogForm(instance=blogitem, data=request.POST)
        if form.is_valid():
            blogitem.oid = form.cleaned_data['oid']
            blogitem.title = form.cleaned_data['title']
            blogitem.text = form.cleaned_data['text']
            blogitem.text_rendered = ''
            blogitem.summary = form.cleaned_data['summary']
            blogitem.display_format = form.cleaned_data['display_format']
            blogitem.codesyntax = form.cleaned_data['codesyntax']
            blogitem.pub_date = form.cleaned_data['pub_date']
            keywords = [x.strip() for x
                        in form.cleaned_data['keywords'].splitlines()
                        if x.strip()]
            blogitem.keywords = keywords
            blogitem.categories.clear()
            for category in form.cleaned_data['categories']:
                blogitem.categories.add(category)
            blogitem.save()

            redis = get_redis_connection(reconnection_wrapped=True)
            for keyword in keywords:
                if not redis.smembers('kw:%s' % keyword):
                    redis.sadd('kw:%s' % keyword, blogitem.pk)
                    redis.incr('kwcount')

            url = reverse('edit_post', args=[blogitem.oid])
            return redirect(url)

    else:
        form = BlogForm(instance=blogitem)
    data['form'] = form
    data['page_title'] = 'Edit post'
    data['blogitem'] = blogitem
    data['INBOUND_EMAIL_ADDRESS'] = settings.INBOUND_EMAIL_ADDRESS
    return render(request, 'plog/edit.html', data)


@csrf_exempt
@login_required
@require_POST
def preview_post(request):
    from django.template import Context
    from django.template.loader import get_template

    post_data = dict()
    for key, value in request.POST.items():
        if value:
            post_data[key] = value
    post_data['categories'] = request.POST.getlist('categories[]')
    post_data['oid'] = 'doesntmatter'
    post_data['keywords'] = []
    form = BlogForm(data=post_data)
    if not form.is_valid():
        return http.HttpResponse(str(form.errors))

    class MockPost(object):

        def count_comments(self):
            return 0

        def has_carousel_tag(self):
            return False

        @property
        def rendered(self):
            if self.display_format == 'structuredtext':
                return utils.stx_to_html(self.text, self.codesyntax)
            else:
                return utils.markdown_to_html(self.text, self.codesyntax)

    post = MockPost()
    post.title = form.cleaned_data['title']
    post.text = form.cleaned_data['text']
    post.display_format = form.cleaned_data['display_format']
    post.codesyntax = form.cleaned_data['codesyntax']
    post.url = form.cleaned_data['url']
    post.pub_date = form.cleaned_data['pub_date']
    post.categories = Category.objects.filter(pk__in=form.cleaned_data['categories'])
    template = get_template("plog/_post.html")
    context = Context({'post': post})
    return http.HttpResponse(template.render(context))


@login_required
@transaction.atomic
def add_file(request):
    data = {}
    user = request.user
    assert user.is_staff or user.is_superuser
    if request.method == 'POST':
        form = BlogFileUpload(request.POST, request.FILES)
        if form.is_valid():
            instance = form.save()
            url = reverse('edit_post', args=[instance.blogitem.oid])
            return redirect(url)
    else:
        initial = {}
        if request.REQUEST.get('oid'):
            blogitem = get_object_or_404(BlogItem, oid=request.REQUEST.get('oid'))
            initial['blogitem'] = blogitem
        form = BlogFileUpload(initial=initial)
    data['form'] = form
    return render(request, 'plog/add_file.html', data)


@login_required
def post_thumbnails(request, oid):
    blogitem = get_object_or_404(BlogItem, oid=oid)
    blogfiles = (BlogFile.objects
                         .filter(blogitem=blogitem)
                         .order_by('-add_date'))
    from sorl.thumbnail import get_thumbnail
    html = ''
    # XXX very rough and hacky code
    for blogfile in blogfiles:
        full_im = get_thumbnail(
            blogfile.file,
            '1000x1000',
            #crop='center',
            upscale=False,
            quality=100
        )
        full_url = settings.STATIC_URL + full_im.url

        for geometry in ('120x120', '230x230'):
            im = get_thumbnail(
                blogfile.file,
                geometry,
                #crop='center',
                quality=81
            )

            url_ = settings.STATIC_URL + im.url
            tag = (
                '<img src="%s" alt="%s" width="%s" height="%s">'
                % (url_,
                   getattr(blogfile, 'title', blogitem.title),
                   im.width,
                   im.height
                )
            )
            html += tag
            delete_url = reverse('delete_post_thumbnail') + '?id=%s' % blogfile.pk
            whole_tag = (
                '<a href="%s" title="%s">%s</a>'
                % (full_url,
                   getattr(blogfile, 'title', blogitem.title),
                   tag.replace('src="', 'class="floatright" src="')
                )
            )
            html += ' (%s, %s)' % (im.width, im.height)
            html += ' <a href="%s">delete</a>' % delete_url
            html += '<br><input value="%s" title="Full size 1000x1000">' % full_url
            html += '<br><input value="%s">' % cgi.escape(tag).replace('"', '&quot;')
            html += '<br><input value="%s">' % cgi.escape(whole_tag).replace('"', '&quot;')
            html += '<br>'

    return http.HttpResponse(html)


@login_required
def delete_post_thumbnail(request):
    pk = request.REQUEST.get('id')
    assert pk
    blogfile = get_object_or_404(BlogFile, pk=pk)
    blogitem = blogfile.blogitem
    edit_post_url = reverse('edit_post', args=[blogitem.oid])
    blogfile.delete()
    return http.HttpResponse(
       'Blogfile deleted.<br><a href="%s">Edit \'%s\'</a>' %
       (edit_post_url, blogitem.title)
    )


@cache_page(ONE_DAY)
def calendar(request):
    data = {'page_title': 'Archive calendar'}
    return render(request, 'plog/calendar.html', data)


@json_view
def calendar_data(request):
    start = request.GET['start']
    end = request.GET['end']
    start = datetime.datetime.fromtimestamp(float(start))
    end = datetime.datetime.fromtimestamp(float(end))
    if not request.user.is_authenticated():
        end = min(end, datetime.datetime.utcnow())
        if end < start:
            return []
    assert start < end
    assert (end - start).days < 50
    start = utils.utcify(start)
    end = utils.utcify(end)

    qs = BlogItem.objects.filter(pub_date__gte=start, pub_date__lt=end)
    items = []
    for each in qs:
        item = {
          'title': each.title,
          'start': time.mktime(each.pub_date.timetuple()),
          'url': reverse('blog_post', args=[each.oid]),
          'className': 'post',
        }
        items.append(item)

    return items


@require_POST
@csrf_exempt
def inbound_email(request):
    raw_data = request.raw_post_data
    #filename = '/tmp/raw_data.%s.json' % (time.time(),)
    #with open(filename, 'w') as f:
    #    f.write(raw_data)

    data = json.loads(raw_data)
    inbound = PostmarkInbound(json=raw_data)
    if not inbound.has_attachments():
        m = "ERROR! No attachments"
        logging.debug(m)
        return http.HttpResponse(m)
    try:
        hashkey, subject = inbound.subject().split(':', 1)
    except ValueError:
        m = "ERROR! No hashkey defined in subject line"
        logging.debug(m)
        return http.HttpResponse(m)
    try:
        post = BlogItem.get_by_inbound_hashkey(hashkey)
    except BlogItem.DoesNotExist:
        m = "ERROR! Unrecognized hashkey"
        logging.debug(m)
        return http.HttpResponse(m)

    attachments = inbound.attachments()
    attachment = attachments[0]
    blogfile = BlogFile(
      blogitem=post,
      title=subject.strip(),
    )
    content = StringIO(attachment.read())
    f = File(content, name=attachment.name())
    f.size = attachment.content_length()
    blogfile.file.save(attachment.name(),
                       f,
                       save=True)
    blogfile.save()
    return http.HttpResponse("OK\n")


def plog_hits(request):
    context = {}
    limit = int(request.GET.get('limit', 100))
    _category_names = dict(
        (x['id'], x['name'])
        for x in Category.objects.all().values('id', 'name')
    )
    categories = defaultdict(list)
    qs = (
        BlogItem.categories.through.objects.all()
        .values('blogitem_id', 'category_id')
    )
    for each in qs:
        categories[each['blogitem_id']].append(
            _category_names[each['category_id']]
        )
    context['categories'] = categories
    query = BlogItem.objects.raw("""
        select
            b.id, b.oid, b.title, h.hits, b.pub_date,
            extract(days from (now() - b.pub_date))::int AS age,
            h.hits / extract(days from (now() - b.pub_date)) AS score
        from plog_blogitem b
        inner join plog_blogitemhits h using (oid)
        where (now() - b.pub_date) > interval '1 day'
        order by score desc
        limit {limit};
    """.format(limit=limit))
    context['all_hits'] = query

    category_scores = defaultdict(list)
    for item in query:
        for cat in categories[item.id]:
            category_scores[cat].append(item.score)

    def median(seq):
        seq.sort()
        return seq[len(seq) / 2]

    summed_category_scores = []
    for name, scores in category_scores.items():
        count = len(scores)
        summed_category_scores.append({
            'name': name,
            'count': count,
            'sum': sum(scores),
            'avg': sum(scores) / count,
            'med': median(scores),
        })
    context['summed_category_scores'] = summed_category_scores
    return render(request, 'plog/plog_hits.html', context)
