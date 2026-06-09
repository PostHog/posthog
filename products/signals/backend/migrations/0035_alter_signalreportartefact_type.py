from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0034_signalscoutemission"),
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
                    ("code_reference", "Code Reference"),
                    ("code_diff", "Code Diff"),
                ],
                max_length=100,
            ),
        ),
    ]
