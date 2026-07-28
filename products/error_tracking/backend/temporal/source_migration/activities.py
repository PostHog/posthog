"""Source-agnostic Temporal activities for error tracking migrations.

Everything source-specific goes through the MigrationSourceAdapter resolved from the
migration's source_type — no per-source branches here.
"""

from typing import Any

import structlog
from temporalio import activity, workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from posthog.hogql.query import execute_hogql_query

    from posthog.api.capture import capture_batch_internal
    from posthog.models import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.error_tracking.backend.logic import issue_mutations
    from products.error_tracking.backend.models import (
        ErrorTrackingIssue,
        ErrorTrackingIssueFingerprintV2,
        ErrorTrackingMigration,
    )
    from products.error_tracking.backend.temporal.source_migration.base import (
        MigrationSourceAdapter,
        TransformContext,
        get_adapter,
    )
    from products.error_tracking.backend.temporal.source_migration.constants import (
        EVENT_SOURCE,
        IMPORT_PAGE_SIZE,
        STATUS_SYNC_CHUNK_SIZE,
        STATUS_SYNC_PAGE_SIZE,
    )
    from products.error_tracking.backend.temporal.source_migration.types import (
        ImportResult,
        ImportTablesInputs,
        MigrationContext,
        MigrationInputs,
        PlanResult,
        SetStatusInputs,
        StatusSyncResult,
        SyncCheckResult,
    )
    from products.warehouse_sources.backend.facade import api as warehouse_api

logger = structlog.get_logger(__name__)


def _get_migration(migration_id: str, team_id: int) -> ErrorTrackingMigration:
    return ErrorTrackingMigration.objects.for_team(team_id).get(id=migration_id)


def _adapter_for(migration: ErrorTrackingMigration) -> MigrationSourceAdapter:
    return get_adapter(migration.source_type)


def _rows_as_dicts(response: Any) -> list[dict[str, Any]]:
    columns = response.columns or []
    return [dict(zip(columns, row)) for row in response.results or []]


@activity.defn
async def get_migration_context_activity(inputs: MigrationInputs) -> MigrationContext:
    def _sync() -> MigrationContext:
        migration = _get_migration(inputs.migration_id, inputs.team_id)
        adapter = _adapter_for(migration)
        config_error = adapter.validate_config(migration.config)
        if config_error is not None:
            raise ApplicationError(config_error, non_retryable=True)
        try:
            source = warehouse_api.get_source(migration.external_data_source_id, inputs.team_id)
        except Exception as e:
            raise ApplicationError(
                f"Warehouse source {migration.external_data_source_id} not found", non_retryable=True
            ) from e
        if source.source_type != adapter.external_source_type:
            raise ApplicationError(
                f"Source {source.id} is type {source.source_type}, expected {adapter.external_source_type}",
                non_retryable=True,
            )
        migration.status = ErrorTrackingMigration.Status.SYNCING
        migration.save(update_fields=["status", "updated_at"])
        return MigrationContext(source_type=migration.source_type, source_id=str(source.id))

    return await database_sync_to_async(_sync, thread_sensitive=False)()


@activity.defn
async def check_warehouse_sync_activity(inputs: MigrationInputs) -> SyncCheckResult:
    def _sync() -> SyncCheckResult:
        migration = _get_migration(inputs.migration_id, inputs.team_id)
        adapter = _adapter_for(migration)
        schemas = {
            s.name: s for s in warehouse_api.list_schemas_for_source(migration.external_data_source_id, inputs.team_id)
        }
        tables: dict[str, str] = {}
        for role, schema_name in adapter.schema_roles.items():
            schema = schemas.get(schema_name)
            if schema is None or not schema.should_sync:
                return SyncCheckResult(ready=False, reason=f"Schema '{schema_name}' is not enabled on the source")
            if not schema.initial_sync_complete or schema.table_id is None:
                return SyncCheckResult(ready=False, reason=f"Schema '{schema_name}' has not completed its initial sync")
            tables[role] = warehouse_api.get_table(schema.table_id, inputs.team_id).name
        return SyncCheckResult(ready=True, tables=tables)

    return await database_sync_to_async(_sync, thread_sensitive=False)()


@activity.defn
async def plan_import_activity(inputs: ImportTablesInputs) -> PlanResult:
    def _sync() -> PlanResult:
        migration = _get_migration(inputs.migration_id, inputs.team_id)
        adapter = _adapter_for(migration)
        team = Team.objects.get(id=inputs.team_id)
        query, placeholders = adapter.build_events_count_query(inputs.tables, migration.config)
        response = execute_hogql_query(query=query, team=team, placeholders=placeholders)
        events_total, issues_total = (response.results or [(0, 0)])[0]
        migration.status = ErrorTrackingMigration.Status.IMPORTING
        migration.state = {
            **migration.state,
            "events_total": int(events_total),
            "issues_total": int(issues_total),
        }
        migration.save(update_fields=["status", "state", "updated_at"])
        return PlanResult(issues_total=int(issues_total), events_total=int(events_total))

    return await database_sync_to_async(_sync, thread_sensitive=False)()


