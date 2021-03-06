# Generated by Django 2.1.4 on 2018-12-20 16:43

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PostProcessing',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('filepath', models.CharField(max_length=400)),
                ('url', models.URLField(max_length=400)),
                ('duration', models.DurationField(null=True)),
                ('notes', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=100), default=list, size=None)),
                ('exception', models.TextField(null=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
