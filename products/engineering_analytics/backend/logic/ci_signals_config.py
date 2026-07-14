from uuid import UUID

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import CISignalsConfig, CISignalsSyncStatus
from products.engineering_analytics.backend.logic.signals.contracts import (
    SOURCE_PRODUCT,
    SOURCE_TYPE_BROKEN_MASTER,
    SOURCE_TYPE_DURATION_REGRESSION,
    SOURCE_TYPE_FLAKY_CHECK,
)
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
)
from products.signals.backend.facade.api import set_signal_source_types_enabled, signal_source_types_state
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

CI_SIGNAL_SOURCE_TYPES = (
    SOURCE_TYPE_FLAKY_CHECK,
    SOURCE_TYPE_BROKEN_MASTER,
    SOURCE_TYPE_DURATION_REGRESSION,
)
CI_SIGNAL_REQUIRED_SCHEMAS = (PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA)


def get_ci_signals_config(*, team: Team) -> CISignalsConfig:
    state = signal_source_types_state(
        team_id=team.id,
        source_product=SOURCE_PRODUCT,
        source_types=CI_SIGNAL_SOURCE_TYPES,
    )
    return CISignalsConfig(configured=state.configured, enabled=state.all_enabled, sync_status=_sync_status(team.id))


def update_ci_signals_config(*, team: Team, enabled: bool, created_by_id: int) -> CISignalsConfig:
    set_signal_source_types_enabled(
        team_id=team.id,
        source_product=SOURCE_PRODUCT,
        source_types=CI_SIGNAL_SOURCE_TYPES,
        enabled=enabled,
        created_by_id=created_by_id,
    )
    return get_ci_signals_config(team=team)


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
