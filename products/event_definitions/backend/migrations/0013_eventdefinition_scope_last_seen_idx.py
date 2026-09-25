from django.db import migrations, models
from django.db.models.expressions import F
from django.db.models.functions import Coalesce

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    The data freshness probe scans every event definition in a project scope.

    It aggregates `last_seen_at` over a 30-day window per project scope, and cannot filter on
    event name because one product claims every name nobody else does. The only index it can use
    is the name-ordered `(coalesce(project_id, team_id), name)` unique expression index, so the
    date range stays a filter and the read grows with the catalog.

    This index leads with the same scope expression and orders by `last_seen_at`, which makes the
    window a range seek. CREATE INDEX CONCURRENTLY takes a SHARE UPDATE EXCLUSIVE lock, so the
    build does not block ingestion.
    """

    atomic = False

    dependencies = [
        ("event_definitions", "0012_alter_eventdefinition_project_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                Coalesce(F("project_id"), F("team_id"), output_field=models.BigIntegerField()),
                F("last_seen_at"),
                name="eventdef_scope_last_seen_idx",
            ),
        ),
    ]
