from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0145_sandboxsession_compute_settlement"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="sandboxsession",
            index=models.Index(
                condition=models.Q(
                    ("compute_settle_conflict_at__isnull", True),
                    ("compute_settled_at__isnull", True),
                    ("user_attributed_at__isnull", False),
                ),
                fields=["ttl_expires_at"],
                name="sandbox_session_settle_ttl_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="sandboxsession",
            index=models.Index(
                models.OrderBy(models.F("compute_settle_attempted_at"), nulls_first=True),
                models.F("ended_at"),
                condition=models.Q(
                    ("compute_settle_conflict_at__isnull", True),
                    ("compute_settled_at__isnull", True),
                    ("user_attributed_at__isnull", False),
                ),
                name="sandbox_session_settle_rt_idx",
            ),
        ),
    ]
