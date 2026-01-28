import re
import builtins
from datetime import timedelta
from typing import Union, cast

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
    EndpointRefreshMode,
    EndpointRequest,
    EndpointRunRequest,
    HogQLQuery,
    HogQLQueryModifiers,
    HogQLVariable,
    ProductKey,
    QueryRequest,
    QueryStatus,
    QueryStatusResponse,
    RefreshType,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_select
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
from posthog.errors import ExposedCHQueryError
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import BLOCKING_EXECUTION_MODES
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
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
from products.endpoints.backend.rate_limit import (
    EndpointBurstThrottle,
    EndpointSustainedThrottle,
    clear_endpoint_materialization_cache,
)

from common.hogvm.python.utils import HogVMException

MIN_CACHE_AGE_SECONDS = 300
MAX_CACHE_AGE_SECONDS = 86400

ENDPOINT_NAME_REGEX = r"^[a-zA-Z][a-zA-Z0-9_-]{0,127}$"


def _endpoint_refresh_mode_to_refresh_type(
    mode: EndpointRefreshMode | None,
) -> RefreshType:
    """
    Map EndpointRefreshMode to RefreshType.

    - cache -> blocking
    - force/direct -> force_blocking (materialization bypass handled in _should_use_materialized_table)
    """
    if mode is None or mode == EndpointRefreshMode.CACHE:
        return RefreshType.BLOCKING
    return RefreshType.FORCE_BLOCKING


