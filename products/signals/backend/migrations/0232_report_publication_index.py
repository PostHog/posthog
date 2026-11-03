from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0231_report_publication_outbox"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                condition=models.Q(
                    ("first_publication_event__isnull", False),
                    ("first_publication_event_sent_at__isnull", True),
                ),
                fields=["first_visible_at", "id"],
                name="signals_report_publication_due",
            ),
        ),
    ]
