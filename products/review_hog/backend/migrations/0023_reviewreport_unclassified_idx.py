from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY cannot run inside a transaction, and building this on the live table must not
    # hold an ACCESS EXCLUSIVE lock against the review paths that write it.
    atomic = False

    dependencies = [
        ("review_hog", "0022_reviewreport_outcomes_emitted_at"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="reviewreport",
            index=models.Index(
                fields=["team", "-updated_at"],
                name="reviewhog_rpt_unclassified_idx",
                condition=models.Q(
                    published_head_sha__isnull=False, pr_number__isnull=False, outcomes_emitted_at__isnull=True
                ),
            ),
        ),
    ]