@extend_schema(tags=[ProductKey.ENDPOINTS])
class EndpointViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ModelViewSet):
    # NOTE: Do we need to override the scopes for the "create"
    scope_object = "endpoint"
    # Special case for query - these are all essentially read actions
    scope_object_read_actions = [
        "retrieve",
        "list",
        "run",
        "versions",
        "version_detail",
        "openapi_spec",
    ]
    scope_object_write_actions: list[str] = [
        "create",
        "destroy",
        "update",
        "partial_update",
    ]
    lookup_field = "name"
    queryset = Endpoint.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_active", "created_by"]

    def get_serializer_class(self):
        return None  # We use Pydantic models instead

    def get_throttles(self):
        return [EndpointBurstThrottle(), EndpointSustainedThrottle()]

    def _serialize_endpoint(self, endpoint: Endpoint, request: Request | None = None) -> dict:
        url = None
        ui_url = None
        if request:
            url = request.build_absolute_uri(endpoint.endpoint_path)
            ui_path = f"/project/{endpoint.team_id}/endpoints/{endpoint.name}"
            ui_url = request.build_absolute_uri(ui_path)

        # Get current version for version-specific fields
        # Note: Every endpoint has at least version 1 (created in create())
        current_version = endpoint.get_version()
        is_materialized = bool(current_version.is_materialized and current_version.saved_query)

        result = {
            "id": str(endpoint.id),
            "name": endpoint.name,
            "description": current_version.description,
            "query": current_version.query,
            "is_active": endpoint.is_active,
            "cache_age_seconds": current_version.cache_age_seconds,
            "endpoint_path": endpoint.endpoint_path,
            "url": url,
            "ui_url": ui_url,
            "created_at": endpoint.created_at,
            "updated_at": endpoint.updated_at,
            "created_by": UserBasicSerializer(endpoint.created_by).data if hasattr(endpoint, "created_by") else None,
            "is_materialized": is_materialized,
            "current_version": endpoint.current_version,
            "versions_count": endpoint.versions.count(),
            "derived_from_insight": endpoint.derived_from_insight,
        }

        if is_materialized and current_version and current_version.saved_query:
            saved_query = current_version.saved_query
            result["materialization"] = {
                "status": saved_query.status or "Unknown",
                "can_materialize": True,
                "last_materialized_at": (saved_query.last_run_at.isoformat() if saved_query.last_run_at else None),
                "error": saved_query.latest_error or "",
                "sync_frequency": sync_frequency_interval_to_sync_frequency(saved_query.sync_frequency_interval),
            }
        else:
            can_mat, reason = current_version.can_materialize() if current_version else (False, "No version exists")
            result["materialization"] = {
                "can_materialize": can_mat,
                "reason": reason if not can_mat else None,
            }

        return result

    def list(self, request: Request, *args, **kwargs) -> Response:
        """List all endpoints for the team."""
        queryset = self.filter_queryset(self.get_queryset())
        results = [self._serialize_endpoint(endpoint, request) for endpoint in queryset]
        return Response({"results": results})

    def retrieve(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Retrieve an endpoint."""
        endpoint = get_object_or_404(Endpoint.objects.all(), team=self.team, name=name)
        return Response(self._serialize_endpoint(endpoint, request), status=status.HTTP_200_OK)

    def _validate_cache_age_seconds(self, cache_age_seconds: float | None) -> None:
        """Validate cache_age_seconds is within allowed range."""
        if cache_age_seconds is not None:
            if cache_age_seconds < MIN_CACHE_AGE_SECONDS or cache_age_seconds > MAX_CACHE_AGE_SECONDS:
                raise ValidationError(
                    {
                        "cache_age_seconds": f"Cache age must be between {MIN_CACHE_AGE_SECONDS} and {MAX_CACHE_AGE_SECONDS} seconds."
                    }
                )

    def _validate_hogql_query(self, query_string: str) -> None:
        """Validate that a HogQL query string is syntactically valid."""
        try:
            parse_select(query_string)
        except ExposedHogQLError as e:
            raise ValidationError({"query": f"Invalid HogQL query: {e}"})
        except ResolutionError as e:
            capture_exception(e)
            raise ValidationError({"query": "Invalid HogQL query: unable to resolve table or field references."})

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

        if query and isinstance(query, HogQLQuery) and query.query:
            self._validate_hogql_query(query.query)

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
                is_active=data.is_active if data.is_active is not None else True,
                current_version=1,
                derived_from_insight=data.derived_from_insight,
            )

            EndpointVersion.objects.create(
                endpoint=endpoint,
                version=1,
                query=query_dict,
                description=data.description or "",
                cache_age_seconds=data.cache_age_seconds,
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

            report_user_action(
                user=cast(User, request.user),
                event="endpoint created",
                properties={
                    "endpoint_id": str(endpoint.id),
                    "endpoint_name": endpoint.name,
                    "query_kind": query_dict.get("kind") if isinstance(query_dict, dict) else None,
                },
                team=self.team,
            )

            current_version = endpoint.get_version()
            can_materialize, _ = current_version.can_materialize()
            if can_materialize and query_dict.get("kind") == "HogQLQuery":
                try:
                    sync_frequency = data.sync_frequency or DataWarehouseSyncInterval.FIELD_24HOUR
                    self._enable_materialization(endpoint, sync_frequency, request)
                except Exception as e:
                    capture_exception(
                        e,
                        {
                            "product": Product.ENDPOINTS,
                            "team_id": self.team_id,
                            "endpoint_name": endpoint.name,
                            "message": "Failed to auto-enable materialization on endpoint creation",
                        },
                    )

            return Response(
                self._serialize_endpoint(endpoint, request),
                status=status.HTTP_201_CREATED,
            )

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
        self,
        data: EndpointRequest,
        endpoint: Endpoint | None = None,
        strict: bool = True,
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

        if data.query and isinstance(data.query, HogQLQuery) and data.query.query:
            self._validate_hogql_query(data.query.query)

    @extend_schema(
        request=EndpointRequest,
        description="Update an existing endpoint. Parameters are optional. Use ?version=N to update a specific version's is_active status.",
    )
    def update(self, request: Request, name: str | None = None, *args, **kwargs) -> Response:
        """Update an existing endpoint.

        Supports version targeting via ?version=N query param.
        When version is specified with is_active, updates that specific version's activation status.
        """
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        before_update = Endpoint.objects.get(pk=endpoint.id)

        # Check for version param (query param takes precedence for version-specific updates)
        version_param = request.query_params.get("version")
        target_version_number: int | None = None
        if version_param is not None:
            try:
                target_version_number = int(version_param)
            except (ValueError, TypeError):
                raise ValidationError({"version": f"Invalid version parameter: {version_param}"})

        upgraded_query = upgrade(request.data)
        data = self.get_model(upgraded_query, EndpointRequest)

        # If targeting a specific version, handle version-specific is_active update
        if target_version_number is not None:
            return self._update_version(endpoint, target_version_number, data, request)

        self.validate_update_request(data, endpoint=endpoint, strict=False)

        try:
            current_version = endpoint.get_version()
            query_changed = False
            new_query_dict = None
            if data.query is not None:
                new_query_dict = data.query.model_dump()
                query_changed = endpoint.has_query_changed(new_query_dict)

            if data.is_active is not None:
                endpoint.is_active = data.is_active
            endpoint.save()

            final_is_active = data.is_active if data.is_active is not None else endpoint.is_active
            was_materialized = bool(current_version and current_version.is_materialized and current_version.saved_query)

            # Step 1: Handle deactivation (disables materialization, prevents any materialization operations)
            if not final_is_active and was_materialized:
                self._disable_materialization(endpoint, current_version)

            # Step 2: Handle query changes and versioning (independent of active/materialization state)
            old_sync_frequency: DataWarehouseSyncInterval | None = None
            if query_changed and new_query_dict is not None:
                if was_materialized and current_version and current_version.saved_query:
                    frequency_str = sync_frequency_interval_to_sync_frequency(
                        current_version.saved_query.sync_frequency_interval
                    )
                    if frequency_str:
                        old_sync_frequency = DataWarehouseSyncInterval(frequency_str)
                    self._disable_materialization(endpoint, current_version)

                new_version = endpoint.create_new_version(query=new_query_dict, user=cast(User, request.user))
                current_version = new_version

            # Step 3: Update version-level fields on ALL versions (these are still endpoint-level settings)
            # Using explicit kwargs to avoid semgrep ORM injection warning
            if data.description is not None:
                endpoint.versions.update(description=data.description)
            if "cache_age_seconds" in request.data:
                endpoint.versions.update(cache_age_seconds=data.cache_age_seconds)

            # Step 4: Handle materialization state (only if endpoint should be active)
            if final_is_active and current_version:
                should_enable = data.is_materialized is True or (data.is_materialized is None and was_materialized)
                should_disable = data.is_materialized is False

                if should_enable:
                    sync_frequency = data.sync_frequency or old_sync_frequency or DataWarehouseSyncInterval.FIELD_24HOUR
                    self._enable_materialization(endpoint, sync_frequency, request, current_version)
                elif should_disable:
                    self._disable_materialization(endpoint, current_version)

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

            return Response(self._serialize_endpoint(endpoint, request))

        except Exception as e:
            current_version = endpoint.get_version()
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team_id,
                    "endpoint_id": endpoint.id,
                    "saved_query_id": current_version.saved_query.id if current_version.saved_query else None,
                },
            )
            raise ValidationError("Failed to update endpoint.")

    def _update_version(
        self,
        endpoint: Endpoint,
        version_number: int,
        data: EndpointRequest,
        request: Request,
    ) -> Response:
        """Update a specific version's properties."""
        try:
            version_obj = endpoint.get_version(version_number)
        except EndpointVersion.DoesNotExist:
            return Response(
                {"error": f"Version {version_number} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Capture state before update for activity logging
        before_update = EndpointVersion.objects.get(pk=version_obj.pk)

        # Update is_active if provided
        if data.is_active is not None:
            if not isinstance(data.is_active, bool):
                raise ValidationError({"is_active": "Must be a boolean"})
            version_obj.is_active = data.is_active
            version_obj.save(update_fields=["is_active"])

        changes = changes_between("EndpointVersion", previous=before_update, current=version_obj)
        if changes:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
                item_id=str(endpoint.id),
                scope="EndpointVersion",
                activity="version_updated",
                detail=Detail(name=endpoint.name, changes=changes),
            )

        return Response(self._serialize_endpoint_version(version_obj))

    def _enable_materialization(
        self,
        endpoint: Endpoint,
        sync_frequency: DataWarehouseSyncInterval,
        request: Request,
        version: EndpointVersion | None = None,
    ) -> None:
        """Enable materialization for an endpoint version.

        If version is not specified, uses the current version.
        """
        version = version or endpoint.get_version()

        can_mat, reason = version.can_materialize()
        if not can_mat:
            raise ValidationError(f"Cannot materialize endpoint: {reason}")

        saved_query = DataWarehouseSavedQuery.objects.filter(name=endpoint.name, team=self.team, deleted=False).first()
        if saved_query is None:
            saved_query = DataWarehouseSavedQuery(
                name=endpoint.name,
                team=self.team,
                origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
            )

        hogql_query = convert_insight_query_to_hogql(version.query, self.team)
        saved_query.query = hogql_query
        saved_query.external_tables = saved_query.s3_tables
        saved_query.is_materialized = True
        saved_query.sync_frequency_interval = (
            sync_frequency_to_sync_frequency_interval(sync_frequency.value) if sync_frequency else timedelta(hours=12)
        )
        saved_query.save()
        saved_query.schedule_materialization()

        # Update version with materialization info
        version.saved_query = saved_query
        version.is_materialized = True
        version.save(update_fields=["saved_query", "is_materialized"])

    def _disable_materialization(self, endpoint: Endpoint, version: EndpointVersion | None = None) -> None:
        """Disable materialization for an endpoint version.

        If version is not specified, uses the current version.
        """
        version = version or endpoint.get_version()
        if version and version.saved_query:
            version.saved_query.revert_materialization()
            version.saved_query.soft_delete()
            version.saved_query = None
            version.is_materialized = False
            version.save(update_fields=["saved_query", "is_materialized"])
        clear_endpoint_materialization_cache(self.team_id, endpoint.name)

    def destroy(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Delete an endpoint and clean up materialized query."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        endpoint_id = str(endpoint.id)
        endpoint_name = endpoint.name

        # Disable materialization on all versions
        for version in endpoint.versions.all():
            if version.saved_query:
                self._disable_materialization(endpoint, version)

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

    def _should_use_materialized_table(
        self, endpoint: Endpoint, data: EndpointRunRequest, version: EndpointVersion | None = None
    ) -> bool:
        """
        Decide whether to use materialized table or inline execution.

        Returns False if:
        - Not materialized
        - Materialization incomplete/failed
        - Materialized data is stale (older than sync frequency)
        - User overrides present (variables, query)
        - 'direct' mode requested (explicitly bypass materialization)
        """
        version = version or endpoint.get_version()
        if not version.is_materialized or not version.saved_query:
            return False

        saved_query = version.saved_query
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

        # 'direct' mode explicitly bypasses materialization to run the original query
        if data.refresh == EndpointRefreshMode.DIRECT:
            return False

        if data.query_override:
            return False

        return True

    def _execute_query_and_respond(
        self,
        query_request_data: dict,
        client_query_id: str | None,
        request: Request,
        variables_override: builtins.list[HogQLVariable] | None = None,
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
        self,
        endpoint: Endpoint,
        data: EndpointRunRequest,
        request: Request,
        version: EndpointVersion | None = None,
        debug: bool = False,
    ) -> Response:
        """Execute against a materialized table in S3."""
        try:
            version = version or endpoint.get_version()
            if not version.saved_query:
                raise ValidationError("No materialized query found for this endpoint")
            saved_query = version.saved_query

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
            tag_queries(workload=Workload.ENDPOINTS, warehouse_query=True)

            result = self._execute_query_and_respond(
                query_request_data,
                data.client_query_id,
                request,
                extra_result_fields=extra_fields,
                debug=debug,
            )

            if self._is_cache_stale(result, saved_query):
                query_request_data["refresh"] = RefreshType.FORCE_BLOCKING
                result = self._execute_query_and_respond(
                    query_request_data,
                    data.client_query_id,
                    request,
                    extra_result_fields=extra_fields,
                    debug=debug,
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
        self,
        endpoint: Endpoint,
        data: EndpointRunRequest,
        request: Request,
        query: dict,
        version: EndpointVersion | None = None,
        debug: bool = False,
    ) -> Response:
        """Execute query directly against ClickHouse."""
        try:
            insight_query_override = data.query_override or {}
            for query_field, value in insight_query_override.items():
                query[query_field] = value

            refresh_type = _endpoint_refresh_mode_to_refresh_type(data.refresh)

            variables_override = self._parse_variables(query, data.variables) if data.variables else None
            query_request_data = {
                "client_query_id": data.client_query_id,
                "filters_override": data.filters_override,
                "name": endpoint.name,
                "refresh": refresh_type,
                "query": query,
            }

            cache_age = version.cache_age_seconds if version else None

            return self._execute_query_and_respond(
                query_request_data,
                data.client_query_id,
                request,
                variables_override=variables_override,
                cache_age_seconds=cache_age,
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

        # Support version from request body or query params (for backwards compatibility)
        version_number = data.version
        if version_number is None:
            version_param = request.query_params.get("version")
            if version_param is not None:
                try:
                    version_number = int(version_param)
                except (ValueError, TypeError):
                    return Response(
                        {"error": f"Invalid version parameter: {version_param}"},
                        status=status.HTTP_400_BAD_REQUEST,
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

        self.validate_run_request(data, endpoint, version_obj)

        # Check if we should use materialization for this version
        use_materialized = self._should_use_materialized_table(endpoint, data, version_obj)

        debug = data.debug or False

        try:
            if use_materialized:
                result = self._execute_materialized_endpoint(endpoint, data, request, version=version_obj, debug=debug)
            else:
                # Use version's query
                if not version_obj:
                    return Response(
                        {"error": "No version found for this endpoint"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                query_to_use = version_obj.query.copy()
                result = self._execute_inline_endpoint(
                    endpoint, data, request, query_to_use, version=version_obj, debug=debug
                )
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

    def validate_run_request(
        self, data: EndpointRunRequest, endpoint: Endpoint, version: EndpointVersion | None = None
    ) -> None:
        version = version or endpoint.get_version()
        query = version.query
        is_materialized = bool(version.is_materialized and version.saved_query)

        if version and not version.is_active:
            raise ValidationError(f"Version {version.version} is inactive and cannot be executed.")

        if query.get("kind") == "HogQLQuery" and (data.query_override):
            raise ValidationError("Only variables and filters_override are allowed when executing a HogQL query")
        if query.get("kind") != "HogQLQuery" and data.variables:
            raise ValidationError(
                "Only query_override and filters_override are allowed when executing an Insight query"
            )
        if data.refresh == EndpointRefreshMode.DIRECT and not is_materialized:
            raise ValidationError(
                "'direct' refresh mode is only valid for materialized endpoints. "
                "Use 'cache' or 'force' instead, or enable materialization on this endpoint."
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
                query=f"select name, max(query_start_time) as last_executed_at from query_log where name in ({names_list}) and endpoint like '%/endpoints/%' and is_personal_api_key_request and query_start_time >= (today() - interval 6 month) group by name",
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
            "is_active": version.is_active,
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
            return Response(
                {"error": f"Version {version_number} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(self._serialize_endpoint_version(version_obj))

    @extend_schema(
        description="Get materialization status for an endpoint.",
    )
    @action(methods=["GET"], detail=True, url_path="materialization_status")
    def materialization_status(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Get materialization status for an endpoint without fetching full endpoint data."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        current_version = endpoint.get_version()
        is_materialized = bool(current_version.is_materialized and current_version.saved_query)

        if is_materialized and current_version and current_version.saved_query:
            saved_query = current_version.saved_query
            result = {
                "status": saved_query.status or "Unknown",
                "can_materialize": True,
                "last_materialized_at": (saved_query.last_run_at.isoformat() if saved_query.last_run_at else None),
                "error": saved_query.latest_error or "",
                "sync_frequency": sync_frequency_interval_to_sync_frequency(saved_query.sync_frequency_interval),
            }
        else:
            can_mat, reason = current_version.can_materialize() if current_version else (False, "No version exists")
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
