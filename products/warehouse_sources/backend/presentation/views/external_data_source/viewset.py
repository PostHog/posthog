"""External data source view set."""

from __future__ import annotations

import uuid
import dataclasses
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.cache import patch_cache_control

import structlog
import temporalio
from dateutil import parser
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from openai import APIConnectionError
from opentelemetry import trace
from psycopg import OperationalError
from rest_framework import filters, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.hogql.database.database import Database
from posthog.hogql.direct_sql.capability import direct_capable_source_types

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import EventSource, get_event_source, is_wizard_self_driving_program, report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.permissions import AccessControlPermission, APIScopePermission, TeamMemberAccessPermission, is_service_auth
from posthog.rate_limit import (
    CustomSourceAIBuilderBurstThrottle,
    CustomSourceAIBuilderDailyThrottle,
    CustomSourceAIBuilderSustainedThrottle,
)

from products.access_control.backend.facade.user_access_control import access_level_satisfied_for_resource
from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.cdp.backend.facade.api import HogFunctionSerializer
from products.cdp.backend.facade.models import HogFunction
from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.data_warehouse.backend.facade.api import (
    bulk_create_external_data_job_schedules,
    bulk_delete_external_data_schedules,
    cancel_external_data_workflow,
    create_and_register_webhook,
    delete_cdc_extraction_schedule,
    delete_discover_schemas_schedule,
    delete_external_data_schedule,
    delete_webhook_and_hog_function,
    ensure_cdc_slot_cleanup_schedule,
    get_direct_query_engine,
    get_namespaced_resource_adapter,
    get_or_create_webhook_hog_function,
    get_webhook_url,
    is_any_external_data_schema_paused,
    is_cdc_enabled_for_team,
    is_cdc_extraction_schedule_paused,
    is_custom_source_ai_builder_enabled_for_team,
    sync_cdc_extraction_schedule,
    sync_discover_schemas_schedule,
    sync_external_data_job_workflow,
    trigger_external_data_source_workflow,
    unpause_cdc_extraction_schedule,
)
from products.revenue_analytics.backend.facade.api import ensure_person_join, remove_person_join
from products.warehouse_sources.backend.facade.api import validate_source_prefix
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    DataWarehouseTable,
    ExternalDataDestination,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
    ExternalDataSourceDestination,
    PendingSourceCredential,
    auto_enable_new_schemas,
    latest_completed_job_prefetch,
    sync_old_schemas_with_new_schemas,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.facade.source_management import (
    DEFAULT_LAG_CRITICAL_THRESHOLD_MB,
    DEFAULT_LAG_WARNING_THRESHOLD_MB,
    AnySource,
    CDCRepairError,
    CDCRepairInProgress,
    CDCSourceAdapter,
    ClickHouseSource,
    Config,
    CustomSource,
    CustomSourceConfig,
    DocsFetchError,
    ExternalWebhookInfo,
    IntegrationAccountListingError,
    MySQLSource,
    OAuthMixin,
    PostgresSource,
    RowFilterValidationError,
    SourceRegistry,
    SourceSchema,
    SQLSource,
    SSLRequiredError,
    WebhookSource,
    build_default_schemas,
    build_default_sync_settings,
    cdc_pg_connection,
    draft_manifest_sync,
    fetch_docs_text,
    filter_dwh_columns_by_enabled_columns,
    filter_integration_accounts,
    get_cdc_adapter,
    get_primary_key_columns,
    new_source_requires_ssl,
    purge_buffer_prefix,
    repair_cdc_source,
    source_type_supports_cdc,
    sql_schema_metadata,
    validate_and_coerce_row_filters,
)
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType
from products.warehouse_sources.backend.presentation.views.destination_links import (
    DestinationLinkSerializer,
    SourceDestinationsSerializer,
    set_source_destinations,
)
from products.warehouse_sources.backend.presentation.views.external_data_schema import (
    ExternalDataSchemaSerializer,
    unsupported_row_filter_reason,
)
from products.warehouse_sources.backend.presentation.views.public_source_configs import build_source_configs

from . import helpers, source_serializers

logger = structlog.get_logger(__name__)


