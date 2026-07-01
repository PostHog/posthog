"""Materialization lifecycle for endpoint versions.

``EndpointMaterializationService`` owns enabling/disabling materialization
(creating and reverting the backing ``DataWarehouseSavedQuery``), the
materialization preview, and the status payload. The AST-level analysis and
query transforms live in ``products.endpoints.backend.materialization_transforms``.
"""

import dataclasses
from typing import cast

import structlog
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.request import Request

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.printer.utils import print_prepared_ast

from posthog.clickhouse.query_tagging import Product
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Detail, log_activity

from products.data_modeling.backend.facade.api import (
    UnsatisfiableFrequencyError,
    UnsupportedFrequencyTargetError,
    delete_node_from_dag,
    sync_saved_query_to_dag,
)
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.endpoints.backend.constants import DATA_FRESHNESS_BUCKETS
from products.endpoints.backend.materialization_transforms import (
    MaterializationNotSupportedError,
    _extract_aggregate_name,
    analyze_variables_for_materialization,
    build_endpoint_hogql,
    convert_insight_query_to_hogql,
    get_reaggregation,
    transform_query_for_materialization,
)
from products.endpoints.backend.metrics import ENDPOINT_MATERIALIZATION_EVENT_TOTAL
from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.endpoints.backend.rate_limit import clear_endpoint_materialization_cache
from products.endpoints.backend.services.activity import EndpointContext
from products.endpoints.backend.services.strategies import apply_where_filter, strategy_for
from products.warehouse_sources.backend.facade.models import sync_frequency_to_sync_frequency_interval

logger = structlog.get_logger(__name__)


class OrphanedEndpointSavedQueryError(Exception):
    pass


def prepare_executable_query(saved_query: DataWarehouseSavedQuery) -> None:
    """Rebuild the saved query's executable HogQL from its endpoint version.

    Called by the data-modeling Temporal workflow before each materialization run,
    so query-printer changes and bucket overrides are always reflected.
    """
    version = saved_query.endpoint_versions.first()
    if version is None:
        raise OrphanedEndpointSavedQueryError(
            f"Saved query {saved_query.id} ({saved_query.name}) has no linked EndpointVersion"
        )

    saved_query.query = build_endpoint_hogql(
        version.query,
        saved_query.team,
        bucket_overrides=version.bucket_overrides,
        # Temporal rebuilds are userless and operate on an already-owned endpoint saved query.
        bypass_warehouse_access_control=True,
    )
    saved_query.save(update_fields=["query", "updated_at"])


def build_materialization_info(version: EndpointVersion, endpoint_name: str | None = None) -> dict:
    """Build the materialization status dict for a version."""
    if version.saved_query:
        result = {
            "status": version.saved_query.status or "Unknown",
            "can_materialize": True,
            "last_materialized_at": (
                version.saved_query.last_run_at.isoformat() if version.saved_query.last_run_at else None
            ),
            "error": (version.saved_query.latest_error or "")
            if version.saved_query.status != DataWarehouseSavedQuery.Status.COMPLETED
            else "",
            "saved_query_id": str(version.saved_query.id),
        }
    else:
        can_mat, reason = version.can_materialize()
        result = {
            "can_materialize": can_mat,
            "reason": reason if not can_mat else None,
        }

    if endpoint_name is not None:
        result["name"] = endpoint_name
    return result


@dataclasses.dataclass(frozen=True)
class MaterializationPreview:
    """Payload of the materialization-preview endpoint."""

    can_materialize: bool
    reason: str | None = None
    transformed_query: str | None = None
    execution_query: str | None = None
    display_execution_query: str | None = None
    range_pairs: list[dict] = dataclasses.field(default_factory=list)
    aggregates: list[dict] = dataclasses.field(default_factory=list)

    @classmethod
    def cant_materialize(cls, reason: str) -> "MaterializationPreview":
        return cls(can_materialize=False, reason=reason)


