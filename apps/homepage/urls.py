from django.http import HttpResponsePermanentRedirect
from django.conf.urls.defaults import patterns, include, url
from django.views.decorators.cache import cache_page
from .feed import PlogFeed
import views


urlpatterns = patterns('',
    url(r'^testview$', views.SampleTView.as_view(), name='testview'),
    url(r'^testview2$', views.Sample2TView.as_view(), name='testview2'),
    url(r'^cachedview$', views.CachedSampleView.as_view(), name='cachedview'),
    url(r'^advcachedview$', views.AdvancedCachedView.as_view(), name='advancedcachedview'),
    url(r'^loginrequiredview$', views.LoginRequiredSampleView.as_view(), name='loginrequiredview'),
    url('^$', views.home, name='home'),
    url(r'(.*?)/?rss.xml$', cache_page(PlogFeed(), 60 * 60)),
    url('^search$', views.search, name='search'),
    url('^About$', lambda x: HttpResponsePermanentRedirect('/about/')),
    url('^about$', views.about, name='about'),
    url('^contact$', views.contact, name='contact'),
    url('^oc-(.*)', views.home, name='only_category'),
    url('^zitemap.xml$', views.sitemap, name='sitemap'),
    url('^(.*)', views.blog_post_by_alias, name='blog_post_by_alias'),
)
