import re
import builtins
from datetime import timedelta
from typing import Optional, Union, cast

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone

from dateutil.parser import isoparse
from django_filters.rest_framework import DjangoFilterBackend
from loginas.utils import is_impersonated_session
from pydantic import BaseModel
from rest_framework import status, viewsets
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    DataWarehouseSyncInterval,
    EndpointLastExecutionTimesRequest,
    EndpointRequest,
    EndpointRunRequest,
    HogQLQuery,
    HogQLQueryModifiers,
    HogQLVariable,
    QueryRequest,
    QueryStatus,
    QueryStatusResponse,
    RefreshType,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.property import property_to_expr

from posthog.api.documentation import extend_schema
from posthog.api.mixins import PydanticModelMixin
from posthog.api.query import _process_query_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.query import process_query_model
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import Product, get_query_tag_value, tag_queries
from posthog.constants import AvailableFeature
from posthog.errors import ExposedCHQueryError
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import BLOCKING_EXECUTION_MODES
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.rate_limit import APIQueriesBurstThrottle, APIQueriesSustainedThrottle
from posthog.schema_migrations.upgrade import upgrade
from posthog.types import InsightQueryNode

from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.external_data_schema import (
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)
from products.endpoints.backend.materialization import convert_insight_query_to_hogql
from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.endpoints.backend.openapi import generate_openapi_spec

from common.hogvm.python.utils import HogVMException

MIN_CACHE_AGE_SECONDS = 300
MAX_CACHE_AGE_SECONDS = 86400

ENDPOINT_NAME_REGEX = r"^[a-zA-Z][a-zA-Z0-9_-]{0,127}$"


