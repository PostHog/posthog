from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("messaging", "0004_alter_messagesuppression_source"),
    ]

    operations = [
        # The suppression list now sorts on `id` as well, to keep rows with the same `updated_at`
        # in a stable order across pages. Build the wider index before dropping the old one, so the
        # list query keeps an index to read for the whole rollout.
        SafeAddIndexConcurrently(
            model_name="messagesuppression",
            index=models.Index(
                fields=["team", "-updated_at", "-id"],
                name="pmsg_supp_active_by_upd_id",
                condition=Q(suppressed=True, deleted=False),
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="messagesuppression",
            name="pmsg_supp_active_by_updated",
        ),
    ]