@extend_schema(extensions={"x-product": "warehouse_sources"})
class ExternalDataSourceViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete External data Sources.
    """

    scope_object = "external_data_source"
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "reload",
        "refresh_schemas",
        "database_schema",
        "setup",
        "store_credentials",
        "source_prefix",
        "revenue_analytics_config",
        "destinations",
        "create_webhook",
        "update_webhook_inputs",
        "delete_webhook",
        "check_cdc_prerequisites",
        "check_cdc_prerequisites_for_source",
        "enable_cdc",
        "disable_cdc",
        "repair_cdc",
        "update_cdc_settings",
        # Enumerates the connected provider's accounts/sites — write-scoped so a read-only token can't
        # list them (info disclosure); also gated behind admin in dangerously_get_permissions.
        "oauth_accounts",
        # Live outbound HTTP to a caller-supplied manifest (including POSTs) — a
        # side-effecting action, so it needs write scope, not read.
        "preview_resource",
        # Fetches a caller-supplied docs URL and calls the (paid) LLM gateway — side-effecting.
        "draft_custom_manifest",
    ]
    scope_object_read_actions = [
        "list",
        "retrieve",
        "jobs",
        "wizard",
        "connect_link",
        "stored_credentials",
        "webhook_info",
        "cdc_status",
    ]
    queryset = ExternalDataSource.objects.all()
    serializer_class = source_serializers.ExternalDataSourceSerializers
    filter_backends = [filters.SearchFilter]
    # `source_id` is an opaque internal connection UUID — useless to search by. Callers
    # (the in-app sources list, the MCP tool) narrow by what they can actually see: the
    # source type ("Stripe", "Postgres") and the HogQL table prefix.
    search_fields = ["source_type", "prefix"]
    ordering = "-created_at"

    def check_object_permissions(self, request: Request, obj: Any) -> None:
        super().check_object_permissions(request, obj)
        if request.method not in ("GET", "HEAD", "OPTIONS") and isinstance(obj, ExternalDataSource):
            if obj.is_system_managed:
                raise PermissionDenied("This source is managed by PostHog and cannot be changed through this API.")

    def _assert_can_write_schemas(self, schemas: Iterable[ExternalDataSchema]) -> None:
        """Per-table gate for source-level endpoints that write or sync schemas.

        Editor on the source isn't enough: a table can be locked below that, and these endpoints
        never resolve a schema through DRF's object permissions, so nothing else checks it. Each
        schema resolves like the schema viewset's permission: through its table, which falls back
        to the source via RESOURCE_FALLBACK_MAP.
        """
        # Service credentials are synthetic users UserAccessControl can't evaluate; they're gated by
        # API scope + project membership. Mirror AccessControlPermission.
        if is_service_auth(self.request):
            return
        uac = self.user_access_control
        for schema in schemas:
            level = uac.get_user_access_level(schema.table or schema.source)
            if level is None or not access_level_satisfied_for_resource("warehouse_table", level, "editor"):
                raise PermissionDenied("You do not have editor access to every table in this source.")

    def dangerously_get_permissions(self):
        if self.action == "connections":
            return [
                IsAuthenticated(),
                APIScopePermission(),
                TeamMemberAccessPermission(),
            ]
        # The account picker enumerates every account/site the connected provider exposes, so require
        # manage access even though it's a GET — a read-only member shouldn't discover unrelated
        # accounts (info disclosure). Other actions fall back to the viewset defaults.
        if self.action == "oauth_accounts":
            return [
                IsAuthenticated(),
                APIScopePermission(),
                AccessControlPermission(),
                TeamMemberAccessPermission(),
                source_serializers.AccountPickerManagementPermission(),
            ]
        raise NotImplementedError()

    def get_throttles(self):
        # The AI manifest builder fans out to several Opus calls per request and isn't billed to the
        # customer, so cap it per team: a burst guard against double-submits/retries, an hourly window
        # for an intense setup session, and a daily backstop against scripted abuse.
        if self.action == "draft_custom_manifest":
            return [
                CustomSourceAIBuilderBurstThrottle(),
                CustomSourceAIBuilderSustainedThrottle(),
                CustomSourceAIBuilderDailyThrottle(),
            ]
        return super().get_throttles()

    def finalize_response(self, request: Request, response: Response, *args: Any, **kwargs: Any) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)
        # Tag the request span with the two things that drive source-list load cost — source count and
        # total serialized schema count — so the historically-slow list endpoint is diagnosable in
        # tracing. Done here rather than by overriding `list`, since a method named `list` would shadow
        # the builtin `list[...]` type used in annotations elsewhere in this class. Guarded for shape
        # because finalize_response also runs for error responses (no `results`) and other actions.
        if self.action == "list" and isinstance(response.data, dict):
            results = response.data.get("results")
            if isinstance(results, list):
                span = trace.get_current_span()
                span.set_attribute("data_warehouse.sources.count", len(results))
                span.set_attribute(
                    "data_warehouse.sources.schemas.count",
                    sum(len(source.get("schemas") or []) for source in results if isinstance(source, dict)),
                )
        return response

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action == "create":
            return source_serializers.ExternalDataSourceCreateSerializer
        if self.action == "database_schema":
            return source_serializers.DatabaseSchemaRequestSerializer
        return source_serializers.ExternalDataSourceSerializers

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        # Building the full HogQL Database and serializing per-schema table columns is expensive
        # and only needed when a caller reads `schemas[].table.columns` — which the source list view
        # never does (it only reads name/row_count). Gate both to single-source reads.
        include_columns = self.action != "list"
        context["include_columns"] = include_columns
        # The list serializes a trimmed per-schema shape; single-source reads serialize the full one.
        context["schemas_list_only"] = self.action == "list"
        if include_columns:
            context["database"] = Database.create_for(team_id=self.team_id, user=cast(User, self.request.user))

        return context

    def safely_get_queryset(self, queryset):
        queryset = queryset.exclude(deleted=True)
        canonical_source = helpers._canonical_legacy_managed_warehouse_source(queryset.filter(team_id=self.team_id))
        queryset = helpers._hide_noncanonical_managed_warehouse_sources(queryset, canonical_source)

        # `table__credential` holds EncryptedTextField key material. The list never reads it (trimmed
        # schema shape, include_columns=False), so joining it across every schema — tens of thousands on
        # large sources — is pure waste there and is dropped. Every other action serializes columns
        # (include_columns=True), and building them reads `table.credential.access_key` per schema
        # (see DataWarehouseTable.hogql_definition), so keep the join off the list path only.
        schema_select = ["table__external_data_source"]
        if self.action != "list":
            schema_select.append("table__credential")

        return (
            queryset
            # created_by (FK) and revenue_analytics_config (reverse 1:1) are read per source during
            # serialization. select_related folds them into the main query instead of firing one
            # extra SELECT per source — the reverse 1:1 was an unprefetched N+1 that dominated the
            # list load (up to one query, and a get_or_create write, per source).
            .select_related("created_by", "revenue_analytics_config")
            .prefetch_related(
                latest_completed_job_prefetch(self.team_id, "jobs", to_attr="ordered_jobs"),
                # The one place schemas are read during serialization. `active_schemas` used to be a
                # second prefetch over the same rows — it's now derived in Python from this one (see
                # `_active_schemas`), so the schema table is scanned once.
                Prefetch(
                    "schemas",
                    queryset=ExternalDataSchema.objects.filter(team_id=self.team_id)
                    .exclude(deleted=True)
                    .select_related(*schema_select)
                    .order_by("name"),
                ),
            )
            .order_by(self.ordering)
        )

    def _resolve_stored_credential(
        self, source_type: str, payload: dict
    ) -> source_serializers.ResolvedStoredCredential:
        """Merge a connect-link stored credential into `payload` when it carries a `credential_id`.

        Lets the create and setup flows reference credentials the user entered on the connect page
        instead of passing secrets inline. Only credentials the requesting user stored resolve —
        ids are listable within a team, so without the owner check any member could consume a
        teammate's stashed secrets into a source they control. Returns the (possibly merged)
        payload, the resolved credential (which the caller deletes once consumed — stored
        credentials are single-use), and a 400 Response to return as-is on a lookup miss or
        source-type mismatch.
        """
        credential_id = payload.pop("credential_id", None)
        if credential_id is None:
            return source_serializers.ResolvedStoredCredential(payload=payload, credential=None, error_response=None)
        try:
            credential = PendingSourceCredential.objects.for_team(self.team_id).get(
                id=credential_id, created_by=cast(User, self.request.user), expires_at__gt=timezone.now()
            )
        except (PendingSourceCredential.DoesNotExist, ValueError, TypeError, DjangoValidationError):
            return source_serializers.ResolvedStoredCredential(
                payload=payload,
                credential=None,
                error_response=Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"Stored credential '{credential_id}' not found or expired"},
                ),
            )
        if credential.source_type != source_type:
            return source_serializers.ResolvedStoredCredential(
                payload=payload,
                credential=None,
                error_response=Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": f"Stored credential '{credential_id}' is for "
                        f"'{credential.source_type}', not '{source_type}'"
                    },
                ),
            )
        # Stored credentials win over inline keys so an agent can't override what the user entered.
        return source_serializers.ResolvedStoredCredential(
            payload={**payload, **credential.payload}, credential=credential, error_response=None
        )

    @extend_schema(
        request=source_serializers.ExternalDataSourceCreateSerializer,
        responses={201: source_serializers.ExternalDataSourceCreateResponseSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        payload = dict(serializer.validated_data["payload"] or {})

        secret_ref_response = source_serializers._unresolved_secret_ref_response(payload)
        if secret_ref_response is not None:
            return secret_ref_response

        # A `credential_id` in the payload references connection details the user entered on the
        # connect-link page — resolve it to the real secrets so `create` can target a specific
        # `schemas` set (unlike `setup`, which discovers and enables every table).
        resolved = self._resolve_stored_credential(source_type, payload)
        if resolved.error_response is not None:
            return resolved.error_response

        response = self._create_external_data_source(
            request,
            source_type=source_type,
            payload=resolved.payload,
            prefix=serializer.validated_data.get("prefix"),
            description=serializer.validated_data.get("description"),
            access_method=serializer.validated_data.get("access_method", ExternalDataSource.AccessMethod.WAREHOUSE),
            created_via=serializer.validated_data.get("created_via", ExternalDataSource.CreatedVia.API),
            direct_query_enabled=serializer.validated_data.get("direct_query_enabled", False),
            destination_ids=serializer.validated_data.get("destination_ids"),
        )
        # Stored credentials are single-use: once the source owns them (in job_inputs), drop the stash.
        if resolved.credential is not None and response.status_code == status.HTTP_201_CREATED:
            resolved.credential.delete()
        return response

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                required=True,
                description="The data warehouse source type (e.g. 'BingAds', 'GoogleSearchConsole').",
            ),
            OpenApiParameter(
                name="integration_id",
                type=int,
                required=True,
                description="The OAuth integration id whose accounts should be listed.",
            ),
            OpenApiParameter(
                name="search",
                type=str,
                required=False,
                description="Optional case-insensitive filter over account name/value, for sources whose "
                "resource list is large (e.g. GitHub repositories).",
            ),
        ],
        responses={200: source_serializers.IntegrationAccountsResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="oauth_accounts")
    def oauth_accounts(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List the accounts/properties a connected OAuth integration exposes, in the shared
        IntegrationAccount shape. The logic lives in each source (via OAuthMixin.get_oauth_accounts);
        this endpoint just routes by source type, applies the optional search filter, and serializes."""
        source_type = request.query_params.get("source_type")
        integration_id = request.query_params.get("integration_id")
        search = request.query_params.get("search") or None
        if not source_type or not integration_id:
            raise ValidationError("source_type and integration_id are required")

        try:
            integration_id_int = int(integration_id)
        except ValueError:
            raise ValidationError("integration_id must be an integer")

        try:
            source = SourceRegistry.get_source(cast(ExternalDataSourceType, source_type))
        except ValueError:
            raise ValidationError(f"Unknown source type: {source_type}")

        if not isinstance(source, OAuthMixin):
            raise ValidationError(f"Source type {source_type} does not support listing OAuth accounts")

        # The integration id is caller-supplied and each source looks it up by (id, team_id) only, so
        # without this a same-team integration of a different provider would be accepted here and its
        # OAuth token handed to this source's provider. Pin it to the kind(s) the source's picker
        # declares before any of that runs.
        expected_kinds = helpers.get_oauth_integration_kinds(source.get_source_config.fields)
        if not expected_kinds:
            raise ValidationError(f"Source type {source_type} does not support listing OAuth accounts")
        if not Integration.objects.filter(
            id=integration_id_int, team_id=self.team_id, kind__in=expected_kinds
        ).exists():
            # One message for "gone" and "wrong kind" alike: from the UI both mean the picker is holding
            # a connection this source can't use, and neither tells the caller anything about ids it
            # isn't already allowed to see.
            raise ValidationError(
                f"No {source_type} connection was found for this integration. Please reconnect the integration."
            )

        cache_key = f"oauth_accounts/{self.team_id}/{source_type}/{integration_id_int}/{search or ''}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            accounts = source.get_oauth_accounts(integration_id_int, self.team_id, search=search)
        except NotImplementedError:
            # An OAuth source that hasn't implemented account listing yet (passes the isinstance check).
            raise ValidationError(f"Source type {source_type} does not support listing OAuth accounts")
        except IntegrationAccountListingError as e:
            # Actionable, customer-side failure (revoked/expired token, deleted integration, the provider
            # rejecting the credentials) — surface the message as a 400. Anything else (e.g. a bare
            # ValueError from an internal bug) stays uncaught and becomes a 500 so monitors see it.
            raise ValidationError(str(e))

        # Belt-and-suspenders: sources that support server-side search already return matching results;
        # this filters sources that returned a full list and ignored `search`.
        accounts = filter_integration_accounts(accounts, search)
        response_data = {"accounts": source_serializers.IntegrationAccountSerializer(accounts, many=True).data}
        # Don't cache an empty result: a transient provider hiccup that returns [] without raising would
        # otherwise poison the picker for 60s for every admin on the team.
        if accounts:
            cache.set(cache_key, response_data, 60)
        return Response(response_data)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        # Runs for both PUT and PATCH (DRF's partial_update delegates to update -> perform_update).
        # `created_via` is write-once and reflects original creation origin; the edit's own origin
        # comes from the request-derived `source` that report_user_action attaches.
        super().perform_update(serializer)
        instance = cast(ExternalDataSource, serializer.instance)
        report_user_action(
            cast(User, self.request.user),
            "data warehouse source updated",
            {
                "source_type": instance.source_type,
                "created_via": instance.created_via,
                "source_id": str(instance.pk),
            },
            team=self.team,
            request=self.request,
        )

    def _create_external_data_source(
        self,
        request: Request,
        *,
        source_type: str,
        payload: dict,
        prefix: str | None,
        description: str | None,
        access_method: str,
        created_via: str,
        direct_query_enabled: bool = False,
        skip_credential_validation: bool = False,
        destination_ids: list | None = None,
    ) -> Response:
        # `skip_credential_validation` is set only by the `setup` action, which has already run the
        # full config + credential gate (including the SSRF host check) before discovering schemas.
        # It avoids a second live credential round-trip — and the confusing failure mode where the
        # first check passes but a transient blip fails the second, leaving nothing created.

        # The setup wizard and PostHog's agent surfaces drive creation through the MCP tools, which
        # inject `created_via=mcp` before the request reaches us — the agent can't set the field
        # itself. Upgrade that machine-injected value when the transport identifies one of them, so
        # their runs are distinguishable from other MCP clients. Explicit `web`/`api` values are
        # left alone. The PostHog apps and the headless agents all map to `self_driving`: the
        # distinction between them is an analytics one, and splitting it here would need a new
        # stored value.
        if created_via == ExternalDataSource.CreatedVia.MCP:
            transport_created_via = {
                EventSource.WIZARD: ExternalDataSource.CreatedVia.WIZARD,
                EventSource.DESKTOP: ExternalDataSource.CreatedVia.SELF_DRIVING,
                EventSource.MOBILE: ExternalDataSource.CreatedVia.SELF_DRIVING,
                EventSource.POSTHOG_CODE: ExternalDataSource.CreatedVia.SELF_DRIVING,
                EventSource.SELF_DRIVING: ExternalDataSource.CreatedVia.SELF_DRIVING,
            }
            created_via = transport_created_via.get(get_event_source(request), created_via)
            # The wizard's `self-driving` onboarding program shares the generic `posthog/wizard`
            # transport but marks its UA distinctly — attribute its sources as self_driving too, so
            # a source connected during a self-driving run isn't lumped in with plain wizard setups.
            if created_via == ExternalDataSource.CreatedVia.WIZARD and is_wizard_self_driving_program(request):
                created_via = ExternalDataSource.CreatedVia.SELF_DRIVING
        is_direct_query = access_method == ExternalDataSource.AccessMethod.DIRECT

        if ExternalDataSource.is_system_managed_prefix(prefix):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": helpers.RESERVED_SOURCE_NAME_MESSAGE},
            )

        if is_direct_query and source_type not in direct_capable_source_types():
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": helpers.DIRECT_QUERY_UNSUPPORTED_SOURCE_MESSAGE},
            )

        if is_direct_query:
            prefix = prefix.strip() if isinstance(prefix, str) else ""
            if not prefix:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Name is required for direct query sources"},
                )
        else:
            is_valid, error_message = validate_source_prefix(prefix)
            if not is_valid:
                raise ValidationError(error_message)

            if not prefix:
                if self.prefix_required(source_type):
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={
                            "message": "You already have a source of this type. Add a table prefix so this connection's tables don't clash with your existing source."
                        },
                    )
            elif self.prefix_exists(source_type, prefix):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": f"Another source of this type already uses the prefix '{prefix}'. Choose a different prefix so this connection's tables don't clash."
                    },
                )

        if access_method == ExternalDataSource.AccessMethod.WAREHOUSE and is_any_external_data_schema_paused(
            self.team_id
        ):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        # Strip leading and trailing whitespace
        if payload is not None:
            for key, value in payload.items():
                if isinstance(value, str):
                    payload[key] = value.strip()
        source_type_model = ExternalDataSourceType(source_type)
        source = SourceRegistry.get_source(source_type_model)
        if not is_direct_query and not source.supports_scheduled_sync:
            return Response(
                source_serializers.ExternalDataSourceErrorResponseSerializer(
                    {"message": f"{source_type_model.label} is available only as a direct connection."}
                ).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        max_instances = source.max_instances_per_team
        if max_instances is not None and helpers.count_active_sources(self.team_id, source_type_model) >= max_instances:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"You can create at most {max_instances} sources of this type per project."},
            )
        if skip_credential_validation:
            source_config: Config = source.parse_config(payload)
        else:
            error_response, validated_config = self._validate_source_config_and_credentials(
                source, source_type_model, payload, access_method=access_method
            )
            if error_response is not None or validated_config is None:
                return error_response or Response(status=status.HTTP_400_BAD_REQUEST)
            source_config = validated_config

        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            created_by=request.user if isinstance(request.user, User) else None,
            created_via=created_via,
            team=self.team,
            status="Running",
            source_type=source_type_model,
            api_version=source.default_version,
            job_inputs=source_config.to_dict(),
            prefix=prefix,
            description=description,
            access_method=access_method,
            direct_query_enabled=direct_query_enabled,
        )

        # Post-create hook (Custom claims its bound OAuth2 integration row here). No-op otherwise.
        source.on_source_created(new_source_model, self.team_id)

        # CDC: gate per-source-type adapter availability up front so downstream blocks
        # can `if cdc_enabled` without repeating the source-type check.
        try:
            cdc_adapter: CDCSourceAdapter | None = get_cdc_adapter(new_source_model)
        except ValueError:
            cdc_adapter = None
        cdc_enabled = (
            payload.get("cdc_enabled", False) and cdc_adapter is not None and is_cdc_enabled_for_team(self.team)
        )

        try:
            source_schemas = source.get_schemas(
                source_config, self.team_id, api_version=source.resolve_api_version(new_source_model.api_version)
            )
        except NotImplementedError:
            # Source doesn't implement schema discovery (e.g. an unreleased scaffold the UI hides).
            # Roll back the row just created so a caller can't accumulate orphaned sources, and return
            # a clean 400 instead of the uncaught 500 this would otherwise raise. Mirrors `setup`.
            new_source_model.delete()
            # nosemgrep: api-response-must-match-schema -- conventional error message, not a schema-bound payload
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": helpers._source_unavailable_message(source_type)},
            )
        except Exception as e:
            # `get_schemas` opens its own connection, so credentials validated above can still fail
            # here (e.g. a BigQuery service account key rotated/revoked in between). Classify via
            # the source's own non-retryable-error map, same as `database_schema` and
            # `refresh_schemas`, and roll back the row so a source that can't discover its schema
            # doesn't linger half-created.
            error_message, is_expected_source_error = helpers._classify_refresh_schemas_error(source, e)
            if not is_expected_source_error:
                capture_exception(
                    e,
                    {
                        "source_type": source_type,
                        "team_id": self.team_id,
                        "source_id": str(new_source_model.id),
                    },
                )
            new_source_model.delete()
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": error_message},
            )
        if is_direct_query:
            new_source_model.connection_metadata = helpers.get_direct_connection_metadata(
                source_impl=source,
                source_config=source_config,
                team_id=self.team_id,
                source_model=new_source_model,
            )
            new_source_model.save(update_fields=["connection_metadata", "updated_at"])
        source_schemas_by_name = {schema.name: schema for schema in source_schemas}
        schema_names = [schema.name for schema in source_schemas]
        source_config_dict = source_config.to_dict()
        default_source_schema = source_config_dict.get("schema")
        default_source_catalog = source_config_dict.get("database") or source_config_dict.get("catalog")
        schema_label_by_name = {s.name: s.label for s in source_schemas}

        # Omitting `schemas` means "sync what you found", the same defaults `setup` builds. A
        # caller that wants to hand-pick tables still sends the array; one that just has
        # credentials no longer has to run schema discovery itself to write back what we already
        # know. Discovery ran above, so the defaults cost nothing extra here.
        payload_schemas = payload.get("schemas")
        if payload_schemas is not None and not isinstance(payload_schemas, list):
            new_source_model.delete()
            return Response(
                data={"message": "The 'schemas' field must be a list of the tables to sync."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not payload_schemas:
            payload_schemas = build_default_schemas(source_schemas)

        # Return 400 if we get any schema names that don't exist in our source
        if any(schema.get("name") not in schema_names for schema in payload_schemas):
            new_source_model.delete()
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Schemas given do not exist in source"},
            )

        # Refuse per-schema `sync_type=cdc` when source-level CDC is off — `_setup_cdc_resources`
        # would be skipped, leaving the source with no replication slot/publication.
        if not cdc_enabled:
            cdc_schemas_in_payload = sorted(
                {
                    schema["name"]
                    for schema in payload_schemas
                    if schema.get("sync_type") == "cdc"
                    and schema.get("should_sync", False)
                    and isinstance(schema.get("name"), str)
                }
            )
            if cdc_schemas_in_payload:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": (
                            "CDC must be enabled on the source before selecting it as a sync type. "
                            f"The following schemas requested CDC: {', '.join(cdc_schemas_in_payload)}."
                        )
                    },
                )

        active_schemas: list[ExternalDataSchema] = []

        # Pre-fetch PK column names for CDC tables
        pk_columns_by_table: dict[str, list[str]] = {}
        if cdc_enabled:
            cdc_table_names_by_schema: dict[str, set[str]] = {}
            cdc_schema_name_by_location: dict[tuple[str, str], str] = {}
            for schema in payload_schemas:
                if schema.get("sync_type") != "cdc" or not schema.get("should_sync", False):
                    continue

                schema_name = schema.get("name")
                if not isinstance(schema_name, str):
                    continue

                _, resolved_source_schema, resolved_source_table_name = helpers.get_postgres_source_table_location(
                    schema_name=schema_name,
                    source_schema=source_schemas_by_name.get(schema_name),
                    default_schema=default_source_schema,
                )
                cdc_table_names_by_schema.setdefault(resolved_source_schema, set()).add(resolved_source_table_name)
                cdc_schema_name_by_location[(resolved_source_schema, resolved_source_table_name)] = schema_name

            if cdc_table_names_by_schema:
                try:
                    with cdc_pg_connection(new_source_model) as conn:
                        for db_schema, cdc_table_names in cdc_table_names_by_schema.items():
                            queried_pks = get_primary_key_columns(conn, db_schema, list(cdc_table_names))
                            for table_name, primary_key_columns in queried_pks.items():
                                schema_name = cdc_schema_name_by_location.get((db_schema, table_name))
                                if schema_name is not None:
                                    pk_columns_by_table[schema_name] = primary_key_columns
                except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
                    # Connecting to the user's database to detect CDC primary keys is expected to
                    # fail when the host, port, credentials, or SSH tunnel are wrong, or the server
                    # requires/refuses SSL. Surface it as a 400, but don't capture it — these are
                    # user/upstream connection problems, not bugs in our code, and capturing every
                    # one floods error tracking. Mirrors the CDC-prerequisite handlers below.
                    new_source_model.delete()
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"Could not connect to your database to set up change data capture: {e}"},
                    )

            # CDC needs a PK for UPDATE/DELETE merges. Refuse here so `_setup_cdc_resources` doesn't
            # create replication state on the source for a config we're about to reject.
            tables_missing_pk = sorted(
                {
                    schema["name"]
                    for schema in payload_schemas
                    if schema.get("sync_type") == "cdc"
                    and schema.get("should_sync", False)
                    and isinstance(schema.get("name"), str)
                    and not pk_columns_by_table.get(schema["name"])
                }
            )
            if tables_missing_pk:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": (
                            "CDC requires a primary key on each table. "
                            f"The following tables have no primary key: {', '.join(tables_missing_pk)}."
                        )
                    },
                )

        # Engine-side CDC resource setup runs after PK validation so we don't leave
        # replication state on the source for a config we're about to refuse.
        if cdc_enabled:
            assert cdc_adapter is not None  # narrowed by `cdc_enabled`
            cdc_error = self._setup_cdc_resources(cdc_adapter, new_source_model, payload)
            if cdc_error is not None:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": cdc_error},
                )

        # Direct-query table materialization is engine-specific; dispatch on the engine, not the
        # source type. None for non-direct-capable sources.
        direct_engine_adapter = get_direct_query_engine(new_source_model.direct_engine)

        # Create all ExternalDataSchema objects and enable syncing for active schemas
        for schema in payload_schemas:
            sync_type = schema.get("sync_type")
            requires_incremental_fields = sync_type == "incremental" or sync_type == "append"
            incremental_field = schema.get("incremental_field")
            incremental_field_type = schema.get("incremental_field_type")
            primary_key_columns = schema.get("primary_key_columns")
            sync_time_of_day = schema.get("sync_time_of_day")
            should_sync = schema.get("should_sync", False)
            payload_enabled_columns = schema.get("enabled_columns")
            if isinstance(payload_enabled_columns, list):
                # `[]` and `None` are distinct: `None` means sync all columns, `[]` means
                # sync only the always-retained PK + incremental field.
                enabled_columns: list[str] | None = [
                    str(column) for column in payload_enabled_columns if isinstance(column, str)
                ]
            else:
                enabled_columns = None

            payload_row_filters = schema.get("row_filters")
            row_filters: list[dict[str, Any]] | None = (
                payload_row_filters if isinstance(payload_row_filters, list) and payload_row_filters else None
            )

            if should_sync and requires_incremental_fields and incremental_field is None:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Incremental schemas given do not have an incremental field set"},
                )

            if should_sync and requires_incremental_fields and incremental_field_type is None:
                new_source_model.delete()
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Incremental schemas given do not have an incremental field type set"},
                )

            schema_name = schema.get("name")
            source_schema = source_schemas_by_name.get(schema_name)

            metadata_source_catalog: str | None
            metadata_source_schema: str | None
            metadata_source_table_name: str | None
            # Direct mode needs a resolved source location for the live-query table; warehouse mode
            # keeps storing whatever the source reported to avoid changing sync routing (except
            # Postgres, which resolves in both modes — carried by the adapter flag).
            if direct_engine_adapter is not None and (
                is_direct_query or direct_engine_adapter.resolves_location_in_warehouse_mode
            ):
                metadata_source_catalog, metadata_source_schema, metadata_source_table_name = (
                    direct_engine_adapter.source_table_location(
                        schema_name=schema_name,
                        source_schema=source_schema,
                        default_schema=default_source_schema,
                        default_catalog=default_source_catalog,
                    )
                )
            else:
                metadata_source_catalog = source_schema.source_catalog if source_schema else None
                metadata_source_schema = source_schema.source_schema if source_schema else None
                metadata_source_table_name = source_schema.source_table_name if source_schema else None

            schema_metadata = (
                sql_schema_metadata(
                    source_schema.columns if source_schema else [],
                    source_schema.foreign_keys if source_schema else [],
                    source_catalog=metadata_source_catalog,
                    source_schema=metadata_source_schema,
                    source_table_name=metadata_source_table_name,
                )
                if source.supports_column_selection
                else {}
            )
            # Sources that namespace tables outside SQL schemas (e.g. GitHub repos) attach their
            # own location keys on the discovered schema; persist them so sync-time resolution
            # never depends on parsing the row name.
            if source_schema is not None and source_schema.schema_metadata:
                schema_metadata = {**schema_metadata, **source_schema.schema_metadata}

            if row_filters is not None:
                # Only sources that push filters into their query (SQL WHERE) can honor them — a
                # saved-but-ignored filter would silently sync unfiltered rows.
                if not source.supports_row_filters:
                    new_source_model.delete()
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={
                            "message": f"Row filter not allowed for schema '{schema_name}': "
                            "row filters are not supported for this source type."
                        },
                    )
                if reason := unsupported_row_filter_reason(
                    is_direct_query=new_source_model.is_direct_query, is_cdc=sync_type == "cdc"
                ):
                    new_source_model.delete()
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"Row filter not allowed for schema '{schema_name}': {reason}"},
                    )
                try:
                    validate_and_coerce_row_filters(row_filters, schema_metadata)
                except RowFilterValidationError as e:
                    new_source_model.delete()
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"Invalid row filter for schema '{schema_name}': {e}"},
                    )

            is_cdc_schema = sync_type == "cdc"
            # A CDC table the user isn't enabling hasn't been "set up" — leave its sync method
            # blank so the schemas UI prompts the user to configure it before it can sync, rather
            # than presetting `cdc` on every discovered table. Only tables the user actively
            # enables get a concrete CDC method + config.
            cdc_not_set_up = is_cdc_schema and not should_sync
            if requires_incremental_fields and new_source_model.supports_scheduled_sync:
                # If the caller didn't provide primary_key_columns, fall back to whatever the
                # source detected during schema discovery. Otherwise we rely on sync-time
                # re-detection, which can disagree with discovery (e.g. permissions differences
                # across query paths) and leave incremental syncs without a primary key.
                effective_primary_key_columns = primary_key_columns or (
                    source_schema.detected_primary_keys if source_schema else None
                )
                # Lookback only applies to incremental (merge-by-PK makes the overlap re-read idempotent).
                # Mirror the schema-update path's IntegerField(min_value=0, max_value=5_184_000) so both
                # creation paths reject the same inputs instead of silently dropping null/float values.
                lookback_seconds = schema.get("incremental_field_lookback_seconds")
                # When the caller didn't set a lookback, fall back to the source-defined default
                # (e.g. Google Ads stats tables, whose recent rows Google keeps revising for days).
                # This loop is the single creation choke point, so the default reaches both the
                # wizard and one-shot flows; it's then validated by the bounds check just below.
                if lookback_seconds is None and source_schema is not None:
                    lookback_seconds = source_schema.default_incremental_lookback_seconds
                if lookback_seconds is not None:
                    # Coerce whole-number floats (e.g. 90.0) the way DRF's IntegerField does.
                    if isinstance(lookback_seconds, float) and lookback_seconds.is_integer():
                        lookback_seconds = int(lookback_seconds)
                    # bool is an int subclass — exclude it so true/false aren't treated as 1/0.
                    is_valid_int = isinstance(lookback_seconds, int) and not isinstance(lookback_seconds, bool)
                    if not is_valid_int or not (0 <= lookback_seconds <= 5_184_000):
                        new_source_model.delete()
                        return Response(
                            status=status.HTTP_400_BAD_REQUEST,
                            data={
                                "message": f"incremental_field_lookback_seconds must be an integer between 0 and 5184000 (60 days) for schema '{schema_name}'."
                            },
                        )
                # Canonicalize the incremental field against what the source declares for this
                # endpoint: discovery surfaces both a display `label` and the underlying `field`
                # (e.g. Stripe's label "created_at" -> field "created"), and API callers regularly
                # send the label — which then fails every sync with a missing-column error. Match on
                # either and persist the declared field + its real field_type.
                if incremental_field is not None and source_schema is not None:
                    for declared in source_schema.incremental_fields:
                        if incremental_field in (declared["field"], declared["label"]):
                            incremental_field = declared["field"]
                            incremental_field_type = str(declared["field_type"])
                            break

                sync_type_config = {
                    "incremental_field": incremental_field,
                    "incremental_field_type": incremental_field_type,
                    "schema_metadata": schema_metadata,
                    **({"primary_key_columns": effective_primary_key_columns} if effective_primary_key_columns else {}),
                    **(
                        {"incremental_field_lookback_seconds": lookback_seconds}
                        if sync_type == "incremental" and lookback_seconds is not None
                        else {}
                    ),
                }
            elif is_cdc_schema and not cdc_not_set_up:
                cdc_table_mode = schema.get("cdc_table_mode", "consolidated")
                sync_type_config = {
                    "cdc_mode": "snapshot",
                    "primary_key_columns": pk_columns_by_table.get(schema_name, []),
                    "schema_metadata": schema_metadata,
                    "cdc_table_mode": cdc_table_mode,
                }
            else:
                sync_type_config = {"schema_metadata": schema_metadata}

            # CDC schemas benefit from a tighter poll cadence — the extraction workflow is cheap
            # and the value prop is near-real-time. Other sync types use the 6h default.
            schema_sync_frequency_interval = (
                timedelta(minutes=5)
                if is_cdc_schema and not cdc_not_set_up and new_source_model.supports_scheduled_sync
                else timedelta(hours=6)
            )
            schema_model = ExternalDataSchema.objects.create(
                name=schema_name,
                team=self.team,
                source=new_source_model,
                should_sync=should_sync,
                sync_type=(None if cdc_not_set_up else sync_type) if new_source_model.supports_scheduled_sync else None,
                sync_time_of_day=sync_time_of_day if new_source_model.supports_scheduled_sync else None,
                sync_type_config=sync_type_config,
                description=source_schema.description if source_schema else None,
                label=schema_label_by_name.get(schema_name),
                sync_frequency_interval=schema_sync_frequency_interval,
                enabled_columns=enabled_columns,
                row_filters=row_filters,
            )

            # The CDC path is Postgres-only, and the engine adapter's `source_table_location`
            # guarantees non-None schema/table when it resolves above. `cast` narrows for mypy
            # without a runtime check. The adapter no-ops for self-managed / no-publication.
            if is_cdc_schema and should_sync and cdc_enabled and cdc_adapter is not None:
                cdc_adapter.add_table(
                    new_source_model,
                    cast(str, metadata_source_schema),
                    cast(str, metadata_source_table_name),
                )

            if direct_engine_adapter is not None and is_direct_query and should_sync:
                # Apply the picker's column subset on the very first DataWarehouseTable build,
                # not just on subsequent updates — otherwise users see all columns in HogQL until
                # they hit save again or a refresh runs. Columns are keyed by raw, case-sensitive
                # source names (`normalize=False`).
                schema_model.table = direct_engine_adapter.upsert_table(
                    None,
                    schema_name=schema_name,
                    source=new_source_model,
                    columns=filter_dwh_columns_by_enabled_columns(
                        direct_engine_adapter.columns_to_dwh_columns(source_schema.columns if source_schema else []),
                        enabled_columns,
                        source_schema.detected_primary_keys if source_schema else None,
                        incremental_field,
                        normalize=False,
                    ),
                    source_catalog=metadata_source_catalog,
                    source_schema=cast(str, metadata_source_schema),
                    source_table_name=cast(str, metadata_source_table_name),
                )
                schema_model.save(update_fields=["table"])

            if should_sync and new_source_model.supports_scheduled_sync:
                active_schemas.append(schema_model)

        # Attach destinations before any schedule starts. Extraction snapshots the set onto the
        # run, so a source whose destinations arrive after its first sync began writes that run
        # to the warehouse alone, and reaching the others costs a full resync.
        if destination_ids:
            try:
                set_source_destinations(
                    team_id=self.team_id,
                    source_id=new_source_model.pk,
                    destination_ids=destination_ids,
                )
            except Exception as e:
                # The source is already created and its tables are configured. Losing that over a
                # destination set the user can still fix on the Destinations tab is the worse trade.
                logger.exception(
                    "Could not attach destinations to a new source",
                    exc_info=e,
                    source_id=new_source_model.pk,
                )

        # Create all sync schedules over a single shared Temporal connection. Creating them
        # one call at a time reconnects to Temporal on every iteration, which does not scale
        # to sources with thousands of schemas (e.g. a Slack workspace with thousands of
        # channels).
        try:
            schedule_errors = bulk_create_external_data_job_schedules(
                [(active_schema, active_schema.should_sync) for active_schema in active_schemas]
            )
            for schema_id, schedule_error in schedule_errors:
                # The source model was already created, so a partial schedule failure
                # shouldn't fail the request — log each failure and carry on.
                logger.exception(
                    "Could not trigger external data job",
                    exc_info=schedule_error,
                    schema_id=schema_id,
                )
        except Exception as e:
            logger.exception("Could not trigger external data job", exc_info=e)

        # Per-source schema discovery schedule. Runs every 6h so newly added
        # upstream resources (Slack channels, Postgres tables, …) get picked up
        # without re-discovering on every per-schema sync tick. Direct-query
        # sources resolve schemas at query time, so they opt out of all
        # background sync — including this discovery cadence.
        if new_source_model.supports_scheduled_sync:
            try:
                sync_discover_schemas_schedule(new_source_model, create=True)
            except Exception as e:
                logger.exception("Could not create schema discovery schedule", exc_info=e)

        # Start CDC extraction schedule if any CDC schemas are active
        if cdc_enabled:
            try:
                sync_cdc_extraction_schedule(new_source_model, create=True)
                ensure_cdc_slot_cleanup_schedule()
            except Exception as e:
                logger.exception("Could not create CDC schedules", exc_info=e)

        if new_source_model.revenue_analytics_config_safe.enabled:
            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team,
                kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
            )
            managed_viewset.sync_views()
            ensure_person_join(self.team.pk, new_source_model.prefix)

        # `source` (web/api/mcp/wizard/posthog_code) is derived from the request by report_user_action;
        # `created_via` is the caller's explicit intent (with one exception: the machine-injected `mcp`
        # is upgraded above when the transport identifies the wizard or PostHog Desktop). They usually
        # agree but are kept separate so a transport change (e.g. a new wrapper UA) doesn't silently
        # rewrite historical attribution.
        report_user_action(
            cast(User, request.user),
            "data warehouse source created",
            {
                "source_type": source_type,
                "created_via": created_via,
                "source_access_method": access_method,
                "direct_query_enabled": direct_query_enabled,
                "schema_count": len(active_schemas),
                "source_id": str(new_source_model.pk),
            },
            team=self.team,
            request=request,
        )

        return Response(status=status.HTTP_201_CREATED, data={"id": new_source_model.pk})

    def _setup_cdc_resources(
        self, adapter: CDCSourceAdapter, source_model: ExternalDataSource, payload: dict
    ) -> str | None:
        """Provision CDC for an existing source by delegating to the engine adapter.

        Writes universal CDC fields (mode, lag thresholds, auto-drop policy) plus the
        adapter-supplied resource fields (slot/publication identifiers, consistent
        point, …) into ``source_model.job_inputs`` and saves. Returns an error string
        on failure, or None on success. Callers decide whether to delete the source
        on failure (create flow does; enable_cdc does not).
        """
        management_mode = payload.get("cdc_management_mode", "posthog")
        logger.info(
            "Setting up CDC resources for source",
            source_id=str(source_model.pk),
            source_type=source_model.source_type,
            management_mode=management_mode,
        )

        resource_fields, error = adapter.setup_resources(source_model, payload)
        if error is not None:
            logger.warning(
                "CDC resource setup failed",
                source_id=str(source_model.pk),
                source_type=source_model.source_type,
                management_mode=management_mode,
                error=error,
            )
            return error

        logger.info(
            "CDC resources provisioned",
            source_id=str(source_model.pk),
            management_mode=management_mode,
            slot_name=resource_fields.get("cdc_slot_name"),
            publication_name=resource_fields.get("cdc_publication_name"),
            resource_keys=sorted(resource_fields.keys()),
        )

        job_inputs = dict(source_model.job_inputs or {})
        job_inputs.update(
            {
                "cdc_enabled": True,
                "cdc_auto_drop_slot": payload.get("cdc_auto_drop_slot", True),
                "cdc_lag_warning_threshold_mb": payload.get(
                    "cdc_lag_warning_threshold_mb", DEFAULT_LAG_WARNING_THRESHOLD_MB
                ),
                "cdc_lag_critical_threshold_mb": payload.get(
                    "cdc_lag_critical_threshold_mb", DEFAULT_LAG_CRITICAL_THRESHOLD_MB
                ),
            }
        )
        job_inputs.update(resource_fields)
        source_model.job_inputs = job_inputs
        source_model.save(update_fields=["job_inputs", "updated_at"])
        return None

    def prefix_required(self, source_type: str) -> bool:
        # A prefix is only needed when a no-prefix source of the same type already
        # exists. Two no-prefix sources would write to the same table names; sources
        # with distinct prefixes (including one no-prefix + N prefixed) have separate
        # table namespaces and cannot collide.
        no_prefix_source_exists = (
            ExternalDataSource.objects.exclude(deleted=True)
            .filter(team_id=self.team.pk, source_type=source_type)
            .filter(Q(prefix__isnull=True) | Q(prefix=""))
            .exists()
        )
        return no_prefix_source_exists

    def prefix_exists(self, source_type: str, prefix: str) -> bool:
        prefix_exists = (
            ExternalDataSource.objects.exclude(deleted=True)
            .filter(team_id=self.team.pk, source_type=source_type, prefix=prefix)
            .exists()
        )
        return prefix_exists

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        schemas = list(
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(team_id=self.team_id, source_id=instance.id)
            .select_related("table")
            .all()
        )

        # Deleting the source deletes every table it synced, so it needs editor on each of them.
        self._assert_can_write_schemas(schemas)

        # Soft-delete source, schemas, tables, and companion _cdc tables atomically
        # first so DB state is consistent even if the external cleanup below fails
        with transaction.atomic():
            for schema in schemas:
                if schema.table:
                    schema.table.soft_delete()

            # Bulk soft-delete the schema rows in a single UPDATE. Per-row soft_delete()
            # runs a SELECT + UPDATE + activity-log write each, which does not scale to
            # sources with thousands of schemas (e.g. a Slack workspace with thousands of
            # channels).
            deleted_at = datetime.now(UTC)
            ExternalDataSchema.objects.filter(team_id=self.team_id, id__in=[schema.id for schema in schemas]).update(
                deleted=True, deleted_at=deleted_at
            )
            # Mirror the bulk update onto the in-memory objects so the post-atomic
            # `schema.delete_table()` save() below doesn't overwrite deleted=True with the
            # stale in-memory value.
            for schema in schemas:
                schema.deleted = True
                schema.deleted_at = deleted_at

            # Clean up CDC companion tables (e.g. {name}_cdc) — these are standalone
            # DataWarehouseTable records linked to the source but not to schema.table.
            DataWarehouseTable.objects.filter(
                external_data_source_id=instance.id,
                team_id=self.team_id,
                deleted=False,
            ).exclude(id__in=[s.table_id for s in schemas if s.table_id is not None]).update(deleted=True)

            instance.soft_delete()

        # Best-effort webhook cleanup — soft-deletes are already committed
        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)
        if isinstance(source, WebhookSource) and instance.job_inputs:
            try:
                config = source.parse_config(instance.job_inputs)
                delete_webhook_and_hog_function(
                    team=self.team,
                    source=source,
                    config=config,
                    source_id=str(instance.pk),
                    api_version=source.resolve_api_version(instance.api_version),
                )
            except Exception as e:
                capture_exception(e)

        # Best-effort external cleanup — soft-deletes are already committed
        latest_running_job = (
            ExternalDataJob.objects.filter(pipeline_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )
        if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
            cancel_external_data_workflow(latest_running_job.workflow_id)

        # Delete all schema sync schedules over a single shared Temporal connection — see
        # the matching comment in `create`. Guarded so a Temporal-connect failure here
        # doesn't skip the source/discovery schedule and S3 cleanup below.
        try:
            schedule_delete_errors = bulk_delete_external_data_schedules([str(schema.id) for schema in schemas])
            for schema_id, schedule_delete_error in schedule_delete_errors:
                capture_exception(schedule_delete_error, {"schema_id": schema_id})
        except Exception as e:
            capture_exception(e)

        for schema in schemas:
            try:
                schema.delete_table()
            except Exception as e:
                capture_exception(e)

        try:
            delete_external_data_schedule(str(instance.id))
        except Exception as e:
            capture_exception(e)

        try:
            delete_discover_schemas_schedule(str(instance.id))
        except Exception as e:
            capture_exception(e)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=True)
    def reload(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSource = self.get_object()

        if instance.is_direct_query:
            return self.refresh_schemas(request, *args, **kwargs)

        # Syncs every enabled schema, so it needs editor on each - a table locked below the source
        # would otherwise be refreshed here, and for a full refresh that drops and reloads it.
        self._assert_can_write_schemas(
            ExternalDataSchema.objects.filter(team_id=self.team_id, source_id=instance.id, should_sync=True)
            .exclude(deleted=True)
            .select_related("source", "table")
        )

        if is_any_external_data_schema_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        try:
            trigger_external_data_source_workflow(instance)

        except temporalio.service.RPCError:
            # if the source schedule has been removed - trigger the schema schedules
            instance.reload_schemas()

        except Exception as e:
            logger.exception("Could not trigger external data job", exc_info=e)
            raise

        instance.status = "Running"
        instance.save()
        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "added": {"type": "integer"},
                    "deleted": {"type": "integer"},
                    "auto_enabled": {"type": "integer"},
                    "total_tables_seen": {"type": "integer"},
                },
            }
        }
    )
    def refresh_schemas(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync)."""
        instance: ExternalDataSource = self.get_object()
        logger.debug(
            "refresh_schemas called",
            source_id=str(instance.id),
            team_id=self.team_id,
            source_type=instance.source_type,
        )
        if not instance.job_inputs:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Source has no configuration."},
            )
        source: AnySource | None = None
        try:
            source_type = ExternalDataSourceType(instance.source_type)
            source = SourceRegistry.get_source(source_type)
            config = source.parse_config(instance.job_inputs)
            # Explicit user action — bypass any cached schema discovery so newly added
            # upstream resources (e.g. Slack channels) appear immediately.
            schemas = source.get_schemas(
                config, self.team_id, force_refresh=True, api_version=source.resolve_api_version(instance.api_version)
            )
            connection_metadata = (
                helpers.get_direct_connection_metadata(
                    source_impl=source,
                    source_config=config,
                    team_id=self.team_id,
                    source_model=instance,
                    fallback=instance.connection_metadata,
                )
                if instance.is_direct_query
                else instance.connection_metadata
            )
            schema_names = {s.name: s.label for s in schemas}
            logger.info(
                "refresh_schemas fetched from source",
                source_id=str(instance.id),
                schema_count=len(schema_names),
                schema_names=schema_names,
            )
        except Exception as e:
            error_message, is_expected_source_error = helpers._classify_refresh_schemas_error(source, e)
            logger.exception(
                "Could not fetch schemas from source",
                exc_info=e,
                source_id=str(instance.id),
                team_id=self.team_id,
                source_type=instance.source_type,
                error_type=type(e).__name__,
                is_expected_source_error=is_expected_source_error,
            )
            if not is_expected_source_error:
                capture_exception(
                    e,
                    {
                        "source_id": str(instance.id),
                        "source_type": instance.source_type,
                        "team_id": self.team_id,
                        "refresh_schemas": True,
                    },
                )
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": error_message},
            )

        descriptions = {s.name: s.description for s in schemas}
        with transaction.atomic():
            ExternalDataSource._base_manager.filter(pk=instance.pk).select_for_update().get()
            if instance.is_direct_query and connection_metadata != instance.connection_metadata:
                instance.connection_metadata = connection_metadata
                instance.save(update_fields=["connection_metadata", "updated_at"])
            # Migrate/dedupe legacy rows before sync_old_schemas; non-Postgres only once namespace cleared.
            engine = get_direct_query_engine(instance.direct_engine)
            name_substitutions = helpers._refresh_name_substitutions(
                engine, source=instance, source_schemas=schemas, team_id=self.team_id
            )

            if name_substitutions:
                schema_names = {name_substitutions.get(name, name): label for name, label in schema_names.items()}
                descriptions = {
                    name_substitutions.get(name, name): description for name, description in descriptions.items()
                }
            # Namespaced-resource sources (GitHub) keep the legacy resource's rows bare alongside
            # qualified rows for the others, so bare↔qualified tail matching would wrongly collapse
            # them; match names exactly and seed per-resource location metadata on new rows.
            namespaced_adapter = get_namespaced_resource_adapter(instance.source_type)
            sync_result = sync_old_schemas_with_new_schemas(
                schema_names,
                source_id=str(instance.id),
                team_id=self.team_id,
                descriptions=descriptions,
                strict_name_match=namespaced_adapter is not None and namespaced_adapter.uses_strict_schema_name_match,
                schema_metadata_by_name=namespaced_adapter.schema_metadata_by_name(schemas)
                if namespaced_adapter is not None
                else None,
            )
            # Mutable local: engine reconciliation below may extend the deleted set.
            schemas_deleted = sync_result.deleted

            if engine is not None:
                reconciled_deleted_schemas = engine.reconcile_schemas(
                    source=instance, source_schemas=schemas, team_id=self.team_id
                )
                if reconciled_deleted_schemas:
                    schemas_deleted = list({*schemas_deleted, *reconciled_deleted_schemas})
            elif isinstance(source, (SQLSource, ClickHouseSource)) and source.supports_column_selection:
                # ClickHouse isn't a SQLSource but exposes the same column-selection
                # capability and reconcile hook, so it reuses this path.
                source.reconcile_schema_metadata(source=instance, source_schemas=schemas, team_id=self.team_id)

        # Outside the atomic block: schedule creation talks to Temporal, which must not run under
        # the source row lock or against rows that could still roll back. `sync_result.created` holds
        # post-substitution stored names, so remap the discovered names to match.
        auto_enabled_names: list[str] = []
        if sync_result.created:
            source_schemas_by_name = {name_substitutions.get(s.name, s.name): s for s in schemas}
            auto_enabled_names = auto_enable_new_schemas(instance, sync_result.created, source_schemas_by_name)

        logger.debug(
            "refresh_schemas completed",
            source_id=str(instance.id),
            team_id=self.team_id,
            added=len(sync_result.created),
            deleted=len(schemas_deleted),
            auto_enabled=len(auto_enabled_names),
            total_tables_seen=len(schemas),
        )
        return Response(
            status=status.HTTP_200_OK,
            data={
                "added": len(sync_result.created),
                "deleted": len(schemas_deleted),
                "auto_enabled": len(auto_enabled_names),
                "total_tables_seen": len(schemas),
            },
        )

    @extend_schema(request=source_serializers.DatabaseSchemaRequestSerializer)
    @action(methods=["POST"], detail=False)
    def database_schema(self, request: Request, *arg: Any, **kwargs: Any):
        source_type = request.data.get("source_type", None)

        if source_type is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Missing required parameter: source_type"},
            )

        secret_ref_response = source_serializers._unresolved_secret_ref_response(request.data)
        if secret_ref_response is not None:
            return secret_ref_response

        try:
            source_type_model = ExternalDataSourceType(source_type)
        except ValueError:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Unknown source_type '{source_type}'"},
            )
        source = SourceRegistry.get_source(source_type_model)
        is_valid, errors = source.validate_config(request.data)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        source_config: Config = source.parse_config(request.data)

        access_method = request.data.get("access_method", ExternalDataSource.AccessMethod.WAREHOUSE)
        try:
            if isinstance(source, (PostgresSource, MySQLSource)):
                credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                    cast(Any, source_config),
                    self.team_id,
                    access_method,
                    require_ssl=new_source_requires_ssl(source_config),
                )
            elif isinstance(source, CustomSource):
                # Schema discovery for an as-yet-uncreated source: an integration-backed manifest may only use
                # an unbound integration owned by the requester, or the probe could send another source's token
                # to the submitted host.
                credentials_valid, credentials_error = source.validate_credentials(
                    source_config, self.team_id, owner_user_id=self.request.user.id
                )
            else:
                credentials_valid, credentials_error = source.validate_credentials(source_config, self.team_id)
        except Exception as e:
            credentials_valid, credentials_error = helpers._credentials_validation_failed(source, self.team_id, e)
        if not credentials_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": credentials_error or helpers.INVALID_CREDENTIALS_FALLBACK_MESSAGE},
            )

        try:
            schemas = source.get_schemas(source_config, self.team_id)
        except NotImplementedError:
            # Source doesn't implement schema discovery (e.g. an unreleased source), so there are
            # no tables to list — a caller mistake, not a server error worth capturing. Mirrors `setup`.
            # nosemgrep: api-response-must-match-schema -- conventional error message, not a schema-bound payload
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": helpers._source_unavailable_message(source_type)},
            )
        except Exception as e:
            error_message, is_expected_source_error = helpers._classify_refresh_schemas_error(source, e)
            if not is_expected_source_error:
                capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": error_message},
            )

        # Best-effort per-endpoint scope probe — transient failure falls back to "available".
        try:
            endpoint_permissions = source.get_endpoint_permissions(
                source_config, self.team_id, [schema.name for schema in schemas]
            )
        except Exception as e:
            capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            endpoint_permissions = {schema.name: None for schema in schemas}

        # Cache the CDC flag once: in non-DEBUG environments this calls posthoganalytics.feature_enabled,
        # which makes a network round-trip per call. With large schema lists (e.g. Slack workspaces with
        # thousands of channels) the per-iteration call inflated the response loop past the 120s gateway.
        cdc_enabled = is_cdc_enabled_for_team(self.team)
        # xmin is gated at the source-type level by the source's capability flag so it never
        # leaks to another SQL source.
        xmin_capable = source.supports_xmin
        data = [
            {
                "table": schema.name,
                "label": schema.label,
                "should_sync": False,
                "incremental_fields": schema.incremental_fields,
                "incremental_available": schema.supports_incremental,
                "append_available": schema.supports_append,
                "cdc_available": schema.supports_cdc if cdc_enabled else None,
                "xmin_available": schema.supports_xmin if xmin_capable else None,
                "incremental_field": schema.incremental_fields[0]["field"]
                if len(schema.incremental_fields) > 0 and len(schema.incremental_fields[0]["field"]) > 0
                else None,
                "sync_type": None,
                "rows": schema.row_count,
                "supports_webhooks": schema.supports_webhooks,
                "webhook_only": schema.webhook_only,
                "description": schema.description,
                "should_sync_default": schema.should_sync_default,
                "available_columns": [
                    {"field": col_name, "label": col_name, "type": col_type, "nullable": nullable}
                    for col_name, col_type, nullable in schema.columns
                ],
                "detected_primary_keys": schema.detected_primary_keys,
                "permission_error": endpoint_permissions.get(schema.name),
                "rls_warning": schema.rls_warning,
            }
            for schema in schemas
        ]
        return Response(status=status.HTTP_200_OK, data=data)

    @extend_schema(
        request=source_serializers.SourceSetupSerializer,
        responses={201: source_serializers.SourceSetupResponseSerializer},
    )
    @action(methods=["POST"], detail=False)
    def setup(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """One-shot data warehouse source setup.

        Validate credentials, discover available tables, enable them all with sensible sync defaults
        (incremental where supported, else append, else full refresh), and create the source in a single
        call — the caller never has to assemble a `schemas` array. For sources that support webhooks
        (e.g. Stripe), a webhook is auto-registered after creation: on success webhook-capable tables
        switch to real-time webhook sync (unlocking webhook-only tables); on failure the polling
        defaults stay in place. For fine-grained table/sync control, use the lower-level
        `database_schema` + `create` flow instead.
        """
        # No database context needed here (unlike the read serializer), and skipping it avoids building
        # the HogQL Database on this hot path.
        serializer = source_serializers.SourceSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        payload = dict(serializer.validated_data.get("payload") or {})

        secret_ref_response = source_serializers._unresolved_secret_ref_response(payload)
        if secret_ref_response is not None:
            return secret_ref_response

        resolved = self._resolve_stored_credential(source_type, payload)
        if resolved.error_response is not None:
            return resolved.error_response
        # Mutable local: the CustomSource branch below rewrites payload keys before source creation.
        payload = resolved.payload

        source_type_model = ExternalDataSourceType(source_type)
        source = SourceRegistry.get_source(source_type_model)

        error_response, source_config = self._validate_source_config_and_credentials(source, source_type_model, payload)
        if error_response is not None or source_config is None:
            return error_response or Response(status=status.HTTP_400_BAD_REQUEST)

        if isinstance(source, CustomSource):
            # Validation may have adopted static OAuth2 secrets into an integration row and rewritten
            # the config to point at it. `_create_external_data_source` below re-parses the raw payload
            # (it skips the credential gate), so propagate the rewrite onto the payload — the created
            # source must store the row pointer, never the raw secrets.
            validated_payload = source_config.to_dict()
            for key in ("auth_oauth2_integration_id", "auth_oauth2_client_secret", "auth_oauth2_refresh_token"):
                if validated_payload.get(key):
                    payload[key] = validated_payload[key]
                else:
                    payload.pop(key, None)

        try:
            source_schemas = source.get_schemas(source_config, self.team_id)
        except NotImplementedError:
            # Source doesn't implement schema discovery (e.g. an unreleased source) so it can't be
            # set up via this one-shot flow — a caller mistake, not a server error worth capturing.
            # nosemgrep: api-response-must-match-schema -- conventional error message, not a schema-bound payload
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": helpers._source_unavailable_message(source_type)},
            )
        except Exception as e:
            # Credentials validated above can still fail here — `get_schemas` opens its own
            # connection — so classify via the source's non-retryable-error map, same as `create`,
            # `database_schema`, and `refresh_schemas`, instead of surfacing the raw driver error.
            error_message, is_expected_source_error = helpers._classify_refresh_schemas_error(source, e)
            if not is_expected_source_error:
                capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": error_message})

        if not source_schemas:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No tables found for this source. Check the credentials and permissions."},
            )

        # Same best-effort per-table scope probe the schema picker runs, so one-shot setup doesn't
        # enable tables the credentials can only ever 403 on. Transient failure falls back to
        # "available", which is the pre-probe behavior.
        try:
            setup_permissions = source.get_endpoint_permissions(
                source_config, self.team_id, [schema.name for schema in source_schemas]
            )
        except Exception as e:
            capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            setup_permissions = {}

        # Some sources report a probe that couldn't run as a per-table reason rather than raising
        # (Stripe does this so the picker can render one row per failure). Setup has no such UI: a
        # blanket denial would silently create a source with every table off. Credentials that
        # genuinely read nothing are already rejected by validate_credentials above, so read
        # "everything denied" as an unreliable probe and keep the polling defaults.
        if setup_permissions and all(setup_permissions.get(schema.name) for schema in source_schemas):
            setup_permissions = {}

        # Build the schemas array server-side so the caller never has to. We've already validated
        # config + credentials above, so `_create_external_data_source` skips that second gate
        # (`skip_credential_validation`) to avoid a duplicate live credential round-trip.
        payload["schemas"] = build_default_schemas(source_schemas, permission_errors=setup_permissions)

        response = self._create_external_data_source(
            request,
            source_type=source_type,
            payload=payload,
            prefix=serializer.validated_data.get("prefix"),
            description=serializer.validated_data.get("description"),
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            created_via=ExternalDataSource.CreatedVia.MCP,
            direct_query_enabled=serializer.validated_data.get("direct_query_enabled", False),
            skip_credential_validation=True,
        )
        # Stored credentials are single-use: once the source owns them (in job_inputs), drop the stash.
        if resolved.credential is not None and response.status_code == status.HTTP_201_CREATED:
            resolved.credential.delete()

        if response.status_code == status.HTTP_201_CREATED and isinstance(source, WebhookSource):
            webhook_result = self._auto_register_webhook(
                source, source_config, str(response.data["id"]), source_schemas, permission_errors=setup_permissions
            )
            if webhook_result is not None:
                response.data["webhook"] = webhook_result
        return response

    @extend_schema(
        request=source_serializers.SourcePreviewRequestSerializer,
        responses={200: source_serializers.SourcePreviewResponseSerializer},
    )
    @action(methods=["POST"], detail=False)
    def preview_resource(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read a bounded sample of rows for one resource of a Custom REST source.

        Lets a manifest author verify `data_selector`, `primary_key`, and the incremental
        `cursor_path` against live data before creating the source. Only `source_type: "Custom"`
        is supported — other source types return 400. The read is bounded (single page per
        resource, capped row count, short timeouts, no redirects). Manifest, validation, and SSRF
        problems return 400; a live fetch failure returns 200 with `error` set and empty `rows`.
        """
        serializer = source_serializers.SourcePreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
        if not isinstance(source, CustomSource):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Preview is not supported for source type '{source_type}'."},
            )

        payload = dict(serializer.validated_data.get("payload") or {})
        is_valid, errors = source.validate_config(payload)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        source_config = source.parse_config(payload)

        try:
            # preview_resource runs its own SSRF host check and bounded live read, so no
            # separate validate_credentials probe — the read is the credential check.
            result = source.preview_resource(
                cast(CustomSourceConfig, source_config),
                self.team_id,
                serializer.validated_data["resource_name"],
                serializer.validated_data["limit"],
                owner_user_id=self.request.user.id,
            )
        except ValueError as e:
            # ManifestValidationError (a ValueError) for manifest/graph/URL issues, or a plain
            # ValueError for an unknown resource_name / dependency cycle — all caller mistakes.
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": str(e)})

        return Response(
            status=status.HTTP_200_OK,
            data={
                "rows": result.rows,
                "row_count": result.row_count,
                "columns": result.columns,
                "error": result.error,
            },
        )

    @extend_schema(
        request=source_serializers.DraftCustomManifestRequestSerializer,
        responses={200: source_serializers.DraftCustomManifestResponseSerializer},
    )
    @action(methods=["POST"], detail=False)
    def draft_custom_manifest(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Draft a Custom REST source manifest from API documentation using an LLM.

        Reads the docs (a URL fetched server-side, or pasted text / OpenAPI spec), asks the model to
        author a RESTAPIConfig manifest, and validates it against the create-path checks — repairing
        against validation errors up to a small budget. Returns the manifest for the user to review
        and tweak in the builder before creating the source; it does NOT create anything. Gated by the
        `dwh-custom-source-ai-builder` flag, and requires the org to have approved AI data processing,
        since the docs are sent to the LLM gateway.
        """
        # Gate on access (flag) then consent before validating input shape, so a caller without the
        # rollout or AI-data-processing opt-in is turned away before learning the request schema.
        if not is_custom_source_ai_builder_enabled_for_team(self.team):
            return Response(
                status=status.HTTP_404_NOT_FOUND,
                data={"message": "AI manifest drafting is not enabled for this organization."},
            )

        if self.team.organization.is_ai_data_processing_approved is not True:
            return Response(
                status=status.HTTP_403_FORBIDDEN,
                data={"message": "Enable AI data processing for this organization to use AI manifest drafting."},
            )

        serializer = source_serializers.DraftCustomManifestRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        docs_text = (data.get("docs_text") or "").strip()
        docs_source = "pasted_text" if docs_text else "fetched_url"
        if not docs_text:
            try:
                docs_text = fetch_docs_text(data["docs_url"])
            except DocsFetchError as e:
                return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": str(e)})

        try:
            result = draft_manifest_sync(
                team_id=self.team_id,
                source_name=data.get("source_name") or "",
                docs_text=docs_text,
            )
        except APIConnectionError as e:
            capture_exception(e, {"team_id": self.team_id})
            return Response(
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                data={
                    "message": "Couldn't reach the AI service. If you're running locally, the LLM gateway isn't running — author the manifest manually instead."
                },
            )
        except Exception as e:
            capture_exception(e, {"team_id": self.team_id})
            return Response(
                status=status.HTTP_502_BAD_GATEWAY,
                data={"message": "The manifest drafting service failed. Try again, or author the manifest manually."},
            )

        # Success-path telemetry: this is a paid, unbilled-to-customer Opus path, so capture how it
        # performed (status, repair rounds, tables, where the docs came from) to drive a funnel from
        # draft → source created. No docs content or credentials — none are accepted here anymore.
        report_user_action(
            cast(User, request.user),
            "data warehouse custom source manifest drafted",
            {
                "draft_status": result.status,
                "attempts": result.attempts,
                "table_count": len(result.resource_names),
                "docs_source": docs_source,
            },
            team=self.team,
            request=request,
        )

        return Response(
            status=status.HTTP_200_OK,
            data={
                "draft_status": result.status,
                "manifest_json": result.manifest_json,
                "resource_names": result.resource_names,
                "attempts": result.attempts,
                "error": result.error,
            },
        )

    def _auto_register_webhook(
        self,
        source: WebhookSource,
        source_config: Config,
        source_id: str,
        source_schemas: list[SourceSchema],
        permission_errors: Mapping[str, str | None] | None = None,
    ) -> dict | None:
        """Best-effort webhook auto-registration for one-shot setup.

        The source was just created with polling sync defaults (webhook-only tables disabled). If the
        source supports webhook auto-creation and the credentials allow it, register the webhook and
        switch every webhook-capable table to the webhook sync method — unlocking webhook-only tables.
        Failure never breaks setup: the polling defaults stay in place and webhook-only tables remain
        disabled, exactly as if the source didn't support webhooks.
        """
        # Tables marked `should_sync_default=False` need explicit opt-in even when webhook-capable —
        # one-shot setup must not force-enable what the schema picker would leave off (the same
        # contract `build_default_schemas` honors). A table the credentials can't read is excluded
        # for the same reason: a webhook can't deliver rows the connection was denied.
        denied = {name for name, reason in (permission_errors or {}).items() if reason}
        webhook_capable = {
            s.name for s in source_schemas if s.supports_webhooks and s.should_sync_default and s.name not in denied
        }
        if not webhook_capable or source.webhook_template is None:
            return None

        instance = ExternalDataSource.objects.get(pk=source_id, team_id=self.team_id)
        # Registration can't succeed on a connection whose grants exclude webhook management, and
        # one-shot setup has no manual-fallback UI to fall back into: leave the polling defaults.
        blocked_reason = self._webhook_creation_blocked_reason(source, instance)
        if blocked_reason is not None:
            return {"success": False, "webhook_url": None, "error": blocked_reason, "pending_inputs": []}

        eligible_schemas = list(
            ExternalDataSchema.objects.filter(source=instance, team_id=self.team_id, name__in=webhook_capable).exclude(
                deleted=True
            )
        )
        if not eligible_schemas:
            return None

        def failure(error: str | None) -> dict:
            return {"success": False, "webhook_url": None, "error": error, "pending_inputs": []}

        try:
            hog_fn_result = get_or_create_webhook_hog_function(
                team=self.team,
                source=source,
                source_id=str(instance.pk),
                eligible_schemas=eligible_schemas,
                config=source_config,
            )
            if hog_fn_result.error or hog_fn_result.hog_function_id is None:
                return failure(hog_fn_result.error)

            registration = create_and_register_webhook(
                source,
                source_config,
                hog_fn_result,
                self.team_id,
                api_version=source.resolve_api_version(instance.api_version),
            )
        except Exception as e:
            capture_exception(e, {"source_id": source_id, "team_id": self.team_id})
            return failure(str(e))

        if not registration.success:
            # The external registration failed (e.g. credentials can't create webhooks), so the
            # handler would never receive events — remove it and keep the polling defaults.
            hog_function = HogFunction.objects.get(id=hog_fn_result.hog_function_id, team_id=self.team_id)
            hog_function.deleted = True
            hog_function.enabled = False
            hog_function.save(update_fields=["deleted", "enabled"])
            return failure(registration.error)

        for schema in eligible_schemas:
            newly_enabled = not schema.should_sync
            schema.sync_type = ExternalDataSchema.SyncType.WEBHOOK
            schema.should_sync = True
            schema.save(update_fields=["sync_type", "should_sync"])
            if newly_enabled:
                # Webhook-only tables were created disabled, so no sync schedule exists yet. The
                # schedule still matters for webhook schemas: it ingests the buffered webhook events.
                try:
                    sync_external_data_job_workflow(schema, create=True)
                except Exception as e:
                    logger.exception(
                        "Could not create sync schedule for webhook schema", exc_info=e, schema_id=str(schema.id)
                    )

        return {
            "success": True,
            "webhook_url": registration.webhook_url,
            "error": None,
            "pending_inputs": list(registration.pending_inputs),
        }

    def _validate_source_config_and_credentials(
        self,
        source: AnySource,
        source_type_model: ExternalDataSourceType,
        payload: dict,
        access_method: str = ExternalDataSource.AccessMethod.WAREHOUSE,
    ) -> tuple[Response | None, Config | None]:
        """Run the config + live credential gate (including the SSRF host check) for a source payload."""
        if isinstance(source, CustomSource):
            # The OAuth2 integration row pointer is server-managed: validation derives it by adopting
            # the submitted auth_oauth2_* secrets into a row. Never trust a client-supplied pointer on
            # a pre-create seam — it could reference a row the caller shouldn't consume.
            payload.pop("auth_oauth2_integration_id", None)
        is_valid, errors = source.validate_config(payload)
        if not is_valid:
            return (
                Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"Invalid source config: {', '.join(errors)}"},
                ),
                None,
            )
        source_config: Config = source.parse_config(payload)

        try:
            if isinstance(source, (PostgresSource, MySQLSource)):
                credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                    cast(Any, source_config),
                    self.team_id,
                    access_method,
                    require_ssl=new_source_requires_ssl(source_config),
                )
            elif isinstance(source, CustomSource):
                # Create-time validation for an integration-backed manifest may only use an unbound integration
                # owned by the requester, so the probe can't send another source's token to the submitted host.
                credentials_valid, credentials_error = source.validate_credentials(
                    source_config, self.team_id, owner_user_id=self.request.user.id
                )
            else:
                credentials_valid, credentials_error = source.validate_credentials(source_config, self.team_id)
        except Exception as e:
            credentials_valid, credentials_error = helpers._credentials_validation_failed(source, self.team_id, e)
        if not credentials_valid:
            return (
                Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": credentials_error or helpers.INVALID_CREDENTIALS_FALLBACK_MESSAGE},
                ),
                None,
            )
        return None, source_config

    @extend_schema(
        request=source_serializers.SourceCredentialCreateSerializer,
        responses={201: source_serializers.SourceCredentialSerializer},
    )
    @action(methods=["POST"], detail=False)
    def store_credentials(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Validate and store credentials for a data warehouse source without creating the source.

        Backs the source connect page: the user enters credentials directly in PostHog, they are
        checked against a live connection, then stashed encrypted in a temporary store. The returned
        credential id can be passed to `setup` as {'credential_id': <id>} to create the source — so
        secrets never travel through an agent conversation. The stash is single-use: it is deleted
        as soon as `setup` consumes it, and expires after 24 hours if never consumed.
        """
        serializer = source_serializers.SourceCredentialCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        payload = dict(serializer.validated_data["payload"])

        for key, value in payload.items():
            if isinstance(value, str):
                payload[key] = value.strip()

        source_type_model = ExternalDataSourceType(source_type)
        source = SourceRegistry.get_source(source_type_model)

        error_response, _ = self._validate_source_config_and_credentials(source, source_type_model, payload)
        if error_response is not None:
            return error_response

        # Opportunistically purge expired stashes — there is no separate cleanup job.
        PendingSourceCredential.objects.for_team(self.team_id).filter(expires_at__lte=timezone.now()).delete()

        credential = PendingSourceCredential.objects.create(
            team_id=self.team_id,
            source_type=source_type,
            payload=payload,
            created_by=cast(User, request.user),
        )

        return Response(
            status=status.HTTP_201_CREATED,
            data=source_serializers.SourceCredentialSerializer(
                {
                    "credential_id": credential.id,
                    "source_type": source_type,
                    "created_at": credential.created_at,
                    "expires_at": credential.expires_at,
                }
            ).data,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return stored credentials for this source type (e.g. 'Stripe', 'Postgres').",
            )
        ],
        responses=source_serializers.SourceCredentialSerializer(many=True),
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def stored_credentials(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List credentials the requesting user stored via the source connect page that haven't been consumed yet.

        Returns metadata only (id, source type, timestamps) — never the secrets themselves. Stored
        credentials are scoped to their creator: only the user who filled the connect page can list
        or consume them. They are temporary too: they disappear once consumed by `setup` or when
        they expire. Newest first, so after a user confirms they've finished the connect page, the
        first entry for the source type is the one to pass to `setup`.
        """
        queryset = (
            PendingSourceCredential.objects.for_team(self.team_id)
            .filter(created_by=cast(User, request.user), expires_at__gt=timezone.now())
            .order_by("-created_at")
        )
        source_type = request.query_params.get("source_type")
        if source_type:
            queryset = queryset.filter(source_type=source_type)

        data = [
            {
                "credential_id": credential.id,
                "source_type": credential.source_type,
                "created_at": credential.created_at,
                "expires_at": credential.expires_at,
            }
            for credential in queryset
        ]
        return Response(
            status=status.HTTP_200_OK, data=source_serializers.SourceCredentialSerializer(data, many=True).data
        )

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {
                        "valid": {"type": "boolean"},
                        "errors": {"type": "array", "items": {"type": "string"}},
                    },
                },
                description="Whether the Postgres database satisfies CDC prerequisites.",
            ),
            400: OpenApiResponse(description="Invalid config, disallowed host, or connection failure."),
        },
    )
    @action(methods=["POST"], detail=False)
    def check_cdc_prerequisites(self, request: Request, *arg: Any, **kwargs: Any):
        """Validate CDC prerequisites against a live Postgres connection.

        Used by the source wizard to surface ✅/❌ checks before source creation,
        and by the self-managed setup popup to verify user-created publications.
        """
        source_type = request.data.get("source_type")
        if not isinstance(source_type, str) or not source_type_supports_cdc(source_type):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "CDC prerequisite checks are only supported for CDC enabled sources."},
            )

        # Dispatch to the actual source class so subclasses (Supabase, Neon) can run
        # their own pre-connection checks, e.g. rejecting pooled hosts for CDC.
        source_impl = SourceRegistry.get_source(ExternalDataSourceType(source_type))
        if not isinstance(source_impl, PostgresSource):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"CDC prerequisite checks are not supported for source type: {source_type}"},
            )
        is_valid, errors = source_impl.validate_config(request.data)
        if not is_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid source config: {', '.join(errors)}"},
            )
        config = source_impl.parse_config(request.data)

        # SSRF protection: reject internal/private hosts (same as validate_credentials).
        is_ssh_valid, ssh_errors = source_impl.ssh_tunnel_is_valid(config, self.team_id)
        if not is_ssh_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": ssh_errors or "SSH tunnel host not allowed"},
            )
        valid_host, host_errors = source_impl.is_database_host_valid(
            config.host,
            self.team_id,
            using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False,
        )
        if not valid_host:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": host_errors or "Host not allowed"},
            )

        management_mode = request.data.get("cdc_management_mode", "posthog")
        if management_mode not in ("posthog", "self_managed"):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "cdc_management_mode must be 'posthog' or 'self_managed'."},
            )

        tables = request.data.get("tables") or []
        slot_name = request.data.get("cdc_slot_name") or None
        publication_name = request.data.get("cdc_publication_name") or None

        try:
            prereq_errors = source_impl.check_cdc_prerequisites(
                config,
                management_mode=management_mode,
                tables=tables,
                slot_name=slot_name,
                publication_name=publication_name,
            )
        except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
            # Probing a user-supplied database to validate it is expected to fail when the host,
            # credentials, or SSH tunnel are wrong or the server drops the connection. Surface it
            # to the wizard as a 400, but don't capture it — these are user/upstream connection
            # problems, not bugs in our code, and capturing every one floods error tracking.
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to Postgres to check prerequisites: {e}"},
            )
        except Exception as e:
            capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to Postgres to check prerequisites: {e}"},
            )

        return Response(
            status=status.HTTP_200_OK,
            data={"valid": len(prereq_errors) == 0, "errors": prereq_errors},
        )

    def _get_cdc_adapter_or_400(self, instance: ExternalDataSource) -> tuple[CDCSourceAdapter | None, Response | None]:
        """Look up the engine adapter for an existing source. Returns 400 if the
        source's type doesn't support CDC."""
        try:
            return get_cdc_adapter(instance), None
        except ValueError:
            return None, Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"CDC is not supported for source type: {instance.source_type}"},
            )

    @action(methods=["POST"], detail=True)
    def check_cdc_prerequisites_for_source(self, request: Request, *arg: Any, **kwargs: Any):
        """Validate CDC prerequisites for an existing source using its stored credentials.

        The detail=False ``check_cdc_prerequisites`` action is for the creation wizard,
        where the client still holds the raw connection config (incl. password) in the
        form. On the Configuration page the source already exists and secret fields are
        stripped from API responses — so the client can't supply them. This reads the
        stored (encrypted) credentials from the DB via the adapter instead.

        Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
        ``cdc_slot_name`` (optional), ``cdc_publication_name`` (optional).
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None  # narrowed by _get_cdc_adapter_or_400

        management_mode = request.data.get("cdc_management_mode", "posthog")
        if management_mode not in ("posthog", "self_managed"):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "cdc_management_mode must be 'posthog' or 'self_managed'."},
            )

        schema_hint = (instance.job_inputs or {}).get("schema") or "public"
        try:
            prereq_errors = adapter.validate_prerequisites(
                instance,
                management_mode=management_mode,
                tables=[],
                schema=schema_hint,
                slot_name=request.data.get("cdc_slot_name") or None,
                publication_name=request.data.get("cdc_publication_name") or None,
            )
        except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
            # Probing the source's database to validate it is expected to fail when the host,
            # credentials, or SSH tunnel are wrong, the server requires/refuses SSL, or it drops the
            # connection. Surface it as a 400, but don't capture it — these are user/upstream
            # connection problems, not bugs in our code, and capturing every one floods error
            # tracking. Mirrors the detail=False check_cdc_prerequisites handler.
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to check prerequisites: {e}"},
            )
        except Exception as e:
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to check prerequisites: {e}"},
            )

        return Response(
            status=status.HTTP_200_OK,
            data={"valid": len(prereq_errors) == 0, "errors": prereq_errors},
        )

    @action(methods=["POST"], detail=True)
    def enable_cdc(self, request: Request, *arg: Any, **kwargs: Any):
        """Enable CDC on an existing source.

        Provisions engine-side CDC resources via the source's adapter, writes the CDC
        config into ``source.job_inputs``, and ensures the CDC extraction schedule
        exists. Re-runs prereq checks server-side so we never trust a stale
        client-side check.

        Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
        plus engine-specific identifier hints (e.g. ``cdc_slot_name``,
        ``cdc_publication_name`` for Postgres). Universal tuning fields:
        ``cdc_auto_drop_slot`` (optional bool), ``cdc_lag_warning_threshold_mb``
        (optional int), ``cdc_lag_critical_threshold_mb`` (optional int).
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None  # narrowed by _get_cdc_adapter_or_400

        if not is_cdc_enabled_for_team(self.team):
            return Response(
                status=status.HTTP_403_FORBIDDEN,
                data={"message": "CDC is not enabled for this team."},
            )

        existing = adapter.parse_cdc_config(instance)
        if existing.enabled:
            return Response(
                status=status.HTTP_409_CONFLICT,
                data={"message": "CDC is already enabled on this source."},
            )

        management_mode = request.data.get("cdc_management_mode", "posthog")
        if management_mode not in ("posthog", "self_managed"):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "cdc_management_mode must be 'posthog' or 'self_managed'."},
            )

        # Validate prerequisites server-side — never trust a client-only check.
        schema_hint = (instance.job_inputs or {}).get("schema") or "public"
        try:
            prereq_errors = adapter.validate_prerequisites(
                instance,
                management_mode=management_mode,
                tables=[],
                schema=schema_hint,
                slot_name=request.data.get("cdc_slot_name") or None,
                publication_name=request.data.get("cdc_publication_name") or None,
            )
        except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
            # Expected user/upstream connection failure (bad host/credentials/SSH tunnel, server
            # requires/refuses SSL, dropped connection). Surface as a 400 without capturing — see the
            # check_cdc_prerequisites_for_source handler above.
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to check prerequisites: {e}"},
            )
        except Exception as e:
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to check prerequisites: {e}"},
            )

        if prereq_errors:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "CDC prerequisites not met.", "errors": prereq_errors},
            )

        cdc_error = self._setup_cdc_resources(adapter, instance, request.data)
        if cdc_error is not None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": cdc_error},
            )

        # Ensure the global cleanup schedule exists. There are no CDC schemas yet (the user
        # picks sync_type=cdc per schema afterward), so `sync_cdc_extraction_schedule` is a
        # no-op here — the extraction schedule is authoritatively (re)created when a schema is
        # switched to CDC. A failure here therefore can't leave a "CDC on, never runs" state:
        # the slot + config are valid and the schedule self-heals on the first CDC schema
        # toggle. Surface failures (capture, not just log) and flag them in the response.
        schedules_ok = True
        try:
            sync_cdc_extraction_schedule(instance, create=True)
            ensure_cdc_slot_cleanup_schedule()
        except Exception as e:
            schedules_ok = False
            logger.exception("Could not create CDC schedules after enable_cdc", exc_info=e)
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})

        return Response(status=status.HTTP_200_OK, data={"success": True, "schedules_ready": schedules_ok})

    @action(methods=["POST"], detail=True)
    def disable_cdc(self, request: Request, *arg: Any, **kwargs: Any):
        """Disable CDC on an existing source.

        Cancels any running CDC extraction workflow, deletes the extraction schedule,
        delegates engine-side teardown to the source's adapter (drops slot/publication
        for Postgres; equivalent for other engines), clears ``cdc_*`` keys from
        ``job_inputs``, soft-deletes companion CDC tables, and sets all CDC schemas to
        ``sync_type=None``, ``should_sync=False`` so the user must pick a new sync
        strategy before they resume.
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None

        cdc_config = adapter.parse_cdc_config(instance)
        if not cdc_config.enabled:
            return Response(status=status.HTTP_200_OK, data={"success": True, "already_disabled": True})

        # Read the CDC schemas before the sync_type reset below, while they're still
        # marked CDC. Scoped so we don't touch unrelated incremental/full-refresh syncs.
        cdc_schemas = list(
            ExternalDataSchema.objects.filter(
                source=instance,
                sync_type=ExternalDataSchema.SyncType.CDC,
            )
            .exclude(deleted=True)
            .select_related("table")
        )
        # Disabling cancels jobs, drops the slot, purges buffered change data, and resets
        # every CDC schema — editor on the source isn't enough when a table is locked below it.
        self._assert_can_write_schemas(cdc_schemas)
        cdc_schema_ids = [schema.id for schema in cdc_schemas]
        running_jobs = ExternalDataJob.objects.filter(
            pipeline_id=instance.pk,
            team_id=instance.team_id,
            status="Running",
            schema_id__in=cdc_schema_ids,
        ).exclude(workflow_id__isnull=True)
        for running_job in running_jobs:
            if not running_job.workflow_id:
                continue
            try:
                cancel_external_data_workflow(running_job.workflow_id)
            except Exception as e:
                capture_exception(e, {"source_id": str(instance.id), "workflow_id": running_job.workflow_id})

        # Generic schedule teardown: schedule lives on our side, independent of engine.
        try:
            delete_cdc_extraction_schedule(str(instance.id))
        except Exception:
            logger.exception("Failed to delete CDC extraction schedule", extra={"source_id": str(instance.id)})

        # Engine-side teardown: best-effort, never blocks the disable.
        try:
            adapter.cleanup_resources(instance)
        except Exception as e:
            logger.exception("Failed engine-side CDC cleanup during disable_cdc", exc_info=e)
            capture_exception(e, {"source_id": str(instance.id)})

        # Drop each schema's S3 change buffer: the shadow lane's files are raw customer
        # change data with no consumer once CDC is off, and nothing else expires them.
        for schema_id in cdc_schema_ids:
            purge_buffer_prefix(instance.team_id, str(schema_id), logger)

        with transaction.atomic():
            # Clear any broken marker (recovery contract): leaving a stale cdc_broken in
            # sync_type_config would make CDC look broken the moment it's re-enabled.
            # Must be inside the atomic block so a failed schema-state reset rolls this back too.
            for schema_id in cdc_schema_ids:
                try:
                    update_sync_type_config_keys(
                        schema_id, instance.team_id, removes=["cdc_broken", "cdc_extraction_paused"]
                    )
                except ExternalDataSchema.DoesNotExist:
                    pass

            # Force CDC schemas to pick a new strategy by clearing sync_type and pausing.
            ExternalDataSchema.objects.filter(
                source=instance,
                sync_type=ExternalDataSchema.SyncType.CDC,
            ).exclude(deleted=True).update(sync_type=None, should_sync=False)

            # Soft-delete `_cdc` companion DataWarehouseTable rows so the next sync
            # rebuilds them once the user picks a new strategy.
            DataWarehouseTable.objects.filter(
                external_data_source_id=instance.id,
                team_id=self.team_id,
                deleted=False,
                name__endswith="_cdc",
            ).update(deleted=True)

            # Clear ALL cdc_* keys from job_inputs — leaving stale engine identifiers
            # behind (e.g. `cdc_consistent_point`) would corrupt resume tracking if
            # CDC is later re-enabled.
            job_inputs = dict(instance.job_inputs or {})
            for key in list(job_inputs.keys()):
                if key.startswith("cdc_"):
                    job_inputs.pop(key, None)
            instance.job_inputs = job_inputs
            instance.save(update_fields=["job_inputs", "updated_at"])

        return Response(status=status.HTTP_200_OK, data={"success": True})

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "schemas_reset": {"type": "integer"},
                    },
                },
                description="CDC repaired; schemas_reset CDC schemas will fully re-sync.",
            ),
            400: OpenApiResponse(
                description="CDC not enabled, no active CDC schemas, source looks healthy, or engine-side recreation failed."
            ),
            409: OpenApiResponse(description="A repair is already running for this source."),
        },
    )
    @action(methods=["POST"], detail=True)
    def repair_cdc(self, request: Request, *arg: Any, **kwargs: Any):
        """Repair CDC on a source whose replication resources were lost.

        Only proceeds on evidence of breakage (a persisted broken marker, or a live probe
        showing the slot/publication missing) — repairing a healthy source would drop its
        slot and force a full re-sync. Cancels running CDC jobs, recreates the engine-side
        slot/publication against the stored CDC config, resets every active CDC schema to
        snapshot mode for a full re-sync (changes since the old slot died are
        unrecoverable), clears the broken markers, and resumes the paused schedules.
        Idempotent: safe to retry after a partial failure. Concurrent repairs of the same
        source are rejected with a 409.
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None  # narrowed by _get_cdc_adapter_or_400

        cdc_config = adapter.parse_cdc_config(instance)
        if not cdc_config.enabled:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "CDC is not enabled on this source."},
            )

        try:
            schemas_reset = repair_cdc_source(instance)
        except CDCRepairInProgress as e:
            return Response(status=status.HTTP_409_CONFLICT, data={"message": str(e)})
        except CDCRepairError as e:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": str(e)})
        except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
            # Expected user/upstream connection failure — surface as a 400 without capturing,
            # mirroring the enable_cdc handler.
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to repair CDC: {e}"},
            )
        except Exception as e:
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not repair CDC: {e}"},
            )

        return Response(status=status.HTTP_200_OK, data={"success": True, "schemas_reset": schemas_reset})

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response={"type": "object", "properties": {"success": {"type": "boolean"}}},
                description="CDC resumed; the extraction schedule is unpaused.",
            ),
            400: OpenApiResponse(
                description="CDC not enabled, the slot/publication were lost (use Repair CDC), the source is still "
                "unreachable, or unpausing failed."
            ),
        },
    )
    @action(methods=["POST"], detail=True)
    def resume_cdc(self, request: Request, *arg: Any, **kwargs: Any):
        """Resume a CDC source whose extraction schedule was paused by a non-retryable
        failure that left the replication slot intact (bad credentials, SSL/host errors).

        Once the user has fixed the root cause, this re-probes the source DB — confirming
        the connection now succeeds and the slot/publication still exist — then unpauses the
        extraction schedule so streaming resumes from where it left off. No re-snapshot, so
        it's the cheap counterpart to Repair CDC. If the slot/publication are actually gone
        (``cdc_broken``, or a live probe showing them missing), resume is refused — only
        Repair CDC can recreate them, at the cost of a full re-sync.
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None  # narrowed by _get_cdc_adapter_or_400

        cdc_config = adapter.parse_cdc_config(instance)
        if not cdc_config.enabled:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "CDC is not enabled on this source."},
            )

        cdc_schemas = list(
            ExternalDataSchema.objects.filter(
                source=instance,
                sync_type=ExternalDataSchema.SyncType.CDC,
                should_sync=True,
            ).exclude(deleted=True)
        )
        if not cdc_schemas:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No schemas are syncing via change data capture, so there is nothing to resume."},
            )

        # A broken source has lost its slot/publication — resuming would just re-fail on the
        # next tick. Route the user to Repair CDC, which recreates them (and re-syncs).
        if any((schema.sync_type_config or {}).get("cdc_broken") for schema in cdc_schemas):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "The replication slot or publication was lost. Use Repair CDC to recreate it."},
            )

        # Re-probe the source: this both re-validates the connection (a still-wrong password
        # raises here) and confirms the slot/publication survive, so we never unpause straight
        # back into the same deterministic failure.
        try:
            live_status = adapter.get_status(instance)
        except (OperationalError, BaseSSHTunnelForwarderError, SSLRequiredError) as e:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "message": f"Could not connect to source to resume CDC — check the credentials and try again: {e}"
                },
            )
        except Exception as e:
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to resume CDC: {e}"},
            )

        if live_status.get("slot_exists") is False or live_status.get("publication_exists") is False:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "The replication slot or publication is missing. Use Repair CDC to recreate it."},
            )

        try:
            # Recreate the schedule if it was deleted out-of-band — unpausing a missing schedule is a
            # silent no-op that would report success while CDC never runs (same ordering as CDC repair's
            # _resume_schedules). sync builds an unpaused schedule; the explicit unpause covers the
            # already-existing-but-paused case.
            sync_cdc_extraction_schedule(instance)
            unpause_cdc_extraction_schedule(str(instance.id))
        except Exception as e:
            capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not resume CDC: {e}"},
            )

        # Extraction is running again: clear the paused marker so the schema stops reading as
        # halted (failure digest badge, loader status guard). Status stays FAILED until a run
        # actually succeeds. After the unpause, so a failure here leaves the marker for retry.
        for schema in cdc_schemas:
            try:
                update_sync_type_config_keys(schema.id, instance.team_id, removes=["cdc_extraction_paused"])
            except ExternalDataSchema.DoesNotExist:
                pass

        return Response(status=status.HTTP_200_OK, data={"success": True})

    @action(methods=["POST"], detail=True)
    def update_cdc_settings(self, request: Request, *arg: Any, **kwargs: Any):
        """Update CDC tuning fields without enabling/disabling.

        Lets users edit ``cdc_auto_drop_slot``, ``cdc_lag_warning_threshold_mb``, and
        ``cdc_lag_critical_threshold_mb`` independently. These fields are universal
        across engines. Engine-specific identifiers (slot name, management mode, …)
        are immutable post-enable — switching them requires disable + enable.
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None

        cdc_config = adapter.parse_cdc_config(instance)
        if not cdc_config.enabled:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "CDC is not enabled on this source."},
            )

        job_inputs = dict(instance.job_inputs or {})
        updates: dict[str, Any] = {}

        if "cdc_auto_drop_slot" in request.data:
            updates["cdc_auto_drop_slot"] = bool(request.data["cdc_auto_drop_slot"])

        for field in ("cdc_lag_warning_threshold_mb", "cdc_lag_critical_threshold_mb"):
            if field in request.data:
                try:
                    value = int(request.data[field])
                except (TypeError, ValueError):
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"{field} must be an integer."},
                    )
                if value < 1:
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"message": f"{field} must be >= 1."},
                    )
                updates[field] = value

        warn = updates.get("cdc_lag_warning_threshold_mb", job_inputs.get("cdc_lag_warning_threshold_mb"))
        crit = updates.get("cdc_lag_critical_threshold_mb", job_inputs.get("cdc_lag_critical_threshold_mb"))
        if warn is not None and crit is not None and int(warn) >= int(crit):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Warning threshold must be less than critical threshold."},
            )

        if not updates:
            return Response(status=status.HTTP_200_OK, data={"success": True, "unchanged": True})

        job_inputs.update(updates)
        instance.job_inputs = job_inputs
        instance.save(update_fields=["job_inputs", "updated_at"])

        return Response(status=status.HTTP_200_OK, data={"success": True})

    @action(methods=["GET"], detail=True)
    def cdc_status(self, request: Request, *arg: Any, **kwargs: Any):
        """Live CDC health for an existing source: slot/publication existence and WAL lag.

        Reads from the source DB via the engine adapter. Returns ``{"enabled": false}``
        when CDC is off, or the stored config plus live ``slot_exists`` /
        ``publication_exists`` / ``lag_bytes`` when on. 400s if the source DB is
        unreachable so the UI can show a degraded/unreachable state.
        """
        instance: ExternalDataSource = self.get_object()

        adapter, err = self._get_cdc_adapter_or_400(instance)
        if err is not None:
            return err
        assert adapter is not None

        cdc_config = adapter.parse_cdc_config(instance)
        if not cdc_config.enabled:
            return Response(status=status.HTTP_200_OK, data={"enabled": False})

        try:
            live_status = adapter.get_status(instance)
        except Exception as e:
            # An unreachable source DB is the degraded state this endpoint exists to report, so
            # don't capture expected connection failures as error-tracking noise. Capture only
            # unexpected errors, which point at a bug in our status read.
            if not adapter.is_connection_error(e):
                capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to read CDC status: {e}"},
            )

        # Paused-but-slot-intact means a non-retryable failure stopped the schedule; the UI offers
        # Resume (vs Repair) so the user can restart without a full re-sync. Best-effort: a Temporal
        # hiccup must not 500 this otherwise DB-only status read, so degrade to not-paused.
        try:
            schedule_paused = is_cdc_extraction_schedule_paused(str(instance.id))
        except Exception:
            logger.warning("cdc_status_schedule_paused_lookup_failed", source_id=str(instance.id), exc_info=True)
            schedule_paused = False

        return Response(
            status=status.HTTP_200_OK,
            data={
                "enabled": True,
                "management_mode": cdc_config.management_mode,
                "slot_name": cdc_config.slot_name,
                "publication_name": cdc_config.publication_name,
                "lag_warning_threshold_mb": cdc_config.lag_warning_threshold_mb,
                "lag_critical_threshold_mb": cdc_config.lag_critical_threshold_mb,
                "schedule_paused": schedule_paused,
                **live_status,
            },
        )

    @action(methods=["POST"], detail=False)
    def source_prefix(self, request: Request, *arg: Any, **kwargs: Any):
        prefix = request.data.get("prefix", None)
        source_type = request.data["source_type"]
        access_method = request.data.get("access_method", ExternalDataSource.AccessMethod.WAREHOUSE)

        if ExternalDataSource.is_system_managed_prefix(prefix):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": helpers.RESERVED_SOURCE_NAME_MESSAGE},
            )

        if access_method == ExternalDataSource.AccessMethod.DIRECT:
            if source_type not in direct_capable_source_types():
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": helpers.DIRECT_QUERY_UNSUPPORTED_SOURCE_MESSAGE},
                )

            normalized_prefix = prefix.strip() if isinstance(prefix, str) else ""
            if not normalized_prefix:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Name is required for direct query sources"},
                )

            return Response(status=status.HTTP_200_OK)

        if not prefix:
            if self.prefix_required(source_type):
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": "You already have a source of this type. Add a table prefix so this connection's tables don't clash with your existing source."
                    },
                )
        elif self.prefix_exists(source_type, prefix):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "message": f"Another source of this type already uses the prefix '{prefix}'. Choose a different prefix so this connection's tables don't clash."
                },
            )

        return Response(status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=True, pagination_class=None)
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="after",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ISO timestamp — only return jobs created after this date.",
            ),
            OpenApiParameter(
                name="before",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ISO timestamp — only return jobs created before this date.",
            ),
            OpenApiParameter(
                name="schemas",
                type={"type": "array", "items": {"type": "string"}},
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter jobs by table schema names.",
            ),
        ],
        responses=source_serializers.ExternalDataJobSerializers(many=True),
    )
    def jobs(self, request: Request, *arg: Any, **kwargs: Any):
        instance: ExternalDataSource = self.get_object()
        after = request.query_params.get("after", None)
        before = request.query_params.get("before", None)
        schemas = request.query_params.getlist("schemas")

        # select_related joins the full ExternalDataSchema row; defer its large JSON/text
        # columns so the serializer only pulls the fields SimpleExternalDataSchemaSerializer
        # actually reads (sync_type_config + latest_error can each be sizeable).
        # Non-billable jobs are included on purpose: the UI shows them tagged so a sync the
        # customer wasn't charged for is still visible in the history.
        jobs = (
            instance.jobs.select_related("schema")
            .defer("schema__sync_type_config", "schema__latest_error")
            .order_by("-created_at")
        )

        if schemas:
            jobs = jobs.filter(schema__name__in=schemas)
        if after:
            after_date = parser.parse(after)
            jobs = jobs.filter(created_at__gt=after_date)
        if before:
            before_date = parser.parse(before)
            jobs = jobs.filter(created_at__lt=before_date)

        jobs = jobs[:50]

        return Response(
            status=status.HTTP_200_OK,
            data=source_serializers.ExternalDataJobSerializers(
                jobs, many=True, read_only=True, context=self.get_serializer_context()
            ).data,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Comma-separated source type(s) to return config for, e.g. 'Postgres' or "
                    "'Postgres,Stripe'. Strongly recommended: the unfiltered response describes every "
                    "supported source and is very large. Omit only to enumerate the available types."
                ),
            )
        ],
    )
    @action(methods=["GET"], detail=False)
    def wizard(self, request: Request, *arg: Any, **kwargs: Any):
        # The documented-tables catalog is only consumed by the posthog.com docs build (via the
        # public endpoint) — skipping it here cuts ~40% off an already >1 MB response.
        configs = build_source_configs(include_tables=False)

        requested = request.query_params.get("source_type")
        if requested:
            requested_types = [t.strip() for t in requested.split(",") if t.strip()]
            unknown = [t for t in requested_types if t not in configs]
            if unknown:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": f"Unknown source_type(s): {', '.join(sorted(unknown))}. "
                        "Omit source_type to list every available type."
                    },
                )
            configs = {st: config for st, config in configs.items() if st in requested_types}

        response = Response(status=status.HTTP_200_OK, data=configs)
        # The catalog is deploy-static and identical for every user (no team/user input), so let the
        # browser reuse it across navigations instead of re-downloading and re-parsing several hundred
        # KB on each visit to the new-source page. `private` because the route is auth-gated; a new
        # source ships at most once per deploy, so a short freshness window is safe.
        patch_cache_control(response, private=True, max_age=600)
        return response

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="source_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="The source type to generate a connect link for (e.g. 'Stripe', 'Postgres', 'Hubspot').",
            )
        ],
        responses=source_serializers.SourceConnectLinkSerializer,
    )
    @action(methods=["GET"], detail=False)
    def connect_link(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return a secure browser link for connecting a data warehouse source.

        The link opens a minimal connect page rendering the source's full connection form — OAuth options
        included — with no table selection and no source creation. The user authenticates in their browser,
        secrets never pass through the agent, and the agent finishes setup afterwards by passing the stored
        credential id to data-warehouse-source-setup.
        """
        source_type = request.query_params.get("source_type")
        if not source_type:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Missing required parameter: source_type"},
            )
        try:
            source_type_model = ExternalDataSourceType(source_type)
        except ValueError:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Unknown source_type '{source_type}'"},
            )

        source = SourceRegistry.get_source(source_type_model)
        oauth_field = source_serializers._find_top_level_oauth_field(source.get_source_config.model_dump())
        action_phrase = (
            f"connect their {source_type} account" if oauth_field else f"enter their {source_type} connection details"
        )

        data = {
            "source_type": source_type,
            "auth_method": "oauth" if oauth_field else "credentials",
            "connect_url": (
                f"{settings.SITE_URL}/project/{self.team_id}/data-warehouse/connect?kind={quote(str(source_type))}"
            ),
            "instructions": (
                f"Share this link with the user. They {action_phrase} directly in PostHog — never ask them to "
                "paste credentials or tokens into the chat. The page only stores the connection details; it does "
                "not create the source. Once the user confirms they're done, find the stored credential id via "
                f"data-warehouse-stored-credentials-list (source_type='{source_type}', newest first) and call "
                'data-warehouse-source-setup with {"credential_id": <id>} in the payload. Stored credentials are '
                "single-use, expire after 24 hours, and are only visible to and consumable by the PostHog user "
                "who entered them — so the page must be filled by the same user this session authenticates as."
            ),
        }
        return Response(status=status.HTTP_200_OK, data=source_serializers.SourceConnectLinkSerializer(data).data)

    @extend_schema(responses=source_serializers.ExternalDataSourceConnectionOptionSerializer(many=True))
    @action(
        methods=["GET"],
        detail=False,
        pagination_class=None,
        filter_backends=[],
        required_scopes=["external_data_source:read"],
    )
    def connections(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        connection_sources = (
            ExternalDataSource._base_manager.filter(
                team_id=self.team_id,
                source_type__in=direct_capable_source_types(),
            )
            # Pure-direct sources are always live; synced sources only when the toggle is on.
            .filter(Q(access_method=ExternalDataSource.AccessMethod.DIRECT) | Q(direct_query_enabled=True))
            .exclude(deleted=True)
            .only(
                "id",
                "prefix",
                "description",
                "connection_metadata",
                "source_type",
                "access_method",
            )
            .order_by(self.ordering)
        )
        managed_candidates = connection_sources.filter(ExternalDataSource.ready_managed_warehouse_q()).only(
            "id",
            "team_id",
            "prefix",
            "description",
            "connection_metadata",
            "source_type",
            "access_method",
            "direct_query_enabled",
            "job_inputs",
        )
        managed_source = next(
            (source for source in managed_candidates if source.is_dynamic_managed_warehouse),
            None,
        ) or next((source for source in managed_candidates if source.is_managed_warehouse_ready), None)
        if managed_source is not None:
            external_sources = connection_sources.exclude(prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        else:
            canonical_source = helpers._canonical_legacy_managed_warehouse_source(connection_sources)
            external_sources = helpers._hide_noncanonical_managed_warehouse_sources(
                connection_sources, canonical_source
            )
        if is_service_auth(request):
            accessible_external_sources = external_sources
        else:
            accessible_external_sources = self.user_access_control.filter_queryset_by_access_level(external_sources)
            if not self.user_access_control.has_resource_access(
                "external_data_source"
            ) and not self.user_access_control.has_any_specific_access_for_resource(
                "external_data_source", required_level="viewer"
            ):
                accessible_external_sources = accessible_external_sources.filter(created_by=cast(User, request.user))
        accessible_sources = list(accessible_external_sources)
        options = ([managed_source] if managed_source is not None else []) + accessible_sources

        serializer = source_serializers.ExternalDataSourceConnectionOptionSerializer(
            options,
            many=True,
            context={"builtin_managed_warehouse_source_id": managed_source.pk if managed_source is not None else None},
        )
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    @extend_schema(responses=source_serializers.DirectConnectionSourceOptionSerializer(many=True))
    @action(methods=["GET"], detail=False, pagination_class=None, filter_backends=[])
    def direct_connection_options(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Source types the user can add as a direct connection, driven by the direct-SQL capability
        surface so the picker never drifts from the engines we actually support."""
        direct_types = direct_capable_source_types()
        options = [
            {
                "source_type": source_type,
                "label": config.get("label") or source_type,
                "icon_path": config.get("iconPath"),
            }
            for source_type, config in build_source_configs(include_tables=False).items()
            if source_type in direct_types
        ]
        options.sort(key=lambda option: str(option["label"]).lower())

        serializer = source_serializers.DirectConnectionSourceOptionSerializer(options, many=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    @extend_schema(
        request=DestinationLinkSerializer,
        responses={200: SourceDestinationsSerializer},
    )
    @action(methods=["GET", "PATCH"], detail=True)
    def destinations(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read or replace the destinations every table on this source syncs to.

        A table with its own override ignores this set until the override is cleared.
        """
        source = self.get_object()

        if request.method == "GET":
            attached = [
                str(link.destination_id)
                for link in ExternalDataSourceDestination.objects.for_team(self.team_id)
                .filter(source_id=source.id, enabled=True)
                .exclude(destination__deleted=True)
            ]
            # A source nobody configured has no links but is not syncing nowhere: it syncs to the
            # PostHog warehouse. Report where it actually goes, or the picker shows every
            # destination off and saving from that state silently drops the warehouse.
            # Looked up rather than resolved, because `resolve_destinations` creates the
            # warehouse row on demand and a GET must not write.
            if not attached:
                warehouse = (
                    ExternalDataDestination.objects.for_team(self.team_id)
                    .filter(type=ExternalDataDestination.Type.POSTHOG_WAREHOUSE, deleted=False)
                    .first()
                )
                attached = [str(warehouse.id)] if warehouse else []
            return Response(
                status=status.HTTP_200_OK, data=SourceDestinationsSerializer({"destination_ids": attached}).data
            )

        serializer = DestinationLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Editor on the source isn't enough on its own: this replaces the destination set every
        # table without its own override inherits, and (like `destroy`) never resolves a schema
        # through DRF's object permissions, so a table locked below the source would otherwise be
        # rerouted to a destination its editor never had access to.
        schemas = list(
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(team_id=self.team_id, source_id=source.id)
            .select_related("table")
        )
        self._assert_can_write_schemas(schemas)

        attached = set_source_destinations(
            team_id=self.team_id,
            source_id=source.id,
            destination_ids=serializer.validated_data["destination_ids"],
        )
        return Response(
            status=status.HTTP_200_OK, data=SourceDestinationsSerializer({"destination_ids": attached}).data
        )

    @action(methods=["PATCH"], detail=True)
    def revenue_analytics_config(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update the revenue analytics configuration and return the full external data source."""
        external_data_source = self.get_object()
        config = external_data_source.revenue_analytics_config_safe

        config_serializer = source_serializers.ExternalDataSourceRevenueAnalyticsConfigSerializer(
            config, data=request.data, partial=True
        )
        config_serializer.is_valid(raise_exception=True)
        config_serializer.save()

        table_prefix = external_data_source.prefix or ""

        if config.enabled:
            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team,
                kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
            )
            managed_viewset.sync_views()
            ensure_person_join(self.team.pk, table_prefix)
        else:
            try:
                managed_viewset = DataWarehouseManagedViewSet.objects.get(
                    team=self.team,
                    kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
                )
                managed_viewset.delete_with_views()

            except DataWarehouseManagedViewSet.DoesNotExist:
                pass
            remove_person_join(self.team.pk, table_prefix)

        # Return the full external data source with updated config
        source_serializer = self.get_serializer(external_data_source, context=self.get_serializer_context())
        return Response(source_serializer.data)

    def _compute_missing_webhook_events(
        self,
        source: WebhookSource,
        config: Any,
        instance: ExternalDataSource,
        external_status: ExternalWebhookInfo | None,
    ) -> list[str]:
        """Desired events not yet on the provider webhook — surfaced so manual-webhook users
        (or keys lacking webhook-write scope) know what to add."""
        if not external_status or not external_status.exists or external_status.error:
            return []

        eligible_schema_names = list(
            ExternalDataSchema.objects.filter(
                source=instance,
                team_id=self.team_id,
                sync_type=ExternalDataSchema.SyncType.WEBHOOK,
                should_sync=True,
            )
            .exclude(deleted=True)
            .values_list("name", flat=True)
        )

        desired = source.get_desired_webhook_events(config, eligible_schema_names)
        if not desired:
            return []

        current = set(external_status.enabled_events or [])
        if "*" in current:
            return []

        return sorted(e for e in desired if e not in current)

    @action(methods=["GET"], detail=True)
    def webhook_info(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()
        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)

        if not isinstance(source, WebhookSource):
            return Response(
                status=status.HTTP_200_OK,
                data={
                    "supports_webhooks": False,
                    "exists": False,
                    "webhook_url": None,
                    "schema_mapping": {},
                    "external_status": None,
                },
            )

        blocked_reason = self._webhook_creation_blocked_reason(source, instance)

        hog_function = HogFunction.objects.filter(
            team=self.team,
            type="warehouse_source_webhook",
            inputs__source_id__value=str(instance.pk),
            deleted=False,
        ).first()

        if not hog_function:
            return Response(
                status=status.HTTP_200_OK,
                data={
                    "supports_webhooks": True,
                    "exists": False,
                    "auto_creation_blocked_reason": blocked_reason,
                },
            )

        webhook_url = get_webhook_url(hog_function.id)

        external_status: ExternalWebhookInfo | None = None
        missing_events: list[str] = []

        if instance.job_inputs:
            try:
                config = source.parse_config(instance.job_inputs)
                external_status = source.get_external_webhook_info(
                    config, webhook_url, self.team_id, api_version=source.resolve_api_version(instance.api_version)
                )
                missing_events = self._compute_missing_webhook_events(source, config, instance, external_status)
            except Exception as e:
                capture_exception(e)

        schema_mapping = {}
        if hog_function.inputs:
            schema_mapping = hog_function.inputs.get("schema_mapping", {}).get("value", {})

        webhook_field_names = {f.name for f in (source.get_source_config.webhookFields or [])}
        all_inputs = HogFunctionSerializer(hog_function).data.get("inputs") or {}
        webhook_inputs = {k: v for k, v in all_inputs.items() if k in webhook_field_names}

        return Response(
            status=status.HTTP_200_OK,
            data={
                "supports_webhooks": True,
                "exists": True,
                "hog_function": {
                    "id": str(hog_function.id),
                    "name": hog_function.name,
                    "enabled": hog_function.enabled,
                    "created_at": hog_function.created_at.isoformat(),
                    "status": hog_function.status,
                },
                "webhook_url": webhook_url,
                "schema_mapping": schema_mapping,
                "inputs": webhook_inputs,
                "external_status": dataclasses.asdict(external_status) if external_status else None,
                "missing_events": missing_events,
                "auto_creation_blocked_reason": blocked_reason,
            },
        )

    def _webhook_creation_blocked_reason(self, source: WebhookSource, instance: ExternalDataSource) -> str | None:
        """Ask the source whether this connection can never create the provider-side webhook.
        Best-effort: an unparseable config or a source-side failure leaves the button offered,
        which is the behavior before the check existed."""
        if not instance.job_inputs:
            return None
        try:
            return source.webhook_creation_blocked_reason(source.parse_config(instance.job_inputs), self.team_id)
        except Exception as e:
            capture_exception(e)
            return None

    @action(methods=["POST"], detail=True)
    def create_webhook(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        if not instance.job_inputs:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Source has no configuration"},
            )

        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)

        if not isinstance(source, WebhookSource):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "This source type does not support webhooks"},
            )

        # A connection known to lack the grant can't be fixed by trying. The hog function is still
        # minted below so manual setup has a URL to paste; only the doomed provider round-trip (one
        # call per repository, for GitHub) is skipped.
        blocked_reason = self._webhook_creation_blocked_reason(source, instance)

        effective_api_version = source.resolve_api_version(instance.api_version)
        try:
            config = source.parse_config(instance.job_inputs)
            source_schemas = source.get_schemas(config, self.team_id, api_version=effective_api_version)
        except ValidationError as e:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Invalid source configuration", "details": getattr(e, "detail", str(e))},
            )
        except Exception as e:
            capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Failed to load source configuration or schemas"},
            )

        webhook_source_schemas = {s.name: s for s in source_schemas if s.supports_webhooks}

        db_schemas = ExternalDataSchema.objects.filter(
            source=instance,
            team_id=self.team_id,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            should_sync=True,
        ).exclude(deleted=True)

        eligible_schemas = [s for s in db_schemas if s.name in webhook_source_schemas]

        hog_fn_result = get_or_create_webhook_hog_function(
            team=self.team,
            source=source,
            source_id=str(instance.pk),
            eligible_schemas=eligible_schemas,
            config=config,
        )

        if hog_fn_result.error:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": hog_fn_result.error},
            )

        if blocked_reason is not None:
            return Response(
                status=status.HTTP_200_OK,
                data={
                    "success": False,
                    "webhook_url": hog_fn_result.webhook_url,
                    "error": blocked_reason,
                    "pending_inputs": [],
                },
            )

        result = create_and_register_webhook(
            source, config, hog_fn_result, self.team_id, api_version=effective_api_version
        )

        return Response(
            status=status.HTTP_200_OK,
            data={
                "success": result.success,
                "webhook_url": result.webhook_url,
                "error": result.error,
                "pending_inputs": result.pending_inputs,
            },
        )

    @action(methods=["POST"], detail=True)
    def update_webhook_inputs(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        if not instance.job_inputs:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Source has no configuration"},
            )

        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)

        if not isinstance(source, WebhookSource):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "This source type does not support webhooks"},
            )

        inputs = request.data.get("inputs", {})
        if not inputs or not isinstance(inputs, dict):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No inputs provided"},
            )

        source_config = source.get_source_config
        webhook_fields = source_config.webhookFields or []
        webhook_field_names = {f.name for f in webhook_fields}

        invalid_keys = set(inputs.keys()) - webhook_field_names
        if invalid_keys:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid input keys: {', '.join(invalid_keys)}"},
            )

        required_fields = [f.name for f in webhook_fields if getattr(f, "required", False)]
        blanked_required = [name for name in required_fields if name in inputs and not inputs[name]]
        if blanked_required:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Missing required fields: {', '.join(blanked_required)}"},
            )

        try:
            hog_function = HogFunction.objects.get(
                team=self.team,
                type="warehouse_source_webhook",
                inputs__source_id__value=str(instance.pk),
                deleted=False,
            )
        except HogFunction.DoesNotExist:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "No webhook function found for this source. Create a webhook first."},
            )

        try:
            config = source.parse_config(instance.job_inputs)
        except ValidationError as e:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Invalid source configuration", "details": getattr(e, "detail", str(e))},
            )
        except Exception as e:
            capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Failed to load source configuration"},
            )

        assert hog_function.inputs is not None
        hog_function.inputs = {
            **hog_function.inputs,
            **{key: {"value": value} for key, value in inputs.items()},
        }
        hog_function.save(update_fields=["inputs", "encrypted_inputs"])

        success, error = source.webhook_inputs_updated(
            config,
            get_webhook_url(hog_function.id),
            self.team.pk,
            inputs,
            api_version=source.resolve_api_version(instance.api_version),
        )
        if not success:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"success": False, "error": error or "Failed to update webhook on the external source."},
            )

        return Response(status=status.HTTP_200_OK, data={"success": True})

    def _fill_default_sync_settings(
        self,
        source: ExternalDataSource,
        schema_updates: list[dict[str, Any]],
        source_schemas_by_id: dict[uuid.UUID, ExternalDataSchema],
    ) -> tuple[dict[str, tuple[str, str]], set[str]]:
        """Fill default sync settings into bulk-update items that ask for them.

        Items with ``apply_sync_defaults`` targeting a schema that has no sync method yet (and
        whose update doesn't set one) get their sync settings discovered from the source — one
        discovery call for the whole batch. Returns per-schema failures (dropped tables,
        webhook-only tables, discovery errors) for the caller to skip and report, plus the ids
        of the schemas whose settings were filled in.
        """
        needing_defaults = [
            schema_update
            for schema_update in schema_updates
            if schema_update.get("apply_sync_defaults")
            and schema_update.get("sync_type") is None
            and source_schemas_by_id[schema_update["id"]].sync_type is None
        ]
        # Direct-query sources have no sync method to configure — enabling is just should_sync.
        if not needing_defaults or not source.supports_scheduled_sync:
            return {}, set()

        failures: dict[str, tuple[str, str]] = {}
        names = [source_schemas_by_id[schema_update["id"]].name for schema_update in needing_defaults]
        source_impl: AnySource | None = None
        try:
            source_impl = SourceRegistry.get_source(ExternalDataSourceType(source.source_type))
            config = source_impl.parse_config(source.job_inputs)
            discovered = source_impl.get_schemas(
                config, self.team_id, names=names, api_version=source_impl.resolve_api_version(source.api_version)
            )
        except Exception as e:
            # Discovery connects to the customer's source, so an expected user/upstream failure
            # (bad credentials, unreachable host) is theirs to fix and is already reported back to
            # them below — don't capture it as error-tracking noise. Mirrors `refresh_schemas`.
            _, is_expected_source_error = helpers._classify_refresh_schemas_error(source_impl, e)
            if not is_expected_source_error:
                capture_exception(e)
            reason = "could not read the source to pick default sync settings; check the source credentials"
            for schema_update in needing_defaults:
                schema = source_schemas_by_id[schema_update["id"]]
                failures[str(schema.id)] = (schema.name, reason)
            return failures, set()

        # Not every source honors the `names` filter, so match by name instead of order.
        discovered_by_name = {discovered_schema.name: discovered_schema for discovered_schema in discovered}
        defaulted_schema_ids: set[str] = set()
        for schema_update in needing_defaults:
            schema = source_schemas_by_id[schema_update["id"]]
            discovered_schema = discovered_by_name.get(schema.name)
            if discovered_schema is None:
                failures[str(schema.id)] = (
                    schema.name,
                    "not found on the source; pull new schemas to refresh the table list",
                )
                continue
            if discovered_schema.webhook_only:
                failures[str(schema.id)] = (
                    schema.name,
                    "can only be synced via webhooks; set up the webhook sync method instead",
                )
                continue
            for key, value in build_default_sync_settings(discovered_schema).items():
                # A caller-sent value wins; None (missing or explicit null) means "not set".
                if schema_update.get(key) is None:
                    schema_update[key] = value
            defaulted_schema_ids.add(str(schema.id))
        return failures, defaulted_schema_ids

    @extend_schema(
        request=source_serializers.ExternalDataSourceBulkUpdateSchemasSerializer,
        responses={200: ExternalDataSchemaSerializer(many=True)},
    )
    @action(methods=["PATCH"], detail=True)
    def bulk_update_schemas(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source = self.get_object()
        serializer = source_serializers.ExternalDataSourceBulkUpdateSchemasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        schema_updates: list[dict[str, Any]] = serializer.validated_data["schemas"]
        schema_ids = [schema_update["id"] for schema_update in schema_updates]

        if len(set(schema_ids)) != len(schema_ids):
            raise ValidationError("Schema updates must contain unique ids")

        source_schemas = ExternalDataSchema.objects.filter(
            team_id=self.team_id,
            source_id=source.id,
            id__in=schema_ids,
        ).select_related("source", "table__credential", "table__external_data_source")
        source_schemas_by_id = {schema.id: schema for schema in source_schemas}

        if len(source_schemas_by_id) != len(schema_ids):
            raise ValidationError("One or more schemas could not be found for this source")

        # Reject up front rather than per-schema, so a batch touching a locked table writes nothing.
        self._assert_can_write_schemas(source_schemas_by_id.values())

        # Items that ask for sync defaults on a not-yet-configured schema get them discovered and
        # filled in up front. Tables that can't get defaults (dropped from the source, webhook-only)
        # fail individually and are skipped below, without blocking the rest of the batch.
        failed_schemas, defaulted_schema_ids = self._fill_default_sync_settings(
            source, schema_updates, source_schemas_by_id
        )
        only_validation_errors = True

        serializer_context = self.get_serializer_context()
        updated_schemas: list[ExternalDataSchema] = []
        # Each deferred action is paired with its schema so a post-commit failure can be attributed.
        post_commit_actions: list[tuple[ExternalDataSchema, Callable[[], None]]] = []

        # Validate every payload before writing anything, so a malformed request is rejected up
        # front. Some checks only run inside the serializer's update() (during save() below), so
        # this catches the common input errors but not all of them — the save loop handles the rest.
        prepared: list[tuple[ExternalDataSchema, ExternalDataSchemaSerializer, list[Callable[[], None]]]] = []
        for schema_update in schema_updates:
            schema_id = schema_update["id"]
            schema = source_schemas_by_id[schema_id]
            if str(schema.id) in failed_schemas:
                continue
            schema_payload = {
                key: value for key, value in schema_update.items() if key not in ("id", "apply_sync_defaults")
            }

            schema_post_commit_actions: list[Callable[[], None]] = []
            schema_serializer = ExternalDataSchemaSerializer(
                schema,
                data=schema_payload,
                partial=True,
                context={**serializer_context, "post_commit_actions": schema_post_commit_actions},
            )
            schema_serializer.is_valid(raise_exception=True)
            if str(schema.id) in defaulted_schema_ids:
                # Defaults discovery already confirmed these tables aren't webhook-only; seed the
                # cache so the warm step below doesn't re-probe the source once per schema.
                schema_serializer.seed_webhook_only_check(False)
            # Do the webhook-only source-discovery call (e.g. Google Ads token refresh + field query)
            # here, before the per-schema transaction below. Running it inside update()'s transaction
            # held the DB connection idle-in-transaction long enough for the server to close it.
            # update() reads the cached result, so it still validates and fails per-schema.
            schema_serializer.warm_webhook_only_check(schema)
            prepared.append((schema, schema_serializer, schema_post_commit_actions))

        # Commit each schema in its own transaction. A single atomic block around the whole batch
        # meant one schema's failure rolled back every schema and failed the request, so the user
        # got nothing applied. Isolating per schema keeps the ones that saved committed, attempts
        # every schema so a single bad one can't block the rest, and reports the failures together.
        for schema, schema_serializer, schema_post_commit_actions in prepared:
            try:
                with transaction.atomic():
                    updated_schemas.append(schema_serializer.save())
            except Exception as e:
                if isinstance(e, ValidationError):
                    reason = source_serializers._validation_error_message(e)
                    logger.warning(
                        "bulk_update_schemas validation error during save",
                        source_id=str(source.id),
                        schema_id=str(schema.id),
                    )
                else:
                    only_validation_errors = False
                    reason = "a database error occurred while saving"
                    capture_exception(e)
                    logger.exception(
                        "bulk_update_schemas failed to persist schema",
                        source_id=str(source.id),
                        schema_id=str(schema.id),
                    )
                failed_schemas[str(schema.id)] = (schema.name, reason)
                # A dropped connection leaves Django holding a dead handle; reset it so the next
                # schema reconnects instead of failing on the same broken connection.
                if not connection.is_usable():
                    connection.close()
                continue

            # Only run a schema's Temporal side effects once its own row is committed.
            post_commit_actions.extend((schema, action) for action in schema_post_commit_actions)

        post_commit_error: Exception | None = None
        for action_schema, post_commit_action in post_commit_actions:
            try:
                post_commit_action()
            except Exception as e:
                # The row is already committed but its schedule still runs the old cadence. Capture +
                # log every failure (with the schema id) so the drift is visible, and remember it so
                # the request fails below — the caller must know the batch did not fully apply.
                post_commit_error = e
                capture_exception(e)
                logger.warning(
                    "bulk_update_schemas saved the schema but its Temporal schedule update failed",
                    source_id=str(source.id),
                    schema_id=str(action_schema.id),
                    exc_info=e,
                )

        # Report save failures first so a schedule-update failure can't mask which schemas didn't
        # save, then fail the request on the schedule-update failure.
        if failed_schemas:
            raise source_serializers.BulkSchemaSaveError(failed_schemas, only_validation_errors=only_validation_errors)
        if post_commit_error is not None:
            raise post_commit_error

        return Response(
            ExternalDataSchemaSerializer(updated_schemas, many=True, context=serializer_context).data,
            status=status.HTTP_200_OK,
        )

    @action(methods=["POST"], detail=True)
    def delete_webhook(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        source_type = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type)

        if not isinstance(source, WebhookSource):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "This source type does not support webhooks"},
            )

        # Check that no schemas are still relying on the webhook — deleting it
        # would break their sync pipeline.
        webhook_schemas = ExternalDataSchema.objects.filter(
            source=instance,
            team_id=self.team_id,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            should_sync=True,
        ).exclude(deleted=True)

        if webhook_schemas.exists():
            schema_names = list(webhook_schemas.values_list("name", flat=True))
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "message": f"Cannot delete webhook while tables are using webhook sync: {', '.join(schema_names)}. Switch them to full refresh, incremental, or disable syncing first.",
                },
            )

        if not instance.job_inputs:
            # No config means we can't call the external API, but we can still
            # clean up the HogFunction.
            try:
                hog_function = HogFunction.objects.get(
                    team=self.team,
                    type="warehouse_source_webhook",
                    inputs__source_id__value=str(instance.pk),
                    deleted=False,
                )
                hog_function.deleted = True
                hog_function.enabled = False
                hog_function.save(update_fields=["deleted", "enabled"])
            except HogFunction.DoesNotExist:
                pass

            return Response(
                status=status.HTTP_200_OK,
                data={"success": True, "external_deleted": False},
            )

        try:
            config = source.parse_config(instance.job_inputs)
        except Exception as e:
            capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Failed to parse source configuration"},
            )

        result = delete_webhook_and_hog_function(
            team=self.team,
            source=source,
            config=config,
            source_id=str(instance.pk),
            api_version=source.resolve_api_version(instance.api_version),
        )

        return Response(
            status=status.HTTP_200_OK,
            data={
                "success": result.success,
                "external_deleted": result.external_deleted,
                "error": result.error,
            },
        )
