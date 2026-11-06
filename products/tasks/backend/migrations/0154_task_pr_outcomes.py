import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0153_task_status_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="merged_pr_urls",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=512), blank=True, db_default=[], default=list
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="closed_pr_urls",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=512), blank=True, db_default=[], default=list
            ),
        ),
    ]
