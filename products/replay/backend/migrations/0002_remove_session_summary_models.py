from django.db import migrations


class Migration(migrations.Migration):
    """Drop the retired session-summarization models from Django state only.

    State-only so the tables survive this deploy: the rows are the last copy of every generated
    summary, and a rollback that recreated empty tables would not bring them back. A follow-up
    migration drops `ee_single_session_summary`, `ee_group_session_summary`, and
    `posthog_teamsessionsummariesconfig` once this has been deployed.
    """

    dependencies = [
        ("replay", "0001_migrate_replay_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="SingleSessionSummary"),
                migrations.DeleteModel(name="SessionGroupSummary"),
                migrations.DeleteModel(name="TeamSessionSummariesConfig"),
            ],
            database_operations=[],
        ),
    ]
