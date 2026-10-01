from datetime import datetime

from django.db.models import Max

from posthog.data_freshness import POSTGRES_TIMEOUT_MS, DataSourceSpec, ProbeWindow
from posthog.models.utils import execute_with_timeout
from posthog.schema_enums import ProductKey

from products.feature_flags.backend.models.feature_flag import FeatureFlag


def last_flag_call_at(team_ids: list[int], window: ProbeWindow) -> dict[int, datetime]:
    """Read the per-flag call stamp that the `last_called_at` sync writes.

    No event definition records flag calls for organizations on `FLAG_EVALUATIONS_ONLY`, because
    their `$feature_flag_called` events skip `events`. This stamp covers them only when the sync
    reads `flag_evaluations`. A soft-deleted flag keeps the stamp of calls made before deletion.
    """
    rows = (
        FeatureFlag.objects_including_soft_deleted.filter(
            team_id__in=team_ids,
            last_called_at__gte=window.cutoff,
            last_called_at__lte=window.horizon,
        )
        .values("team_id")
        .annotate(last_called=Max("last_called_at"))
    )
    with execute_with_timeout(POSTGRES_TIMEOUT_MS):
        return {row["team_id"]: row["last_called"] for row in rows}


# Flag evaluations, not flag edits: a project with flags configured but nothing calling them
# is not receiving data. The spec also claims the event name, because otherwise the product
# analytics residual would count it. The event definition also catches calls for keys that the
# sync never stamps.
DATA_SOURCES = [
    DataSourceSpec(product=ProductKey.FEATURE_FLAGS, event_names=("$feature_flag_called",), probe=last_flag_call_at)
]
