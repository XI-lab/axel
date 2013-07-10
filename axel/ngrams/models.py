from __future__ import division
from collections import defaultdict
import nltk
import re
import itertools
from nltk.metrics.association import BigramAssocMeasures as bigram_assoc

from django.db import models
import MicrosoftNgram

from axel.libs import nlp

ms_ngram_service = MicrosoftNgram.LookupService('37a80cca-9fee-487f-9bbd-c45f252534df',
                                                'bing-body/apr10/5')


class Ngram(models.Model):
    """Describes ngram"""
    value = models.TextField()
    log_prob = models.FloatField()
    pos_seq = models.CharField(max_length=255)

    PUNKT_RE = re.compile(r'[`~/%\*\+\[\]\.?!,":;()\'|]+')

    class Meta:
        """Meta info"""
        ordering = ['value']

    def __unicode__(self):
        """String representation"""
        return self.value

    @classmethod
    def create_from_sentence(cls, sent):
        """
        :param text: text to parse, can be more than on sentence.
        """
        existing = set(Ngram.objects.values_list("value", flat=True))
        sentence = re.sub(r'[!.?]', '. ', sent)
        sentence = sentence.strip()
        if not sentence:
            return
        pos_tag_sents = nltk.pos_tag(nltk.regexp_tokenize(sentence, nlp.Stemmer.TOKENIZE_REGEXP))
        # join ngrams with tags
        pos_tag_sents = ['/'.join(x) for x in pos_tag_sents]
        pos_tag_sents = [list(x[1]) for x in itertools.groupby(pos_tag_sents,
                                            lambda x: cls.PUNKT_RE.match(x)) if not x[0]]
        for pos_tag_sent in pos_tag_sents:
            for i in range(1, 6):
                for pos_ngram in nltk.ngrams(pos_tag_sent, i):
                    ngram, pos_seq = zip(*[x.rsplit('/', 1) for x in pos_ngram])
                    ngram = u' '.join(ngram)
                    pos_seq = u' '.join(pos_seq)
                    if ngram not in existing:
                        log_prob = ms_ngram_service.GetJointProbability(ngram.encode('utf-8'))
                        print ngram, log_prob, pos_seq
                        Ngram.objects.create(value=ngram, log_prob=log_prob, pos_seq=pos_seq)
                        existing.add(ngram)


class Sentence(models.Model):
    sentence1 = models.TextField()
    sentence2 = models.TextField()

    def __unicode__(self):
        """String representation"""
        return self.sentence1

    @classmethod
    def _tokenize(cls, sentence):
        """Tokenize sentence and return lists of tokens."""
        sentence = re.sub(r'[!.?]', '. ', sentence)
        tokens = nltk.regexp_tokenize(sentence, nlp.Stemmer.TOKENIZE_REGEXP)
        tokens = [list(x[1]) for x in itertools.groupby(tokens, lambda y: Ngram.PUNKT_RE.match(y))
                  if not x[0]]
        return tokens

    @classmethod
    def _tokenize_positions(cls, sentence):
        """
        Tokenize sentence and return lists of tokens with corresponding positions in the sentence.
        """
        sentence = re.sub(r'[!.?]', '. ', sentence)
        positional_tokens = []
        for match in re.finditer(nlp.Stemmer.TOKENIZE_REGEXP, sentence):
            positional_tokens.append((match.group(), match.start(), match.end()))

        tokens = [list(x[1]) for x in
                  itertools.groupby(positional_tokens, lambda y: Ngram.PUNKT_RE.match(y[0]))
                  if not x[0]]
        return tokens

    @classmethod
    def get_sentence_prob(cls, sentence):
        """Return averaged probability scores for the sentence using 2- to 5-ngram splits"""
        scores = defaultdict(list)
        for tokens in Sentence._tokenize(sentence):
            for i in range(1, 6):
                for ngram in nltk.ngrams(tokens, i):
                    log_prob = Ngram.objects.get(value=' '.join(ngram)).log_prob
                    scores[i].append(10**log_prob)
        return dict([(i, sum(probs)/len(probs) if probs else 0) for i, probs in
                     sorted(scores.items(), key=lambda x: x[0])])

    @classmethod
    def get_positional_metrics_data(cls, function='prob_sorted_ngrams'):
        """Gets positional data to calculate metrics"""
        positional_data = {}
        for sentence in cls.objects.all():
            pos_sent_data = getattr(sentence, function)()
            if pos_sent_data:
                positional_data[sentence.id] = [pos_sent_data]
        return positional_data

    def prob_sorted_ngrams(self):
        """Returns diverging ngrams in the sentence"""
        # TODO: Exclude 100 most frequent words?

        # sentence can contain more than one sequence of tokens
        position_data = defaultdict(list)
        for tokens in Sentence._tokenize_positions(self.sentence1):
            for i in range(1, 6):
                for ngram_pos in nltk.ngrams(tokens, i):
                    ngram = ' '.join(zip(*ngram_pos)[0])
                    log_prob = Ngram.objects.get(value=ngram).log_prob
                    # report ngram with position
                    position_data[i].append((ngram_pos, log_prob))

        position_data = dict([(i, sorted(ngrams, key=lambda x: x[1]))
                              for i, ngrams in position_data.items()])

        try:
            lowest_bigram = position_data[2][0][0]
        except:
            return
        return (lowest_bigram[0][1], lowest_bigram[1][2])

    def small_likelihood_ratio(self):
        """
        Tries to identify errors using likelihood ration test under binomial distribution assumption
        """
        # TODO: here
        bigram_assoc.likelihood_ratio()


