from dataclasses import dataclass
from uuid import UUID

from posthog.models.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl

from products.engineering_analytics.backend.facade.contracts import CISignalsConfig, CISignalsSyncStatus
from products.engineering_analytics.backend.logic.signals.contracts import (
    SOURCE_PRODUCT,
    SOURCE_TYPE_BROKEN_DEFAULT_BRANCH,
    SOURCE_TYPE_DURATION_REGRESSION,
    SOURCE_TYPE_FLAKY_CHECK,
)
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    list_github_sources,
)
from products.signals.backend.facade.api import set_signal_source_types_enabled, signal_source_types_state
from products.signals.backend.models import SignalSourceConfig
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

CI_SIGNAL_SOURCE_TYPES = (
    SOURCE_TYPE_FLAKY_CHECK,
    SOURCE_TYPE_BROKEN_DEFAULT_BRANCH,
    SOURCE_TYPE_DURATION_REGRESSION,
)
CI_SIGNAL_REQUIRED_SCHEMAS = (PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA)
# SignalSourceConfig.config key holding the GitHub source ids the enabling user was authorized to
# read. The coordinator scans only this snapshot — never "all of the team's sources".
AUTHORIZED_SOURCES_CONFIG_KEY = "github_source_ids"


def get_ci_signals_config(*, team: Team) -> CISignalsConfig:
    state = signal_source_types_state(
        team_id=team.id,
        source_product=SOURCE_PRODUCT,
        source_types=CI_SIGNAL_SOURCE_TYPES,
    )
    return CISignalsConfig(configured=state.configured, enabled=state.all_enabled, sync_status=_sync_status(team.id))


def update_ci_signals_config(
    *,
    team: Team,
    enabled: bool,
    created_by_id: int,
    user_access_control: UserAccessControl | None = None,
) -> CISignalsConfig:
    """Enable or disable the CI-signals bundle.

    Enabling snapshots the GitHub sources the requesting user may access (per their warehouse
    RBAC) as the sweep's authorization. The coordinator is userless, so this explicit snapshot —
    not team membership — is what lets it read a source; a source connected after enabling isn't
    scanned until someone re-enables and thereby authorizes it."""
    config = None
    if enabled:
        authorized = [source.id for source in list_github_sources(team=team, user_access_control=user_access_control)]
        config = {AUTHORIZED_SOURCES_CONFIG_KEY: authorized}
    set_signal_source_types_enabled(
        team_id=team.id,
        source_product=SOURCE_PRODUCT,
        source_types=CI_SIGNAL_SOURCE_TYPES,
        enabled=enabled,
        created_by_id=created_by_id,
        config=config,
    )
    return get_ci_signals_config(team=team)


@dataclass(frozen=True)
class AuthorizedCISignalSource:
    """One GitHub source the CI-signals sweep may scan, and the user whose access authorizes it."""

    source_id: str
    authorized_by_user_id: int


def list_authorized_ci_signal_sources(*, team: Team) -> list[AuthorizedCISignalSource]:
    """The GitHub sources the CI-signals coordinator may scan for ``team``.

    Fail-closed on every edge: the enabled snapshot is re-filtered through the enabling user's
    *current* access, so a source deleted or revoked since enabling drops out; a missing snapshot
    (legacy rows), a deleted or deactivated enabling user, or a disabled bundle yield nothing.
    Never widens to "all of the team's sources" — the sweep runs with no request user, so the
    snapshot plus the authorizer's live RBAC is its entire authorization."""
    row = (
        SignalSourceConfig.objects.filter(
            team_id=team.id,
            source_product=SOURCE_PRODUCT,
            source_type__in=CI_SIGNAL_SOURCE_TYPES,
            enabled=True,
        )
        .order_by("-updated_at")
        .first()
    )
    if row is None or row.created_by_id is None:
        return []
    snapshot = row.config.get(AUTHORIZED_SOURCES_CONFIG_KEY) if isinstance(row.config, dict) else None
    if not isinstance(snapshot, list) or not snapshot:
        return []
    user = User.objects.filter(id=row.created_by_id, is_active=True).first()
    if user is None:
        return []
    access_control = UserAccessControl(user=user, team=team)
    accessible = {source.id for source in list_github_sources(team=team, user_access_control=access_control)}
    return [
        AuthorizedCISignalSource(source_id=source_id, authorized_by_user_id=user.id)
        for source_id in snapshot
        if source_id in accessible
    ]


def _sync_status(team_id: int) -> CISignalsSyncStatus | None:
    source_ids: set[UUID] = set(
        ExternalDataSource.objects.filter(
            team_id=team_id,
            source_type=ExternalDataSourceType.GITHUB,
        )
        .exclude(deleted=True)
        .values_list("id", flat=True)
    )
    if not source_ids:
        return None
    schemas = list(
        ExternalDataSchema.objects.filter(
            team_id=team_id,
            source_id__in=source_ids,
            name__in=CI_SIGNAL_REQUIRED_SCHEMAS,
            should_sync=True,
        )
        .exclude(source__deleted=True)
        .exclude(deleted=True)
        .values_list("source_id", "name", "status")
    )
    failure_statuses = {
        ExternalDataSchema.Status.FAILED,
        ExternalDataSchema.Status.BILLING_LIMIT_REACHED,
        ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW,
    }
    completed_by_source: dict[UUID, set[str]] = {}
    for source_id, name, status in schemas:
        if status == ExternalDataSchema.Status.COMPLETED:
            completed_by_source.setdefault(source_id, set()).add(name)
    required = set(CI_SIGNAL_REQUIRED_SCHEMAS)
    if any(status in failure_statuses for _, _, status in schemas):
        return CISignalsSyncStatus.FAILED
    if all(completed_by_source.get(source_id, set()) >= required for source_id in source_ids):
        return CISignalsSyncStatus.COMPLETED
    return CISignalsSyncStatus.RUNNING
