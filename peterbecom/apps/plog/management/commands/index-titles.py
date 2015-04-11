import json
from optparse import make_option
from pprint import pprint

from django.core.management.base import BaseCommand
from django.core.urlresolvers import reverse
from django.conf import settings
from django.contrib.sites.models import Site

import requests

from peterbecom.apps.plog import models
from peterbecom.apps.plog.utils import utc_now


class Command(BaseCommand):

    option_list = BaseCommand.option_list + (
        make_option(
            '--all',
            action='store_true',
            dest='all',
            default=False,
            help='Index every single post'
        ),
        make_option(
            '--max',
            dest='max',
            default=100,
            help='Number of (random) elements to index'
        )
    )

    def handle(self, *args, **options):
        now = utc_now()
        verbose = int(options['verbosity']) > 1

        base_url = 'http://%s' % Site.objects.all()[0].domain
        qs = models.BlogItem.objects.filter(pub_date__lte=now).order_by('?')
        if not options['all']:
            qs = qs[:options['max']]

        documents = []
        for plog in qs:
            if verbose:
                print repr(plog.title),
            try:
                hits = models.BlogItemHits.objects.get(oid=plog.oid).hits
            except models.BlogItemHits.DoesNotExist:
                hits = 1
            data = {
                'title': plog.title,
                'url': base_url + reverse('blog_post', args=(plog.oid,)),
                'popularity': hits,
            }
            documents.append(data)
        response = requests.post(
            'https://autocompeter.com/v1/bulk',
            data=json.dumps({'documents': documents}),
            headers={'Auth-Key': settings.AUTOCOMPETER_AUTH_KEY}
        )
        if verbose:
            pprint(documents)
            print response
