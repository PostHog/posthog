from collections.abc import Callable
from typing import Any

from posthog.event_usage import groups

from products.exports.backend.models.exported_asset import ExportedAsset


def capture_export_event(
    asset: ExportedAsset,
    event: str,
    capture: Callable[..., None],
    **properties: Any,
) -> None:
    """Emit an export lifecycle event with the shape every export format reports.

    The caller supplies `capture` because the right client depends on the process it runs in: a
    Temporal worker has no request cycle whose end flushes the module-level client, and a Celery task
    can exit before that client's background consumer delivers anything.
    """
    capture(
        distinct_id=asset.created_by.distinct_id if asset.created_by else str(asset.team.uuid),
        event=event,
        properties={**asset.get_analytics_metadata(), **properties},
        groups=groups(asset.team.organization, asset.team),
    )
