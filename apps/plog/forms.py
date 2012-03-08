from django.forms import ModelForm
from django.forms.fields import ChoiceField
from django.forms.widgets import Textarea
from apps.plog.models import BlogItem


class BlogForm(ModelForm):

    class Meta:
        model = BlogItem
        exclude = ('alias', 'bookmark', 'text_rendered', 'plogrank',
                   'modify_date')

    def __init__(self, *args, **kwargs):
        super(BlogForm, self).__init__(*args, **kwargs)
        self.fields['display_format'] = ChoiceField()
        self.fields['display_format'].choices = [
          ('structuredtext', 'structuredtext'),
          ('markdown', 'markdown'),
        ]
        self.fields['keywords'].widget = Textarea()
        self.fields['url'].required = False
        self.fields['summary'].required = False
        self.fields['keywords'].required = False
