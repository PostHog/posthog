from django.db import migrations


class Migration(migrations.Migration):
    """Drop the ``integration`` FK from ``SlackThreadTaskMapping`` and
    ``SlackUserProfileCache``. Both rows now key on
    ``slack_workspace_id`` (+ ``team`` for the mapping). Application code in
    this PR no longer touches either ``integration`` field, so the column can
    go in the same deploy as the code change.

    Split from 0009 so a phased rollout has the option of landing the workspace
    backfill + new unique constraint first, verifying nothing reads
    ``integration`` anymore, and only then dropping the column.
    """

    dependencies = [
        ("slack_app", "0009_slack_models_workspace_scope"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="slackthreadtaskmapping",
            name="integration",
        ),
        migrations.RemoveField(
            model_name="slackuserprofilecache",
            name="integration",
        ),
    ]
