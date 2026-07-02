from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0052_signalscoutrun_edited_report_ids"),
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
                    ("commit", "Commit"),
                    ("task_run", "Task Run"),
                    ("note", "Note"),
                    ("title_change", "Title Change"),
                    ("summary_change", "Summary Change"),
                ],
                max_length=100,
            ),
        ),
    ]
