from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0131_taskrun_github_pr_run_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                condition=models.Q(
                    models.Func(
                        "output",
                        models.Value('$.pr_url ? (@.type() == "string" && @ != "")'),
                        function="jsonb_path_exists",
                        output_field=models.BooleanField(),
                    ),
                    models.Func(
                        "output",
                        models.Value('$.pr_urls[*] ? (@.type() == "string" && @ != "")'),
                        function="jsonb_path_exists",
                        output_field=models.BooleanField(),
                    ),
                    _connector="OR",
                ),
                fields=["team", "task"],
                name="task_run_pr_carrying_idx",
            ),
        ),
    ]
