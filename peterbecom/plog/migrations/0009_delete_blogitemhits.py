# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-08-03 13:13
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('plog', '0008_blogitemhit'),
    ]

    operations = [
        migrations.DeleteModel(
            name='BlogItemHits',
        ),
    ]
