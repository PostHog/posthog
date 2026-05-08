from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0017_add_resolved_signal_report_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="signaluserautonomyconfig",
            name="notify_on_slack_when_assigned",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When true, the user receives a Slack DM (via the team's Slack integration) the first time "
                    "a signal report transitions to ready and lists them as a suggested reviewer."
                ),
            ),
        ),
        migrations.AddField(
            model_name="signalreport",
            name="slack_notified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
