"""Url mappings"""
from django.conf.urls import patterns, url
from axel.stats.views import CollocationStats, ConceptIndexStats, FilteredCollectionModelView


urlpatterns = patterns('axel.stats.views',
    url(r'^(?P<model_name>[^/]+)/$', CollocationStats.as_view(), name='stats'),
    url(r'^(?P<model_name>[^/]+)/ci/$', ConceptIndexStats.as_view(), name='ci_stats'),
    url(r'^(?P<model_name>[^/]+)/filter', FilteredCollectionModelView.as_view(), name='colloc_filter')
)
