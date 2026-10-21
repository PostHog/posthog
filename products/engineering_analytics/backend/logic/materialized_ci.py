from datetime import datetime
from typing import TYPE_CHECKING

from django.db.models import OuterRef, Subquery

import structlog
import posthoganalytics

from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.escape_sql import escape_hogql_string

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.api import (
    definition_fingerprint,
    get_incremental_config,
    get_incremental_state,
    is_materialization_fresh,
)
from products.data_modeling.backend.facade.models import DataModelingJob, DataWarehouseSavedQuery
from products.engineering_analytics.backend.facade.contracts import MATERIALIZED_VIEWS_FEATURE_FLAG, CIDataFreshness
from products.engineering_analytics.backend.logic.sources import GitHubTables, resolve_job_source_tables
from products.engineering_analytics.backend.logic.views import ci_rows, depot_ci, workflow_jobs, workflow_runs
from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

    from posthog.models.team import Team

logger = structlog.get_logger(__name__)

MAX_MATERIALIZATION_AGE = ci_rows.SYNC_FREQUENCY * 2


def materialized_views_enabled(team: "Team") -> bool | None:
    org_id = str(team.organization_id)
    project_id = str(team.id)
    try:
        return posthoganalytics.feature_enabled(
            MATERIALIZED_VIEWS_FEATURE_FLAG,
            str(team.uuid),
            groups={"organization": org_id, "project": project_id},
            group_properties={"organization": {"id": org_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("engineering_analytics_materialized_flag_unavailable", team_id=team.id, exc_info=True)
        return None


@frozen
class MaterializedCI:
    source_id: str
    repository: str
    freshness: CIDataFreshness
    cache_scope: str

    @classmethod
    def resolve(
        cls,
        *,
        team: "Team",
        tables: GitHubTables,
        depot: depot_ci.DepotJobAttempts | None,
        catalog: "Database",
    ) -> "MaterializedCI | None":
        if not tables.workflow_jobs or materialized_views_enabled(team) is not True:
            return None
        sources = resolve_job_source_tables(team)
        selected = next(
            (
                source
                for source in sources
                if source.source_id == tables.source_id and source.repository.casefold() == tables.repository.casefold()
            ),
            None,
        )
        # Stored rows embed the system resolver's Depot selection, which can differ from the caller's.
        if (
            selected is None
            or selected.github_workflow_runs != tables.workflow_runs
            or selected.github_workflow_jobs != tables.workflow_jobs
            or selected.pull_requests != tables.pull_requests
            or selected.depot_job_attempts != depot
        ):
            return None
        raw_tables = [tables.pull_requests, tables.workflow_runs, tables.workflow_jobs]
        if depot is not None:
            raw_tables.append(depot.table)
        if not all(catalog.has_table(name) and not catalog.is_table_access_denied(name) for name in raw_tables):
            return None

        # Read completion and its published table in one snapshot, so publication cannot race readiness.
        jobs = DataModelingJob.objects.filter(
            team_id=team.id,
            engine=DataModelingJob.Engine.CLICKHOUSE,
            saved_query__team_id=team.id,
            saved_query__origin=DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET,
            saved_query__managed_viewset__kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS,
            saved_query__deleted=False,
            saved_query__is_materialized=True,
            saved_query__table__deleted=False,
        ).select_related("saved_query__table")
        materialized_at: dict[str, datetime] = {}
        started_at: dict[str, datetime] = {}
        for name, fields, config, sql in (
            (
                ci_rows.RUNS_VIEW_NAME,
                ci_rows.RUN_FIELDS,
                ci_rows.RUN_INCREMENTAL_CONFIG,
                "\nUNION ALL\n".join(ci_rows.runs_select(source) for source in sources),
            ),
            (
                ci_rows.JOBS_VIEW_NAME,
                ci_rows.JOB_FIELDS,
                ci_rows.JOB_INCREMENTAL_CONFIG,
                "\nUNION ALL\n".join(ci_rows.jobs_select(source) for source in sources),
            ),
        ):
            job = jobs.filter(saved_query__name=name).order_by("-last_run_at").first()
            view = job.saved_query if job is not None else None
            if (
                job is None
                or job.status != DataModelingJob.Status.COMPLETED
                or view is None
                or view.table is None
                or view.table.team_id != team.id
                or not fields.keys() <= (view.table.columns or {}).keys()
                or view.query != {"kind": "HogQLQuery", "query": sql}
                or view.incremental_config != config
                or not catalog.has_table(name)
                or catalog.is_table_access_denied(name)
            ):
                return None
            table = catalog.get_table(name)
            if (
                not isinstance(table, HogQLDataWarehouseTable)
                or table.saved_query_id != str(view.id)
                or table.table_id != str(view.table_id)
                or table.url != view.table.url_pattern
                or table.queryable_folder != view.table.queryable_folder
                or not fields.keys() <= table.fields.keys()
            ):
                return None
            incremental = get_incremental_config(view)
            fingerprint = definition_fingerprint(view.query, incremental) if incremental is not None else None
            if fingerprint is None or fingerprint != get_incremental_state(view).definition_fingerprint:
                return None
            completed_at = job.last_run_at
            if not is_materialization_fresh(completed_at, int(MAX_MATERIALIZATION_AGE.total_seconds())):
                return None
            materialized_at[name] = completed_at
            started_at[name] = job.created_at

        runs_at = materialized_at[ci_rows.RUNS_VIEW_NAME]
        jobs_at = materialized_at[ci_rows.JOBS_VIEW_NAME]
        # Later source syncs do not make an older stored result more current.
        completed_import = ExternalDataJob.objects.filter(
            team_id=team.id,
            pipeline_id=OuterRef("source_id"),
            schema_id=OuterRef("id"),
            status=ExternalDataJob.Status.COMPLETED,
        ).order_by("-finished_at")
        schemas = ExternalDataSchema.objects.filter(
            team_id=team.id, table__name__in=raw_tables, deleted=False, should_sync=True
        )
        consumed_schemas = schemas.annotate(
            consumed_sync=Subquery(
                completed_import.filter(finished_at__lte=min(started_at.values())).values("created_at")[:1]
            )
        )
        frontiers: dict[str, datetime | None] = dict(consumed_schemas.values_list("table__name", "consumed_sync"))

        def synced_at(table: str) -> datetime | None:
            names = [table, *([depot.table] if depot else [])]
            times = [frontiers.get(name) for name in names]
            return min(time for time in times if time is not None) if all(time is not None for time in times) else None

        return cls(
            source_id=tables.source_id,
            repository=tables.repository.casefold(),
            freshness=CIDataFreshness(
                runs_synced_at=synced_at(tables.workflow_runs), jobs_synced_at=synced_at(tables.workflow_jobs)
            ),
            cache_scope=f"materialized:{runs_at.isoformat()}:{jobs_at.isoformat()}",
        )

    def _scope(self) -> str:
        return (
            f"source_id = {escape_hogql_string(self.source_id)} AND repository = {escape_hogql_string(self.repository)}"
        )

    def runs(self, *, started_floor: bool = False, include_shells: bool = False) -> str:
        columns = [column for column in ci_rows.RUN_COLUMNS if column != "is_handoff_shell"]
        floor = " AND run_started_at_raw >= {run_started_floor}" if started_floor else ""
        shells = "" if include_shells else " AND NOT is_handoff_shell"
        return f"""SELECT {", ".join(columns)}, {workflow_runs.STOPPED_REPORTING_SQL} AS stopped_reporting
            FROM {ci_rows.RUNS_VIEW_NAME} WHERE {self._scope()}{shells}{floor}"""

    def jobs(self, *, created_floor: bool = False, with_cost: bool = False) -> str:
        columns = (
            [column for column in ci_rows.JOB_COLUMNS if column != "is_handoff_shell"]
            if with_cost
            else workflow_jobs.COLUMNS
        )
        floor = " AND created_at_raw >= {job_created_floor}" if created_floor else ""
        return f"""SELECT {", ".join(columns)} FROM {ci_rows.JOBS_VIEW_NAME}
            WHERE {self._scope()} AND NOT is_handoff_shell{floor}"""
