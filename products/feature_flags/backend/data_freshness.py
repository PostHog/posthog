from datetime import datetime

from posthog.data_freshness import DataSourceSpec, ProbeWindow, latest_per_team
from posthog.schema_enums import ProductKey

from products.feature_flags.backend.models.feature_flag import FeatureFlag


def last_flag_call_at(team_ids: list[int], window: ProbeWindow) -> dict[int, datetime]:
    """Read the per-flag call stamp that the `last_called_at` sync writes.

    No event definition records flag calls for organizations on `FLAG_EVALUATIONS_ONLY`, because
    their `$feature_flag_called` events skip `events`. This stamp covers them only when the sync
    reads `flag_evaluations`. A soft-deleted flag keeps the stamp of calls made before deletion.
    """
    return latest_per_team(FeatureFlag.objects_including_soft_deleted.all(), "last_called_at", team_ids, window)


# Flag evaluations, not flag edits: a project with flags configured but nothing calling them
# is not receiving data. The spec also claims the event name, because otherwise the product
# analytics residual would count it. The event definition also catches calls for keys with no
# undeleted flag, because the sync only stamps undeleted flags it finds by key.
DATA_SOURCES = [
    DataSourceSpec(product=ProductKey.FEATURE_FLAGS, event_names=("$feature_flag_called",), probe=last_flag_call_at)
]
