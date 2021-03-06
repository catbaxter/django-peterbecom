import datetime
from urllib.parse import urlparse

from django.contrib.auth.models import User
from django.urls import reverse
from django.conf import settings
from django.utils import timezone
from django.test import TestCase
from django.core import mail

from peterbecom.plog.models import BlogItem, BlogComment, Category, BlogItemHit
from peterbecom.plog.utils import utc_now


class PlogTestCase(TestCase):
    def setUp(self):
        super(PlogTestCase, self).setUp()

    def _login(self):
        admin = User.objects.create(username="admin", is_staff=True)
        admin.set_password("secret")
        admin.save()
        assert self.client.login(username="admin", password="secret")
        return admin

    def test_blog_post_caching(self):
        blog = BlogItem.objects.create(
            oid="some-longish-test-post",
            title="TITLEX",
            text="BLABLABLA",
            display_format="structuredtext",
            pub_date=utc_now() - datetime.timedelta(seconds=10),
        )
        url = reverse("blog_post", args=[blog.oid])

        import peterbecom.plog.views

        old_render = peterbecom.plog.views.render
        from django.shortcuts import render as django_render

        render_counts = []

        def mocked_render(*a, **k):
            render_counts.append(1)
            return django_render(*a, **k)

        peterbecom.plog.views.render = mocked_render
        try:
            response = self.client.get(url)
            content = response.content.decode("utf-8")
            assert blog.title in content
            assert "0 comments" in content
            response = self.client.get(url)
            content = response.content.decode("utf-8")
            assert "0 comments" in content

            BlogComment.objects.create(
                comment="textext",
                blogitem=blog,
                approved=True,
                add_date=utc_now() + datetime.timedelta(seconds=1),
            )
            response = self.client.get(url)
            content = response.content.decode("utf-8")
            assert "1 comment" in content
        finally:
            peterbecom.plog.views.render = old_render

        # XXX HACK!
        # Need to upgrade fancy-cache thing so that it doesn't
        # call the key prefixer for both the request and the response.
        # assert len(render_counts) == 2, render_counts

    def test_preview_post(self):
        cat = Category.objects.create(name="MyCategory")
        self._login()
        url = reverse("plog_preview_post")
        data = {
            "title": "Some <script> TITLE",
            "text": "This is\n*great*\nin `verbatim`",
            "display_format": "markdown",
            "pub_date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "categories[]": str(cat.pk),
        }
        response = self.client.post(url, data)
        assert response.status_code == 200
        # assert 'Some &lt;script&gt; TITLE' in response.content
        content = response.content.decode("utf-8")
        assert "This is<br" in content
        assert "<em>great</em>" in content
        assert "<code>verbatim</code>" in content

        data[
            "text"
        ] = """This is

```python
def foo():
    return None
```

code"""

        response = self.client.post(url, data)
        content = response.content.decode("utf-8")
        assert '<div class="highlight">' in content
        assert '<span class="k">def</span>' in content

    def test_old_redirects(self):
        blog = BlogItem.objects.create(
            oid="myoid",
            title="TITLEX",
            text="""
            ttest test
            """,
            display_format="structuredtext",
            pub_date=utc_now() - datetime.timedelta(seconds=10),
        )
        url = reverse("blog_post", args=[blog.oid])

        response = self.client.get(url)
        assert response.status_code == 200

        response = self.client.get(url, {"replypath": "foo"})
        assert response.status_code == 301
        assert urlparse(response["location"]).path == url
        assert not urlparse(response["location"]).query

    def test_blog_post_ping(self):
        blog = BlogItem.objects.create(
            oid="myoid",
            title="TITLEX",
            text="""
            ttest test
            """,
            display_format="structuredtext",
            pub_date=utc_now() - datetime.timedelta(seconds=10),
        )
        url = reverse("blog_post_ping", args=[blog.oid])
        response = self.client.get(url)
        assert response.status_code == 405
        response = self.client.put(url)
        assert response.status_code == 200
        assert response.json()["ok"]

        hit, = BlogItemHit.objects.all()
        assert hit.blogitem == blog

    def test_blog_post_with_newline_request_path(self):
        url = reverse("blog_post", args=["myoid"])
        response = self.client.get(url + "\n")
        assert response.status_code == 301
        assert urlparse(response["location"]).path == url

        response = self.client.get(url + "\nsomething")
        assert response.status_code == 301
        assert urlparse(response["location"]).path == url

    def test_submit_comment(self):
        blog = BlogItem.objects.create(
            oid="myoid",
            title="TITLEX",
            text="""
            ttest test
            """,
            display_format="markdown",
            pub_date=timezone.now() - datetime.timedelta(seconds=10),
        )
        url = reverse("submit", args=[blog.oid])
        response = self.client.get(url)
        assert response.status_code == 405

        response = self.client.post(url, {})
        assert response.status_code == 400

        data = {
            "comment": "Hey there!\n\n",
            "name": " Peter ",
            "email": "test@peterbe.com ",
        }
        response = self.client.post(url, data)
        assert response.status_code == 200
        sent = mail.outbox[-1]
        assert sent.to[0] == settings.MANAGERS[0][1]

        blog_comment = BlogComment.objects.get(
            blogitem=blog,
            parent=None,
            approved=False,
            comment=data["comment"].strip(),
            name=data["name"].strip(),
            email=data["email"].strip(),
        )
        assert blog_comment.comment_rendered
        response = self.client.post(url, data)
        assert response.status_code == 200
        assert len(mail.outbox) == 1
        assert BlogComment.objects.all().count() == 1

    def test_submit_reply_comment(self):
        blog = BlogItem.objects.create(
            oid="myoid",
            title="TITLEX",
            text="""
            ttest test
            """,
            display_format="markdown",
            pub_date=timezone.now() - datetime.timedelta(seconds=10),
        )
        blog_comment = BlogComment.objects.create(
            oid=BlogComment.next_oid(),
            blogitem=blog,
            approved=True,
            comment="Sure!",
            name="Greger",
            email="greger@example.com",
        )
        assert blog_comment.oid
        url = reverse("submit", args=[blog.oid])

        response = self.client.post(
            url,
            {
                "parent": blog_comment.oid,
                "comment": "Hey there!\n\n",
                "name": " Peter ",
                "email": "test@peterbe.com ",
            },
        )
        assert response.status_code == 200
        sent = mail.outbox[-1]
        assert sent.to[0] == settings.MANAGERS[0][1]

        assert BlogComment.objects.filter(parent=blog_comment)

    def test_spam_prevention(self):
        settings.SPAM_URL_PATTERNS = ["http*://www.spam.com"]

        blog = BlogItem.objects.create(
            oid="myoid",
            title="TITLEX",
            text="""
            ttest test
            """,
            display_format="markdown",
            pub_date=timezone.now() - datetime.timedelta(seconds=10),
        )
        url = reverse("submit", args=[blog.oid])

        data = {"comment": "This is www.spam.com isn't it", "name": "", "email": ""}

        response = self.client.post(url, data)
        assert response.status_code == 400
