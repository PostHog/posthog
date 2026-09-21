from django.db import migrations


def backfill_destinations(apps, schema_editor):
    """Copy each run's destination off the channel row it used to point at.

    Without this every past run reads back with an empty audience and channel, so the history shows
    a blank destination for work that did have one, and the claim floor treats every existing
    audience as one that has never posted.
    """
    run_table = apps.get_model("stamphog", "DigestRun")._meta.db_table
    channel_table = apps.get_model("stamphog", "DigestChannel")._meta.db_table
    schema_editor.execute(
        f'UPDATE "{run_table}" AS r SET '
        '"audience_key" = c."audience_key", '
        '"slack_channel_id" = c."slack_channel_id", '
        '"slack_channel_name" = c."slack_channel_name", '
        '"resolution_source" = c."resolution_source" '
        f'FROM "{channel_table}" AS c WHERE r."digest_channel_id" = c."id"'
    )


class Migration(migrations.Migration):
    """Backfill each run's destination, then retire the channel model from state.

    Separate from 0003 because a data migration in the same file as schema changes is blocked: it
    can hold a lock while those changes wait on it.

    The backfill runs before the state removal, while ``DigestChannel`` is still reachable. The
    removal is state only, so the table and the column stay for pods on the previous release.
    """

    dependencies = [("stamphog", "0003_digest_runs_record_their_destination")]

    operations = [
        migrations.RunPython(backfill_destinations, migrations.RunPython.noop, elidable=True),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="digestrun", name="digest_channel"),
                migrations.DeleteModel(name="DigestChannel"),
            ],
        ),
    ]
