from __future__ import division

from collections import defaultdict
from django.db import models
from django.db.models import Q, Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
import operator
from axel.articles.models import ArticleCollocation
from axel.articles.utils.concepts_index import update_index
import axel.articles.utils.sw_indexes as sw
from axel.libs.utils import get_context


class CommonCollocationInfo(models.Model):
    """Aggregated collocation statistics model"""
    keywords = models.CharField(max_length=255)
    count = models.IntegerField(default=1)

    # boolean field to mark concept either correct or not,
    # null when unknown
    correct = models.NullBooleanField(blank=True)

    class Meta:
        """Meta info"""
        abstract = True
        ordering = ['-count']

    def __unicode__(self):
        """String representation"""
        return u'{0}'.format(self.keywords)

    @property
    def context(self):
        """Get random context for collocation, used in collocation list view"""
        article =  ArticleCollocation.objects.filter(keywords=self.keywords)[0].article
        return get_context(article.stemmed_text, self.keywords).replace(self.keywords,
            '<span class="error">{0}</span>'.format(self.keywords))

    @property
    def all_contexts(self):
        """Get all contexts for detailed view page"""
        contexts = []
        for text in  ArticleCollocation.objects.filter(keywords=self.keywords).values_list(
            'article__stemmed_text', flat=True):
            contexts.append(get_context(text, self.keywords).replace(self.keywords,
                '<span class="error">{0}</span>'.format(self.keywords)))
        return contexts

    @property
    def partial_match_score(self):
        """
        Sum of the counts of words from a given collocation in the ontology
        (how often a word appears as a part of a concept in the ontology).
        """
        return sw.get_concept_score(self.keywords)

    @property
    def often_score_glob(self):
        """How many articles do contain an ngram"""
        return ArticleCollocation.objects.filter(keywords=self.keywords).count()

    @property
    def often_word_local(self):
        """How many times do words from the ngram occur in other ngrams from the same article"""
        argument_list = []
        for word in self.keywords.split():
            argument_list.append(Q(**{'keywords__regex': r'\b'+word+r'\b'}))
        query = reduce(operator.or_, argument_list)

        article_ids = ArticleCollocation.objects.filter(keywords=self.keywords).values_list(
            'article', flat=True)
        score = ArticleCollocation.objects.filter(article__id__in=article_ids).filter(query)\
                                            .count() - len(article_ids)
        return score

    @property
    def often_consumed(self):
        """How often does an ngram gets consumed by a bigger one"""
        score = SWCollocations.objects.filter(keywords__contains=self.keywords).aggregate(
            count=Sum('count'))['count']
        return score // self.count - 1

    @property
    def occur_distribution(self):
        """
        :rtype: str
        :returns: histogram data in a string form suitable for highcharts
        """
        counts = defaultdict(lambda: 0)
        for count in ArticleCollocation.objects.filter(keywords=self.keywords).values_list('count',
                                flat=True):
            counts[count] += 1

        histogram_data = str(counts.items()).replace('(', '[').replace(')', ']')
        return histogram_data


class Collocations(CommonCollocationInfo):
    """Aggregated collocation statistics model for Computer Science"""


class SWCollocations(CommonCollocationInfo):
    """
    collocation for ScienceWISE
    everything is the same except table name
    """


#@receiver(post_save, sender=Collocations)
def create_collocations(sender, instance, created, **kwargs):
    """
    Add to index on create
    :type instance: Collocations
    """
    if created:
        update_index(instance.id, instance.keywords)