@extend_schema(tags=["endpoints"])
class EndpointViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ModelViewSet):
    # NOTE: Do we need to override the scopes for the "create"
    scope_object = "endpoint"
    # Special case for query - these are all essentially read actions
    scope_object_read_actions = ["retrieve", "list", "run", "versions", "version_detail", "openapi_spec"]
    scope_object_write_actions: list[str] = ["create", "destroy", "update"]
    lookup_field = "name"
    queryset = Endpoint.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_active", "created_by"]

    def get_serializer_class(self):
        return None  # We use Pydantic models instead

    def get_throttles(self):
        return [APIQueriesBurstThrottle(), APIQueriesSustainedThrottle()]

    def check_team_api_queries_concurrency(self):
        cache_key = f"team/{self.team_id}/feature/{AvailableFeature.API_QUERIES_CONCURRENCY}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        if self.team:
            new_val = self.team.organization.is_feature_available(AvailableFeature.API_QUERIES_CONCURRENCY)
            cache.set(cache_key, new_val)
            return new_val
        return False

    def _serialize_endpoint(self, endpoint: Endpoint) -> dict:
        result = {
            "id": str(endpoint.id),
            "name": endpoint.name,
            "description": endpoint.description,
            "query": endpoint.query,
            "parameters": endpoint.parameters,
            "is_active": endpoint.is_active,
            "cache_age_seconds": endpoint.cache_age_seconds,
            "endpoint_path": endpoint.endpoint_path,
            "created_at": endpoint.created_at,
            "updated_at": endpoint.updated_at,
            "created_by": UserBasicSerializer(endpoint.created_by).data if hasattr(endpoint, "created_by") else None,
            "is_materialized": endpoint.is_materialized,
            "current_version": endpoint.current_version,
            "versions_count": endpoint.versions.count(),
            "derived_from_insight": endpoint.derived_from_insight,
        }

        if endpoint.is_materialized and endpoint.saved_query:
            sync_freq_str = None
            if endpoint.saved_query.sync_frequency_interval:
                sync_freq_str = sync_frequency_interval_to_sync_frequency(endpoint.saved_query.sync_frequency_interval)

            result["materialization"] = {
                "status": endpoint.materialization_status,
                "can_materialize": True,
                "last_materialized_at": (
                    endpoint.last_materialized_at.isoformat() if endpoint.last_materialized_at else None
                ),
                "error": endpoint.materialization_error,
                "sync_frequency": sync_freq_str,
            }
        else:
            can_mat, reason = endpoint.can_materialize()
            result["materialization"] = {
                "can_materialize": can_mat,
                "reason": reason if not can_mat else None,
            }

        return result

    def list(self, request: Request, *args, **kwargs) -> Response:
        """List all endpoints for the team."""
        queryset = self.filter_queryset(self.get_queryset()).select_related("saved_query")
        results = [self._serialize_endpoint(endpoint) for endpoint in queryset]
        return Response({"results": results})

    def retrieve(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Retrieve an endpoint."""
        endpoint = get_object_or_404(Endpoint.objects.select_related("saved_query"), team=self.team, name=name)
        return Response(self._serialize_endpoint(endpoint), status=status.HTTP_200_OK)

    def _validate_cache_age_seconds(self, cache_age_seconds: float | None) -> None:
        """Validate cache_age_seconds is within allowed range."""
        if cache_age_seconds is not None:
            if cache_age_seconds < MIN_CACHE_AGE_SECONDS or cache_age_seconds > MAX_CACHE_AGE_SECONDS:
                raise ValidationError(
                    {
                        "cache_age_seconds": f"Cache age must be between {MIN_CACHE_AGE_SECONDS} and {MAX_CACHE_AGE_SECONDS} seconds."
                    }
                )

    def validate_request(self, data: EndpointRequest, strict: bool = True) -> None:
        query = data.query
        if not query and strict:
            raise ValidationError("Must specify query")

        name = data.name
        if not name:
            if name is not None or strict:
                raise ValidationError("Endpoint must have a name.")
            return
        if not isinstance(name, str) or not re.fullmatch(ENDPOINT_NAME_REGEX, name):
            raise ValidationError(
                "Endpoint name must start with a letter, contain only alphanumeric characters, hyphens, or underscores, "
                "and be between 1 and 128 characters long."
            )

        self._validate_cache_age_seconds(data.cache_age_seconds)

    @extend_schema(
        request=EndpointRequest,
        description="Create a new endpoint",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        """Create a new endpoint."""
        upgraded_query = upgrade(request.data)
        data = self.get_model(upgraded_query, EndpointRequest)
        self.validate_request(data, strict=True)

        try:
            query_dict = cast(Union[HogQLQuery, InsightQueryNode], data.query).model_dump()
            endpoint = Endpoint.objects.create(
                team=self.team,
                created_by=cast(User, request.user),
                name=cast(str, data.name),  # verified in validate_request
                query=query_dict,
                description=data.description or "",
                is_active=data.is_active if data.is_active is not None else True,
                cache_age_seconds=data.cache_age_seconds,
                current_version=1,
                derived_from_insight=data.derived_from_insight,
            )

            EndpointVersion.objects.create(
                endpoint=endpoint,
                version=1,
                query=query_dict,
                created_by=cast(User, request.user),
            )

            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
                item_id=str(endpoint.id),
                scope="Endpoint",
                activity="created",
                detail=Detail(name=endpoint.name),
            )

            # Report endpoint created event
            report_user_action(
                user=cast(User, request.user),
                event="endpoint created",
                properties={
                    "endpoint_id": str(endpoint.id),
                    "endpoint_name": endpoint.name,
                    "query_kind": endpoint.query.get("kind") if isinstance(endpoint.query, dict) else None,
                },
                team=self.team,
            )

            return Response(self._serialize_endpoint(endpoint), status=status.HTTP_201_CREATED)

        except Exception as e:
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team_id,
                    "endpoint_name": data.name,
                },
            )
            raise ValidationError("Failed to create endpoint.")

    def validate_update_request(
        self, data: EndpointRequest, endpoint: Endpoint | None = None, strict: bool = True
    ) -> None:
        self._validate_cache_age_seconds(data.cache_age_seconds)

        # Determine final states after this request (for validation)
        will_be_active = data.is_active if data.is_active is not None else (endpoint.is_active if endpoint else True)

        if not will_be_active and data.is_materialized is True:
            raise ValidationError({"is_materialized": "Cannot enable materialization on inactive endpoint."})

        if not will_be_active and data.sync_frequency is not None:
            raise ValidationError({"sync_frequency": "Cannot set sync_frequency on inactive endpoint."})

        if data.is_materialized is False and data.sync_frequency is not None:
            raise ValidationError({"sync_frequency": "Cannot set sync_frequency when disabling materialization."})

    @extend_schema(
        request=EndpointRequest,
        description="Update an existing endpoint. Parameters are optional.",
    )
    def update(self, request: Request, name: str | None = None, *args, **kwargs) -> Response:
        """Update an existing endpoint."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        before_update = Endpoint.objects.get(pk=endpoint.id)

        upgraded_query = upgrade(request.data)
        data = self.get_model(upgraded_query, EndpointRequest)
        self.validate_update_request(data, endpoint=endpoint, strict=False)

        try:
            query_changed = False
            new_query_dict = None
            if data.query is not None:
                new_query_dict = data.query.model_dump()
                query_changed = endpoint.has_query_changed(new_query_dict)

            if data.description is not None:
                endpoint.description = data.description
            if data.is_active is not None:
                endpoint.is_active = data.is_active
            if "cache_age_seconds" in request.data:
                endpoint.cache_age_seconds = data.cache_age_seconds

            endpoint.save()

            final_is_active = data.is_active if data.is_active is not None else endpoint.is_active
            was_materialized = endpoint.is_materialized

            # Step 1: Handle deactivation (disables materialization, prevents any materialization operations)
            if not final_is_active and was_materialized:
                self._disable_materialization(endpoint)

            # Step 2: Handle query changes and versioning (independent of active/materialization state)
            old_sync_frequency: DataWarehouseSyncInterval | None = None
            if query_changed and new_query_dict is not None:
                if was_materialized and endpoint.saved_query:
                    frequency_str = sync_frequency_interval_to_sync_frequency(
                        endpoint.saved_query.sync_frequency_interval
                    )
                    if frequency_str:
                        old_sync_frequency = DataWarehouseSyncInterval(frequency_str)
                    self._disable_materialization(endpoint)

                endpoint.create_new_version(query=new_query_dict, user=cast(User, request.user))

            # Step 3: Handle materialization state (only if endpoint should be active)
            if final_is_active:
                should_enable = data.is_materialized is True or (data.is_materialized is None and was_materialized)
                should_disable = data.is_materialized is False

                if should_enable:
                    sync_frequency = data.sync_frequency or old_sync_frequency or DataWarehouseSyncInterval.FIELD_24HOUR
                    self._enable_materialization(endpoint, sync_frequency, request)
                elif should_disable:
                    self._disable_materialization(endpoint)

            changes = changes_between("Endpoint", previous=before_update, current=endpoint)
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
                item_id=str(endpoint.id),
                scope="Endpoint",
                activity="updated",
                detail=Detail(name=endpoint.name, changes=changes),
            )

            return Response(self._serialize_endpoint(endpoint))

        except Exception as e:
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team_id,
                    "endpoint_id": endpoint.id,
                    "saved_query_id": endpoint.saved_query.id if endpoint.saved_query else None,
                },
            )
            raise ValidationError("Failed to update endpoint.")

    def _enable_materialization(
        self,
        endpoint: Endpoint,
        sync_frequency: DataWarehouseSyncInterval,
        request: Request,
    ) -> None:
        can_mat, reason = endpoint.can_materialize()
        if not can_mat:
            raise ValidationError(f"Cannot materialize endpoint: {reason}")

        saved_query = DataWarehouseSavedQuery.objects.filter(name=endpoint.name, team=self.team, deleted=False).first()
        if saved_query is None:
            saved_query = DataWarehouseSavedQuery(
                name=endpoint.name, team=self.team, origin=DataWarehouseSavedQuery.Origin.ENDPOINT
            )

        hogql_query = convert_insight_query_to_hogql(endpoint.query, self.team)
        saved_query.query = hogql_query
        saved_query.external_tables = saved_query.s3_tables
        saved_query.is_materialized = True
        saved_query.sync_frequency_interval = (
            sync_frequency_to_sync_frequency_interval(sync_frequency.value) if sync_frequency else timedelta(hours=12)
        )
        saved_query.save()
        saved_query.schedule_materialization()

        endpoint.saved_query = saved_query
        endpoint.save()

    def _disable_materialization(self, endpoint: Endpoint) -> None:
        """Disable materialization for an endpoint."""
        if endpoint.saved_query:
            endpoint.saved_query.revert_materialization()
            endpoint.saved_query.soft_delete()
            endpoint.saved_query = None
            endpoint.save()

    def destroy(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Delete an endpoint and clean up materialized query."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        endpoint_id = str(endpoint.id)
        endpoint_name = endpoint.name

        if endpoint.saved_query:
            self._disable_materialization(endpoint)

        endpoint.delete()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated_session(request),
            item_id=endpoint_id,
            scope="Endpoint",
            activity="deleted",
            detail=Detail(name=endpoint_name),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _should_use_materialized_table(self, endpoint: Endpoint, data: EndpointRunRequest) -> bool:
        """
        Decide whether to use materialized table or inline execution.

        Returns False if:
        - Not materialized
        - Materialization incomplete/failed
        - Materialized data is stale (older than sync frequency)
        - User overrides present (variables, filters, query)
        - Force refresh requested
        """
        if not endpoint.is_materialized or not endpoint.saved_query:
            return False

        saved_query = endpoint.saved_query
        if saved_query.status not in ["Completed"]:
            return False

        if not saved_query.table:
            return False

        # Check if materialized data is stale
        if saved_query.last_run_at and saved_query.sync_frequency_interval:
            next_refresh_due = saved_query.last_run_at + saved_query.sync_frequency_interval
            if timezone.now() >= next_refresh_due:
                return False

        if data.variables:
            return False

        if data.refresh in ["force_blocking"]:
            return False

        if data.query_override:
            return False

        return True

    def _execute_query_and_respond(
        self,
        query_request_data: dict,
        client_query_id: str | None,
        request: Request,
        variables_override: Optional[builtins.list[HogQLVariable]] = None,
        cache_age_seconds: int | None = None,
        extra_result_fields: dict | None = None,
        debug: bool = False,
    ) -> Response:
        """Shared query execution logic."""
        merged_data = self.get_model(query_request_data, QueryRequest)

        query, client_query_id, execution_mode = _process_query_request(
            merged_data, self.team, client_query_id, request.user
        )
        self._tag_client_query_id(client_query_id)
        tag_queries(product=Product.ENDPOINTS)

        if execution_mode not in BLOCKING_EXECUTION_MODES:
            raise ValidationError("Only sync modes are supported (refresh param)")

        result = process_query_model(
            self.team,
            query,
            variables_override=variables_override,
            execution_mode=execution_mode,
            query_id=client_query_id,
            user=cast(User, request.user),
            is_query_service=(get_query_tag_value("access_method") == "personal_api_key"),
            cache_age_seconds=cache_age_seconds,
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

        if "results" in result:
            results_value = result.pop("results")
            result = {"results": results_value, **result}

        response_status = (
            status.HTTP_202_ACCEPTED
            if result.get("query_status") and result["query_status"].get("complete") is False
            else status.HTTP_200_OK
        )
        return Response(result, status=response_status)

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

    def _execute_materialized_endpoint(
        self, endpoint: Endpoint, data: EndpointRunRequest, request: Request, debug: bool = False
    ) -> Response:
        """Execute against a materialized table in S3."""
        try:
            saved_query = endpoint.saved_query
            if not saved_query:
                raise ValidationError("No materialized query found for this endpoint")

            select_query = ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=[saved_query.name])),
            )

            if data.filters_override and data.filters_override.properties:
                try:
                    property_expr = property_to_expr(data.filters_override.properties, self.team)
                    select_query.where = property_expr
                except Exception:
                    raise ValidationError("Failed to apply property filters.")

            materialized_hogql_query = HogQLQuery(
                query=select_query.to_hogql(), modifiers=HogQLQueryModifiers(useMaterializedViews=True)
            )

            query_request_data = {
                "client_query_id": data.client_query_id,
                "name": f"{endpoint.name}_materialized",
                "refresh": data.refresh or RefreshType.BLOCKING,
                "query": materialized_hogql_query.model_dump(),
            }

            extra_fields = {
                "endpoint_materialized": True,
                "endpoint_materialized_at": saved_query.last_run_at.isoformat() if saved_query.last_run_at else None,
            }
            tag_queries(workload=Workload.ENDPOINTS, warehouse_query=True)

            result = self._execute_query_and_respond(
                query_request_data, data.client_query_id, request, extra_result_fields=extra_fields, debug=debug
            )

            if self._is_cache_stale(result, saved_query):
                query_request_data["refresh"] = RefreshType.FORCE_BLOCKING
                result = self._execute_query_and_respond(
                    query_request_data, data.client_query_id, request, extra_result_fields=extra_fields, debug=debug
                )

            return result
        except Exception as e:
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team_id,
                    "endpoint_name": endpoint.name,
                    "materialized": True,
                    "saved_query_id": saved_query.id if saved_query else None,
                },
            )
            raise

    def _parse_variables(
        self, query: dict[str, dict], variables: dict[str, str]
    ) -> builtins.list[HogQLVariable] | None:
        query_variables = query.get("variables", None)
        if not query_variables:
            return None

        variables_override = []
        for request_variable_code_name, request_variable_value in variables.items():
            variable_id = None
            for query_variable_id, query_variable_value in query_variables.items():
                if query_variable_value.get("code_name", None) == request_variable_code_name:
                    variable_id = query_variable_id

            if variable_id is None:
                raise ValidationError(f"Variable '{request_variable_code_name}' not found in query")

            variables_override.append(
                HogQLVariable(
                    variableId=variable_id,
                    code_name=request_variable_code_name,
                    value=request_variable_value,
                    isNull=True if request_variable_value is None else None,
                )
            )
        return variables_override

    def _execute_inline_endpoint(
        self, endpoint: Endpoint, data: EndpointRunRequest, request: Request, query: dict, debug: bool = False
    ) -> Response:
        """Execute query directly against ClickHouse."""
        try:
            insight_query_override = data.query_override or {}
            for query_field, value in insight_query_override.items():
                query[query_field] = value

            variables_override = self._parse_variables(query, data.variables) if data.variables else None
            query_request_data = {
                "client_query_id": data.client_query_id,
                "filters_override": data.filters_override,
                "name": endpoint.name,
                "refresh": data.refresh,
                "query": query,
            }

            return self._execute_query_and_respond(
                query_request_data,
                data.client_query_id,
                request,
                variables_override=variables_override,
                cache_age_seconds=endpoint.cache_age_seconds,
                debug=debug,
            )

        except Exception as e:
            self.handle_column_ch_error(e)
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team_id,
                    "materialized": False,
                    "endpoint_name": endpoint.name,
                },
            )
            raise

    @extend_schema(
        request=EndpointRunRequest,
        description="Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.",
    )
    @action(methods=["GET", "POST"], detail=True)
    def run(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Execute endpoint with optional parameters."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name, is_active=True)
        data = self.get_model(request.data, EndpointRunRequest)
        self.validate_run_request(data, endpoint)

        # Support version from request body or query params (for backwards compatibility)
        version_number = data.version
        if version_number is None:
            version_param = request.query_params.get("version")
            if version_param is not None:
                try:
                    version_number = int(version_param)
                except (ValueError, TypeError):
                    return Response(
                        {"error": f"Invalid version parameter: {version_param}"}, status=status.HTTP_400_BAD_REQUEST
                    )

        version_obj = None
        try:
            version_obj = endpoint.get_version(version_number)
        except EndpointVersion.DoesNotExist:
            if version_number is not None:
                return Response(
                    {
                        "error": f"Version {version_number} not found for endpoint '{name}'",
                        "current_version": endpoint.current_version,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        # Only the latest version is materialized
        use_materialized = version_number is None and self._should_use_materialized_table(endpoint, data)

        debug = data.debug or False

        try:
            if use_materialized:
                result = self._execute_materialized_endpoint(endpoint, data, request, debug=debug)
            else:
                # Use version's query if available, otherwise use endpoint.query
                query_to_use = (version_obj.query if version_obj else endpoint.query).copy()
                result = self._execute_inline_endpoint(endpoint, data, request, query_to_use, debug=debug)
        except (ExposedHogQLError, ExposedCHQueryError, HogVMException) as e:
            raise ValidationError("An internal error occurred.", getattr(e, "code_name", None))
        except ResolutionError:
            raise ValidationError("An internal error occurred while resolving the query.")
        except ConcurrencyLimitExceeded:
            raise Throttled(detail="Too many concurrent requests. Please try again later.")

        if get_query_tag_value("access_method") == "personal_api_key":
            now = timezone.now()
            if endpoint.last_executed_at is None or (now - endpoint.last_executed_at > timedelta(hours=1)):
                endpoint.last_executed_at = now
                endpoint.save(update_fields=["last_executed_at"])

        if version_obj and isinstance(result.data, dict):
            result.data["endpoint_version"] = version_obj.version
            result.data["endpoint_version_created_at"] = version_obj.created_at.isoformat()

        return result

    def validate_run_request(self, data: EndpointRunRequest, endpoint: Endpoint) -> None:
        if endpoint.query.get("kind") == "HogQLQuery" and (data.query_override):
            raise ValidationError("Only variables and filters_override are allowed when executing a HogQL query")
        if endpoint.query.get("kind") != "HogQLQuery" and data.variables:
            raise ValidationError(
                "Only query_override and filters_override are allowed when executing an Insight query"
            )

    @extend_schema(
        description="Get the last execution times in the past 6 months for multiple endpoints.",
        request=EndpointLastExecutionTimesRequest,
        responses={200: QueryStatusResponse},
    )
    @action(methods=["POST"], detail=False, url_path="last_execution_times")
    def get_endpoints_last_execution_times(self, request: Request, *args, **kwargs) -> Response:
        try:
            tag_queries(product=Product.ENDPOINTS)
            data = EndpointLastExecutionTimesRequest.model_validate(request.data)
            names = data.names
            if not names:
                return Response(
                    QueryStatusResponse(
                        query_status=QueryStatus(id="", team_id=self.team.pk, complete=True)
                    ).model_dump(),
                    status=200,
                )

            validated_names = []
            for name in names:
                if not isinstance(name, str) or not re.fullmatch(ENDPOINT_NAME_REGEX, name):
                    raise ValidationError(f"Invalid endpoint name: {name}")
                validated_names.append(f"'{name}'")
            names_list = ",".join(validated_names)

            query = HogQLQuery(
                query=f"select name, max(query_start_time) as last_executed_at from query_log where name in ({names_list}) and endpoint like '%/endpoints/%' and query_start_time >= (today() - interval 6 month) group by name",
                name="get_endpoints_last_execution_times",
            )
            hogql_runner = HogQLQueryRunner(
                query=query,
                team=self.team,
                modifiers=HogQLQueryModifiers(),
                limit_context=LimitContext.QUERY,
            )
            result = hogql_runner.calculate()

            query_status = QueryStatus(id="", team_id=self.team.pk, complete=True, results=result.results)

            return Response(QueryStatusResponse(query_status=query_status).model_dump(), status=200)
        except ConcurrencyLimitExceeded as c:
            raise Throttled(detail=str(c))
        except Exception as e:
            capture_exception(e, {"product": Product.ENDPOINTS, "team_id": self.team_id})
            raise

    def handle_column_ch_error(self, error):
        if getattr(error, "message", None):
            match = re.search(r"There's no column.*in table", error.message)
            if match:
                # TODO: remove once we support all column types
                raise ValidationError(
                    match.group(0) + ". Note: While in beta, not all column types may be fully supported"
                )
        return

    def _tag_client_query_id(self, query_id: str | None):
        if query_id is None:
            return

        tag_queries(client_query_id=query_id)

    def _serialize_endpoint_version(self, version: EndpointVersion) -> dict:
        """Serialize an EndpointVersion object."""
        return {
            "id": str(version.id),
            "version": version.version,
            "query": version.query,
            "created_at": version.created_at.isoformat(),
            "created_by": UserBasicSerializer(version.created_by).data if version.created_by else None,
        }

    @extend_schema(
        description="List all versions for an endpoint.",
    )
    @action(methods=["GET"], detail=True)
    def versions(self, request: Request, name=None, *args, **kwargs) -> Response:
        """List all versions for an endpoint.

        Returns versions in descending order (latest first).
        """
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        versions = endpoint.versions.all()

        results = [self._serialize_endpoint_version(v) for v in versions]
        return Response(results)

    @extend_schema(
        description="Get details of a specific endpoint version.",
    )
    @action(methods=["GET"], detail=True, url_path=r"versions/(?P<version_number>[0-9]+)")
    def version_detail(self, request: Request, name=None, version_number=None, *args, **kwargs) -> Response:
        """Get details of a specific version."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)

        try:
            version_obj = endpoint.get_version(int(version_number))
        except EndpointVersion.DoesNotExist:
            return Response({"error": f"Version {version_number} not found"}, status=status.HTTP_404_NOT_FOUND)

        if version_obj is None:
            return Response({"error": f"Version {version_number} not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(self._serialize_endpoint_version(version_obj))

    @extend_schema(
        description="Get materialization status for an endpoint.",
    )
    @action(methods=["GET"], detail=True, url_path="materialization_status")
    def materialization_status(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Get materialization status for an endpoint without fetching full endpoint data."""
        endpoint = get_object_or_404(Endpoint.objects.select_related("saved_query"), team=self.team, name=name)

        if endpoint.is_materialized and endpoint.saved_query:
            sync_freq_str = None
            if endpoint.saved_query.sync_frequency_interval:
                sync_freq_str = sync_frequency_interval_to_sync_frequency(endpoint.saved_query.sync_frequency_interval)

            result = {
                "status": endpoint.materialization_status,
                "can_materialize": True,
                "last_materialized_at": (
                    endpoint.last_materialized_at.isoformat() if endpoint.last_materialized_at else None
                ),
                "error": endpoint.materialization_error,
                "sync_frequency": sync_freq_str,
            }
        else:
            can_mat, reason = endpoint.can_materialize()
            result = {
                "can_materialize": can_mat,
                "reason": reason if not can_mat else None,
            }

        return Response(result)

    @extend_schema(
        description="Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.",
    )
    @action(methods=["GET"], detail=True, url_path="openapi.json")
    def openapi_spec(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Generate OpenAPI 3.0 specification for this endpoint.

        Returns a spec that can be used with tools like openapi-generator,
        `@hey-api/openapi-ts`, or any other OpenAPI-compatible SDK generator.
        """
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        spec = generate_openapi_spec(endpoint, self.team.id, request)
        return Response(spec, content_type="application/json")
