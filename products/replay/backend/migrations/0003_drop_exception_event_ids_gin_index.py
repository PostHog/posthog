from django.db import migrations

from posthog.migration_helpers.concurrent_index import DropIndexConcurrently


class Migration(migrations.Migration):
    """Drop the GIN index on `ee_single_session_summary.exception_event_ids`.

    Migration 0002 removed the session-summarization models from Django state, so nothing reads
    this column any more. The two remaining callers of the table, the recording deletion in
    `nodejs/src/session-replay/recording-api/recording-service.ts` and the team predelete sweep in
    `posthog/models/team/util.py`, both filter on `team_id` and use the composite index. The GIN
    index only adds write cost to those deletes.

    The operation is database-only because the model is gone from Django state, so there is no
    index to remove from a model's `Meta.indexes`. The table drop stays blocked on the Node
    recording service, as migration 0002 says.
    """

    atomic = False

    dependencies = [
        ("replay", "0002_remove_session_summary_models"),
    ]

    operations = [
        DropIndexConcurrently(
            index_name="idx_exception_event_ids_gin",
            table_name="ee_single_session_summary",
            columns="(exception_event_ids)",
            using="gin",
        ),
    ]
