import django.contrib.postgres.fields
from django.db import migrations, models

import products.logs.backend.models


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0019_backfill_logs_distinct_id_attribute_keys"),
    ]

    operations = [
        # Metadata-only default change (ALTER COLUMN SET DEFAULT). Applies to rows created
        # after this migration; existing rows are intentionally left untouched. Mirrors the
        # Python-level default in products/logs/backend/models.py.
        migrations.AlterField(
            model_name="teamlogsconfig",
            name="logs_distinct_id_attribute_keys",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=200),
                db_default=models.Value("{posthogDistinctId,distinctId}"),
                default=products.logs.backend.models.default_logs_distinct_id_attribute_keys,
                size=None,
            ),
        ),
    ]
