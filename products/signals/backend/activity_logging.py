"""Activity-log hooks for SignalScoutConfig, SignalSourceConfig and SignalTeamConfig changes.

`ModelActivityMixin.save()` only *emits* `model_activity_signal` — it does not persist
anything. These receivers are the consumers that turn the emitted signal into a stored
`ActivityLog` row. Without them, nothing about these models would ever appear in the
activity log. Imported from `SignalsConfig.ready()` so they register at startup.
"""

import dataclasses
from typing import Any

import structlog

from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    ActivityScope,
    Change,
    Detail,
    LogActivityEntry,
    bulk_log_activity,
    changes_between,
    field_name_overrides,
    log_activity,
)
from posthog.models.activity_logging.model_activity import get_current_trigger, get_current_user, get_was_impersonated
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from .enums import SIGNAL_SOURCE_PRODUCT_LABELS, SignalSourceProduct
from .models import SignalScoutConfig, SignalSourceConfig, SignalTeamConfig

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class SignalScoutConfigContext(ActivityContextBase):
    skill_name: str


@mutable_receiver(model_activity_signal, sender=SignalScoutConfig)
def handle_signal_scout_config_change(
    sender: type[SignalScoutConfig],
    scope: ActivityScope,
    before_update: SignalScoutConfig | None,
    after_update: SignalScoutConfig | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance: SignalScoutConfig | None = after_update or before_update
    if instance is None:
        return

    changes = changes_between(scope, previous=before_update, current=after_update)
    if (
        before_update is not None
        and after_update is not None
        and before_update.allowed_mcp_tools != after_update.allowed_mcp_tools
        and not any(
            change.field == field_name_overrides["SignalScoutConfig"]["allowed_mcp_tools"] for change in changes
        )
    ):
        # The generic diff treats null and [] as empty, but these select different permissions.
        changes.append(
            Change(
                type=scope,
                field=field_name_overrides["SignalScoutConfig"]["allowed_mcp_tools"],
                action="changed",
                before=before_update.allowed_mcp_tools,
                after=after_update.allowed_mcp_tools,
            )
        )
    if before_update is None and after_update is not None and after_update.write_scopes:
        # `changes_between` records no fields for a creation, so a scout created with a grant
        # would leave the log unable to say what it held before the first edit. Write access
        # decides what an unattended agent can change, so its first value is part of the trail.
        changes.append(
            Change(
                type=scope,
                field=field_name_overrides["SignalScoutConfig"]["write_scopes"],
                action="created",
                after=after_update.write_scopes,
            )
        )

    if before_update is None and after_update is not None and after_update.allowed_mcp_tools is not None:
        for field in ("allowed_mcp_tools", "tool_preset"):
            changes.append(
                Change(
                    type=scope,
                    field=field_name_overrides["SignalScoutConfig"][field],
                    action="created",
                    after=getattr(after_update, field),
                )
            )

    log_activity(
        organization_id=None,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes,
            name=instance.skill_name,
            # Set by system-driven saves (the inactivity sweep) so an entry with no user reads as
            # "this job did it" rather than as an unattributed edit.
            trigger=get_current_trigger(),
            context=SignalScoutConfigContext(skill_name=instance.skill_name),
        ),
    )


@mutable_receiver(model_activity_signal, sender=SignalTeamConfig)
def handle_signal_team_config_change(
    sender: type[SignalTeamConfig],
    scope: ActivityScope,
    before_update: SignalTeamConfig | None,
    after_update: SignalTeamConfig | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance: SignalTeamConfig | None = after_update or before_update
    if instance is None:
        return

    # On create, diff against a fresh default row rather than None. `changes_between` yields
    # nothing when `previous` is None, which would drop the create branch of update_or_create() —
    # the path Slack onboarding takes to set a channel on a team whose row was never materialized.
    # Diffing against defaults keeps an all-default create (team creation, lazy read) silent while
    # still auditing a create that carries a non-default value.
    previous = before_update if before_update is not None else SignalTeamConfig()
    changes = changes_between(scope, previous=previous, current=after_update)
    # Only persist saves that moved a field, which also keeps idempotent re-saves out of the log.
    if not changes:
        return

    log_activity(
        organization_id=None,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes,
            # Singleton per team, so there's no per-row name to show; label it where a reader
            # would go to find the setting instead of exposing the model name.
            name="Inbox settings",
            trigger=get_current_trigger(),
        ),
    )


@dataclasses.dataclass(frozen=True)
class SignalSourceConfigContext(ActivityContextBase):
    source_product: str
    source_type: str


def _source_config_name(instance: SignalSourceConfig) -> str:
    try:
        product_label = SIGNAL_SOURCE_PRODUCT_LABELS.get(SignalSourceProduct(instance.source_product))
    except ValueError:
        product_label = None
    return f"{product_label or instance.source_product}: {instance.get_source_type_display()}"


def _source_config_detail(instance: SignalSourceConfig, changes: list[Change]) -> Detail:
    return Detail(
        changes=changes,
        name=_source_config_name(instance),
        trigger=get_current_trigger(),
        context=SignalSourceConfigContext(source_product=instance.source_product, source_type=instance.source_type),
    )


@mutable_receiver(model_activity_signal, sender=SignalSourceConfig)
def handle_signal_source_config_change(
    sender: type[SignalSourceConfig],
    scope: ActivityScope,
    before_update: SignalSourceConfig | None,
    after_update: SignalSourceConfig | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance: SignalSourceConfig | None = after_update or before_update
    if instance is None:
        return

    # A create diffs against a default row, so a source created with a config, such as an issue
    # filter, records what it held before the first edit.
    previous = before_update if before_update is not None else SignalSourceConfig()
    log_activity(
        organization_id=None,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=_source_config_detail(instance, changes_between(scope, previous=previous, current=after_update)),
    )


def log_source_configs_disabled(rows: list[SignalSourceConfig]) -> None:
    """Log rows that a bulk `update(enabled=False)` turned off, which `ModelActivityMixin` never sees.

    Pass the rows as they were read before the update, and only those that were enabled.
    """
    user = get_current_user()
    was_impersonated = get_was_impersonated()
    entries: list[LogActivityEntry] = [
        LogActivityEntry(
            organization_id=None,
            team_id=row.team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=row.id,
            scope="SignalSourceConfig",
            activity="updated",
            detail=_source_config_detail(
                row,
                [Change(type="SignalSourceConfig", field="enabled", action="changed", before=True, after=False)],
            ),
        )
        for row in rows
    ]
    bulk_log_activity(entries)
