"""Activity-log receiver for streamlit apps.

The module stays import-light because `apps.py` imports it at `ready()`.
A version upload or activation is not logged here: the field change alone cannot tell an upload
from a rollback to the newest version, so the facade logs those at the write site.
"""

from typing import TYPE_CHECKING, Any

from posthog.models.activity_logging.activity_log import AuditableScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.streamlit_apps.backend.models import StreamlitApp

if TYPE_CHECKING:
    from posthog.models.user import User


def _was_soft_deleted(before_update: StreamlitApp | None, after_update: StreamlitApp | None) -> bool:
    return before_update is not None and after_update is not None and after_update.deleted and not before_update.deleted


@mutable_receiver(model_activity_signal, sender=StreamlitApp)
def handle_streamlit_app_change(
    sender: type[StreamlitApp],
    scope: AuditableScope,
    before_update: StreamlitApp | None,
    after_update: StreamlitApp | None,
    activity: str,
    user: "User | None",
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    app = after_update or before_update
    if app is None:
        return

    if _was_soft_deleted(before_update, after_update):
        activity = "deleted"

    if activity == "updated":
        detail = Detail(changes=changes_between(scope, previous=before_update, current=after_update), name=app.name)
    else:
        detail = Detail(name=app.name)

    log_activity(
        organization_id=app.team.organization_id,
        team_id=app.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(app.id),
        scope=scope,
        activity=activity,
        detail=detail,
    )
