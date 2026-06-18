"""Endpoint run-path orchestration.

``EndpointExecutionService`` owns everything that happens after the viewset has
authenticated the caller and parsed the request: run-request validation, choosing
between materialized / inline / DuckLake execution, query-service invocation,
response post-processing, metrics, and failure signals. Kind-specific behavior
(variables, WHERE building, response re-shaping) is delegated to the
``EndpointQueryStrategy`` classes.
"""

import re
import time
import uuid
from datetime import timedelta
from typing import Literal, Union, cast

from django.utils import timezone

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from dateutil.parser import isoparse
from pydantic import BaseModel
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    EndpointRefreshMode,
    EndpointRunRequest,
    HogQLQuery,
    HogQLQueryModifiers,
    HogQLVariable,
    QueryRequest,
    RefreshType,
)

from posthog.hogql.errors import ExposedHogQLError, ResolutionError

from posthog.api.mixins import PydanticModelMixin
from posthog.api.query import _process_query_request
from posthog.api.services.query import process_query_model
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import (
    Feature,
    Product,
    get_query_tag_value,
    is_api_key_access_method,
    tag_queries,
)
from posthog.ducklake.common import get_duckgres_server_for_organization
from posthog.errors import ExposedCHQueryError
from posthog.event_usage import get_request_analytics_properties, report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.permissions import is_authenticated_via_project_secret_api_key
from posthog.synthetic_user import SyntheticUser

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.data_load.saved_query_service import trigger_saved_query_schedule
from products.endpoints.backend.insight_transformers import MaterializedSeriesMismatchError
from products.endpoints.backend.logs import build_execution_message, log_endpoint_execution
from products.endpoints.backend.metrics import (
    ENDPOINT_CACHE_RESULT_TOTAL,
    ENDPOINT_CONCURRENCY_REJECTED_TOTAL,
    ENDPOINT_DUCKLAKE_FALLBACK_TOTAL,
    ENDPOINT_EXECUTION_DURATION_SECONDS,
    ENDPOINT_EXECUTION_TOTAL,
    ENDPOINT_HOGQL_RESULT_ROWS,
    ENDPOINT_MATERIALIZED_FRESHNESS_RATIO,
    ENDPOINT_VALIDATION_ERROR_TOTAL,
    query_kind_label,
)
from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.endpoints.backend.services.pagination import EndpointPagination
from products.endpoints.backend.services.strategies import EndpointQueryStrategy, strategy_for

from common.hogvm.python.utils import HogVMException

logger = structlog.get_logger(__name__)

LAST_EXECUTED_THROTTLE = timedelta(minutes=30)

ExecutionType = Literal["materialized", "materialized_fallback", "inline", "ducklake", "ducklake_fallback"]


