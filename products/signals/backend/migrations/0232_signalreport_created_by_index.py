from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0231_signalreport_user_authored")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                condition=models.Q(("created_by__isnull", False)),
                fields=["created_by", "created_at"],
                name="signals_report_created_by",
            ),
        ),
    ]
