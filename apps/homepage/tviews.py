from functools import wraps
from django.views.generic import View
from django import http
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator
import json

class TView(View):

    def dispatch(self, request, *args, **kwargs):
        # Try to dispatch to the right method; if a method doesn't exist,
        # defer to the error handler. Also defer to the error handler if the
        # request method isn't on the approved list.
        if request.method.lower() in self.http_method_names:
            handler = getattr(self, request.method.lower(), self.http_method_not_allowed)
        else:
            handler = self.http_method_not_allowed
        self.request = request
        self.args = args
        self.kwargs = kwargs
        handler(request, *args, **kwargs)

        return self.response

    def write(self, content):
        if not getattr(self, 'response', None):
            self.response = http.HttpResponse()
        if isinstance(content, dict):
            self.response.content_type = 'application/json; charset=utf-8'
            self.response.write(json.dumps(content))
        else:
            self.response.write(content)

    def render(self, template_name, data):
        self.response = TemplateResponse(self.request, template_name, data)


def class_decorator(decorator):
    def inner(cls):
        orig_dispatch = cls.dispatch
        @method_decorator(decorator)
        def new_dispatch(self, request, *args, **kwargs):
            return orig_dispatch(self, request, *args, **kwargs)
        cls.dispatch = new_dispatch
        return cls
    return inner
