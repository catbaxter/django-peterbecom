from django.conf.urls.defaults import patterns, include, url


from . import views
urlpatterns = patterns('',
    url('^$', views.index, name='index'),
    url('^view1$', views.view1, name='view1'),
    url('^view2$', views.view2, name='view2'),
    url('^view2-table$', views.view2_table, name='view2_table'),
    url('^view3$', views.view3, name='view3'),
    url('^view3-data$', views.view3_data, name='view3_data'),
)