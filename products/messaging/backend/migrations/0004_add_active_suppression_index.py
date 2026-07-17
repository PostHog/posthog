from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers.concurrent_index import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Partial B-tree index on (team_id, updated_at DESC) WHERE suppressed AND NOT deleted.
    # Serves the Suppression list scene query, which filters on those two flags and sorts by
    # updated_at. The paginator COUNT reads the same predicate so it benefits too. Only the
    # actively-suppressed subset of rows is indexed → much smaller than a full-table index.
    atomic = False

    dependencies = [
        ("messaging", "0003_message_suppression"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="messagesuppression",
            index=models.Index(
                fields=["team", "-updated_at"],
                name="pmsg_supp_active_by_updated",
                condition=Q(suppressed=True, deleted=False),
            ),
        ),
    ]
