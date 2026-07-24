from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0017_add_resolved_signal_report_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="signalreportartefact",
            name="type",
            field=models.CharField(
                choices=[
                    ("video_segment", "Video Segment"),
                    ("safety_judgment", "Safety Judgment"),
                    ("actionability_judgment", "Actionability Judgment"),
                    ("priority_judgment", "Priority Judgment"),
                    ("signal_finding", "Signal Finding"),
                    ("repo_selection", "Repo Selection"),
                    ("suggested_reviewers", "Suggested Reviewers"),
                    ("dismissal", "Dismissal"),
                ],
                max_length=100,
            ),
        ),
    ]
