# Activity-log receivers, kept in a module with no API/query-runner imports so
# AppConfig.ready() can wire them cheaply in every process type (celery, temporal,
# migrate) without pulling the viewset import graph into django.setup().
import dataclasses

from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.tasks.backend.models import Loop


@dataclasses.dataclass(frozen=True)
class LoopContext(ActivityContextBase):
    visibility: str
    created_by_user_id: str | None


@mutable_receiver(model_activity_signal, sender=Loop)
def handle_loop_change(sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs):
    loop = after_update or before_update
    if not loop:
        return

    log_activity(
        organization_id=loop.team.organization_id,
        team_id=loop.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=loop.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=loop.name,
            context=LoopContext(
                visibility=loop.visibility,
                created_by_user_id=str(loop.created_by_id) if loop.created_by_id else None,
            ),
        ),
    )
