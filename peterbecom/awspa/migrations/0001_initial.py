# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-11-10 03:13
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='AWSProduct',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('keyword', models.CharField(db_index=True, max_length=200)),
                ('searchindex', models.CharField(max_length=100)),
                ('asin', models.CharField(db_index=True, max_length=100)),
                ('payload', django.contrib.postgres.fields.jsonb.JSONField()),
                ('title', models.CharField(max_length=300)),
                ('add_date', models.DateTimeField(auto_now_add=True)),
                ('modify_date', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]