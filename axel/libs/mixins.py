"""Auxiliary mixins"""
import json
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.views.generic import TemplateView
from test_collection.views import _get_model_from_string


class JSONResponseMixin(object):
    """
    A mixin that can be used to render a JSON response.
    """
    response_class = HttpResponse

    def render_to_response(self, context, **response_kwargs):
        """
        Returns a JSON response, transforming 'context' to make the payload.
        """
        response_kwargs['content_type'] = 'application/json'
        return self.response_class(self.convert_context_to_json(context), **response_kwargs)

    def convert_context_to_json(self, context):
        """Convert the context dictionary into a JSON object"""
        return json.dumps(context)


class AttributeFilterMixin(object):
    """
    Supplies a form to perform data filtration based on the attribute values
    """
    attribute_names = None

    def _FilterForm(self):
        """:rtype: Form"""
        if self.attribute_names is None:
            raise ImproperlyConfigured(
                "AttributeFilterMixin requires a definition of 'attribute_names'")
        fields = {}
        for attribute in self.attribute_names:
            attribute += '__regex'
            fields[attribute] = forms.CharField(label=attribute)
        return type('AttributeForm', (forms.Form,), fields)


class AttributeFilterView(AttributeFilterMixin, TemplateView):
    """
    A view that adds an attribute filter form to view.
    Also handles forms processing (filtration)
    """
    context_form_name = 'filter_form'
    model_name = 'model_name'
    queryset = None
    """:type: QuerySet"""

    def get_context_data(self, **kwargs):
        context = super(AttributeFilterView, self).get_context_data(**kwargs)
        if not self.queryset:
            try:
                model = _get_model_from_string(self.kwargs[self.model_name])
                self.queryset = model.objects.all()
            except:
                raise ImproperlyConfigured(
                    "AttributeFilterView requires either a definition of "
                    "'queryset' or a 'model_name' kwarg attribute")
        form = self._FilterForm()(self.request.POST or None)
        if form.is_valid():
            filter_values = dict([(field, value) for field, value in form.cleaned_data.iteritems()])
            self.queryset = self.queryset.filter(**filter_values)
        context[self.context_form_name] = form
        return context

    def post(self, request, *args, **kwargs):
        return self.get(request, args, kwargs)