def _emit_endpoint_failure_signal(
    team,
    endpoint: Endpoint,
    exc: BaseException,
    *,
    materialized: bool,
    version: int | None = None,
    saved_query_id: Union[str, uuid.UUID, None] = None,
    query_kind: str | None = None,
    executed_sql: str | None = None,
    saved_query_status: str | None = None,
    saved_query_last_run_at: str | None = None,
    saved_query_columns: dict | None = None,
    endpoint_columns: list | None = None,
) -> None:
    """Fire a Signal when an endpoint execution fails, so the AI can reason about it later.

    Fails silently — signal emission must never mask the underlying error.
    """
    from products.signals.backend.facade.api import emit_signal

    try:
        error_class = type(exc).__name__
        error_msg = str(exc)
        version_str = f" v{version}" if version else ""

        if materialized:
            execution_mode = "materialized"
            context = (
                f"The materialized table (saved_query_id={saved_query_id}) may be stale, missing, or have a schema mismatch. "
                f"Check whether the materialization refresh completed successfully and whether the underlying query still produces valid columns."
            )
            if saved_query_status:
                context += f"\nSaved query status: {saved_query_status}"
            if saved_query_last_run_at:
                context += f", last materialized at: {saved_query_last_run_at}"
            if saved_query_columns:
                context += f"\nMaterialized table columns: {saved_query_columns}"
            if endpoint_columns:
                context += f"\nEndpoint version columns: {endpoint_columns}"
        else:
            execution_mode = "inline"
            context = (
                f"The query is executed on-demand against live data. "
                f"Common causes: invalid HogQL syntax, missing or renamed properties, query timeout, or incompatible variable overrides."
            )

        parts = [
            f"Endpoint '{endpoint.name}'{version_str} failed during {execution_mode} execution.",
            f"Error: {error_class}: {error_msg}",
        ]
        if query_kind:
            parts.append(f"Query kind: {query_kind}")
        if executed_sql:
            parts.append(f"Executed HogQL: {executed_sql}")
        parts.append(context)
        parts.append(f"Endpoint path: {endpoint.endpoint_path}")
        description = "\n".join(parts)

        async_to_sync(emit_signal)(
            team=team,
            source_product="endpoints",
            source_type="endpoint_execution_failed",
            source_id=f"{team.id}:{endpoint.name}",
            description=description,
            weight=0.5,
            extra={
                "endpoint_name": endpoint.name,
                "endpoint_version": version,
                "materialized": materialized,
                "saved_query_id": str(saved_query_id) if saved_query_id else None,
                "error_class": error_class,
                "error_message": error_msg,
            },
        )
    except Exception as signal_exc:
        logger.exception(
            "Failed to emit endpoint failure signal",
            endpoint_name=endpoint.name,
            team_id=team.id,
            signal_error_class=type(signal_exc).__name__,
            signal_error=str(signal_exc),
        )
        capture_exception(
            signal_exc,
            {
                "product": Product.ENDPOINTS,
                "team_id": team.id,
                "endpoint_name": endpoint.name,
                "signal_emission": True,
            },
        )


def _endpoint_refresh_mode_to_refresh_type(
    mode: EndpointRefreshMode | None,
) -> RefreshType:
    """
    Map EndpointRefreshMode to RefreshType.

    - cache -> blocking
    - force/direct -> force_blocking (materialization bypass handled in should_use_materialized_table)
    """
    if mode is None or mode == EndpointRefreshMode.CACHE:
        return RefreshType.BLOCKING
    return RefreshType.FORCE_BLOCKING