class Edit(models.Model):
    DELETE = 'DEL'
    INSERT = 'INS'
    REPLACE = 'REP'

    EDIT_TYPES = (
        (DELETE, 'delete'),
        (INSERT, 'insert'),
        (REPLACE, 'replace'),
    )
    edit_type = models.CharField(max_length=3, choices=EDIT_TYPES)
    start_pos_orig = models.IntegerField()
    end_pos_orig = models.IntegerField()
    start_pos_new = models.IntegerField()
    end_pos_new = models.IntegerField()
    sentence = models.ForeignKey(Sentence)
    edit1 = models.CharField(max_length=255)
    # Edit2 is not null when type is REPLACE
    edit2 = models.CharField(max_length=255, null=True)

    class Meta:
        unique_together = ('sentence', 'start_pos_orig', 'end_pos_orig')

    @classmethod
    def calculate_positional_metrics(cls, position_data):
        """
        Calculate precision and recall given the positional data for
        possible incorrect places in the data.
        :param position_data: of form {sentence_id: set((start_pos, end_pos), ...), ...}
        :type position_data: dict
        """
        tp = 0
        fp = 0
        fn = 0
        temp_edit_data = cls.objects.values_list('sentence', 'start_pos_orig', 'end_pos_orig')
        true_edit_data = defaultdict(set)
        true_edit_data1 = defaultdict(list)
        for sent_id, start_pos, end_pos in temp_edit_data:
            true_edit_data[sent_id].add((start_pos, end_pos))
            true_edit_data1[sent_id].append((start_pos, end_pos))

        for sent_id, true_sent_edit_data in true_edit_data.iteritems():
            if len(true_sent_edit_data) != len(true_edit_data1[sent_id]):
                print sent_id

        for sent_id, true_sent_edit_data in true_edit_data.iteritems():
            if sent_id in position_data:
                sent_edit_data = sorted(position_data[sent_id])
                index = 0
                sent_tp_count = 0
                for true_start_pos, true_end_pos in sorted(true_sent_edit_data):
                    if index >= len(sent_edit_data):
                        fn += 1
                    elif true_start_pos >= sent_edit_data[index][0] and true_end_pos <= sent_edit_data[index][1]:
                        tp += 1
                        sent_tp_count += 1
                        index += 1
                    else:
                        print sent_edit_data[index]
                        print true_start_pos, true_end_pos
                        print Sentence.objects.get(id=sent_id)
                        fn += 1
                fp += len(sent_edit_data) - sent_tp_count
            else:
                fn += len(true_sent_edit_data)
        return tp, fp, fn

    @classmethod
    def calculate_final_metrics(cls, edit_data):
        """Calculate precision and recall given the edit data"""
        orig_edit_data = set(cls.objects.values_list())
        precision = len(edit_data - orig_edit_data) / edit_data
        recall = len(orig_edit_data - edit_data) / edit_data

        return precision, recall