def _run_import(inputs: ImportTablesInputs) -> ImportResult:
    migration = _get_migration(inputs.migration_id, inputs.team_id)
    adapter = _adapter_for(migration)
    team = Team.objects.get(id=inputs.team_id)

    state = dict(migration.state)
    cursor: dict[str, Any] | None = state.get("cursor")
    emitted = int(state.get("events_emitted", 0))
    dropped = int(state.get("events_dropped", 0))
    ctx = TransformContext(config=migration.config, import_job_id=str(migration.id), anchored_issue_ids=set())

    while True:
        query, placeholders = adapter.build_events_page_query(inputs.tables, migration.config, cursor, IMPORT_PAGE_SIZE)
        response = execute_hogql_query(query=query, team=team, placeholders=placeholders)
        rows = _rows_as_dicts(response)
        if not rows:
            break

        batch: list[dict[str, Any]] = []
        for row in rows:
            batch.extend(adapter.events_for_row(row, ctx))

        if batch:
            result = capture_batch_internal(
                events=batch,
                token=team.api_token,
                event_source=EVENT_SOURCE,
                historical_migration=True,
            )
            if result.error is not None or result.unaccounted:
                raise ApplicationError(
                    f"capture_batch_internal failed: {result.error} "
                    f"(status={result.status_code}, unaccounted={len(result.unaccounted)})"
                )
            emitted += len(result.ok)
            # Quota-limited teams get per-event drops rather than errors; surface, don't fail.
            dropped += len(result.dropped)

        cursor = adapter.event_cursor(rows[-1])
        migration.refresh_from_db(fields=["state"])
        migration.state = {
            **migration.state,
            "cursor": cursor,
            "events_emitted": emitted,
            "events_dropped": dropped,
        }
        migration.save(update_fields=["state", "updated_at"])

    return ImportResult(events_emitted=emitted, events_dropped=dropped)


@activity.defn
async def import_events_activity(inputs: ImportTablesInputs) -> ImportResult:
    async with Heartbeater():
        return await database_sync_to_async(_run_import, thread_sensitive=False)(inputs)


@activity.defn
async def count_imported_fingerprints_activity(inputs: MigrationInputs) -> int:
    def _sync() -> int:
        migration = _get_migration(inputs.migration_id, inputs.team_id)
        adapter = _adapter_for(migration)
        prefix = adapter.fingerprint_prefix(migration.config)
        return ErrorTrackingIssueFingerprintV2.objects.filter(
            team_id=inputs.team_id, fingerprint__startswith=prefix
        ).count()

    return await database_sync_to_async(_sync, thread_sensitive=False)()


def _run_status_sync(inputs: ImportTablesInputs) -> StatusSyncResult:
    migration = _get_migration(inputs.migration_id, inputs.team_id)
    adapter = _adapter_for(migration)
    if migration.created_by is None:
        # Status mutations are activity-logged against a user; without one we leave
        # every imported issue active rather than writing unattributed changes.
        return StatusSyncResult(resolved=0, suppressed=0, skipped_reason="Migration has no creating user")

    team = Team.objects.get(id=inputs.team_id)
    by_status: dict[ErrorTrackingIssue.Status, list[str]] = {}
    cursor: str | None = None

    while True:
        query, placeholders = adapter.build_issue_status_page_query(inputs.tables, cursor, STATUS_SYNC_PAGE_SIZE)
        response = execute_hogql_query(query=query, team=team, placeholders=placeholders)
        rows = response.results or []
        if not rows:
            break
        for issue_key, raw_status in rows:
            target = adapter.map_status(raw_status)
            if target is not None:
                by_status.setdefault(target, []).append(str(issue_key))
        cursor = str(rows[-1][0])

    counts = {ErrorTrackingIssue.Status.RESOLVED: 0, ErrorTrackingIssue.Status.SUPPRESSED: 0}
    for target_status, issue_keys in by_status.items():
        for start in range(0, len(issue_keys), STATUS_SYNC_CHUNK_SIZE):
            chunk = issue_keys[start : start + STATUS_SYNC_CHUNK_SIZE]
            fingerprints = [adapter.issue_fingerprint(migration.config, issue_key) for issue_key in chunk]
            issue_ids = [
                str(issue_id)
                for issue_id in ErrorTrackingIssueFingerprintV2.objects.filter(
                    team_id=inputs.team_id, fingerprint__in=fingerprints
                ).values_list("issue_id", flat=True)
            ]
            if not issue_ids:
                continue
            issue_mutations.bulk_update_issues(
                inputs.team_id,
                issue_ids,
                action="set_status",
                status=target_status.value,
                assignee=None,
                user=migration.created_by,
                was_impersonated=False,
            )
            counts[target_status] += len(issue_ids)

    return StatusSyncResult(
        resolved=counts[ErrorTrackingIssue.Status.RESOLVED],
        suppressed=counts[ErrorTrackingIssue.Status.SUPPRESSED],
    )


@activity.defn
async def sync_issue_status_activity(inputs: ImportTablesInputs) -> StatusSyncResult:
    async with Heartbeater():
        return await database_sync_to_async(_run_status_sync, thread_sensitive=False)(inputs)


@activity.defn
async def set_migration_status_activity(inputs: SetStatusInputs) -> None:
    def _sync() -> None:
        migration = _get_migration(inputs.migration_id, inputs.team_id)
        migration.status = ErrorTrackingMigration.Status(inputs.status)
        update_fields = ["status", "updated_at"]
        if inputs.error is not None:
            migration.latest_error = inputs.error
            update_fields.append("latest_error")
        migration.save(update_fields=update_fields)

    await database_sync_to_async(_sync, thread_sensitive=False)()
