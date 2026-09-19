from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0130_report_work_pull_requests")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(fields=["pull_request", "report"], name="signals_artefact_pr_report_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(fields=["claim"], name="signals_artefact_claim_idx"),
        ),
    ]
