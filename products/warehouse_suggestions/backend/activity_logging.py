from typing import Any, Optional, cast

from posthog.models import User
from posthog.models.activity_logging.activity_log import AuditableScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from .models import WarehouseSuggestion


@mutable_receiver(model_activity_signal, sender=WarehouseSuggestion)
def handle_warehouse_suggestion_activity(
    sender: type,
    scope: str,
    before_update: Optional[WarehouseSuggestion],
    after_update: WarehouseSuggestion,
    activity: str,
    user: Optional[User],
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    log_activity(
        organization_id=None,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(after_update.id),
        scope=scope,
        activity=activity,
        detail=Detail(
            name=f"{after_update.kind} suggestion",
            changes=changes_between(cast(AuditableScope, scope), previous=before_update, current=after_update),
        ),
    )
