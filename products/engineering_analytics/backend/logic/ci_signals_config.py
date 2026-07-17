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
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

CI_SIGNAL_SOURCE_TYPES = (
    SOURCE_TYPE_FLAKY_CHECK,
    SOURCE_TYPE_BROKEN_DEFAULT_BRANCH,
    SOURCE_TYPE_DURATION_REGRESSION,
)
CI_SIGNAL_REQUIRED_SCHEMAS = (PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA)
# SignalSourceConfig.config key: the source ids the enabling user authorized the sweep to read.
AUTHORIZED_SOURCES_CONFIG_KEY = "github_source_ids"
# SignalSourceConfig.config key: detect and log, emit nothing. Mirrors the scout's `emit` flag.
DRY_RUN_CONFIG_KEY = "dry_run"


def is_dry_run(*, team: Team) -> bool:
    row = (
        SignalSourceConfig.objects.filter(team=team, source_product=SOURCE_PRODUCT, source_type=SOURCE_TYPE_FLAKY_CHECK)
        .only("config")
        .first()
    )
    if row is None or not isinstance(row.config, dict):
        return False
    return bool(row.config.get(DRY_RUN_CONFIG_KEY, False))


def get_ci_signals_config(*, team: Team, user_access_control: UserAccessControl | None = None) -> CISignalsConfig:
    state = signal_source_types_state(
        team_id=team.id,
        source_product=SOURCE_PRODUCT,
        source_types=CI_SIGNAL_SOURCE_TYPES,
    )
    return CISignalsConfig(
        configured=state.configured,
        enabled=state.all_enabled,
        sync_status=_sync_status(team, user_access_control),
    )


def update_ci_signals_config(
    *,
    team: Team,
    enabled: bool,
    created_by_id: int,
    user_access_control: UserAccessControl | None = None,
) -> CISignalsConfig:
    """Enable or disable the CI-signals bundle. Enabling snapshots the requesting user's accessible
    GitHub sources as the userless sweep's authorization; a source connected later isn't scanned
    until a re-enable authorizes it."""
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
    return get_ci_signals_config(team=team, user_access_control=user_access_control)


def resolve_authorizer(*, team: Team, user_id: int) -> User | None:
    """The user whose access authorizes a sweep read, or None once deactivated or out of the org.
    Discovery and the detection activity both resolve through here so the gates can't diverge."""
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None or not user.organization_memberships.filter(organization_id=team.organization_id).exists():
        return None
    return user


@dataclass(frozen=True)
class AuthorizedCISignalSource:
    source_id: str
    authorized_by_user_id: int


def list_authorized_ci_signal_sources(*, team: Team) -> list[AuthorizedCISignalSource]:
    """The sources the coordinator may scan: the enabled snapshot re-filtered through the enabling
    user's *current* access. Every edge fails closed (deleted/revoked source, missing snapshot,
    deactivated authorizer) — never widens to all of the team's sources."""
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
    user = resolve_authorizer(team=team, user_id=row.created_by_id)
    if user is None:
        return []
    access_control = UserAccessControl(user=user, team=team)
    accessible = {source.id for source in list_github_sources(team=team, user_access_control=access_control)}
    return [
        AuthorizedCISignalSource(source_id=source_id, authorized_by_user_id=user.id)
        for source_id in snapshot
        if source_id in accessible
    ]


def _sync_status(team: Team, user_access_control: UserAccessControl | None) -> CISignalsSyncStatus | None:
    source_ids: set[UUID] = {
        UUID(source.id) for source in list_github_sources(team=team, user_access_control=user_access_control)
    }
    if not source_ids:
        return None
    schemas = list(
        ExternalDataSchema.objects.filter(
            team_id=team.id,
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
