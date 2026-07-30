"""HTTP layer for the Endpoints product.

The viewset is intentionally thin: authentication/permissions, request parsing,
and response serialization. Business logic lives in ``backend/logic``:

- ``logic.crud``: create/update/destroy orchestration + activity logging
- ``logic.execution``: the /run path (materialized / inline / DuckLake)
- ``logic.materialization``: enable/disable/preview materialization
- ``logic.strategies``: HogQL vs insight query behavior
- ``logic.validation``: request payload validation
"""

import re
import dataclasses
from typing import cast

from django.shortcuts import get_object_or_404

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema_view
from openai import APIConnectionError
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    EndpointLastExecutionTimesRequest,
    EndpointRequest,
    EndpointRunRequest,
    QueryStatus,
    QueryStatusResponse,
)

from posthog.api.documentation import extend_schema
from posthog.api.log_entries import LogEntryMixin
from posthog.api.mixins import PydanticModelMixin, ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemViewSetMixin
from posthog.api.utils import action
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.clickhouse.query_tagging import Product
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.permissions import (
    APIScopePermission,
    TeamMemberAccessPermission,
    is_authenticated_via_project_secret_api_key,
)
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import access_level_satisfied_for_resource
from posthog.schema_migrations.upgrade import upgrade

from products.endpoints.backend.facade.api import (
    REWRITE_CONTRACT,
    EndpointCrudService,
    EndpointExecutionService,
    EndpointMaterializationService,
    build_materialization_info,
    generate_openapi_spec,
    get_last_execution_times,
    live_materialization_conditions_source,
    materialization_fix_enabled,
    suggest_materialization_fix,
    validate_bucket_overrides,
    validate_endpoint_request,
    validate_update_request,
)
from products.endpoints.backend.facade.enums import ENDPOINT_NAME_REGEX, ENDPOINTS_LOG_SOURCE
from products.endpoints.backend.facade.models import Endpoint, EndpointVersion
from products.endpoints.backend.presentation.serializers import (
    EndpointMaterializationConditionsSerializer,
    EndpointMaterializationSerializer,
    EndpointMaterializationSuggestionRequestSerializer,
    EndpointMaterializationSuggestionSerializer,
    EndpointRequestSerializer,
    EndpointResponseSerializer,
    EndpointRunResponseSerializer,
    EndpointVersionResponseSerializer,
)
from products.endpoints.backend.presentation.throttles import (
    EndpointBurstThrottle,
    EndpointProjectSecretApiKeyTeamBurstThrottle,
    EndpointProjectSecretApiKeyTeamSustainedThrottle,
    EndpointSustainedThrottle,
)


class MaterializationPreviewRequestSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False)
    bucket_overrides = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text='Per-column bucket function overrides, e.g. {"timestamp": "hour"}',
    )


