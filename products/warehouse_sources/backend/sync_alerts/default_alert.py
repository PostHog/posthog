"""The sync failure email alert a project gets with its first warehouse source.

It replaces the daily failure digest email for the project. The same people get it, because the
alert emails the members the pipeline error emails reach. A person can edit or delete it like any
other alert. A marker on the project's warehouse config records that the default was decided, so a
deleted default never comes back, and a project that already set up its own alert gets none.
"""

from enum import StrEnum
from typing import Final

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.permissions import posthog_feature_flag_enabled

from products.alerts_platform.backend.facade.api import create_configuration, list_configurations
from products.alerts_platform.backend.facade.contracts import (
    Grouping,
    GroupingMode,
    PlatformAlertConfigurationEdit,
    SourceKind,
)
from products.data_warehouse.backend.facade.models import TeamDataWarehouseConfig
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.sync_alerts.wording import SOURCE_ID_KEY

logger = structlog.get_logger(__name__)

DEFAULT_FAILURE_ALERT_FLAG: Final = "dwh-platform-failure-email"
DEFAULT_FAILURE_ALERT_NAME: Final = "Warehouse sync failures"

_SOURCE_KINDS: Final = (SourceKind.WAREHOUSE_SOURCE.value,)
_PAGE_SIZE: Final = 100

# One instance per source, so a source that fails many tables sends one email rather than one per
# table. Billing limits stay out, because billing already tells the project about its limits and the
# digest this replaces never listed them.
DEFAULT_FAILURE_ALERT: Final = PlatformAlertConfigurationEdit(
    name=DEFAULT_FAILURE_ALERT_NAME,
    enabled=True,
    source_config={"source_ids": [], "group_by": "source", "email_project_members": True},
    grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=(SOURCE_ID_KEY,)),
    schedule_restriction=None,
    evaluation_periods=1,
    datapoints_to_alarm=1,
    cooldown_minutes=0,
)


class DefaultAlertOutcome(StrEnum):
    CREATED = "created"
    HAS_OWN_ALERT = "has_own_alert"
    ALREADY_DECIDED = "already_decided"
    NO_SOURCE = "no_source"
    FLAG_OFF = "flag_off"


def failure_email_enabled(team: Team) -> bool:
    """Whether alerts replace the failure digest for this project. A flag that cannot be read is off,
    which keeps the digest, so a flags outage costs a duplicate email and never a missing one."""
    try:
        return posthog_feature_flag_enabled(
            DEFAULT_FAILURE_ALERT_FLAG, str(team.uuid), organization_id=team.organization_id, team_id=team.id
        )
    except Exception as error:
        capture_exception(error, {"team_id": team.id})
        return False


def ensure_default_failure_alert(team: Team, *, dry_run: bool = False) -> DefaultAlertOutcome:
    """Create the project's default failure alert, once. With `dry_run`, say what would happen and write nothing."""
    if not failure_email_enabled(team):
        return DefaultAlertOutcome.FLAG_OFF
    if dry_run:
        decided_at = (
            TeamDataWarehouseConfig.objects.filter(team_id=team.id)
            .values_list("default_failure_alert_at", flat=True)
            .first()
        )
        return _decide(team.id, already_decided=decided_at is not None)
    with transaction.atomic():
        get_or_create_team_extension(team, TeamDataWarehouseConfig)
        # Locked, so two sources created at once give the project one default.
        config = TeamDataWarehouseConfig.objects.select_for_update().get(team_id=team.id)
        outcome = _decide(team.id, already_decided=config.default_failure_alert_at is not None)
        if outcome == DefaultAlertOutcome.CREATED:
            with team_scope(team.id):
                create_configuration(
                    team_id=team.id,
                    source_kind=SourceKind.WAREHOUSE_SOURCE,
                    edit=DEFAULT_FAILURE_ALERT,
                    created_by_id=None,
                )
        if outcome in (DefaultAlertOutcome.CREATED, DefaultAlertOutcome.HAS_OWN_ALERT):
            config.default_failure_alert_at = timezone.now()
            config.save(update_fields=["default_failure_alert_at"])
    return outcome


def ensure_default_failure_alert_safely(team: Team) -> None:
    """For a caller whose own work must not fail because the default alert could not be made."""
    try:
        outcome = ensure_default_failure_alert(team)
    except Exception as error:
        capture_exception(error, {"team_id": team.id})
        return
    if outcome == DefaultAlertOutcome.CREATED:
        logger.info("warehouse_default_failure_alert_created", team_id=team.id)


def emails_replace_failure_digest(team: Team) -> bool:
    """Whether an enabled alert emails the project members about every source, so the digest would repeat it.

    An alert scoped to some sources does not count, because the digest also covers the others.
    """
    if not failure_email_enabled(team):
        return False
    offset = 0
    while True:
        with team_scope(team.id):
            page = list_configurations(team_id=team.id, source_kinds=_SOURCE_KINDS, limit=_PAGE_SIZE, offset=offset)
        for configuration in page.configurations:
            config = configuration.source_config
            if configuration.enabled and config.get("email_project_members") and not config.get("source_ids"):
                return True
        offset += len(page.configurations)
        if not page.configurations or offset >= page.total:
            return False


def _decide(team_id: int, *, already_decided: bool) -> DefaultAlertOutcome:
    if already_decided:
        return DefaultAlertOutcome.ALREADY_DECIDED
    if not ExternalDataSource.objects.filter(team_id=team_id).exclude(deleted=True).exists():
        return DefaultAlertOutcome.NO_SOURCE
    with team_scope(team_id):
        has_own_alert = list_configurations(team_id=team_id, source_kinds=_SOURCE_KINDS, limit=1, offset=0).total > 0
    return DefaultAlertOutcome.HAS_OWN_ALERT if has_own_alert else DefaultAlertOutcome.CREATED
