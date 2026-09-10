"""External data source view set."""

from __future__ import annotations

from typing import Any, cast

from django.db.models import Prefetch

import structlog
from drf_spectacular.utils import extend_schema
from opentelemetry import trace
from rest_framework import filters, serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.database.database import Database

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.permissions import AccessControlPermission, APIScopePermission, TeamMemberAccessPermission
from posthog.rate_limit import (
    CustomSourceAIBuilderBurstThrottle,
    CustomSourceAIBuilderDailyThrottle,
    CustomSourceAIBuilderSustainedThrottle,
)

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.data_warehouse.backend.facade.api import (
    bulk_create_external_data_job_schedules,
    bulk_delete_external_data_schedules,
    cancel_external_data_workflow,
    delete_discover_schemas_schedule,
    delete_external_data_schedule,
    ensure_cdc_slot_cleanup_schedule,
    is_cdc_enabled_for_team,
    is_cdc_extraction_schedule_paused,
    sync_cdc_extraction_schedule,
    sync_discover_schemas_schedule,
    trigger_external_data_source_workflow,
    unpause_cdc_extraction_schedule,
)
from products.revenue_analytics.backend.facade.api import ensure_person_join
from products.warehouse_sources.backend.facade.models import (
    ExternalDataSchema,
    ExternalDataSource,
    latest_completed_job_prefetch,
)
from products.warehouse_sources.backend.facade.source_management import (
    SourceRegistry,
    cdc_pg_connection,
    get_primary_key_columns,
    purge_buffer_prefix,
)

from . import credential_store, helpers, oauth_accounts, source_setup
from .change_data_capture import ExternalDataSourceCDCMixin
from .connection_options import ExternalDataSourceConnectionOptionsMixin
from .credential_store import ExternalDataSourceCredentialStoreMixin
from .job_runs import ExternalDataSourceJobRunsMixin
from .oauth_accounts import ExternalDataSourceOAuthAccountsMixin
from .schema_operations import ExternalDataSourceSchemaOperationsMixin
from .source_setup import ExternalDataSourceSetupMixin
from .webhook_setup import ExternalDataSourceWebhookSetupMixin

logger = structlog.get_logger(__name__)

__all__ = [
    "SourceRegistry",
    "bulk_create_external_data_job_schedules",
    "bulk_delete_external_data_schedules",
    "cancel_external_data_workflow",
    "capture_exception",
    "cdc_pg_connection",
    "delete_discover_schemas_schedule",
    "delete_external_data_schedule",
    "ensure_cdc_slot_cleanup_schedule",
    "ensure_person_join",
    "get_primary_key_columns",
    "is_cdc_enabled_for_team",
    "is_cdc_extraction_schedule_paused",
    "logger",
    "purge_buffer_prefix",
    "sync_cdc_extraction_schedule",
    "sync_discover_schemas_schedule",
    "trigger_external_data_source_workflow",
    "unpause_cdc_extraction_schedule",
]


@extend_schema(extensions={"x-product": "warehouse_sources"})
class ExternalDataSourceViewSet(
    ExternalDataSourceSetupMixin,
    ExternalDataSourceSchemaOperationsMixin,
    ExternalDataSourceCredentialStoreMixin,
    ExternalDataSourceOAuthAccountsMixin,
    ExternalDataSourceJobRunsMixin,
    ExternalDataSourceConnectionOptionsMixin,
    ExternalDataSourceWebhookSetupMixin,
    ExternalDataSourceCDCMixin,
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
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
    serializer_class = source_setup.ExternalDataSourceSerializers
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
                oauth_accounts.AccountPickerManagementPermission(),
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
            return source_setup.ExternalDataSourceCreateSerializer
        if self.action == "database_schema":
            return credential_store.DatabaseSchemaRequestSerializer
        return source_setup.ExternalDataSourceSerializers

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
