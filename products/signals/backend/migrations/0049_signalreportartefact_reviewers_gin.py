# Reviewer-membership lookups: the inbox's default sort surfaces "you're a suggested reviewer"
# first, which tests `content::jsonb @> '[{"github_login": ...}]'` over the suggested_reviewers
# artefacts. Without an index that's a full scan + jsonb parse of every such artefact on each
# inbox load; this partial GIN index turns it into a bitmap probe.
#
# Built CONCURRENTLY (atomic=False, SeparateDatabaseAndState) like 0048 — CONCURRENTLY cannot run
# in a transaction, and bin/migrate re-runs a failed migration in full, so it must be isolated and
# idempotent. The Cast/`content::jsonb` expression can't be modelled as plain index `fields`, so
# the DB side is raw SQL while the Django state mirrors the model's GinIndex.

import django.contrib.postgres.indexes
import django.db.models.functions.comparison
from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("signals", "0048_signalreportartefact_latest_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="signalreportartefact",
                    index=django.contrib.postgres.indexes.GinIndex(
                        django.db.models.functions.comparison.Cast("content", output_field=models.JSONField()),
                        condition=models.Q(("type", "suggested_reviewers")),
                        name="signals_artefact_reviewers_gin",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="signals_artefact_reviewers_gin",
                    table_name="signals_signalreportartefact",
                    columns="((content::jsonb))",
                    using="gin",
                    where="WHERE type = 'suggested_reviewers'",
                ),
            ],
        ),
    ]
