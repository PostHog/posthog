import re
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

from common.hogvm.python.utils import HogVMException

from .models import Endpoint


@extend_schema(tags=["endpoints"])
class EndpointViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ModelViewSet):
    # NOTE: Do we need to override the scopes for the "create"
    scope_object = "endpoint"
    # Special case for query - these are all essentially read actions
    scope_object_read_actions = ["retrieve", "list", "run"]
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

    def list(self, request: Request, *args, **kwargs) -> Response:
        """List all endpoints for the team."""
        queryset = self.filter_queryset(self.get_queryset())

        results = []
        for endpoint in queryset:
            results.append(
                {
                    "id": str(endpoint.id),
                    "name": endpoint.name,
                    "description": endpoint.description,
                    "query": endpoint.query,
                    "parameters": endpoint.parameters,
                    "is_active": endpoint.is_active,
                    "endpoint_path": endpoint.endpoint_path,
                    "created_at": endpoint.created_at,
                    "updated_at": endpoint.updated_at,
                    "created_by": UserBasicSerializer(endpoint.created_by).data,
                }
            )

        return Response({"results": results})

    def retrieve(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Retrieve an endpoint."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        return Response(
            {
                "id": str(endpoint.id),
                "name": endpoint.name,
                "description": endpoint.description,
                "query": endpoint.query,
                "parameters": endpoint.parameters,
                "is_active": endpoint.is_active,
                "endpoint_path": endpoint.endpoint_path,
                "created_at": endpoint.created_at,
                "updated_at": endpoint.updated_at,
                "created_by": UserBasicSerializer(endpoint.created_by).data,
            },
            status=status.HTTP_200_OK,
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
            endpoint = Endpoint.objects.create(
                team=self.team,
                created_by=cast(User, request.user),
                name=cast(str, data.name),  # verified in validate_request
                query=cast(Union[HogQLQuery, InsightQueryNode], data.query).model_dump(),
                description=data.description or "",
                is_active=data.is_active if data.is_active is not None else True,
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

            return Response(
                {
                    "id": str(endpoint.id),
                    "name": endpoint.name,
                    "description": endpoint.description,
                    "query": endpoint.query,
                    "parameters": endpoint.parameters,
                    "is_active": endpoint.is_active,
                    "endpoint_path": endpoint.endpoint_path,
                    "created_at": endpoint.created_at,
                    "updated_at": endpoint.updated_at,
                },
                status=status.HTTP_201_CREATED,
            )

        # We should expose if the query name is duplicate
        except Exception as e:
            capture_exception(e)
            raise ValidationError("Failed to create endpoint.")

    @extend_schema(
        request=EndpointRequest,
        description="Update an existing endpoint. Parameters are optional.",
    )
    def update(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Update an existing endpoint."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        # Capture a snapshot for diffing
        try:
            before_update = Endpoint.objects.get(pk=endpoint.id)
        except Endpoint.DoesNotExist:
            before_update = None

        upgraded_query = upgrade(request.data)
        data = self.get_model(upgraded_query, EndpointRequest)
        self.validate_request(data, strict=False)

        try:
            if data.name is not None:
                endpoint.name = data.name
            if data.query is not None:
                endpoint.query = data.query.model_dump()
            if data.description is not None:
                endpoint.description = data.description
            if data.is_active is not None:
                endpoint.is_active = data.is_active

            endpoint.save()

            # Activity log: updated with field diffs
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

            return Response(
                {
                    "id": str(endpoint.id),
                    "name": endpoint.name,
                    "description": endpoint.description,
                    "query": endpoint.query,
                    "parameters": endpoint.parameters,
                    "is_active": endpoint.is_active,
                    "endpoint_path": endpoint.endpoint_path,
                    "created_at": endpoint.created_at,
                    "updated_at": endpoint.updated_at,
                }
            )

        except Exception as e:
            capture_exception(e)
            raise ValidationError("Failed to update endpoint.")

    def destroy(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Delete a endpoint."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)
        endpoint.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=EndpointRunRequest,
        description="Update an existing endpoint. Parameters are optional.",
    )
    @action(methods=["GET", "POST"], detail=True)
    def run(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Execute a endpoint with optional parameters."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name, is_active=True)
        data = self.get_model(request.data, EndpointRunRequest)

        self.validate_run_request(data, endpoint)
        data.variables_values = data.variables_values or {}

        try:
            query_variables = endpoint.query.get("variables", {})
            for code_name, value in data.variables_values.items():
                for variable in query_variables.values():
                    if variable.get("code_name", "") == code_name:
                        variable["value"] = value

            insight_query_override = data.query_override or {}
            for query_field, value in insight_query_override.items():
                endpoint.query[query_field] = value

            query_request_data = {
                "client_query_id": data.client_query_id,
                "filters_override": data.filters_override,
                "name": endpoint.name,
                "refresh": data.refresh,  # Allow overriding QueryRequest fields like refresh, client_query_id
                "query": endpoint.query,
                "variables_override": data.variables_override,
            }

            merged_data = self.get_model(query_request_data, QueryRequest)

            query, client_query_id, execution_mode = _process_query_request(
                merged_data, self.team, data.client_query_id, request.user
            )
            self._tag_client_query_id(client_query_id)

            if execution_mode not in BLOCKING_EXECUTION_MODES:
                raise ValidationError("only sync modes are supported (refresh param)")

            result = process_query_model(
                self.team,
                query,
                execution_mode=execution_mode,
                query_id=client_query_id,
                user=cast(User, request.user),
                is_query_service=(get_query_tag_value("access_method") == "personal_api_key"),
            )

            if isinstance(result, BaseModel):
                result = result.model_dump(by_alias=True)

            response_status = (
                status.HTTP_202_ACCEPTED
                if result.get("query_status") and result["query_status"].get("complete") is False
                else status.HTTP_200_OK
            )
            return Response(result, status=response_status)

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

    def validate_run_request(self, data: EndpointRunRequest, endpoint: Endpoint) -> None:
        if endpoint.query.get("kind") == "HogQLQuery" and data.query_override:
            raise ValidationError("Query override is not supported for HogQL queries")

    @extend_schema(
        description="Get the last execution times in the past 6 monthsfor multiple endpoints.",
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


MAX_QUERY_TIMEOUT = 600
