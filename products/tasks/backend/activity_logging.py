from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.activity_logging.model_activity import get_was_impersonated
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.tasks.backend.models import SandboxCustomImage, SandboxEnvironment


def _private_throughout(*rows: SandboxEnvironment | SandboxCustomImage | None) -> bool:
    return all(row.private for row in rows if row is not None)


@mutable_receiver(model_activity_signal, sender=SandboxEnvironment)
def handle_sandbox_environment_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    instance = after_update or before_update
    if instance.internal or (before_update is not None and before_update.internal):
        return
    if _private_throughout(before_update, after_update):
        return
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=instance.name,
        ),
    )


@mutable_receiver(model_activity_signal, sender=SandboxCustomImage)
def handle_sandbox_custom_image_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    if _private_throughout(before_update, after_update):
        return
    instance = after_update or before_update
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=instance.name,
        ),
    )


def log_sandbox_custom_image_update(before: SandboxCustomImage, after: SandboxCustomImage, user_id: int) -> None:
    if _private_throughout(before, after):
        return
    log_activity(
        organization_id=after.team.organization_id,
        team_id=after.team_id,
        user=User.objects.filter(pk=user_id).first(),
        was_impersonated=get_was_impersonated(),
        item_id=after.id,
        scope="SandboxCustomImage",
        activity="updated",
        detail=Detail(
            changes=changes_between("SandboxCustomImage", previous=before, current=after),
            name=after.name,
        ),
    )
