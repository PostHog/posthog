from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Drop the created_by foreign keys on the retired session-summary tables.

    0002 took the session-summarization models out of Django state and kept the tables,
    because their rows are the last copy of every generated summary. The table drop it names
    waits on the recording service in nodejs/, which still deletes from
    ee_single_session_summary, so it cannot land yet.

    Team deletion already works: _delete_retired_session_summaries_for_teams in
    posthog/models/team/util.py clears these rows before the Team cascade reaches them. That
    helper filters on team_id and runs on team deletion only, so the keys to posthog_user stay
    live. Deleting a user runs the whole cascade and Postgres then rejects the transaction at
    COMMIT, which is what an erasure request does.

    Only the two user keys go here. The team keys stay under the helper until the tables drop.
    """

    dependencies = [
        ("replay", "0003_drop_exception_event_ids_gin_index"),
    ]

    operations = [
        DropForeignKey("ee_single_session_summary", column="created_by_id"),
        DropForeignKey("ee_group_session_summary", column="created_by_id"),
    ]
