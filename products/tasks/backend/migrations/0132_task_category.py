from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0131_taskrun_github_pr_run_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="category",
            field=models.CharField(
                blank=True,
                choices=[
                    ("feat", "Feature"),
                    ("fix", "Fix"),
                    ("perf", "Performance"),
                    ("refactor", "Refactor"),
                    ("docs", "Docs"),
                    ("test", "Test"),
                    ("chore", "Chore"),
                    ("ci", "CI"),
                    ("build", "Build"),
                    ("style", "Style"),
                    ("revert", "Revert"),
                ],
                max_length=16,
                null=True,
            ),
        ),
    ]
