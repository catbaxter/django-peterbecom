# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-01-11 19:45
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("podcasttime", "0018_podcast_error")]

    operations = [
        migrations.AddField(
            model_name="podcast",
            name="latest_episode",
            field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name="picked",
            name="session_key",
            field=models.CharField(default="legacy", max_length=32),
        ),
    ]