class EndpointExecutionService(PydanticModelMixin):
    """Executes an endpoint version, choosing the best execution path."""

    def __init__(self, team: Team, request: Request):
        self.team = team
        self.request = request

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def format_validation_detail(detail: object) -> str:
        """Flatten a DRF ValidationError detail into one line for logs."""
        if isinstance(detail, dict):
            return "; ".join(
                f"{field}: {EndpointExecutionService.format_validation_detail(messages)}"
                for field, messages in detail.items()
            )
        if isinstance(detail, list):
            return "; ".join(EndpointExecutionService.format_validation_detail(item) for item in detail)
        return str(detail)

    def log_rejected_run(self, endpoint: Endpoint, reason: str) -> None:
        log_endpoint_execution(
            team_id=self.team.pk,
            endpoint_id=str(endpoint.id),
            instance_id=str(uuid.uuid4()),
            level="ERROR",
            message=f"Endpoint execution failed · invalid request · {reason}",
        )

    def validate_run_request(
        self,
        data: EndpointRunRequest,
        endpoint: Endpoint,
        version: EndpointVersion,
        offset: int | None = None,
    ) -> None:
        strategy = strategy_for(endpoint, version, self.team)

        is_materialized = bool(version.is_materialized and version.saved_query)

        if not version.is_active:
            ENDPOINT_VALIDATION_ERROR_TOTAL.labels(reason="inactive_version").inc()
            raise ValidationError(f"Version {version.version} is inactive and cannot be executed.")

        # Reject query_override (always)
        if hasattr(data, "query_override") and data.query_override is not None:
            raise ValidationError({"query_override": "Not allowed. Use variables instead."})

        # Allow filters_override for insight endpoints (deprecated but backwards compatible)
        # Reject for HogQL endpoints
        if data.filters_override is not None:
            if strategy.query_kind == "HogQLQuery":
                raise ValidationError({"filters_override": "Not allowed for HogQL endpoints. Use variables instead."})

        if offset is not None and not strategy.supports_pagination:
            raise ValidationError({"offset": "offset is only supported for HogQL endpoints"})

        # Validate refresh mode
        if data.refresh == EndpointRefreshMode.DIRECT and not is_materialized:
            ENDPOINT_VALIDATION_ERROR_TOTAL.labels(reason="direct_refresh_not_materialized").inc()
            raise ValidationError(
                {
                    "refresh": "'direct' refresh mode is only valid for materialized endpoints. "
                    "Use 'cache' or 'force' instead, or enable materialization on this endpoint."
                }
            )

        # Validate variables
        if data.variables:
            allowed_vars = strategy.allowed_variables(is_materialized)
            unknown_vars = set(data.variables.keys()) - allowed_vars
            if unknown_vars:
                ENDPOINT_VALIDATION_ERROR_TOTAL.labels(reason="unknown_variable").inc()
                raise ValidationError({"variables": f"Unknown variable(s): {', '.join(sorted(unknown_vars))}"})

        # SECURITY: For materialized endpoints with required variables, ALL must be provided.
        # Without this check, omitting variables would return ALL data instead of filtered data.
        # filters_override (deprecated) only counts when it actually applies the breakdown filter —
        # a property with no usable value adds no WHERE clause and must not bypass this check.
        if is_materialized and not strategy.materialized_filters_override_satisfies_required(data):
            required_vars = strategy.required_materialized_variables()
            if required_vars:
                provided = {key for key, value in (data.variables or {}).items() if value is not None}
                missing = sorted(required_vars - provided)
                if missing:
                    ENDPOINT_VALIDATION_ERROR_TOTAL.labels(reason="missing_required_variable").inc()
                    raise ValidationError(
                        {"variables": f"Required variable(s) {', '.join(repr(v) for v in missing)} not provided"}
                    )

    # ------------------------------------------------------------------
    # Execution path selection
    # ------------------------------------------------------------------

    def should_use_materialized_table(
        self, endpoint: Endpoint, data: EndpointRunRequest, version: EndpointVersion
    ) -> bool:
        """
        Decide whether to use materialized table or inline execution.

        Reads materialization state from the DB — the authoritative source. (The redis
        "materialization ready" cache in rate_limit.py only classifies requests for
        throttling and is intentionally not consulted here.)

        Returns False if:
        - Not materialized
        - Materialization incomplete/failed
        - Materialized data is stale (older than sync frequency)
        - User overrides present (variables, query)
        - 'direct' mode requested (explicitly bypass materialization)
        """
        if not version.is_materialized or not version.saved_query:
            return False

        saved_query = version.saved_query
        if saved_query.status != DataWarehouseSavedQuery.Status.COMPLETED:
            return False

        if not saved_query.table:
            return False

        # Check if materialized data is stale
        if saved_query.last_run_at and saved_query.sync_frequency_interval:
            next_refresh_due = saved_query.last_run_at + saved_query.sync_frequency_interval
            if timezone.now() >= next_refresh_due:
                return False

        # 'direct' mode explicitly bypasses materialization to run the original query
        if data.refresh == EndpointRefreshMode.DIRECT:
            return False

        # Check if variables are valid for materialized execution
        if data.variables:
            strategy = strategy_for(endpoint, version, self.team)
            if not strategy.can_serve_variables_from_materialized(set(data.variables.keys())):
                return False

        return True

    def _should_use_ducklake(self, endpoint: Endpoint, version: EndpointVersion | None) -> bool:
        if version is None:
            return False
        if version.query.get("kind") != "HogQLQuery":
            return False

        ff_result = posthoganalytics.feature_enabled(
            "endpoints-ducklake-execution",
            str(self.team.uuid),
            groups={
                "organization": str(self.team.organization_id),
                "project": str(self.team.id),
            },
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        logger.info(
            "Ducklake FF evaluation",
            endpoint_name=endpoint.name,
            ff_result=ff_result,
        )
        if not ff_result:
            return False

        server = get_duckgres_server_for_organization(str(self.team.organization_id))
        if server is None:
            logger.info("Ducklake skip: no duckgres server", endpoint_name=endpoint.name, team_id=self.team.pk)
        return server is not None

    # ------------------------------------------------------------------
    # Top-level entry point
    # ------------------------------------------------------------------

    def execute(
        self,
        endpoint: Endpoint,
        data: EndpointRunRequest,
        version_obj: EndpointVersion | None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Response:
        """Run an endpoint version and return the HTTP response.

        Assumes the caller has resolved the version (or established that none was
        requested explicitly) and parsed limit/offset.
        """
        if version_obj is None:
            return Response(
                {"error": "No version found for this endpoint"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            self.validate_run_request(data, endpoint, version_obj, offset=offset)
        except ValidationError as exc:
            self.log_rejected_run(endpoint, self.format_validation_detail(exc.detail))
            raise

        report_user_action(
            cast("User | SyntheticUser", self.request.user),
            "endpoint executed",
            {
                "endpoint_id": str(endpoint.id),
                "endpoint_name": endpoint.name,
                "has_filters_override": bool(data.filters_override),
                "has_variables": bool(data.variables),
                "has_limit": data.limit is not None,
                "has_offset": data.offset is not None,
                "refresh_mode": data.refresh.value if data.refresh else None,
                "auth_method": "project_secret_api_key"
                if is_authenticated_via_project_secret_api_key(self.request)
                else "user",
            },
            team=self.team,
            analytics_props=get_request_analytics_properties(self.request),
        )

        # Check if we should use materialization for this version
        use_materialized = self.should_use_materialized_table(endpoint, data, version_obj)

        debug = data.debug or False
        execution_type: ExecutionType = "materialized" if use_materialized else "inline"
        query_kind_metric = query_kind_label(version_obj.query)
        execution_status: str | None = None
        execution_id = str(uuid.uuid4())
        error_label: str | None = None
        _start_time = time.monotonic()
        _duration = 0.0

        try:
            result: Response | None = None
            if use_materialized:
                try:
                    result = self._execute_materialized_endpoint(
                        endpoint, data, version=version_obj, debug=debug, limit=limit, offset=offset
                    )
                except ConcurrencyLimitExceeded:
                    raise
                except Exception:
                    # Already logged/captured/signaled inside the materialized path. Serve the
                    # request from the original query instead of failing — stale tables and
                    # series drift self-heal on the next materialization run.
                    execution_type = "materialized_fallback"
                    result = None
            elif self._should_use_ducklake(endpoint, version_obj):
                try:
                    result = self._execute_ducklake_endpoint(endpoint, version_obj.query.copy(), debug=debug)
                    execution_type = "ducklake"
                except Exception:
                    logger.warning(
                        "DuckLake execution failed, falling back to inline",
                        endpoint_name=endpoint.name,
                    )
                    ENDPOINT_DUCKLAKE_FALLBACK_TOTAL.inc()
                    execution_type = "ducklake_fallback"
                    result = None

            if result is None:
                result = self._execute_inline_endpoint(
                    endpoint,
                    data,
                    version_obj.query.copy(),
                    version=version_obj,
                    debug=debug,
                    limit=limit,
                    offset=offset,
                )
            execution_status = "success"
        except (ExposedHogQLError, ExposedCHQueryError) as e:
            execution_status = "user_error"
            error_label = getattr(e, "code_name", None) or type(e).__name__
            logger.exception(
                "Endpoint execution failed",
                endpoint_name=endpoint.name,
                code_name=getattr(e, "code_name", None),
            )
            raise ValidationError("Query execution failed.", getattr(e, "code_name", None))
        except HogVMException:
            execution_status = "user_error"
            error_label = "HogVMException"
            logger.exception(
                "Endpoint execution failed (HogVM)",
                endpoint_name=endpoint.name,
            )
            raise ValidationError("Query execution failed: HogQL virtual machine error")
        except ResolutionError:
            execution_status = "user_error"
            error_label = "ResolutionError"
            logger.exception(
                "Endpoint resolution failed",
                endpoint_name=endpoint.name,
            )
            raise ValidationError("Query resolution failed: unable to resolve table or field references.")
        except ConcurrencyLimitExceeded:
            ENDPOINT_CONCURRENCY_REJECTED_TOTAL.labels(team_id=str(self.team.pk)).inc()
            raise Throttled(detail="Too many concurrent requests. Please try again later.")
        except Exception as e:
            execution_status = "error"
            error_label = type(e).__name__
            raise
        finally:
            if execution_status is not None:
                _duration = time.monotonic() - _start_time
                ENDPOINT_EXECUTION_DURATION_SECONDS.labels(
                    execution_type=execution_type, query_kind=query_kind_metric
                ).observe(_duration)
                ENDPOINT_EXECUTION_TOTAL.labels(
                    execution_type=execution_type, query_kind=query_kind_metric, status=execution_status
                ).inc()
            if execution_status in ("error", "user_error"):
                log_endpoint_execution(
                    team_id=self.team.pk,
                    endpoint_id=str(endpoint.id),
                    instance_id=execution_id,
                    level="ERROR",
                    message=build_execution_message(
                        succeeded=False,
                        execution_type=execution_type,
                        version=version_obj.version,
                        error=error_label,
                    ),
                )

        cache_outcome, result_row_count = self._record_result_metrics(result, execution_type, query_kind_metric)
        log_endpoint_execution(
            team_id=self.team.pk,
            endpoint_id=str(endpoint.id),
            instance_id=execution_id,
            level="INFO",
            message=build_execution_message(
                succeeded=True,
                execution_type=execution_type,
                cache_outcome=cache_outcome,
                duration_ms=round(_duration * 1000),
                rows=result_row_count,
                version=version_obj.version,
            ),
        )
        self._track_last_executed(endpoint, version_obj)

        if isinstance(result.data, dict):
            result.data["name"] = endpoint.name
            result.data["execution_id"] = execution_id
            result.data["endpoint_version"] = version_obj.version
            result.data["endpoint_version_created_at"] = version_obj.created_at.isoformat()

        return result

    def _record_result_metrics(
        self, result: Response, execution_type: str, query_kind_metric: str
    ) -> tuple[str | None, int | None]:
        cache_outcome: str | None = None
        result_row_count: int | None = None
        try:
            if isinstance(result.data, dict):
                # DuckLake bypasses the query result cache entirely — don't claim hit/miss for it.
                if execution_type != "ducklake":
                    cache_outcome = "hit" if bool(result.data.get("is_cached")) else "miss"
                    ENDPOINT_CACHE_RESULT_TOTAL.labels(
                        execution_type=execution_type, query_kind=query_kind_metric, outcome=cache_outcome
                    ).inc()

                results_value = result.data.get("results")
                if isinstance(results_value, list):
                    result_row_count = len(results_value)
                    if query_kind_metric == "hogql":
                        ENDPOINT_HOGQL_RESULT_ROWS.labels(execution_type=execution_type).observe(result_row_count)
        except Exception:
            logger.debug("Failed to record endpoint result metrics", exc_info=True)
        return cache_outcome, result_row_count

    def _track_last_executed(self, endpoint: Endpoint, version_obj: EndpointVersion) -> None:
        """Record last execution time (30-minute granularity, API key calls only)."""
        if not is_api_key_access_method(get_query_tag_value("access_method")):
            return
        now = timezone.now()
        if endpoint.last_executed_at is None or (now - endpoint.last_executed_at > LAST_EXECUTED_THROTTLE):
            endpoint.last_executed_at = now
            endpoint.save(update_fields=["last_executed_at"])
        if version_obj.last_executed_at is None or (now - version_obj.last_executed_at > LAST_EXECUTED_THROTTLE):
            version_obj.last_executed_at = now
            version_obj.save(update_fields=["last_executed_at"])

    # ------------------------------------------------------------------
    # Materialized execution
    # ------------------------------------------------------------------

    def _execute_materialized_endpoint(
        self,
        endpoint: Endpoint,
        data: EndpointRunRequest,
        version: EndpointVersion,
        debug: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Response:
        """Execute against a materialized table in S3."""
        materialized_hogql_query = None
        query_kind = None
        saved_query = version.saved_query
        try:
            if not saved_query:
                raise ValidationError("No materialized query found for this endpoint")

            strategy = strategy_for(endpoint, version, self.team)
            query_kind = strategy.query_kind

            select_query, original_limit = strategy.build_materialized_select(table_name=saved_query.name)

            pagination: EndpointPagination | None = None

            # Only paginate flat-row HogQL results. Insight types get transformed
            # into nested structures where flat-row LIMIT/OFFSET is meaningless.
            if limit is not None and strategy.supports_pagination:
                pagination = EndpointPagination(limit=limit, offset=offset or 0, ceiling=original_limit)
                pagination.apply_to(select_query)

            deprecation_headers = strategy.apply_materialized_filters(select_query, data)

            materialized_hogql_query = HogQLQuery(
                query=select_query.to_hogql(),
                modifiers=HogQLQueryModifiers(useMaterializedViews=True),
            )

            refresh_type = _endpoint_refresh_mode_to_refresh_type(data.refresh)

            query_request_data = {
                "client_query_id": data.client_query_id,
                "name": f"{endpoint.name}_materialized",
                "refresh": refresh_type,
                "query": materialized_hogql_query.model_dump(),
            }

            extra_fields = {
                "endpoint_materialized": True,
                "endpoint_materialized_at": saved_query.last_run_at.isoformat() if saved_query.last_run_at else None,
            }
            tag_queries(
                workload=Workload.ENDPOINTS,
                warehouse_query=True,
                endpoint_version=version.version,
            )

            # Compute dynamic cache TTL: time remaining until data_freshness window expires
            cache_ttl = None
            if saved_query.last_run_at and version.data_freshness_seconds:
                remaining = (
                    saved_query.last_run_at + timedelta(seconds=version.data_freshness_seconds) - timezone.now()
                ).total_seconds()
                if remaining <= 0:
                    logger.warning(
                        "endpoint_materialization_behind_sla",
                        endpoint_name=endpoint.name,
                        team_id=self.team.pk,
                        data_freshness_seconds=version.data_freshness_seconds,
                        last_run_at=saved_query.last_run_at.isoformat(),
                        remaining_seconds=remaining,
                    )
                    tag_queries(endpoint_materialization_behind=True)
                cache_ttl = max(1, int(remaining))  # at least 1 second to enable caching

            result = self._execute_query_and_respond(
                query_request_data,
                data.client_query_id,
                cache_age_seconds=cache_ttl,
                extra_result_fields=extra_fields,
                debug=debug,
                headers=deprecation_headers,
                pagination=pagination,
            )

            if self._is_cache_stale(result, saved_query):
                query_request_data["refresh"] = RefreshType.FORCE_BLOCKING
                result = self._execute_query_and_respond(
                    query_request_data,
                    data.client_query_id,
                    extra_result_fields=extra_fields,
                    debug=debug,
                    headers=deprecation_headers,
                    pagination=pagination,
                )

            if isinstance(result.data, dict):
                strategy.clean_response_sentinels(result.data)

            try:
                strategy.transform_materialized_response(result.data, saved_query)
            except MaterializedSeriesMismatchError:
                # Series drift: query was likely edited after materialization. Trigger a refresh
                # so future materialized reads succeed; the caller serves this request inline.
                logger.warning(
                    "Materialized endpoint series mismatch, triggering re-materialization",
                    endpoint_name=endpoint.name,
                    saved_query_id=saved_query.id,
                )
                trigger_saved_query_schedule(saved_query)
                raise

            # Freshness relative to the configured target: >1.0 means behind SLA.
            # Absolute age is meaningless across endpoints with different frequencies.
            if saved_query.last_run_at and version.data_freshness_seconds:
                age_seconds = max((timezone.now() - saved_query.last_run_at).total_seconds(), 0.0)
                ENDPOINT_MATERIALIZED_FRESHNESS_RATIO.observe(age_seconds / version.data_freshness_seconds)

            return result
        except Exception as e:
            logger.exception(
                "Materialized endpoint execution failed",
                endpoint_name=endpoint.name,
                saved_query_id=saved_query.id if saved_query else None,
                saved_query_status=saved_query.status if saved_query else None,
            )
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team.pk,
                    "endpoint_name": endpoint.name,
                    "materialized": True,
                    "saved_query_id": saved_query.id if saved_query else None,
                },
            )
            _emit_endpoint_failure_signal(
                self.team,
                endpoint,
                e,
                materialized=True,
                version=version.version,
                saved_query_id=saved_query.id if saved_query else None,
                query_kind=query_kind,
                executed_sql=materialized_hogql_query.query if materialized_hogql_query else None,
                saved_query_status=saved_query.status if saved_query else None,
                saved_query_last_run_at=(
                    saved_query.last_run_at.isoformat() if saved_query and saved_query.last_run_at else None
                ),
                saved_query_columns=saved_query.columns if saved_query else None,
                endpoint_columns=version.columns,
            )
            raise

    def _is_cache_stale(self, result: Response, saved_query) -> bool:
        """Check if cached result is older than the materialization."""
        if not isinstance(result.data, dict) or not result.data.get("is_cached"):
            return False

        last_refresh = result.data.get("last_refresh")
        if not last_refresh or not saved_query.last_run_at:
            return False

        if isinstance(last_refresh, str):
            last_refresh = isoparse(last_refresh)

        return last_refresh < saved_query.last_run_at

    # ------------------------------------------------------------------
    # Inline + DuckLake execution
    # ------------------------------------------------------------------

    def _execute_inline_endpoint(
        self,
        endpoint: Endpoint,
        data: EndpointRunRequest,
        query: dict,
        version: EndpointVersion,
        debug: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Response:
        """Execute query directly against ClickHouse."""
        strategy: EndpointQueryStrategy | None = None
        try:
            strategy = strategy_for(endpoint, version, self.team)

            query = strategy.prepare_inline_query(query)

            pagination: EndpointPagination | None = None
            if limit is not None:
                query, pagination = strategy.apply_pagination(query, limit, offset or 0)

            refresh_type = _endpoint_refresh_mode_to_refresh_type(data.refresh)

            plan = strategy.build_inline_plan(query, data)

            query_request_data = {
                "client_query_id": data.client_query_id,
                "filters_override": plan.filters_override.model_dump() if plan.filters_override else None,
                "name": endpoint.name,
                "refresh": refresh_type,
                "query": query,
            }

            cache_age = version.data_freshness_seconds
            tag_queries(endpoint_version=version.version)

            result = self._execute_query_and_respond(
                query_request_data,
                data.client_query_id,
                variables_override=plan.variables_override,
                cache_age_seconds=cache_age,
                debug=debug,
                headers=plan.deprecation_headers,
                pagination=pagination,
            )

            if isinstance(result.data, dict):
                strategy.clean_response_sentinels(result.data)

            return result

        except Exception as e:
            self.handle_column_ch_error(e)
            logger.exception(
                "Inline endpoint execution failed",
                endpoint_name=endpoint.name,
            )
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team.pk,
                    "materialized": False,
                    "endpoint_name": endpoint.name,
                },
            )
            query_kind = strategy.query_kind if strategy else query.get("kind")
            _emit_endpoint_failure_signal(
                self.team,
                endpoint,
                e,
                materialized=False,
                version=version.version,
                query_kind=query_kind,
                executed_sql=query.get("query") if query_kind == "HogQLQuery" else None,
                endpoint_columns=version.columns,
            )
            raise

    def _execute_ducklake_endpoint(
        self,
        endpoint: Endpoint,
        query: dict,
        debug: bool = False,
    ) -> Response:
        from posthog.ducklake.client import execute_ducklake_query

        try:
            result = execute_ducklake_query(
                self.team.pk,
                query=HogQLQuery(query=query["query"]),
                organization_id=str(self.team.organization_id),
            )
            response_data: dict = {
                "results": result.results,
                "columns": result.columns,
                "types": result.types,
                "hasMore": False,
                "backend": "ducklake",
            }
            if debug:
                response_data["query"] = query.get("query")
                response_data["hogql"] = result.hogql
                response_data["ducklake_sql"] = result.sql
            return Response(response_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception(
                "DuckLake endpoint execution failed",
                endpoint_name=endpoint.name,
            )
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team.pk,
                    "ducklake": True,
                    "endpoint_name": endpoint.name,
                },
            )
            raise

    # ------------------------------------------------------------------
    # Query service plumbing
    # ------------------------------------------------------------------

    def _is_interactive_session(self) -> bool:
        """Whether this request came from the PostHog UI (session auth) rather than a
        programmatic credential (personal API key, OAuth, project secret API key, ...).

        Same idiom as get_event_source (posthog/event_usage.py) minus its session-cookie
        fallback, which could misclassify API-key requests sent from a logged-in browser.
        """
        return isinstance(getattr(self.request, "successful_authenticator", None), SessionAuthentication)

    def _execute_query_and_respond(
        self,
        query_request_data: dict,
        client_query_id: str | None,
        variables_override: list[HogQLVariable] | None = None,
        cache_age_seconds: int | None = None,
        extra_result_fields: dict | None = None,
        debug: bool = False,
        headers: dict[str, str] | None = None,
        pagination: EndpointPagination | None = None,
    ) -> Response:
        """Shared query execution logic."""
        merged_data = self.get_model(query_request_data, QueryRequest)

        query, client_query_id, execution_mode = _process_query_request(
            merged_data, self.team, client_query_id, self.request.user
        )
        self._tag_client_query_id(client_query_id)
        endpoint_feature = Feature.ENDPOINT_PLAYGROUND if self._is_interactive_session() else Feature.ENDPOINT_EXECUTION
        tag_queries(product=Product.ENDPOINTS, feature=endpoint_feature)

        result = process_query_model(
            self.team,
            query,
            variables_override=variables_override,
            execution_mode=execution_mode,
            query_id=client_query_id,
            user=cast(User, self.request.user),
            is_query_service=is_api_key_access_method(get_query_tag_value("access_method")),
            cache_age_seconds=cache_age_seconds,
            analytics_props=get_request_analytics_properties(self.request),
        )

        if isinstance(result, BaseModel):
            result = result.model_dump(by_alias=True)

        if isinstance(result, dict) and extra_result_fields:
            result.update(extra_result_fields)

        if not debug:
            debug_fields_to_remove = [
                "calculation_trigger",
                "cache_key",
                "explain",
                "modifiers",
                "resolved_date_range",
                "timings",
                "hogql",
            ]

            for field in debug_fields_to_remove:
                result.pop(field, None)

        if pagination and "results" in result:
            pagination.process_results(result)
        elif "results" in result:
            result["hasMore"] = False

        if "results" in result:
            result = {"results": result.pop("results"), **result}

        return Response(result, status=status.HTTP_200_OK, headers=headers)

    def handle_column_ch_error(self, error) -> None:
        if getattr(error, "message", None):
            match = re.search(r"There's no column.*in table", error.message)
            if match:
                # TODO: remove once we support all column types
                raise ValidationError(match.group(0) + ". Not all column types are fully supported yet.")
        return

    def _tag_client_query_id(self, query_id: str | None) -> None:
        if query_id is None:
            return

        tag_queries(client_query_id=query_id)
