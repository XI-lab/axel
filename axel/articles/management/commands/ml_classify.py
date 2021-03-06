from __future__ import division
import os
import re
import pickle
from collections import defaultdict
from sklearn import cross_validation
from sklearn.metrics import *
from sklearn.tree import DecisionTreeClassifier
from axel.stats.models import STATS_CLUSTERS_DICT
from axel.stats.scores import compress_pos_tag
from optparse import make_option
import numpy as np
import networkx as nx
from termcolor import colored

from django.core.management.base import BaseCommand, CommandError

from axel.articles.models import CLUSTERS_DICT, Article
from axel.stats.scores.binding_scores import populate_article_dict_ML


RULES_DICT_START = [(u'STOP_WORD', re.compile(r'(NONE|DT|CC|MD|RP|JJR|JJS|\:)')),
                    (u'NUMBER_STARTS', re.compile('^CD')),
                    (u'ADVERB_STARTS', re.compile('^RB')),
                    (u'PREP_START', re.compile(r'(^IN)')),
                    (u'NNS_START', re.compile(r'^NNS')),
                    (u'VB_STARTS', re.compile(r'^VB')),
                    (u'NN_STARTS', re.compile(r'^NN')),
                    (u'JJ_STARTS', re.compile(r'^JJ'))]
RULES_DICT_END = [(u'STOP_WORD', re.compile(r'(NONE|DT|CC|MD|RP|JJR|JJS|\:)')),
                  (u'NUMBER_ENDS', re.compile('CD$')),
                  (u'ADVERB_ENDS', re.compile('RB.?$')),
                  (u'PREP_ENDS', re.compile(r'(IN$)')),
                  (u'NNS_ENDS', re.compile(r'NNS$')),
                  (u'VB_ENDS', re.compile(r'VB.?$')),
                  (u'NN_ENDS', re.compile(r'NN(P|PS)?$')),
                  (u'JJ_ENDS', re.compile(r'JJ.?$'))]


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--cluster', '-c',
                    action='store',
                    dest='cluster',
                    help='cluster id for article type'),
        make_option('--redirects',
                    action='store_true',
                    dest='redirects',
                    default=False,
                    help='whether to use redicrects property from wikipedia or not'),
        make_option('--global-pos-tag',
                    action='store_true',
                    dest='global_pos_tag',
                    default=False,
                    help='whether to use collection-wide pos tags or not'),
        make_option('--uncompressed-pos',
                    action='store_true',
                    dest='uncompressed',
                    default=False,
                    help='whether to use compressed pos tags or not'),
        make_option('--cvnum', '-n',
                    action='store',
                    dest='cv_num',
                    type='int',
                    default=10,
                    help='number of cross validation folds, defaults to 10'),
    )
    help = 'Train SVM classified with a set of features'

    def _total_valid(self, article_dict):
        total_valid = 0
        for values in article_dict.itervalues():
            for value in values.itervalues():
                total_valid += int(value['is_rel'])
        return total_valid

    def handle(self, *args, **options):

        self.cluster_id = cluster_id = options['cluster']
        if not cluster_id:
            raise CommandError("need to specify cluster id")
        cv_num = options['cv_num']
        self.redirects = options['redirects']
        self.global_pos_tag = options['global_pos_tag']
        self.uncompressed = options['uncompressed']
        self.Model = Model = CLUSTERS_DICT[cluster_id]
        #Model.quick_stats()
        self.StatsModel = STATS_CLUSTERS_DICT[cluster_id]
        print 'Building initial binding scores...'
        cached_file = cluster_id + '_article_dict.pcl'
        if os.path.exists(cached_file):
            print 'File found, loading...'
            article_dict = pickle.load(open(cached_file))
        else:
            article_dict = dict(populate_article_dict_ML(Model, cutoff=0))
            pickle.dump(article_dict, open(cached_file, 'wb'))
            print 'File stored, continuing...'
        # Calculate total valid for recall
        total_valid = self._total_valid(article_dict)

        scored_ngrams = []
        print 'Reformatting the results...'
        for article, values in article_dict.iteritems():
            for scores in values.itervalues():
                scored_ngrams.append((article, scores))

        print 'Fitting classifier...'
        self.fit_ml_algo(scored_ngrams, cv_num)

    def fit_ml_algo(self, scored_ngrams, cv_num):
        """
        :param scored_ngrams: list of tuple of type (ngram, score) after initial scoring
        """
        # 1. Calculate scores with float numbers for ngram bindings, as a dict
        collection = []
        collection_labels = []
        component_size_dict = {}
        dblp_component_dict = defaultdict(lambda: set())

        # Calculate max pos tag count and build pos_tag_list
        start_pos_tag_list = []
        end_pos_tag_list = []
        pos_tag_list = []

        # Populate component size dict
        for article in Article.objects.filter(cluster_id=self.cluster_id):
            temp_dict = defaultdict(lambda: 0)
            dbpedia_graph = article.dbpedia_graph(redirects=self.redirects)
            for component in nx.connected_components(dbpedia_graph):
                nodes = [node for node in component if 'Category' not in node]
                stats_ngrams = self.StatsModel.objects.filter(ngram__in=nodes)
                is_dblp_inside = bool([True for ngram in stats_ngrams if 'dblp' in ngram.source])
                # ScienceWISE
                #is_dblp_inside = bool([True for ngram in stats_ngrams if ngram.is_ontological])
                if is_dblp_inside:
                    dblp_component_dict[article.id].update(nodes)
                comp_len = len(nodes)
                for node in component:
                    temp_dict[node] = comp_len
            component_size_dict[article.id] = temp_dict

        if self.global_pos_tag:
            queryset = self.StatsModel.objects.all()
        else:
            queryset = self.Model.objects.all()
        for ngram in queryset:
            max_pos_tag = ngram.max_pos_tag
            pos_tag_start = str(compress_pos_tag(max_pos_tag, RULES_DICT_START))
            pos_tag_end = str(compress_pos_tag(max_pos_tag, RULES_DICT_END))
            if pos_tag_start not in start_pos_tag_list:
                start_pos_tag_list.append(pos_tag_start)
            if pos_tag_end not in end_pos_tag_list:
                end_pos_tag_list.append(pos_tag_end)
            if max_pos_tag not in pos_tag_list:
                pos_tag_list.append(max_pos_tag)
        max_pos_tag_start_len = len(start_pos_tag_list)
        max_pos_tag_end_len = len(end_pos_tag_list)
        max_pos_tag_len = len(pos_tag_list)

        # 2. Iterate through all ngrams, add scores - POS tag (to number), DBLP, DBPEDIA, IS_REL
        for article, score_dict in scored_ngrams:
            ngram = score_dict['ngram']
            collection_ngram = score_dict['collection_ngram']

            # POS TAG enumeration
            if self.global_pos_tag:
                max_pos_tag = collection_ngram.max_pos_tag
                pos_tag_prev = collection_ngram.pos_tag_prev
                pos_tag_after = collection_ngram.pos_tag_after
            else:
                max_pos_tag = ngram.max_pos_tag
                pos_tag_prev = ngram.pos_tag_prev
                pos_tag_after = ngram.pos_tag_after
            pos_tag_start = str(compress_pos_tag(max_pos_tag, RULES_DICT_START))
            pos_tag_end = str(compress_pos_tag(max_pos_tag, RULES_DICT_END))

            pos_tag_extra = set([' '.join(set(tags)) for tags in zip(*ngram.pos_tag)[0]])

            wiki_edges_count = len(article.wikilinks_graph.edges([ngram.ngram]))
            feature = [
                ngram.ngram in article.wiki_text_index,
                ngram.ngram in dblp_component_dict[article.id],
                ngram.ngram.isupper(),
                'dblp' in collection_ngram.source,
                component_size_dict[article.id][ngram.ngram],
                wiki_edges_count,
                #collection_ngram.is_ontological,
                #'dbpedia' in collection_ngram.source,
                'wiki_redirect' in collection_ngram.source,
                bool({'.', ',', ':', ';'}.intersection(zip(*pos_tag_prev)[0])),
                bool({'.', ',', ':', ';'}.intersection(zip(*pos_tag_after)[0])),
                len(ngram.ngram.split()),
                score_dict['participation_count']
            ]

            if not self.uncompressed:
                # extend with compressed part of speech
                extended_feature = [1 if i == start_pos_tag_list.index(pos_tag_start) else 0
                                    for i in range(max_pos_tag_start_len)]
                feature.extend(extended_feature)
                extended_feature = [1 if i == end_pos_tag_list.index(pos_tag_end) else 0
                                    for i in range(max_pos_tag_end_len)]
                feature.extend(extended_feature)
            else:
                # Normal part of speech
                extended_feature = [1 if i == pos_tag_list.index(max_pos_tag) else 0 for i in
                                    range(max_pos_tag_len)]
                feature.extend(extended_feature)

            collection.append(feature)
            collection_labels.append(score_dict['is_rel'])

        feature_names = [
            'is_wiki_text',
            'dblp_inside',
            'is_upper',
            'dblp',
            'comp_size',
            'wikilinks',
            #'ScienceWISE',
            #'is_wiki',
            'is_redirect',
            'punkt_prev',
            'punkt_after',
            'word_len',
            'part_count'
        ]
        if not self.uncompressed:
            feature_names.extend(start_pos_tag_list)
            feature_names.extend(end_pos_tag_list)
        else:
            feature_names.extend(pos_tag_list)

        from sklearn.ensemble import ExtraTreesClassifier
        e_clf = ExtraTreesClassifier(random_state=0, compute_importances=True, n_estimators=100)
        new_collection = e_clf.fit(collection, collection_labels).transform(collection)
        print sorted(zip(list(e_clf.feature_importances_), feature_names), key=lambda x: x[0],
                     reverse=True)[:new_collection.shape[1]]
        print new_collection.shape

        datas = []
        for depth, min_split in ((5, 50), (5, 100), (5, 200), (3, 50), (3, 100), (3, 200)):
            print 'Parameters: depth {0}, split {1}'.format(depth, min_split)
            clf = DecisionTreeClassifier(max_depth=depth, min_samples_split=min_split)
            #for tag, values in pos_tag_counts.iteritems():
            #    print tag, values[1]/values[0]
            # clf.fit(new_collection, collection_labels)
            #import StringIO, pydot
            #from sklearn import tree
            #dot_data = StringIO.StringIO()
            #tree.export_graphviz(clf, out_file=dot_data, feature_names=feature_names)
            #graph = pydot.graph_from_dot_data(dot_data.getvalue())
            #graph.write_pdf("decision.pdf")
            #
            # for i, vector in enumerate(collection):
            #     value = clf.predict(vector)[0]
            #     if value != collection_labels[i] and value:
            #         print scored_ngrams[i][1]['ngram'], vector, value, collection_labels[i]

            # K-fold cross-validation
            print 'Performing cross validation'
            scores = cross_validation.cross_val_score(clf, new_collection, np.array(collection_labels),
                                                      cv=cv_num, score_func=precision_score)
            print("Precision: %0.4f (+/- %0.4f)" % (scores.mean(), scores.std() / 2))
            #print "Precision full scores (for t-test:): ", '\n'.join([str(score) for score in scores])
            scores = cross_validation.cross_val_score(clf, new_collection, np.array(collection_labels),
                                                      cv=cv_num, score_func=recall_score)
            print("Recall: %0.4f (+/- %0.4f)" % (scores.mean(), scores.std() / 2))
            #print "Recall full scores (for t-test:): ", '\n'.join([str(score) for score in scores])
            scores = cross_validation.cross_val_score(clf, new_collection, np.array(collection_labels),
                                                      cv=cv_num, score_func=f1_score)
            # TODO: update recall with full collection labels
            print("F1: %0.4f (+/- %0.4f)" % (scores.mean(), scores.std() / 2))
            #print "F1 full scores (for t-test:): ", '\n'.join([str(score) for score in scores])

            data = {'f1': scores.mean(), 'min_split': min_split, 'depth': depth}

            scores = cross_validation.cross_val_score(clf, new_collection, np.array(collection_labels),
                                                      cv=cv_num)
            print("Accuracy: %0.4f (+/- %0.4f)" % (scores.mean(), scores.std() / 2))
            datas.append(data)

        max_data = {'f1': 0}
        for data in datas:
            if max_data['f1'] < data['f1']:
                max_data = data
        print 'Best result:'
        print max_data
        print
        clf = DecisionTreeClassifier(max_depth=max_data['depth'],
                                     min_samples_split=max_data['min_split'])
        clf.fit(new_collection, collection_labels)
        pickle.dump(clf, open('ngram_clf.pcl', 'w'))
        return max_data

