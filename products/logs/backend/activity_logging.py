# Activity-log receivers, kept in a module with no API/query-runner imports so
# AppConfig.ready() can wire them cheaply in every process type (celery, temporal,
# migrate) without pulling the viewset import graph into django.setup().

from typing import Any, cast

from posthog.models.activity_logging.activity_log import ActivityScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.logs.backend.models import LogsAlertConfiguration, LogsExclusionRule


@mutable_receiver(model_activity_signal, sender=LogsAlertConfiguration)
def handle_logs_alert_activity(
    sender,
    scope,
    before_update,
    after_update,
    activity,
    user,
    was_impersonated=False,
    **kwargs,
):
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


@mutable_receiver(model_activity_signal, sender=LogsExclusionRule)
def handle_logs_sampling_rule_activity(
    sender: Any,
    scope: str,
    before_update: LogsExclusionRule | None,
    after_update: LogsExclusionRule | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
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
            changes=changes_between(cast(ActivityScope, scope), previous=before_update, current=after_update),
            name=instance.name,
        ),
    )
