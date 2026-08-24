import django.db.models.deletion
from django.db import migrations, models

import products.stamphog.backend.facade.enums


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
    """Move the digest destination onto the run, and retire the channel table from state.

    Routing is now derived from the repositories on every run rather than memoized in a row, so a
    run has to record where it actually posted. A foreign key to a row that later re-resolves would
    rewrite the destination of every past digest that pointed at it.

    The channel table and the ``digest_channel_id`` column stay in the database. Pods running the
    previous release still read both during a rolling deploy, so this migration only drops the NOT
    NULL that would reject a row the new code writes without them. A later migration drops the
    column and the table for real, once no running release refers to either.
    """

    dependencies = [("stamphog", "0002_digest_audiences_and_summaries")]

    operations = [
        migrations.AddField(
            model_name="digestrun",
            name="audience_key",
            field=models.CharField(db_default="", default="", max_length=255),
        ),
        migrations.AddField(
            model_name="digestrun",
            name="slack_channel_id",
            field=models.CharField(db_default="", default="", max_length=64),
        ),
        migrations.AddField(
            model_name="digestrun",
            name="slack_channel_name",
            field=models.CharField(blank=True, db_default="", default="", max_length=255),
        ),
        migrations.AddField(
            model_name="digestrun",
            name="resolution_source",
            field=models.CharField(
                choices=[
                    ("manual", "manual"),
                    ("slack_name_match", "slack_name_match"),
                    ("stamphog_config", "stamphog_config"),
                    ("owners_contact", "owners_contact"),
                ],
                db_default="slack_name_match",
                default=products.stamphog.backend.facade.enums.ChannelResolutionSource["SLACK_NAME_MATCH"],
                max_length=32,
            ),
        ),
        # Catalog-only DROP NOT NULL. The new code inserts a run without a channel row, and the
        # column is still there for the previous release to read.
        migrations.AlterField(
            model_name="digestrun",
            name="digest_channel",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="runs",
                to="stamphog.digestchannel",
            ),
        ),
        # Runs before the model leaves state, while the channel rows are still reachable.
        migrations.RunPython(backfill_destinations, migrations.RunPython.noop, elidable=True),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="digestrun", name="digest_channel"),
                migrations.DeleteModel(name="DigestChannel"),
            ],
        ),
    ]
