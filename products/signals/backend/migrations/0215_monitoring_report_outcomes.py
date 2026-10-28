from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0214_closed_report_state")]

    operations = [
        migrations.AddField(
            model_name="signalreportmonitoringattempt",
            name="aggregation_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="signalreportmonitoringattempt",
            name="aggregation_reason",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="signalreportmonitoringattempt",
            name="aggregation_result_ids",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="signalreportmonitoringattempt",
            name="aggregation_state",
            field=models.CharField(
                blank=True,
                choices=[
                    ("waiting", "Waiting"),
                    ("passed", "Passed"),
                    ("failed", "Failed"),
                    ("assessment_required", "Assessment Required"),
                ],
                max_length=24,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="signalreportmonitoringattempt",
            name="assessment_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="signalreportmonitoringattempt",
            name="research_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="signalreportmonitoringattempt",
            name="tracker_issue_close_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
