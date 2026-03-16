from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 1000
LOG_INTERVAL = 25


def backfill_endpoints_to_dags(apps, _):
    pass


def reverse_backfill(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0018_endpointversion_bucket_overrides"),
        ("data_modeling", "0010_add_endpoint_node_type"),
    ]

    operations = [
        migrations.RunPython(backfill_endpoints_to_dags, reverse_backfill, elidable=True),
    ]
