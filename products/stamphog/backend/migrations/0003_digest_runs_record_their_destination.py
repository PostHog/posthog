import django.db.models.deletion
from django.db import migrations, models

import products.stamphog.backend.facade.enums


class Migration(migrations.Migration):
    """Move the digest destination onto the run, and retire the channel table from state.

    Routing is now derived from the repositories on every run rather than memoized in a row, so a
    run has to record where it actually posted. A foreign key to a row that later re-resolves would
    rewrite the destination of every past digest that pointed at it.

    The channel table and the ``digest_channel_id`` column stay in the database. Pods on the
    previous release still read both during a rolling deploy. This migration therefore only drops
    the NOT NULL that would reject a row the new code writes without them. A later migration drops
    the column and the table, once no running release reads either.

    Schema only. The backfill and the state removal live in 0004, because the migration analyzer
    blocks a data migration that shares a file with schema changes: the data migration can hold a
    lock while the schema changes wait on it.
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
    ]