class EndpointMaterializationService:
    """Enable, disable, and preview materialization for endpoint versions."""

    def __init__(self, team: Team, request: Request):
        self.team = team
        self.request = request
        self.user = cast(User, request.user)

    def enable_materialization(
        self,
        endpoint: Endpoint,
        version: EndpointVersion,
        data_freshness_seconds: int,
        bucket_overrides: dict[str, str] | None = None,
    ) -> None:
        """Enable materialization for an endpoint version.

        Each version gets its own saved_query named {endpoint_name}_v{version}.
        """
        try:
            self._enable_materialization_inner(endpoint, version, data_freshness_seconds, bucket_overrides)
            ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="enable", status="success").inc()
            if version.saved_query:
                log_activity(
                    organization_id=self.team.organization_id,
                    team_id=self.team.pk,
                    user=self.user,
                    was_impersonated=is_impersonated(self.request),
                    item_id=str(version.saved_query.id),
                    scope="DataWarehouseSavedQuery",
                    activity="materialization_enabled",
                    detail=Detail(
                        name=version.saved_query.name,
                        context=EndpointContext(version=version.version),
                    ),
                )
        except ValidationError:
            ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="enable", status="validation_error").inc()
            raise
        except (ExposedHogQLError, MaterializationNotSupportedError) as e:
            # A bad user query, not a system fault — surface as a 400. Pre-flight validation
            # (can_materialize) normally catches these, so reaching here is a backstop.
            ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="enable", status="validation_error").inc()
            raise ValidationError(f"Cannot materialize endpoint. Reason: {e}")
        except Exception as e:
            ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="enable", status="error").inc()
            # Genuine system fault (user-query limitations are handled above). Log + capture so
            # status="error" — which the alert fires on — is never a blind spot.
            logger.exception(
                "Failed to enable endpoint materialization",
                endpoint_name=endpoint.name,
                version=version.version,
                team_id=self.team.pk,
            )
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team.pk,
                    "endpoint_name": endpoint.name,
                },
            )
            # Not a request-validation problem — surface as a server error, not a 400.
            raise APIException("Failed to enable materialization.")

    def _enable_materialization_inner(
        self,
        endpoint: Endpoint,
        version: EndpointVersion,
        data_freshness_seconds: int,
        bucket_overrides: dict[str, str] | None = None,
    ) -> None:
        can_mat, reason = version.can_materialize()
        if not can_mat:
            raise ValidationError(f"Cannot materialize endpoint. Reason: {reason}")

        saved_query = self._get_or_build_saved_query(version)
        self._configure_saved_query(saved_query, version, data_freshness_seconds, bucket_overrides)
        version.enable_materialization(saved_query, bucket_overrides)

        # The DAG node must exist before scheduling: the v2 detection and the freshness-target
        # write-through both resolve this saved query through its Node row.
        try:
            sync_saved_query_to_dag(saved_query)
        except Exception as e:
            logger.exception(
                "Failed to sync endpoint node to DAG",
                endpoint_name=endpoint.name,
                saved_query_id=saved_query.id,
            )
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team.pk,
                    "endpoint_name": endpoint.name,
                    "saved_query_id": saved_query.id,
                },
            )

        # NOTE: schedule_materialization only triggers an immediate run when it CREATES the
        # Temporal schedule; re-enabling an existing materialization just (re)syncs the schedule.
        try:
            saved_query.schedule_materialization()
        except (UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError) as e:
            # The chosen data freshness can't be honored (e.g. finer than an upstream import
            # delivers) — a request problem, not a server one.
            raise ValidationError(str(e))

    def _get_or_build_saved_query(self, version: EndpointVersion) -> DataWarehouseSavedQuery:
        """Find this version's saved query, or build a new (unsaved) one.

        SECURITY: only adopt a saved query that this endpoint owns (ENDPOINT origin and not
        linked to a different version). Without this, a user-created saved query whose name
        happens to collide with {endpoint}_v{n} would be silently taken over — its query
        overwritten and served as the endpoint's data.
        """
        name = version.materialized_view_name
        existing = DataWarehouseSavedQuery.objects.filter(name=name, team=self.team, deleted=False).first()
        if existing is None:
            return DataWarehouseSavedQuery(
                name=name,
                team=self.team,
                origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
            )

        is_foreign = existing.origin != DataWarehouseSavedQuery.Origin.ENDPOINT or (
            existing.endpoint_versions.exclude(pk=version.pk).exists()
        )
        if is_foreign:
            raise ValidationError(
                f"A saved query named '{name}' already exists and is not managed by this endpoint. "
                "Rename or delete it before enabling materialization."
            )
        return existing

    def _configure_saved_query(
        self,
        saved_query: DataWarehouseSavedQuery,
        version: EndpointVersion,
        data_freshness_seconds: int,
        bucket_overrides: dict[str, str] | None,
    ) -> None:
        """Point the saved query at the version's materializable HogQL and sync cadence."""
        saved_query.query = build_endpoint_hogql(
            version.query,
            self.team,
            bucket_overrides=bucket_overrides,
            user=self.user,
        )
        saved_query.external_tables = saved_query.s3_tables
        saved_query.is_materialized = True
        saved_query.sync_frequency_interval = sync_frequency_to_sync_frequency_interval(
            DATA_FRESHNESS_BUCKETS[data_freshness_seconds]
        )
        saved_query.save()

    def disable_materialization(self, endpoint: Endpoint, version: EndpointVersion) -> None:
        """Disable materialization for an endpoint version."""
        if version.saved_query:
            saved_query_id = str(version.saved_query.id)
            saved_query_name = version.saved_query.name
            try:
                delete_node_from_dag(version.saved_query)
            except Exception as e:
                logger.exception(
                    "Failed to remove endpoint node from DAG",
                    endpoint_name=endpoint.name,
                    saved_query_id=saved_query_id,
                )
                capture_exception(
                    e,
                    {
                        "product": Product.ENDPOINTS,
                        "team_id": self.team.pk,
                        "endpoint_name": endpoint.name,
                        "saved_query_id": saved_query_id,
                    },
                )
            try:
                version.disable_materialization()
            except Exception:
                ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="disable", status="error").inc()
                raise
            ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="disable", status="success").inc()
            log_activity(
                organization_id=self.team.organization_id,
                team_id=self.team.pk,
                user=self.user,
                was_impersonated=is_impersonated(self.request),
                item_id=saved_query_id,
                scope="DataWarehouseSavedQuery",
                activity="materialization_disabled",
                detail=Detail(
                    name=saved_query_name,
                    context=EndpointContext(version=version.version),
                ),
            )
        # Clears this version's throttle-readiness key plus the "current" key (the disabled
        # version may be the current one) — the next request lazily re-checks the DB.
        clear_endpoint_materialization_cache(self.team.pk, endpoint.name, versions=[version.version])

    def preview(
        self,
        endpoint: Endpoint,
        version: EndpointVersion,
        bucket_overrides: dict[str, str] | None = None,
    ) -> MaterializationPreview:
        """Preview the materialization transform without enabling it."""
        can_mat, reason = version.can_materialize()
        if not can_mat:
            return MaterializationPreview.cant_materialize(reason)

        hogql_query = convert_insight_query_to_hogql(version.query, self.team, user=self.user)

        range_pairs: list[dict] = []
        aggregates: list[dict] = []
        transformed_query_str: str | None = None
        variable_infos: list = []

        if version.query.get("variables"):
            can_materialize_vars, var_reason, variable_infos = analyze_variables_for_materialization(
                version.query, bucket_overrides=bucket_overrides
            )

            if not can_materialize_vars:
                return MaterializationPreview.cant_materialize(var_reason)

            if variable_infos:
                transformed = transform_query_for_materialization(
                    hogql_query,
                    variable_infos,
                    self.team,
                    bucket_overrides=bucket_overrides,
                    user=self.user,
                )
                transformed_query_str = transformed.get("query")

                # Extract range pairs grouped by column
                seen_columns: dict[str, dict] = {}
                for v in variable_infos:
                    if v.bucket_fn is not None:
                        col_key = ".".join(v.column_chain) if v.column_chain else v.column_expression
                        if col_key not in seen_columns:
                            seen_columns[col_key] = {
                                "column": col_key,
                                "variables": [],
                                "bucket_fn": v.bucket_fn,
                            }
                        seen_columns[col_key]["variables"].append(v.code_name)
                range_pairs = list(seen_columns.values())

                query_str = hogql_query.get("query", "")
                if query_str:
                    try:
                        parsed = parse_select(query_str)
                    except Exception as e:
                        # Preview degrades (no aggregate re-aggregation info), the request succeeds.
                        logger.warning(
                            "materialization_preview: converted HogQL failed to parse; "
                            "skipping aggregate re-aggregation preview",
                            endpoint_name=endpoint.name,
                            team_id=self.team.pk,
                        )
                        capture_exception(
                            e,
                            {
                                "product": Product.ENDPOINTS,
                                "team_id": self.team.pk,
                                "endpoint_name": endpoint.name,
                                "materialization_preview": True,
                            },
                        )
                    else:
                        if isinstance(parsed, ast.SelectQuery) and parsed.select:
                            for expr in parsed.select:
                                agg_name = _extract_aggregate_name(expr)
                                if agg_name:
                                    reagg_info = get_reaggregation(agg_name)
                                    reagg = reagg_info.reaggregate_fn if reagg_info else None
                                    if isinstance(expr, ast.Alias):
                                        label = expr.alias
                                    else:
                                        label = expr.to_hogql()
                                    aggregates.append(
                                        {
                                            "expression": label,
                                            "reaggregate_fn": reagg,
                                        }
                                    )
        else:
            # No variables — just show the converted query as-is
            transformed_query_str = hogql_query.get("query")

        # Build the execution query preview — what runs at request time against the materialized table
        execution_query_str: str | None = None
        display_execution_query_str: str | None = None
        try:
            strategy = strategy_for(endpoint, version, self.team)

            def _build_exec_preview(table_name: str) -> ast.SelectQuery:
                q, _ = strategy.build_materialized_select(
                    table_name=table_name,
                    variable_infos=variable_infos or None,
                )
                for v in variable_infos:
                    apply_where_filter(
                        q,
                        v.code_name,
                        f"{{variables.{v.code_name}}}",
                        op=v.operator,
                        value_wrapper_fns=v.value_wrapper_fns,
                        bucket_fn=v.bucket_fn,
                    )
                return q

            # Each call builds a fresh SelectQuery, so WHERE mutations don't leak between calls.
            # Type resolution (to_printed_hogql) needs the materialized table to exist in the
            # database, which only holds once materialization has completed. Previewing a
            # not-yet-materialized version means that table is absent, so we'd otherwise hit
            # "Unknown table". Fall back to printing without type resolution in that case — the
            # frontend uses execution_query only as a presence flag and renders the display variant.
            if version.is_materialized:
                execution_query_str = to_printed_hogql(
                    _build_exec_preview(version.materialized_view_name), team=self.team
                )
            else:
                execution_query_str = print_prepared_ast(
                    node=_build_exec_preview(version.materialized_view_name),
                    context=HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                    dialect="hogql",
                    pretty=True,
                )

            # Display variant uses the friendly endpoint name — printed without type resolution
            # since the friendly name isn't a real table in the database
            display_execution_query_str = print_prepared_ast(
                node=_build_exec_preview(endpoint.name),
                context=HogQLContext(team_id=self.team.pk, enable_select_queries=True),
                dialect="hogql",
                pretty=True,
            )
        except Exception as e:
            logger.warning(
                "Failed to build materialization execution query preview",
                endpoint_name=endpoint.name,
                team_id=self.team.pk,
                exc_info=True,
            )
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team.pk,
                    "endpoint_name": endpoint.name,
                    "materialization_preview": True,
                },
            )

        return MaterializationPreview(
            can_materialize=True,
            transformed_query=transformed_query_str,
            execution_query=execution_query_str,
            display_execution_query=display_execution_query_str,
            range_pairs=range_pairs,
            aggregates=aggregates,
        )
