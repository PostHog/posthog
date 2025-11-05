import re
from datetime import timedelta
from typing import Union, cast

from django.core.cache import cache
from django.shortcuts import get_object_or_404

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
    QueryRequest,
    QueryStatus,
    QueryStatusResponse,
)

from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError, ResolutionError

from posthog.api.documentation import extend_schema
from posthog.api.mixins import PydanticModelMixin
from posthog.api.query import _process_query_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.query import process_query_model
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import get_query_tag_value, tag_queries
from posthog.constants import AvailableFeature
from posthog.errors import ExposedCHQueryError
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import BLOCKING_EXECUTION_MODES
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.rate_limit import APIQueriesBurstThrottle, APIQueriesSustainedThrottle
from posthog.schema_migrations.upgrade import upgrade
from posthog.types import InsightQueryNode

from products.data_warehouse.backend.data_load.saved_query_service import sync_saved_query_workflow
from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.external_data_schema import (
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
)
from products.data_warehouse.backend.models.modeling import DataWarehouseModelPath
from products.endpoints.backend.models import Endpoint, EndpointVersion

from common.hogvm.python.utils import HogVMException

MIN_CACHE_AGE_SECONDS = 300
MAX_CACHE_AGE_SECONDS = 86400


@extend_schema(tags=["endpoints"])
class EndpointViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ModelViewSet):
    # NOTE: Do we need to override the scopes for the "create"
    scope_object = "endpoint"
    # Special case for query - these are all essentially read actions
    scope_object_read_actions = ["retrieve", "list", "run", "versions", "version_detail"]
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
        if not isinstance(name, str) or not re.fullmatch(r"^[a-zA-Z0-9_-]{1,128}$", name):
            raise ValidationError(
                "Endpoint name must be alphanumeric characters, hyphens, underscores, or spaces, "
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
            )

            EndpointVersion.objects.create(
                endpoint=endpoint,
                version=1,
                query=query_dict,
                created_by=cast(User, request.user),
            )

            # Activity log: created
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

            return Response(self._serialize_endpoint(endpoint), status=status.HTTP_201_CREATED)

        # We should expose if the query name is duplicate
        except Exception as e:
            capture_exception(e)
            raise ValidationError("Failed to create endpoint.")

    def validate_update_request(self, data: EndpointRequest, strict: bool = True) -> None:
        self._validate_cache_age_seconds(data.cache_age_seconds)

        if data.sync_frequency is not None:
            if data.is_materialized is not None and not data.is_materialized:
                raise ValidationError(
                    {"sync_frequency": "sync_frequency can not be set when is_materialized is False."}
                )

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
        self.validate_update_request(data, strict=False)

        try:
            query_changed = False
            new_query_dict = None

            if data.query is not None:
                new_query_dict = data.query.model_dump()
                if endpoint.has_query_changed(new_query_dict):
                    query_changed = True

            if data.description is not None:
                endpoint.description = data.description
            if data.is_active is not None:
                endpoint.is_active = data.is_active
            if "cache_age_seconds" in request.data:
                endpoint.cache_age_seconds = data.cache_age_seconds

            endpoint.save()

            # Handle materialization
            if data.is_materialized is False:
                self._disable_materialization(endpoint)
            elif data.is_materialized is True or (endpoint.is_materialized and data.sync_frequency):
                sync_frequency = data.sync_frequency or DataWarehouseSyncInterval.FIELD_24HOUR
                self._enable_materialization(endpoint, sync_frequency, request)

            if query_changed and new_query_dict is not None:
                # Store old materialization state before creating new version
                old_saved_query = endpoint.saved_query
                was_materialized = old_saved_query is not None
                sync_frequency = None
                if was_materialized and old_saved_query:
                    # Convert sync_frequency_interval back to DataWarehouseSyncInterval enum
                    frequency_str = sync_frequency_interval_to_sync_frequency(old_saved_query.sync_frequency_interval)
                    if frequency_str:
                        sync_frequency = DataWarehouseSyncInterval(frequency_str)

                endpoint.create_new_version(query=new_query_dict, user=cast(User, request.user))

                # Transfer materialization to new version
                if was_materialized and sync_frequency:
                    self._disable_materialization(endpoint)
                    self._enable_materialization(endpoint, sync_frequency, request)

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
            capture_exception(e)
            raise ValidationError("Failed to update endpoint.")

    def _enable_materialization(
        self,
        endpoint: Endpoint,
        sync_frequency: DataWarehouseSyncInterval,
        request: Request,
    ) -> None:
        """Enable materialization for an endpoint."""
        can_mat, reason = endpoint.can_materialize()
        if not can_mat:
            raise ValidationError(f"Cannot materialize endpoint: {reason}")

        saved_query = DataWarehouseSavedQuery.objects.filter(name=endpoint.name, team=self.team, deleted=False).first()
        if saved_query:
            created = False
        else:
            saved_query = DataWarehouseSavedQuery(
                name=endpoint.name, team=self.team, origin=DataWarehouseSavedQuery.Origin.ENDPOINT
            )
            created = True

        saved_query.query = endpoint.query
        saved_query.external_tables = saved_query.s3_tables
        saved_query.is_materialized = True
        saved_query.sync_frequency_interval = (
            sync_frequency_to_sync_frequency_interval(sync_frequency.value) if sync_frequency else timedelta(hours=12)
        )
        saved_query.save()

        endpoint.saved_query = saved_query

        DataWarehouseModelPath.objects.create_or_update_from_saved_query(saved_query)

        if created:
            try:
                sync_saved_query_workflow(saved_query, create=True)
            except Exception as e:
                capture_exception(e, {"endpoint_id": endpoint.id, "saved_query_id": saved_query.id})
                saved_query.is_materialized = False
                saved_query.save(update_fields=["is_materialized"])

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

        if endpoint.saved_query:
            self._disable_materialization(endpoint)

        endpoint.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _should_use_materialized_table(self, endpoint: Endpoint, data: EndpointRunRequest) -> bool:
        """
        Decide whether to use materialized table or inline execution.

        Returns False if:
        - Not materialized
        - Materialization incomplete/failed
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

        if data.variables_values:
            return False

        if data.refresh in ["force_blocking"]:
            return False

        if data.query_override or data.filters_override:
            return False

        return True

    def _execute_query_and_respond(
        self,
        query_request_data: dict,
        client_query_id: str | None,
        request: Request,
        cache_age_seconds: int | None = None,
        extra_result_fields: dict | None = None,
    ) -> Response:
        """Shared query execution logic."""
        merged_data = self.get_model(query_request_data, QueryRequest)

        query, client_query_id, execution_mode = _process_query_request(
            merged_data, self.team, client_query_id, request.user
        )
        self._tag_client_query_id(client_query_id)

        if execution_mode not in BLOCKING_EXECUTION_MODES:
            raise ValidationError("Only sync modes are supported (refresh param)")

        result = process_query_model(
            self.team,
            query,
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

        response_status = (
            status.HTTP_202_ACCEPTED
            if result.get("query_status") and result["query_status"].get("complete") is False
            else status.HTTP_200_OK
        )
        return Response(result, status=response_status)

    def _execute_materialized_endpoint(
        self, endpoint: Endpoint, data: EndpointRunRequest, request: Request
    ) -> Response:
        """Execute using materialized S3 table."""
        from posthog.schema import RefreshType

        saved_query = endpoint.saved_query
        if not saved_query:
            raise ValidationError("No materialized query found for this endpoint")

        materialized_hogql_query = HogQLQuery(
            query=f"SELECT * FROM {saved_query.name}",
            modifiers=HogQLQueryModifiers(useMaterializedViews=True),
        )

        query_request_data = {
            "client_query_id": data.client_query_id,
            "name": f"{endpoint.name}_materialized",
            "refresh": data.refresh or RefreshType.BLOCKING,
            "query": materialized_hogql_query.model_dump(),
        }

        extra_fields = {
            "_materialized": True,
            "_materialized_at": saved_query.last_run_at.isoformat() if saved_query.last_run_at else None,
        }

        return self._execute_query_and_respond(
            query_request_data, data.client_query_id, request, extra_result_fields=extra_fields
        )

    def _execute_inline_endpoint(
        self, endpoint: Endpoint, data: EndpointRunRequest, request: Request, query_override: dict | None = None
    ) -> Response:
        """Execute using inline query (existing implementation).

        Args:
            endpoint: The endpoint to execute
            data: Run request data
            request: HTTP request
            query_override: Optional query to use instead of endpoint.query (for versioning)
        """
        self.validate_run_request(data, endpoint)
        data.variables_values = data.variables_values or {}

        try:
            # Use provided query or fall back to endpoint.query
            base_query = query_override if query_override is not None else endpoint.query.copy()

            query_variables = base_query.get("variables", {})
            for code_name, value in data.variables_values.items():
                for variable in query_variables.values():
                    if variable.get("code_name", "") == code_name:
                        variable["value"] = value

            insight_query_override = data.query_override or {}
            for query_field, value in insight_query_override.items():
                base_query[query_field] = value

            query_request_data = {
                "client_query_id": data.client_query_id,
                "filters_override": data.filters_override,
                "name": endpoint.name,
                "refresh": data.refresh,
                "query": base_query,
                "variables_override": data.variables_override,
            }

            return self._execute_query_and_respond(
                query_request_data, data.client_query_id, request, cache_age_seconds=endpoint.cache_age_seconds
            )

        except (ExposedHogQLError, ExposedCHQueryError, HogVMException) as e:
            raise ValidationError(str(e), getattr(e, "code_name", None))
        except ResolutionError as e:
            raise ValidationError(str(e))
        except ConcurrencyLimitExceeded as c:
            raise Throttled(detail=str(c))
        except Exception as e:
            self.handle_column_ch_error(e)
            capture_exception(e)
            raise

    @extend_schema(
        request=EndpointRunRequest,
        description="Execute endpoint with optional materialization. Supports version parameter to execute specific versions.",
    )
    @action(methods=["GET", "POST"], detail=True)
    def run(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Execute endpoint with optional parameters.

        Query Parameters:
            version (int, optional): Specific version to execute. Defaults to latest.
        """
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name, is_active=True)
        data = self.get_model(request.data, EndpointRunRequest)

        version_param = request.query_params.get("version") or request.data.get("version")
        version_number = None

        if version_param is not None:
            try:
                version_number = int(version_param)
            except (ValueError, TypeError):
                return Response(
                    {"error": f"Invalid version parameter: {version_param}"}, status=status.HTTP_400_BAD_REQUEST
                )

        # Get the version object (if versions exist)
        version_obj = None
        try:
            version_obj = endpoint.get_version(version_number)
        except EndpointVersion.DoesNotExist:
            if version_number is not None:
                # User explicitly requested a version that doesn't exist
                return Response(
                    {
                        "error": f"Version {version_number} not found for endpoint '{name}'",
                        "current_version": endpoint.current_version,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            # No versions exist yet (backward compatibility), use endpoint.query
            version_obj = None

        # Materialization only works with latest version
        use_materialized = version_number is None and self._should_use_materialized_table(endpoint, data)

        if use_materialized:
            result = self._execute_materialized_endpoint(endpoint, data, request)
        else:
            # Use version's query if available, otherwise use endpoint.query
            query_to_use = version_obj.query if version_obj else None
            result = self._execute_inline_endpoint(endpoint, data, request, query_override=query_to_use)

        # Add version metadata to response if version exists
        if version_obj and isinstance(result.data, dict):
            result.data["_version"] = version_obj.version
            result.data["_version_created_at"] = version_obj.created_at.isoformat()

        return result

    def validate_run_request(self, data: EndpointRunRequest, endpoint: Endpoint) -> None:
        if endpoint.query.get("kind") == "HogQLQuery" and data.query_override:
            raise ValidationError("Query override is not supported for HogQL queries")

    @extend_schema(
        description="Get the last execution times in the past 6 months for multiple endpoints.",
        request=EndpointLastExecutionTimesRequest,
        responses={200: QueryStatusResponse},
    )
    @action(methods=["POST"], detail=False, url_path="last_execution_times")
    def get_endpoints_last_execution_times(self, request: Request, *args, **kwargs) -> Response:
        try:
            data = EndpointLastExecutionTimesRequest.model_validate(request.data)
            names = data.names
            if not names:
                return Response(
                    QueryStatusResponse(
                        query_status=QueryStatus(id="", team_id=self.team.pk, complete=True)
                    ).model_dump(),
                    status=200,
                )

            quoted_names = [f"'{name}'" for name in names]
            names_list = ",".join(quoted_names)

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
            capture_exception(e)
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
        versions = endpoint.versions.all()  # Already ordered by -version

        results = [self._serialize_endpoint_version(v) for v in versions]
        return Response(results)

    @extend_schema(
        description="Get details of a specific version.",
    )
    @action(methods=["GET"], detail=True, url_path=r"versions/(?P<version_number>[0-9]+)")
    def version_detail(self, request: Request, name=None, version_number=None, *args, **kwargs) -> Response:
        """Get details of a specific version."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)

        try:
            version_obj = endpoint.get_version(int(version_number))
        except EndpointVersion.DoesNotExist:
            return Response({"error": f"Version {version_number} not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(self._serialize_endpoint_version(version_obj))


MAX_QUERY_TIMEOUT = 600
