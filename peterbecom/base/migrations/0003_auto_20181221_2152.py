# Generated by Django 2.1.4 on 2018-12-22 03:52

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0002_postprocessing'),
    ]

    operations = [
        migrations.AddField(
            model_name='postprocessing',
            name='previous',
            field=models.ForeignKey(db_index=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='postprocessing', to='base.PostProcessing'),
        ),
        migrations.AlterField(
            model_name='postprocessing',
            name='url',
            field=models.URLField(db_index=True, max_length=400),
        ),
    ]