@extend_schema_view(
    partial_update=extend_schema(
        request=EndpointRequestSerializer,
        responses={200: EndpointResponseSerializer},
        description="Update an existing endpoint.",
    ),
)
class EndpointViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    PydanticModelMixin,
    TaggedItemViewSetMixin,
    LogEntryMixin,
    viewsets.ModelViewSet,
):
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["run"]
    scope_object = "endpoint"
    # Read endpoint execution logs from the `log_entries` table keyed by this source.
    log_source = ENDPOINTS_LOG_SOURCE
    # Special case for query - these are all essentially read actions
    scope_object_read_actions = [
        "retrieve",
        "list",
        "run",
        "versions",
        "openapi_spec",
        "materialization_conditions",
        "materialization_preview",
        "materialization_status",
        "materialization_suggestion",
        "get_endpoints_last_execution_times",
        "logs",
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

    def safely_get_queryset(self, queryset):
        return queryset.filter(deleted=False)

    def get_serializer_class(self):
        return serializers.Serializer  # We use Pydantic models instead; this fallback satisfies drf-spectacular

    def get_throttles(self):
        # Per-user AI throttles: the suggestion action holds a worker on LLM calls, and the
        # endpoint throttles below don't cover session auth
        if self.action == "materialization_suggestion":
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return [
            EndpointBurstThrottle(),
            EndpointSustainedThrottle(),
            EndpointProjectSecretApiKeyTeamBurstThrottle(),
            EndpointProjectSecretApiKeyTeamSustainedThrottle(),
        ]

    def dangerously_get_permissions(self):
        # `run` is the public-facing execution API. It still requires authentication, the
        # `endpoint:read` API scope, and project membership, but intentionally skips
        # resource-level access control (AccessControlPermission) — a restrictive resource-level
        # default must not break execution for API consumers. Explicit per-endpoint
        # (object-level) denials are still enforced in run() via _enforce_object_level_access.
        if self.action == "run":
            return [permission() for permission in (IsAuthenticated, APIScopePermission, TeamMemberAccessPermission)]
        raise NotImplementedError()

    # ------------------------------------------------------------------
    # Access control helpers
    # ------------------------------------------------------------------

    def _get_endpoint_with_object_access(self, name: str | None) -> Endpoint:
        """Fetch a team-scoped endpoint by name and enforce object-level access controls.

        The custom retrieve/destroy/versions/materialization actions fetch endpoints directly via
        get_object_or_404, which bypasses get_object()'s built-in check_object_permissions. Routing
        through here restores that check so per-endpoint resource access controls (RBAC) are honored,
        not just the resource-level defaults.
        """
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name, deleted=False)
        self.check_object_permissions(self.request, endpoint)
        return endpoint

    def _enforce_object_level_access(self, endpoint: Endpoint) -> None:
        """Block execution only when the user is explicitly denied this specific endpoint via an
        object-level access control. Unlike check_object_permissions, this ignores resource-level
        defaults so a restrictive project default doesn't break the public execution API. Creators
        and org admins always pass (specific_access_level_for_object returns the highest level).
        """
        # PSAK scopes are project-wide and deliberately bypass object-level access controls.
        if is_authenticated_via_project_secret_api_key(self.request):
            return
        specific_level = self.user_access_control.specific_access_level_for_object(endpoint)
        if specific_level is not None and not access_level_satisfied_for_resource("endpoint", specific_level, "viewer"):
            raise PermissionDenied("You do not have access to this endpoint.")

    # ------------------------------------------------------------------
    # Request parsing helpers
    # ------------------------------------------------------------------

    def _parse_version_param(self, request: Request) -> int | None:
        """Parse version number from request body or query params.

        Priority: request.data > query param
        Returns int or None. Raises ValidationError if invalid format.
        """
        body_version = request.data.get("version")
        if body_version is not None:
            try:
                return int(body_version)
            except (ValueError, TypeError):
                raise ValidationError({"version": f"Must be an integer, got: {body_version}"})

        query_version = request.query_params.get("version")
        if query_version is not None:
            try:
                return int(query_version)
            except (ValueError, TypeError):
                raise ValidationError({"version": f"Must be an integer, got: {query_version}"})

        return None

    @staticmethod
    def _parse_int_param(
        body_value: int | None, query_param: str | None, name: str, min_value: int | None = None
    ) -> tuple[int | None, Response | None]:
        """Parse an integer from the request body or query params. Returns (value, error_response)."""
        value = body_value
        if value is None and query_param is not None:
            try:
                value = int(query_param)
                if min_value is not None and value < min_value:
                    raise ValueError()
            except (ValueError, TypeError):
                return None, Response(
                    {"error": f"Invalid {name} parameter: {query_param}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif value is not None and min_value is not None and value < min_value:
            return None, Response(
                {"error": f"Invalid {name} parameter: {value}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return value, None

    def _resolve_version_param(self, request: Request, endpoint: Endpoint) -> EndpointVersion | Response:
        """Resolve the ?version=N param to a version, or a 404 Response if it doesn't exist."""
        version_number = self._parse_version_param(request)
        if version_number is None:
            return endpoint.get_version()
        try:
            return endpoint.get_version(version_number)
        except EndpointVersion.DoesNotExist:
            return Response({"error": f"Version {version_number} not found"}, status=status.HTTP_404_NOT_FOUND)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _get_tag_names(self, endpoint: Endpoint) -> list[str]:
        """Read tag names from the prefetched cache or from the DB if not prefetched."""
        if hasattr(endpoint, "prefetched_tags"):
            return sorted({ti.tag.name for ti in endpoint.prefetched_tags})
        return sorted(endpoint.tagged_items.values_list("tag__name", flat=True))

    def _serialize(
        self,
        obj: Endpoint | EndpointVersion,
        request: Request | None = None,
    ) -> dict:
        """Serialize an Endpoint or EndpointVersion.

        Both return the same base fields. EndpointVersion adds version-specific fields.
        """
        if isinstance(obj, EndpointVersion):
            endpoint = obj.endpoint
            version = obj
        else:
            endpoint = obj
            version = endpoint.get_version()

        url = None
        ui_url = None
        if request:
            url = request.build_absolute_uri(endpoint.endpoint_path)
            ui_path = f"/project/{endpoint.team_id}/endpoints/{endpoint.name}"
            ui_url = request.build_absolute_uri(ui_path)

        result = {
            "id": str(endpoint.id),
            "name": endpoint.name,
            "description": version.description,
            "query": version.query,
            "is_active": version.is_active if isinstance(obj, EndpointVersion) else endpoint.is_active,
            "data_freshness_seconds": version.data_freshness_seconds,
            "endpoint_path": endpoint.endpoint_path,
            "url": url,
            "ui_url": ui_url,
            "created_at": endpoint.created_at,
            "updated_at": endpoint.updated_at,
            "created_by": UserBasicSerializer(endpoint.created_by).data if hasattr(endpoint, "created_by") else None,
            "is_materialized": version.is_materialized,
            "current_version": endpoint.current_version,
            "current_version_id": str(version.id),
            "versions_count": endpoint.versions.count(),
            "derived_from_insight": endpoint.derived_from_insight,
            "last_executed_at": endpoint.last_executed_at.isoformat() if endpoint.last_executed_at else None,
            "materialization": build_materialization_info(version),
            "bucket_overrides": version.bucket_overrides,
            "columns": version.get_columns() if version else [],
            "tags": self._get_tag_names(endpoint),
            "optional_breakdown_properties": list(version.optional_breakdown_properties or []),
        }

        if isinstance(obj, EndpointVersion):
            result["version"] = version.version
            result["version_id"] = str(version.id)
            result["endpoint_is_active"] = endpoint.is_active
            # Version detail returns the version's own execution time (may be null until it's been run).
            result["last_executed_at"] = version.last_executed_at.isoformat() if version.last_executed_at else None
            result["version_created_at"] = version.created_at.isoformat()
            result["version_updated_at"] = version.updated_at.isoformat() if version.updated_at else None
            result["version_created_by"] = UserBasicSerializer(version.created_by).data if version.created_by else None

        return result

    # ------------------------------------------------------------------
    # CRUD actions
    # ------------------------------------------------------------------

    @extend_schema(
        responses={200: EndpointResponseSerializer(many=True)},
        description="List all endpoints for the team.",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        """List all endpoints for the team."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            results = [self._serialize(endpoint, request) for endpoint in page]
            return self.get_paginated_response(results)
        results = [self._serialize(endpoint, request) for endpoint in queryset]
        return Response({"results": results})

    @extend_schema(
        responses={200: EndpointVersionResponseSerializer},
        description="Retrieve an endpoint, or a specific version via ?version=N.",
    )
    def retrieve(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Retrieve an endpoint, or a specific endpoint version."""
        endpoint = self._get_endpoint_with_object_access(name)

        version_number = self._parse_version_param(request)
        try:
            if version_number is not None:
                try:
                    version = endpoint.get_version(version_number)
                    return Response(self._serialize(version), status=status.HTTP_200_OK)
                except EndpointVersion.DoesNotExist:
                    return Response(
                        {"error": f"Version {version_number} not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

            return Response(self._serialize(endpoint, request), status=status.HTTP_200_OK)
        except Exception as e:
            capture_exception(e, {"endpoint_name": endpoint.name, "team_id": self.team_id})
            raise ValidationError("Failed to retrieve endpoint.")

    @extend_schema(
        request=EndpointRequestSerializer,
        responses={201: EndpointResponseSerializer},
        description="Create a new endpoint.",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        """Create a new endpoint."""
        upgraded_query = upgrade(request.data)
        data = self.get_model(upgraded_query, EndpointRequest)
        validate_endpoint_request(data, self.team, cast(User, request.user), strict=True)

        endpoint = EndpointCrudService(self.team, request).create(data)

        return Response(
            self._serialize(endpoint, request),
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=EndpointRequestSerializer,
        responses={200: EndpointResponseSerializer},
        description="Update an existing endpoint. Parameters are optional. Pass version in body or ?version=N query param to target a specific version.",
    )
    def update(self, request: Request, name: str | None = None, *args, **kwargs) -> Response:
        """Update an existing endpoint.

        Supports version from body or query params (body takes precedence).
        If version is specified, updates target that specific version.
        Otherwise, the current version is used.
        """
        # Enforce object-level RBAC: a user with global editor scope can still be restricted
        # from a specific endpoint via per-object access controls.
        endpoint = self._get_endpoint_with_object_access(name)

        upgraded_query = upgrade(request.data)
        data = self.get_model(upgraded_query, EndpointRequest)

        # Soft-delete via PATCH {deleted: true} — reuses destroy() logic, returns 200 with body for MCP
        if data.deleted is True:
            self.destroy(request, name=name)
            return Response({"success": True}, status=status.HTTP_200_OK)

        version_number = self._parse_version_param(request)
        validate_update_request(
            data, self.team, cast(User, request.user), endpoint=endpoint, version_number=version_number
        )

        outcome = EndpointCrudService(self.team, request).update(endpoint, data, request.data, version_number)

        # When targeting a specific version, return version data; otherwise return endpoint data
        if outcome.version_targeted and outcome.target_version is not None:
            result = self._serialize(outcome.target_version)
        else:
            result = self._serialize(outcome.endpoint, request)

        if outcome.materialization_error:
            result["materialization_error"] = outcome.materialization_error

        return Response(result)

    def destroy(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Delete an endpoint and clean up materialized query."""
        endpoint = self._get_endpoint_with_object_access(name)
        EndpointCrudService(self.team, request).destroy(endpoint)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_run_request(request: Request) -> EndpointRunRequest:
        """Parse the run body into field-level errors instead of pydantic's raw error dump."""
        try:
            return EndpointRunRequest.model_validate(request.data)
        except PydanticValidationError as exc:
            field_errors = {
                ".".join(str(part) for part in error["loc"]) or "body": error["msg"] for error in exc.errors()
            }
            raise ValidationError(field_errors) from exc

    @staticmethod
    def _rejection_reason(response: Response) -> str:
        data = response.data
        if isinstance(data, dict):
            return str(data.get("error", data))
        return str(data)

    @extend_schema(
        request=EndpointRunRequest,
        responses={200: EndpointRunResponseSerializer},
        description="Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.",
    )
    @action(methods=["GET", "POST"], detail=True)
    def run(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Execute endpoint with optional parameters."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name, is_active=True, deleted=False)
        self._enforce_object_level_access(endpoint)
        service = EndpointExecutionService(self.team, request)
        try:
            data = self._parse_run_request(request)
        except ValidationError as exc:
            service.log_rejected_run(endpoint, service.format_validation_detail(exc.detail))
            raise

        version_number, err = self._parse_int_param(data.version, request.query_params.get("version"), "version")
        if err:
            service.log_rejected_run(endpoint, self._rejection_reason(err))
            return err
        limit, err = self._parse_int_param(data.limit, request.query_params.get("limit"), "limit", min_value=1)
        if err:
            service.log_rejected_run(endpoint, self._rejection_reason(err))
            return err
        offset, err = self._parse_int_param(data.offset, request.query_params.get("offset"), "offset", min_value=0)
        if err:
            service.log_rejected_run(endpoint, self._rejection_reason(err))
            return err

        if offset is not None and limit is None:
            response = Response(
                {"error": "offset requires limit to be set"},
                status=status.HTTP_400_BAD_REQUEST,
            )
            service.log_rejected_run(endpoint, self._rejection_reason(response))
            return response

        version_obj = None
        try:
            version_obj = endpoint.get_version(version_number)
        except EndpointVersion.DoesNotExist:
            if version_number is not None:
                response = Response(
                    {
                        "error": f"Version {version_number} not found for endpoint '{name}'",
                        "current_version": endpoint.current_version,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
                service.log_rejected_run(endpoint, self._rejection_reason(response))
                return response

        return service.execute(endpoint, data, version_obj, limit=limit, offset=offset)

    @extend_schema(
        description=(
            "Get the most recent execution time per endpoint (endpoint-level). "
            "Timestamps are recorded by the run path for personal-API-key calls. "
            "For per-version usage, query the query_log table directly."
        ),
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

            for name in names:
                if not isinstance(name, str) or not re.fullmatch(ENDPOINT_NAME_REGEX, name):
                    raise ValidationError({"names": f"Invalid endpoint name: {name}"})

            results = [[name, ts.isoformat()] for name, ts in get_last_execution_times(self.team.pk, names)]

            query_status = QueryStatus(id="", team_id=self.team.pk, complete=True, results=results)

            return Response(QueryStatusResponse(query_status=query_status).model_dump(), status=200)
        except Exception as e:
            capture_exception(e, {"product": Product.ENDPOINTS, "team_id": self.team_id})
            raise

    # ------------------------------------------------------------------
    # Versions + materialization
    # ------------------------------------------------------------------

    @extend_schema(
        responses={200: EndpointVersionResponseSerializer(many=True)},
        description="List all versions for an endpoint.",
    )
    @action(methods=["GET"], detail=True)
    def versions(self, request: Request, name=None, *args, **kwargs) -> Response:
        """List all versions for an endpoint.

        Returns versions in descending order (latest first).
        """
        endpoint = self._get_endpoint_with_object_access(name)
        versions_qs = endpoint.versions.all()
        page = self.paginate_queryset(versions_qs)
        if page is not None:
            results = [self._serialize(v) for v in page]
            return self.get_paginated_response(results)
        results = [self._serialize(v) for v in versions_qs]
        return Response({"results": results})

    @extend_schema(
        responses={200: EndpointMaterializationSerializer},
        description="Get materialization status for an endpoint. Supports ?version=N query param.",
    )
    @action(methods=["GET"], detail=True, url_path="materialization_status")
    def materialization_status(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Get materialization status for an endpoint without fetching full endpoint data.

        Supports ?version=N query param to get status for a specific version.
        """
        endpoint = self._get_endpoint_with_object_access(name)

        version = self._resolve_version_param(request, endpoint)
        if isinstance(version, Response):
            return version

        return Response(build_materialization_info(version, endpoint_name=endpoint.name))

    @validated_request(
        MaterializationPreviewRequestSerializer,
        description="Preview the materialization transform for an endpoint. Shows what the query will look like after materialization, including range pair detection and bucket functions.",
    )
    @action(methods=["POST"], detail=True, url_path="materialization_preview")
    def materialization_preview(self, request: ValidatedRequest, name=None, *args, **kwargs) -> Response:
        """Preview the materialization transform without enabling it.

        Returns the transformed query, range pair info, and aggregate re-aggregation info.
        """
        endpoint = self._get_endpoint_with_object_access(name)

        version_number = request.validated_data.get("version")
        if version_number is not None:
            try:
                version = endpoint.get_version(version_number)
            except EndpointVersion.DoesNotExist:
                return Response({"error": f"Version {version_number} not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            version = endpoint.get_version()

        bucket_overrides = request.validated_data.get("bucket_overrides")
        if bucket_overrides:
            validate_bucket_overrides(bucket_overrides)

        service = EndpointMaterializationService(self.team, request)
        return Response(dataclasses.asdict(service.preview(endpoint, version, bucket_overrides)))

    @validated_request(
        EndpointMaterializationSuggestionRequestSerializer,
        responses={200: OpenApiResponse(response=EndpointMaterializationSuggestionSerializer)},
        description=(
            "Ask AI to rewrite the endpoint's query into a semantically equivalent form that can be "
            "materialized. Only applicable to SQL (HogQL) endpoints that currently fail the "
            "materialization checks. The suggestion is validated against the live checks before being "
            "returned; nothing is saved. Requires the organization's AI data processing approval."
        ),
    )
    @action(methods=["POST"], detail=True, url_path="materialization_suggestion")
    def materialization_suggestion(self, request: ValidatedRequest, name=None, *args, **kwargs) -> Response:
        """Suggest a semantically equivalent, materializable rewrite of the endpoint's query."""
        endpoint = self._get_endpoint_with_object_access(name)

        if not materialization_fix_enabled(self.team):
            return Response(
                status=status.HTTP_404_NOT_FOUND,
                data={"error": "AI materialization suggestions are not enabled for this project."},
            )

        if self.team.organization.is_ai_data_processing_approved is not True:
            return Response(
                status=status.HTTP_403_FORBIDDEN,
                data={"error": "Enable AI data processing for this organization to use AI suggestions."},
            )

        version = self._resolve_version_param(request, endpoint)
        if isinstance(version, Response):
            return version

        if (version.query or {}).get("kind") != "HogQLQuery":
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": "AI materialization suggestions are only available for SQL endpoints."},
            )

        can_materialize, _ = version.can_materialize()
        if can_materialize:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": "This query can already be materialized."},
            )

        try:
            result = suggest_materialization_fix(
                team_id=self.team_id, query=version.query, original_columns=version.get_columns()
            )
        except APIConnectionError as e:
            capture_exception(e, {"team_id": self.team_id})
            return Response(
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                data={
                    "error": "Couldn't reach the AI service. If you're running locally, the LLM gateway isn't running."
                },
            )
        except Exception as e:
            capture_exception(e, {"team_id": self.team_id, "endpoint_name": endpoint.name})
            return Response(
                status=status.HTTP_502_BAD_GATEWAY,
                data={"error": "The AI suggestion service failed. Try again, or edit the query manually."},
            )

        report_user_action(
            cast(User, request.user),
            "endpoint materialization fix suggested",
            {
                "suggestion_status": result.status,
                "attempts": result.attempts,
                "original_reason": result.original_reason,
            },
            team=self.team,
        )

        return Response(
            {
                "suggestion_status": result.status,
                "suggested_query": result.suggested_query,
                "explanation": result.explanation,
                "attempts": result.attempts,
                "error": result.error,
                "original_reason": result.original_reason,
            }
        )

    @extend_schema(
        responses={200: OpenApiResponse(response=EndpointMaterializationConditionsSerializer)},
        description=(
            "Get the source code of the live materialization checks, plus the rewrite contract. "
            "Lets an agent rewrite a rejected endpoint query itself: fetch these conditions, produce a "
            "semantically equivalent query that passes every check, update the endpoint with it, then "
            "confirm via materialization_status. The source is read from the running system, so it always "
            "matches the checks this instance enforces."
        ),
    )
    @action(methods=["GET"], detail=False, url_path="materialization_conditions")
    def materialization_conditions(self, request: Request, *args, **kwargs) -> Response:
        """Expose the live materialization conditions for client-side (agent) query rewriting."""
        return Response(
            {
                "conditions_source": live_materialization_conditions_source(),
                "rewrite_contract": REWRITE_CONTRACT,
            }
        )

    @extend_schema(
        # url_path="openapi.json" would otherwise produce `..._openapi.json_retrieve` —
        # the `.` is rejected by lint_spec_consistency_hook + the MCP YAML scaffolder.
        operation_id="endpoints_openapi_spec_retrieve",
        description="Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.",
        parameters=[
            OpenApiParameter(
                name="version",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Specific endpoint version to generate the spec for. Defaults to latest.",
            ),
        ],
    )
    @action(methods=["GET"], detail=True, url_path="openapi.json")
    def openapi_spec(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Generate OpenAPI 3.0 specification for this endpoint.

        Returns a spec that can be used with tools like openapi-generator,
        `@hey-api/openapi-ts`, or any other OpenAPI-compatible SDK generator.

        Supports ?version=N query param to generate spec for a specific version.
        """
        endpoint = self._get_endpoint_with_object_access(name)

        version = None
        version_number = self._parse_version_param(request)
        if version_number is not None:
            try:
                version = endpoint.get_version(version_number)
            except EndpointVersion.DoesNotExist:
                return Response({"error": f"Version {version_number} not found"}, status=status.HTTP_404_NOT_FOUND)

        spec = generate_openapi_spec(endpoint, self.team.id, request, version)
        return Response(spec, content_type="application/json")

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    @extend_schema(exclude=True)
    @action(methods=["POST"], detail=False)
    def bulk_update_tags(self, request: Request, *args, **kwargs) -> Response:
        # The inherited TaggedItemViewSetMixin.bulk_update_tags assumes integer PKs (its
        # BulkUpdateTagsRequestSerializer validates ids as IntegerField). Endpoint uses
        # UUID PKs, so the action is unusable. Return 405 until the mixin gains UUID support.
        return Response(
            {"detail": "Bulk tag updates are not supported for endpoints."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )
