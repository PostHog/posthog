from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0153_signalreport_latest_actionability"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(
                condition=models.Q(
                    ("type", "task_run"),
                    ("content__regex", '"product"\\s*:\\s*"signals"'),
                    models.Q(("content__regex", '"type"\\s*:\\s*"(repo_selection|research|scout)"'), _negated=True),
                ),
                fields=["team", "task", "report"],
                name="signals_artefact_pr_run_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="signalreportassignment",
            index=models.Index(
                condition=models.Q(
                    (
                        "pr_url__regex",
                        "^[A-Za-z][A-Za-z0-9+.-]*://(www\\.)?github\\.com/+[^/?#]+/+[^/?#]+/+pull/+[+-]?[ \\t\\r\\n\\f\\v]*[0-9]+([/?#].*)?$",
                    )
                ),
                fields=["team", "report"],
                name="signals_assign_pr_url_idx",
            ),
        ),
    ]
