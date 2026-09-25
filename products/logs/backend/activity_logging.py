# Activity-log receivers, kept in a module with no API/query-runner imports so
# AppConfig.ready() can wire them cheaply in every process type (celery, temporal,
# migrate) without pulling the viewset import graph into django.setup().

from typing import Any

from posthog.models.activity_logging.activity_log import AuditableScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.logs.backend.models import LogsAlertConfiguration, LogsExclusionRule, LogsRetentionRule, LogsSource


def _log_named_activity(
    scope: AuditableScope,
    before_update: Any,
    after_update: Any,
    activity: str,
    user: User | None,
    was_impersonated: bool,
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
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=instance.name,
        ),
    )


# One named receiver per model: the receiver baseline in
# posthog/test/repo_invariants/setup_receivers_baseline.txt lists them by dotted name.


@mutable_receiver(model_activity_signal, sender=LogsAlertConfiguration)
def handle_logs_alert_activity(
    sender: Any,
    scope: AuditableScope,
    before_update: LogsAlertConfiguration | None,
    after_update: LogsAlertConfiguration | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    _log_named_activity(scope, before_update, after_update, activity, user, was_impersonated)


@mutable_receiver(model_activity_signal, sender=LogsExclusionRule)
def handle_logs_sampling_rule_activity(
    sender: Any,
    scope: AuditableScope,
    before_update: LogsExclusionRule | None,
    after_update: LogsExclusionRule | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    _log_named_activity(scope, before_update, after_update, activity, user, was_impersonated)


@mutable_receiver(model_activity_signal, sender=LogsRetentionRule)
def handle_logs_retention_rule_activity(
    sender: Any,
    scope: AuditableScope,
    before_update: LogsRetentionRule | None,
    after_update: LogsRetentionRule | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    _log_named_activity(scope, before_update, after_update, activity, user, was_impersonated)


@mutable_receiver(model_activity_signal, sender=LogsSource)
def handle_logs_source_activity(
    sender: Any,
    scope: AuditableScope,
    before_update: LogsSource | None,
    after_update: LogsSource | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    _log_named_activity(scope, before_update, after_update, activity, user, was_impersonated)
