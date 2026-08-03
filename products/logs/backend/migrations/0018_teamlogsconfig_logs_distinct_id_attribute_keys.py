import django.contrib.postgres.fields
from django.db import migrations, models

import products.logs.backend.models


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0017_logsmetricrule"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamlogsconfig",
            name="logs_distinct_id_attribute_keys",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=200),
                db_default=models.Value("{posthogDistinctId}"),
                default=products.logs.backend.models.default_logs_distinct_id_attribute_keys,
                size=None,
            ),
        ),
    ]
