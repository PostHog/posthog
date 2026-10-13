from django.db import migrations


def backfill_conversation_type(apps, schema_editor):
    """Classify the direct-message threads we never recorded a conversation type for.

    A `D…` conversation id is a DM, and this is the only classification recoverable without
    calling Slack. Channel rows stay NULL, which reads as non-private — the same access they
    have today. DM rows are the ones whose access changes, so they are the ones that matter:
    without this, every Slack thread that predates the column keeps team-wide read access,
    including the direct messages.
    """
    SlackThreadTaskMapping = apps.get_model("slack_app", "SlackThreadTaskMapping")
    SlackThreadTaskMapping.objects.filter(conversation_type__isnull=True, channel__startswith="D").update(
        conversation_type="im"
    )


class Migration(migrations.Migration):
    # Data migration kept apart from the AddField in 0014 so the schema change never shares a
    # transaction (and its locks) with the backfill.
    dependencies = [
        ("slack_app", "0014_slackthreadtaskmapping_conversation_type"),
    ]

    operations = [
        migrations.RunPython(backfill_conversation_type, migrations.RunPython.noop, elidable=True),
    ]
