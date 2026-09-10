"""Serializers and endpoints for source setup."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import temporalio
from drf_spectacular.utils import extend_schema, extend_schema_field
from openai import APIConnectionError
from psycopg import OperationalError
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.hogql.direct_sql.capability import direct_capable_source_types

from posthog.api.utils import action
from posthog.event_usage import EventSource, get_event_source, is_wizard_self_driving_program, report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.data_warehouse.backend.facade.api import (
    apply_on_schema_clear as apply_sql_warehouse_schema_clear_migration,
    delete_webhook_and_hog_function,
    detect_schema_clear_transition as detect_sql_schema_clear_transition,
    get_direct_query_engine,
    get_namespaced_resource_adapter,
    is_any_external_data_schema_paused,
    is_custom_source_ai_builder_enabled_for_team,
)
from products.warehouse_sources.backend.facade.api import validate_source_prefix
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
    PendingSourceCredential,
    sync_old_schemas_with_new_schemas,
)
from products.warehouse_sources.backend.facade.source_management import (
    PREVIEW_DEFAULT_ROWS,
    PREVIEW_MAX_ROWS,
    AnySource,
    CDCSourceAdapter,
    Config,
    CustomSource,
    CustomSourceConfig,
    DocsFetchError,
    MySQLSource,
    PostgresSource,
    RowFilterValidationError,
    SourceRegistry,
    SourceSchema,
    SSLRequiredError,
    WebhookSource,
    build_default_schemas,
    draft_manifest_sync,
    fetch_docs_text,
    filter_dwh_columns_by_enabled_columns,
    get_cdc_adapter,
    new_source_requires_ssl,
    sql_schema_metadata,
    validate_and_coerce_row_filters,
)
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType
from products.warehouse_sources.backend.presentation.views.destination_links import set_source_destinations
from products.warehouse_sources.backend.presentation.views.external_data_schema import (
    ExternalDataSchemaListSerializer,
    ExternalDataSchemaSerializer,
    source_supports_column_selection,
    unsupported_row_filter_reason,
)
from products.warehouse_sources.backend.presentation.views.source_api_versions import (
    ExternalDataSourceApiVersionDeprecationSerializer,
    api_version_deprecation_payload,
)

from . import base, connection_options, credential_store, helpers, webhook_setup


class ExternalDataSourceSerializers(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    created_by = serializers.SerializerMethodField(read_only=True)
    latest_error = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    schemas = serializers.SerializerMethodField(read_only=True)
    engine = serializers.ChoiceField(
        source="connection_metadata.engine",
        read_only=True,
        allow_null=True,
        required=False,
        choices=helpers.DIRECT_CONNECTION_ENGINE_CHOICES,
        help_text="Backend engine detected for the direct connection.",
    )
    revenue_analytics_config = connection_options.ExternalDataSourceRevenueAnalyticsConfigSerializer(
        source="revenue_analytics_config_safe", read_only=True
    )
    access_method = serializers.ChoiceField(choices=ExternalDataSource.AccessMethod.choices, read_only=True)
    supports_webhooks = serializers.SerializerMethodField(read_only=True)
    supports_column_selection = serializers.SerializerMethodField(
        read_only=True,
        help_text="Whether this source supports per-column sync selection via `enabled_columns`.",
    )
    # Optional on both create and update. On create, missing values default to `api`
    # in the viewset to preserve backward compatibility with direct API callers that
    # predate this field; the in-app UI and MCP tool always send it explicitly.
    # `update` strips it to make the field write-once.
    # `allow_null=True` because historical rows (created before migration 0049) have
    # `created_via=NULL`, and the settings page spreads the GET payload back into PATCH.
    created_via = serializers.ChoiceField(
        choices=ExternalDataSource.CreatedVia.choices,
        required=False,
        allow_null=True,
        help_text=(
            "How this source was created. Defaults to `api` on create when omitted. "
            "`web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls, "
            "`wizard` for the setup wizard and `self_driving` for the PostHog Desktop app "
            "(both derived server-side from the caller's user agent). "
            "Ignored on update."
        ),
    )
    direct_query_enabled = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether this synced source is also live-queryable via direct connection. "
            "Defaults to false for new sources; ignored for pure direct-query sources."
        ),
    )
    auto_sync_new_schemas = serializers.BooleanField(
        required=False,
        help_text=(
            "Automatically enable syncing for schemas discovered on this source after creation, "
            "on both the scheduled discovery pass and manual schema refreshes. Defaults to false. "
            "Not supported for direct-query sources."
        ),
    )
    auto_sync_schema_patterns = serializers.ListField(
        child=serializers.CharField(
            max_length=250,
            allow_blank=False,
            help_text="An fnmatch-style glob pattern, e.g. `raw_*`.",
        ),
        required=False,
        allow_null=True,
        max_length=100,
        help_text=(
            "Optional fnmatch-style globs (`*` and `?` wildcards) restricting which newly discovered "
            "schema names auto-sync, matched case-insensitively against both the qualified and bare "
            "table name. Null or empty means every new schema qualifies. Only used when "
            "`auto_sync_new_schemas` is true."
        ),
    )
    api_version = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Vendor API version this source is pinned to (an opaque vendor label, e.g. a Stripe "
            "date version). Null resolves to the source type's default version at sync time."
        ),
    )
    api_version_deprecation = serializers.SerializerMethodField(
        read_only=True,
        help_text=(
            "Set when the vendor has deprecated the API version this source is pinned to; "
            "null otherwise. Drives the in-product deprecation warning."
        ),
    )

    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "created_at",
            "created_by",
            "created_via",
            "status",
            "client_secret",
            "account_id",
            "source_type",
            "latest_error",
            "prefix",
            "description",
            "access_method",
            "direct_query_enabled",
            "auto_sync_new_schemas",
            "auto_sync_schema_patterns",
            "engine",
            "last_run_at",
            "schemas",
            "job_inputs",
            "revenue_analytics_config",
            "user_access_level",
            "supports_webhooks",
            "supports_column_selection",
            "api_version",
            "api_version_deprecation",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "status",
            "source_type",
            "latest_error",
            "last_run_at",
            "schemas",
            "engine",
            "revenue_analytics_config",
            "user_access_level",
            "access_method",
            "supports_webhooks",
            "supports_column_selection",
            "api_version",
            "api_version_deprecation",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        job_inputs = representation.get("job_inputs", {})
        if not isinstance(job_inputs, dict):
            return representation

        # Derive allowed keys dynamically from source config field definitions
        try:
            source_type_model = ExternalDataSourceType(instance.source_type)
            source = SourceRegistry.get_source(source_type_model)
            split = helpers.get_nonsensitive_and_sensitive_field_names(source.get_source_config.fields)
            # CDC fields aren't form fields but are non-secret operational config the UI needs.
            nonsensitive = split.nonsensitive | helpers._CDC_EXPOSED_JOB_INPUT_KEYS
        except (ValueError, KeyError):
            representation["job_inputs"] = {}
            return representation

        # Normalize SSH tunnel legacy format before stripping
        if "ssh_tunnel" in job_inputs and isinstance(job_inputs["ssh_tunnel"], dict):
            tunnel = job_inputs["ssh_tunnel"]
            # Normalize 'auth_type' (legacy from migration 0807) -> 'auth'
            if "auth_type" in tunnel and "auth" not in tunnel:
                tunnel["auth"] = tunnel.pop("auth_type")
            if isinstance(tunnel.get("auth"), dict):
                auth = tunnel["auth"]
                # Normalize 'type' (legacy) -> 'selection'
                if "type" in auth and "selection" not in auth:
                    auth["selection"] = auth.pop("type")
            # Backfill require_tls default for sources created before the toggle existed
            if "require_tls" not in tunnel:
                tunnel["require_tls"] = {"enabled": True}

        stripped = helpers.strip_sensitive_from_dict(job_inputs, nonsensitive, split.sensitive)
        declared = helpers.get_declared_field_names(source.get_source_config.fields)
        representation["job_inputs"] = helpers.restore_declared_field_names(stripped, declared.hyphenated)
        return representation

    def get_last_run_at(self, instance: ExternalDataSource) -> str | None:
        latest_completed_run = instance.ordered_jobs[0] if instance.ordered_jobs else None  # type: ignore

        return latest_completed_run.created_at.isoformat() if latest_completed_run else None

    def get_created_by(self, instance: ExternalDataSource) -> str | None:
        return instance.created_by.email if instance.created_by else None

    def get_supports_webhooks(self, instance: ExternalDataSource) -> bool:
        try:
            source = SourceRegistry.get_source(ExternalDataSourceType(instance.source_type))
            return isinstance(source, WebhookSource)
        except Exception as e:
            capture_exception(e)
            return False

    def get_supports_column_selection(self, instance: ExternalDataSource) -> bool:
        return source_supports_column_selection(instance.source_type)

    @extend_schema_field(ExternalDataSourceApiVersionDeprecationSerializer(allow_null=True))
    def get_api_version_deprecation(self, instance: ExternalDataSource) -> dict[str, Any] | None:
        return api_version_deprecation_payload(instance.source_type, instance.api_version)

    def _prefetched_schemas(self, instance: ExternalDataSource) -> list[ExternalDataSchema] | None:
        prefetched = getattr(instance, "_prefetched_objects_cache", {}).get("schemas")
        if prefetched is None:
            return None
        return [schema for schema in prefetched if not schema.deleted]

    def _active_schemas(self, instance: ExternalDataSource) -> list[ExternalDataSchema]:
        """Schemas that are syncing or carry an error — derived in Python from the single `schemas`
        prefetch rather than a second DB scan of the same (potentially huge) table."""
        prefetched = self._prefetched_schemas(instance)
        if prefetched is not None:
            return [schema for schema in prefetched if schema.should_sync or schema.latest_error is not None]
        return list(instance.schemas.exclude(deleted=True).filter(Q(should_sync=True) | Q(latest_error__isnull=False)))

    def get_status(self, instance: ExternalDataSource) -> str:
        active_schemas: list[ExternalDataSchema] = self._active_schemas(instance)
        # Negative statuses should ignore schemas the user has disabled — those can linger in
        # active_schemas via the latest_error prefetch but shouldn't drag the source into a failed state.
        syncing_schemas = [schema for schema in active_schemas if schema.should_sync]
        any_failures = any(schema.status == ExternalDataSchema.Status.FAILED for schema in syncing_schemas)
        any_billing_limits_reached = any(
            schema.status == ExternalDataSchema.Status.BILLING_LIMIT_REACHED for schema in syncing_schemas
        )
        any_billing_limits_too_low = any(
            schema.status == ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW for schema in syncing_schemas
        )
        any_paused = any(schema.status == ExternalDataSchema.Status.PAUSED for schema in active_schemas)
        any_running = any(schema.status == ExternalDataSchema.Status.RUNNING for schema in active_schemas)
        any_completed = any(schema.status == ExternalDataSchema.Status.COMPLETED for schema in active_schemas)

        if any_failures:
            return ExternalDataSchema.Status.FAILED
        elif any_billing_limits_reached:
            return "Billing limits"
        elif any_billing_limits_too_low:
            return "Billing limits too low"
        elif any_paused:
            return ExternalDataSchema.Status.PAUSED
        elif any_running:
            return ExternalDataSchema.Status.RUNNING
        elif any_completed:
            return ExternalDataSchema.Status.COMPLETED
        else:
            # Fallback during migration phase of going from source -> schema as the source of truth for syncs
            return instance.status

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_latest_error(self, instance: ExternalDataSource):
        prefetched_schemas = self._prefetched_schemas(instance)
        if prefetched_schemas is not None:
            schema_with_error = next(
                (schema for schema in prefetched_schemas if schema.latest_error is not None),
                None,
            )
        else:
            schema_with_error = instance.schemas.filter(latest_error__isnull=False).first()
        return schema_with_error.latest_error if schema_with_error else None

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_schemas(self, instance: ExternalDataSource):
        prefetched_schemas = getattr(instance, "_prefetched_objects_cache", {}).get("schemas")
        if prefetched_schemas is not None:
            schemas = [schema for schema in prefetched_schemas if not schema.deleted]
        else:
            schemas = list(instance.schemas.exclude(deleted=True).order_by("name"))
        # The source list embeds every schema of every source; large projects have tens of thousands.
        # The list UI only reads a handful of per-schema fields, so serialize the trimmed shape there
        # and reserve the full serializer for single-source reads.
        if self.context.get("schemas_list_only"):
            return ExternalDataSchemaListSerializer(schemas, many=True, read_only=True, context=self.context).data
        return ExternalDataSchemaSerializer(schemas, many=True, read_only=True, context=self.context).data

    def update(self, instance: ExternalDataSource, validated_data: Any) -> Any:
        request = self.context.get("request")
        requested_access_method = request.data.get("access_method") if request is not None else None
        if requested_access_method is not None and requested_access_method != instance.access_method:
            raise ValidationError("Access method cannot be changed. Create a new source instead.")

        validated_data.pop("access_method", None)
        # created_via is set at creation time and cannot be mutated afterwards
        validated_data.pop("created_via", None)

        if validated_data.get("auto_sync_new_schemas") and instance.is_direct_query:
            raise ValidationError(
                "Auto-syncing new schemas is not supported for direct query sources, "
                "because their schemas resolve at query time."
            )

        incoming_prefix = validated_data.get("prefix", instance.prefix)

        if instance.is_direct_query:
            # For direct query sources the prefix acts as the user-facing source name.
            normalized_prefix = incoming_prefix.strip() if isinstance(incoming_prefix, str) else ""
            if not normalized_prefix:
                raise ValidationError("Name is required for direct query sources")
            if ExternalDataSource.is_system_managed_prefix(normalized_prefix):
                raise ValidationError(helpers.RESERVED_SOURCE_NAME_MESSAGE)
            validated_data["prefix"] = normalized_prefix
        else:
            validated_data["prefix"] = instance.prefix

        existing_job_inputs = instance.job_inputs or {}
        job_inputs_were_submitted = "job_inputs" in validated_data
        incoming_job_inputs = validated_data.get("job_inputs", {})

        source_type_model = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type_model)
        sensitive_fields = helpers.get_sensitive_field_names(source.get_source_config.fields)
        declared_field_names = helpers.get_declared_field_names(source.get_source_config.fields)
        discovered_schemas: list[SourceSchema] | None = None

        new_job_inputs = {**existing_job_inputs, **incoming_job_inputs}

        # CDC resource ownership changes must go through the CDC-specific endpoints.
        for key in helpers._CDC_EXPOSED_JOB_INPUT_KEYS:
            if key in existing_job_inputs:
                new_job_inputs[key] = existing_job_inputs[key]
            else:
                new_job_inputs.pop(key, None)

        # Server-managed job_inputs (Custom's OAuth2 row pointer, GitHub's legacy `repository`
        # marker): pin each to the stored value so an editor can't repoint the source at a different
        # row/marker (and through it, different credentials). Re-entered auth_oauth2_* secrets flow
        # into the pinned row during credential validation. The source declares which fields these
        # are — the API never names the source type.
        for field in source.server_managed_job_input_fields(incoming_job_inputs, existing_job_inputs):
            if existing_job_inputs.get(field):
                new_job_inputs[field] = existing_job_inputs[field]
            else:
                new_job_inputs.pop(field, None)

        # If the connection target changed, require credentials to be re-entered. Covers
        # both the generic `host` field and source-specific URL fields like ServiceNow's
        # `instance_url`, so a stored credential can't be redirected to a new host.
        connection_host_changed = any(
            field in incoming_job_inputs and incoming_job_inputs[field] != existing_job_inputs.get(field)
            for field in helpers._CONNECTION_TARGET_FIELDS
        )

        # Some sources keep their connection target in a differently named field (e.g. Okta's
        # `okta_domain`, Freshdesk's `subdomain`). Changing one would send the preserved credential
        # to a new host — the same exfiltration risk as a `host` change — so require re-entry too.
        connection_host_changed = connection_host_changed or any(
            field in incoming_job_inputs and incoming_job_inputs[field] != existing_job_inputs.get(field)
            for field in source.connection_host_fields
        )

        # If the SSH tunnel's connection target changed, also require credentials. Without this an
        # editor could swap in a tunnel that routes the backend's auth to an attacker-controlled
        # server, exfiltrating the stored database credentials (VERIA-311).
        ssh_tunnel_changed = "ssh_tunnel" in incoming_job_inputs and helpers.ssh_tunnel_connection_changed(
            existing_job_inputs.get("ssh_tunnel"),
            incoming_job_inputs.get("ssh_tunnel"),
        )

        # Some sources keep their connection target somewhere other than a named field — Custom's
        # lives inside its manifest. An edit that introduces a new request host would send the
        # preserved credential somewhere it wasn't going before, the same exfiltration risk, so
        # require re-entry too. The source decides; the API never names the source type.
        job_inputs_host_added = source.job_inputs_add_connection_host(incoming_job_inputs, existing_job_inputs)

        # Some sources keep their secrets in a bound row, not job_inputs (Custom's
        # CustomOAuth2Integration) — the generic preserved-credentials check can't see those, yet a
        # host change would still redirect the row's injected token. The source reports whether such
        # row-backed secrets are preserved (not re-entered) on this update.
        preserved_row_backed_credentials = source.has_preserved_row_backed_credentials(instance, incoming_job_inputs)

        if connection_host_changed or ssh_tunnel_changed or job_inputs_host_added:
            gate_sensitive_fields = sensitive_fields - helpers._CREATION_ONLY_SECRET_FIELDS
            preserved_credentials = helpers.has_preserved_credentials(
                existing_job_inputs,
                incoming_job_inputs,
                gate_sensitive_fields,
                nested_containers=(*helpers._NESTED_AUTH_CONTAINERS, *declared_field_names.switch_groups),
            )
            if preserved_credentials or preserved_row_backed_credentials:
                if ssh_tunnel_changed:
                    raise ValidationError("Changing the SSH tunnel requires re-entering your database credentials.")
                if job_inputs_host_added:
                    raise ValidationError("Changing the manifest's request host requires re-entering your credentials.")
                raise ValidationError("Changing the connection host requires re-entering your credentials.")

        # Preserve sensitive credentials not explicitly provided (API response omits them for security)
        for key in sensitive_fields:
            if existing_job_inputs.get(key) and not incoming_job_inputs.get(key):
                new_job_inputs[key] = existing_job_inputs[key]

        # SSH tunnel is a nested config - deep-merge it so partial updates preserve existing fields
        existing_ssh_tunnel = existing_job_inputs.get("ssh_tunnel")

        # Nested containers (e.g. Stripe `auth_method`, Snowflake `auth_type`, Billomat `registered_app`)
        # need a deep-merge that preserves sensitive fields not explicitly provided. The shallow merge
        # above would otherwise wipe redacted credentials nested inside these containers. Same container
        # list as the host-change gate above, so a merge here always has a matching preserved-credential check.
        for container_key in helpers._NESTED_AUTH_CONTAINERS:
            existing_container = existing_job_inputs.get(container_key)
            incoming_container = incoming_job_inputs.get(container_key)
            if incoming_container is not None and not isinstance(incoming_container, dict):
                raise ValidationError({"job_inputs": {container_key: "Must be an object."}})
            if not (isinstance(existing_container, dict) and isinstance(incoming_container, dict)):
                continue
            selection_changed = existing_container.get("selection") != incoming_container.get("selection")
            if selection_changed:
                # Selection switched (e.g. password→keypair) — use only incoming, don't carry over old secrets
                new_job_inputs[container_key] = incoming_container
            else:
                merged_container = {**existing_container, **incoming_container}
                for key in sensitive_fields:
                    if existing_container.get(key) and not incoming_container.get(key):
                        merged_container[key] = existing_container[key]
                new_job_inputs[container_key] = merged_container

        # Switch groups are nested containers too. The settings form submits only the fields the
        # user touched and skips a disabled group's children, so a payload that just flips
        # `enabled` would otherwise replace the whole stored group and drop a required nested
        # value that validation then rejects. Switching a group off keeps its stored value —
        # the user hasn't asked to forget it, and consumers gate on `enabled` before reading it.
        for group_key in declared_field_names.switch_groups:
            # A group declared with a hyphen can be stored under either spelling (see
            # `restore_declared_field_names`), so resolve both sides by declared name.
            incoming_key = helpers._stored_key(incoming_job_inputs, group_key)
            if incoming_key is None:
                continue
            incoming_group = incoming_job_inputs[incoming_key]
            if not isinstance(incoming_group, dict):
                raise ValidationError({"job_inputs": {group_key: "Must be an object."}})
            existing_group = helpers._stored_value(existing_job_inputs, group_key)
            if not isinstance(existing_group, dict):
                continue
            merged_group = {**existing_group, **incoming_group}
            # No switch group declares a secret today, but keep the carry-over so one could.
            for key in sensitive_fields:
                if existing_group.get(key) and not incoming_group.get(key):
                    merged_group[key] = existing_group[key]
            # Drop the other spelling so parsing can't see two competing groups.
            for key in helpers._name_variants(group_key):
                new_job_inputs.pop(key, None)
            new_job_inputs[incoming_key] = merged_group

        incoming_ssh_tunnel = incoming_job_inputs.get("ssh_tunnel")
        if existing_ssh_tunnel and incoming_ssh_tunnel is not None:
            ssh_tunnel_host_changed = "host" in incoming_ssh_tunnel and incoming_ssh_tunnel[
                "host"
            ] != existing_ssh_tunnel.get("host")

            # Deep-merge: start with existing, overlay incoming top-level keys
            merged_ssh_tunnel = {**existing_ssh_tunnel, **incoming_ssh_tunnel}

            # Check both 'auth' (new format) and 'auth_type' (legacy format from migration 0807)
            existing_auth = (
                (existing_ssh_tunnel or {}).get("auth") or (existing_ssh_tunnel or {}).get("auth_type") or {}
            )
            incoming_auth = (
                (incoming_ssh_tunnel or {}).get("auth") or (incoming_ssh_tunnel or {}).get("auth_type") or {}
            )

            if ssh_tunnel_host_changed and not incoming_auth:
                raise ValidationError("Changing the SSH tunnel host requires re-entering your SSH credentials.")

            if not incoming_auth:
                # No auth in incoming request - preserve entire existing auth
                merged_ssh_tunnel["auth"] = {**existing_auth}
            else:
                # Merge auth, preserving sensitive fields not explicitly provided
                merged_auth = {**incoming_auth}
                if not ssh_tunnel_host_changed:
                    for key in ("password", "passphrase", "private_key"):
                        if existing_auth.get(key) and not incoming_auth.get(key):
                            merged_auth[key] = existing_auth[key]
                merged_ssh_tunnel["auth"] = merged_auth

            new_job_inputs["ssh_tunnel"] = merged_ssh_tunnel

        is_valid, errors = source.validate_config(new_job_inputs)
        if not is_valid:
            raise ValidationError(f"Invalid source config: {', '.join(errors)}")

        # Clearing a multi-schema source's namespace migrates legacy rows to qualified naming.
        old_schema = detect_sql_schema_clear_transition(
            source_type=instance.source_type,
            existing_job_inputs=existing_job_inputs,
            incoming_job_inputs=incoming_job_inputs,
        )
        if old_schema is not None:
            apply_sql_warehouse_schema_clear_migration(instance, old_schema)

        source_config: Config = source.parse_config(new_job_inputs)
        validated_job_inputs = source_config.to_dict()

        # The settings form resubmits the whole connection config on every save, so changing an
        # unrelated setting (auto-syncing new tables, the prefix, the description) re-probed the
        # live connection too — and a momentarily unreachable database then failed the whole save,
        # leaving nothing to do but retry. Compare the parsed config against what's stored so the
        # probe below only runs when the connection actually changed. Direct query sources still
        # probe on every save: the same call refreshes their schemas and connection metadata.
        try:
            stored_job_inputs = source.parse_config(existing_job_inputs).to_dict()
        except Exception:
            # A stored config that no longer parses can't be compared, so treat it as changed and
            # let the probe run rather than skipping validation on a config we can't read.
            stored_job_inputs = None
        connection_config_changed = stored_job_inputs is None or stored_job_inputs != validated_job_inputs

        for key in helpers._CDC_EXPOSED_JOB_INPUT_KEYS:
            if key in existing_job_inputs:
                validated_job_inputs[key] = existing_job_inputs[key]
        validated_data["job_inputs"] = validated_job_inputs

        if job_inputs_were_submitted and (connection_config_changed or instance.is_direct_query):
            effective_api_version = source.resolve_api_version(instance.api_version)
            try:
                if isinstance(source, (PostgresSource, MySQLSource)):
                    credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                        cast(Any, source_config),
                        instance.team_id,
                        instance.access_method,
                        api_version=effective_api_version,
                    )
                elif isinstance(source, CustomSource):
                    # Pass the source being updated so an integration-backed OAuth2 source can only validate
                    # with the integration bound to it — not another source's, whose token the probe would
                    # otherwise mint and send to the submitted manifest host. owner_user_id additionally gates
                    # an as-yet-unbound integration to its creator.
                    credentials_valid, credentials_error = source.validate_credentials(
                        source_config,
                        instance.team_id,
                        source_id=str(instance.pk),
                        owner_user_id=self.context["request"].user.id,
                        api_version=effective_api_version,
                    )
                else:
                    credentials_valid, credentials_error = source.validate_credentials(
                        source_config, instance.team_id, api_version=effective_api_version
                    )
            except Exception as e:
                credentials_valid, credentials_error = helpers._credentials_validation_failed(
                    source, instance.team_id, e
                )
            if not credentials_valid:
                raise ValidationError(credentials_error or helpers.INVALID_CREDENTIALS_FALLBACK_MESSAGE)
            if instance.is_direct_query:
                discovered_schemas = source.get_schemas(
                    source_config, instance.team_id, api_version=effective_api_version
                )
                validated_data["connection_metadata"] = helpers.get_direct_connection_metadata(
                    source_impl=source,
                    source_config=source_config,
                    team_id=instance.team_id,
                    source_model=instance,
                    fallback=instance.connection_metadata,
                )

        if job_inputs_were_submitted and isinstance(source, CustomSource):
            # Credential validation adopts re-entered OAuth2 secrets into the integration row and
            # rewrites the config (pointer set, static secrets cleared) — re-serialize so job_inputs
            # stores the pointer and never the raw secrets.
            validated_job_inputs = source_config.to_dict()
            for key in helpers._CDC_EXPOSED_JOB_INPUT_KEYS:
                if key in existing_job_inputs:
                    validated_job_inputs[key] = existing_job_inputs[key]
            validated_data["job_inputs"] = validated_job_inputs

        # Namespaced-resource sources (GitHub repos) track their schema rows against a resource
        # set in job_inputs; capture the old set before the write so we can reconcile after.
        namespaced_adapter = get_namespaced_resource_adapter(source_type_model)
        old_namespaced_resources: list[str] = []
        if namespaced_adapter is not None and job_inputs_were_submitted:
            old_namespaced_resources = namespaced_adapter.resources_for_job_inputs(existing_job_inputs)

        updated_source: ExternalDataSource = super().update(instance, validated_data)

        if namespaced_adapter is not None and job_inputs_were_submitted:
            # Adds schema rows for added resources, retires removed ones, and reconciles their
            # webhooks. No-op when the effective resource list didn't change.
            namespaced_adapter.reconcile_resources(
                source_model=updated_source,
                team=instance.team,
                old_resources=old_namespaced_resources,
                new_config=source_config,
            )

        if updated_source.is_direct_query and discovered_schemas is not None:
            schema_names = {schema.name: schema.label for schema in discovered_schemas}
            descriptions = {schema.name: schema.description for schema in discovered_schemas}

            with transaction.atomic():
                ExternalDataSource._base_manager.filter(pk=updated_source.pk).select_for_update().get()
                engine = get_direct_query_engine(updated_source.direct_engine)
                name_substitutions = helpers._refresh_name_substitutions(
                    engine, source=updated_source, source_schemas=discovered_schemas, team_id=instance.team_id
                )
                if name_substitutions:
                    schema_names = {name_substitutions.get(name, name): label for name, label in schema_names.items()}
                    descriptions = {
                        name_substitutions.get(name, name): description for name, description in descriptions.items()
                    }
                sync_old_schemas_with_new_schemas(
                    schema_names,
                    source_id=str(updated_source.id),
                    team_id=instance.team_id,
                    descriptions=descriptions,
                )
                # Direct call on the engine adapter (not the source hook) so tests mocking
                # `SourceRegistry.get_source` still exercise the real DataWarehouseTable rebuild.
                if engine is not None:
                    engine.reconcile_schemas(
                        source=updated_source, source_schemas=discovered_schemas, team_id=instance.team_id
                    )

            schemas = list(
                ExternalDataSchema.objects.filter(team_id=instance.team_id, source_id=updated_source.id)
                .exclude(deleted=True)
                # This is the update() response path, which serializes the full column shape
                # (include_columns=True) — building columns reads table.credential.access_key per schema,
                # so keep the credential joined here to avoid an N+1.
                .select_related("table__credential", "table__external_data_source")
                .order_by("name")
            )
            # `get_status`/`get_latest_error` derive the active/errored subset from this prefetch, so no
            # separate `active_schemas` query is needed.
            updated_source_any = cast(Any, updated_source)
            updated_source_any._prefetched_objects_cache = {"schemas": schemas}

        return updated_source


class ExternalDataSourceCreateSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type (e.g. 'Postgres', 'Stripe').",
    )
    payload = serializers.DictField(
        help_text=(
            "Connection credentials. Keys depend on source_type. Add a 'schemas' array to pick "
            "which tables sync; omit it and every discovered table syncs with default settings."
        ),
    )
    prefix = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Prefix added to the table names PostHog creates in HogQL. Does not filter which tables are imported.",
    )
    description = serializers.CharField(
        max_length=400, required=False, allow_null=True, allow_blank=True, help_text="Human-readable description."
    )
    access_method = serializers.ChoiceField(
        choices=ExternalDataSource.AccessMethod.choices,
        required=False,
        default=ExternalDataSource.AccessMethod.WAREHOUSE,
        help_text="Connection mode: 'warehouse' (import) or 'direct' (live query).",
    )
    created_via = serializers.ChoiceField(
        # `wizard` and `self_driving` are intentionally omitted: they are never accepted from a
        # caller (that would let any client self-label as wizard- or self-driving-created). They
        # are derived server-side by upgrading a machine-injected `mcp` value based on the request
        # transport (the wizard, PostHog Desktop, or the wizard's self-driving program).
        choices=[
            ExternalDataSource.CreatedVia.WEB,
            ExternalDataSource.CreatedVia.API,
            ExternalDataSource.CreatedVia.MCP,
        ],
        required=False,
        default=ExternalDataSource.CreatedVia.API,
        help_text=(
            "Where the request came from: `web` for the in-app UI, `api` for direct API callers, "
            "`mcp` for agent/MCP tool calls. `wizard` and `self_driving` cannot be set directly — "
            "they are derived server-side for wizard- and PostHog Desktop-driven MCP calls. Defaults to `api`."
        ),
    )
    direct_query_enabled = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Whether a synced source should also be live-queryable via direct connection. "
            "Defaults to false; ignored for pure direct-query sources."
        ),
    )
    destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text=(
            "Destinations every table on this source writes to. Set here rather than afterwards, "
            "so the opening sync already carries them. Omit to write to the PostHog warehouse only."
        ),
    )


class SourceSetupSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot').",
    )
    payload = serializers.DictField(
        required=False,
        help_text=(
            "Connection details as flat keys for the source_type (discover required fields with the wizard "
            "tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection "
            "details the user stored via the connect-link page (discover ids with the stored_credentials "
            "endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth "
            "integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). "
            "For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified "
            "RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth "
            "type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' "
            "(http_basic); keep secrets in these auth_* keys, never inline in the manifest. "
            "A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible "
            "sync defaults."
        ),
    )
    prefix = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Prefix added to the table names PostHog creates in HogQL, e.g. 'stripe' produces stripe_charges. "
            "Does not filter which tables are imported. Defaults to the source type."
        ),
    )
    description = serializers.CharField(
        max_length=400, required=False, allow_null=True, allow_blank=True, help_text="Human-readable description."
    )
    direct_query_enabled = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Whether a synced source should also be live-queryable via direct connection. "
            "Defaults to false; ignored for pure direct-query sources."
        ),
    )


class SourceSetupResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the created external data source.")
    webhook = webhook_setup.SourceSetupWebhookSerializer(
        required=False,
        help_text=(
            "Outcome of automatic webhook registration. Only present for sources that support webhooks "
            "(e.g. Stripe) and have webhook-capable tables."
        ),
    )


class ExternalDataSourceCreateResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the created external data source.")


class ExternalDataSourceErrorResponseSerializer(serializers.Serializer):
    message = serializers.CharField(help_text="Human-readable explanation of why the source could not be created.")


class SourcePreviewRequestSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to preview. Only 'Custom' (a user-defined REST API) is supported today.",
    )
    payload = serializers.DictField(
        required=False,
        help_text=(
            "Source config as flat keys. For source_type 'Custom': 'manifest_json' (a stringified RESTAPIConfig "
            "describing client.base_url, auth, and resources) plus the credential for the manifest's declared auth "
            "type — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic). Secrets stay "
            "in these auth_* keys, never inline in the manifest."
        ),
    )
    resource_name = serializers.CharField(
        help_text="Which manifest resource (table) to read a sample from — one of the resource names in manifest_json.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=PREVIEW_DEFAULT_ROWS,
        min_value=1,
        max_value=PREVIEW_MAX_ROWS,
        help_text=f"Maximum sample rows to return (1–{PREVIEW_MAX_ROWS}). Defaults to {PREVIEW_DEFAULT_ROWS}.",
    )


class SourcePreviewColumnSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Column name as it appears in the previewed rows.")
    type = serializers.CharField(
        help_text="JSON type inferred from the first non-null value: string, integer, number, boolean, object, array, or null."
    )


class SourcePreviewResponseSerializer(serializers.Serializer):
    rows = serializers.ListField(
        child=serializers.DictField(),
        help_text="Up to `limit` sample rows, after data_selector extraction — the raw records the sync would ingest.",
    )
    row_count = serializers.IntegerField(help_text="Number of sample rows returned (≤ limit).")
    columns = SourcePreviewColumnSerializer(
        many=True,
        help_text="Columns observed across the sample rows, each with an inferred JSON type.",
    )
    error = serializers.CharField(
        allow_null=True,
        help_text=(
            "Set when the live read failed (e.g. the host was unreachable or returned an auth error); rows is then "
            "empty. Manifest, validation, and SSRF problems return HTTP 400 instead of populating this field."
        ),
    )


class DraftCustomManifestRequestSerializer(serializers.Serializer):
    source_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional human name of the API being connected (e.g. 'Acme CRM'). Used only to orient the model.",
    )
    docs_url = serializers.URLField(
        required=False,
        allow_blank=True,
        help_text="URL of the API documentation to read. Provide this or docs_text; fetched server-side via the egress proxy.",
    )
    docs_text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Raw API documentation or an OpenAPI/Swagger spec, pasted directly. Provide this or docs_url.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Strip first: a whitespace-only docs_text is truthy but useless (it'd fetch an empty URL).
        if not ((attrs.get("docs_url") or "").strip() or (attrs.get("docs_text") or "").strip()):
            raise serializers.ValidationError("Provide either docs_url or docs_text.")
        return attrs


class DraftCustomManifestResponseSerializer(serializers.Serializer):
    draft_status = serializers.ChoiceField(
        choices=["ok", "invalid", "model_error"],
        help_text=(
            "'ok' = a manifest validated; 'invalid' = a manifest was drafted but never validated within the budget "
            "(see error; manifest_json holds the last attempt to fix by hand); 'model_error' = the model returned no "
            "usable JSON."
        ),
    )
    manifest_json = serializers.CharField(
        allow_null=True,
        help_text="The drafted RESTAPIConfig manifest as a JSON string (non-secret), or null if none was produced.",
    )
    resource_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Names of the resources (tables) the validated manifest exposes. Empty unless draft_status is 'ok'.",
    )
    attempts = serializers.IntegerField(
        help_text="How many draft→validate→repair rounds were run.",
    )
    error = serializers.CharField(
        allow_null=True,
        help_text="The last validation error when draft_status is not 'ok'; null on success.",
    )


class SimpleExternalDataSourceSerializers(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "created_at",
            "created_by",
            "status",
            "source_type",
        ]
        read_only_fields = ["id", "created_by", "created_at", "status", "source_type"]


class ExternalDataSourceSetupMixin(base.ExternalDataSourceViewSetBase):
    def _resolve_stored_credential(self, source_type: str, payload: dict) -> credential_store.ResolvedStoredCredential:
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
            return credential_store.ResolvedStoredCredential(payload=payload, credential=None, error_response=None)
        try:
            credential = PendingSourceCredential.objects.for_team(self.team_id).get(
                id=credential_id, created_by=cast(User, self.request.user), expires_at__gt=timezone.now()
            )
        except (PendingSourceCredential.DoesNotExist, ValueError, TypeError, DjangoValidationError):
            return credential_store.ResolvedStoredCredential(
                payload=payload,
                credential=None,
                error_response=Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"Stored credential '{credential_id}' not found or expired"},
                ),
            )
        if credential.source_type != source_type:
            return credential_store.ResolvedStoredCredential(
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
        return credential_store.ResolvedStoredCredential(
            payload={**payload, **credential.payload}, credential=credential, error_response=None
        )

    @extend_schema(
        request=ExternalDataSourceCreateSerializer,
        responses={201: ExternalDataSourceCreateResponseSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        payload = dict(serializer.validated_data["payload"] or {})

        secret_ref_response = credential_store._unresolved_secret_ref_response(payload)
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
        source = base.SourceRegistry.get_source(source_type_model)
        if not is_direct_query and not source.supports_scheduled_sync:
            return Response(
                ExternalDataSourceErrorResponseSerializer(
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
            payload.get("cdc_enabled", False) and cdc_adapter is not None and base.is_cdc_enabled_for_team(self.team)
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
                base.capture_exception(
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
                    with base.cdc_pg_connection(new_source_model) as conn:
                        for db_schema, cdc_table_names in cdc_table_names_by_schema.items():
                            queried_pks = base.get_primary_key_columns(conn, db_schema, list(cdc_table_names))
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
                base.logger.exception(
                    "Could not attach destinations to a new source",
                    exc_info=e,
                    source_id=new_source_model.pk,
                )

        # Create all sync schedules over a single shared Temporal connection. Creating them
        # one call at a time reconnects to Temporal on every iteration, which does not scale
        # to sources with thousands of schemas (e.g. a Slack workspace with thousands of
        # channels).
        try:
            schedule_errors = base.bulk_create_external_data_job_schedules(
                [(active_schema, active_schema.should_sync) for active_schema in active_schemas]
            )
            for schema_id, schedule_error in schedule_errors:
                # The source model was already created, so a partial schedule failure
                # shouldn't fail the request — log each failure and carry on.
                base.logger.exception(
                    "Could not trigger external data job",
                    exc_info=schedule_error,
                    schema_id=schema_id,
                )
        except Exception as e:
            base.logger.exception("Could not trigger external data job", exc_info=e)

        # Per-source schema discovery schedule. Runs every 6h so newly added
        # upstream resources (Slack channels, Postgres tables, …) get picked up
        # without re-discovering on every per-schema sync tick. Direct-query
        # sources resolve schemas at query time, so they opt out of all
        # background sync — including this discovery cadence.
        if new_source_model.supports_scheduled_sync:
            try:
                base.sync_discover_schemas_schedule(new_source_model, create=True)
            except Exception as e:
                base.logger.exception("Could not create schema discovery schedule", exc_info=e)

        # Start CDC extraction schedule if any CDC schemas are active
        if cdc_enabled:
            try:
                base.sync_cdc_extraction_schedule(new_source_model, create=True)
                base.ensure_cdc_slot_cleanup_schedule()
            except Exception as e:
                base.logger.exception("Could not create CDC schedules", exc_info=e)

        if new_source_model.revenue_analytics_config_safe.enabled:
            managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team,
                kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
            )
            managed_viewset.sync_views()
            base.ensure_person_join(self.team.pk, new_source_model.prefix)

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
        source = base.SourceRegistry.get_source(source_type)
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
                base.capture_exception(e)

        # Best-effort external cleanup — soft-deletes are already committed
        latest_running_job = (
            ExternalDataJob.objects.filter(pipeline_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )
        if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
            base.cancel_external_data_workflow(latest_running_job.workflow_id)

        # Delete all schema sync schedules over a single shared Temporal connection — see
        # the matching comment in `create`. Guarded so a Temporal-connect failure here
        # doesn't skip the source/discovery schedule and S3 cleanup below.
        try:
            schedule_delete_errors = base.bulk_delete_external_data_schedules([str(schema.id) for schema in schemas])
            for schema_id, schedule_delete_error in schedule_delete_errors:
                base.capture_exception(schedule_delete_error, {"schema_id": schema_id})
        except Exception as e:
            base.capture_exception(e)

        for schema in schemas:
            try:
                schema.delete_table()
            except Exception as e:
                base.capture_exception(e)

        try:
            base.delete_external_data_schedule(str(instance.id))
        except Exception as e:
            base.capture_exception(e)

        try:
            base.delete_discover_schemas_schedule(str(instance.id))
        except Exception as e:
            base.capture_exception(e)

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
            base.trigger_external_data_source_workflow(instance)

        except temporalio.service.RPCError:
            # if the source schedule has been removed - trigger the schema schedules
            instance.reload_schemas()

        except Exception as e:
            base.logger.exception("Could not trigger external data job", exc_info=e)
            raise

        instance.status = "Running"
        instance.save()
        return Response(status=status.HTTP_200_OK)

    @extend_schema(
        request=SourceSetupSerializer,
        responses={201: SourceSetupResponseSerializer},
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
        serializer = SourceSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        payload = dict(serializer.validated_data.get("payload") or {})

        secret_ref_response = credential_store._unresolved_secret_ref_response(payload)
        if secret_ref_response is not None:
            return secret_ref_response

        resolved = self._resolve_stored_credential(source_type, payload)
        if resolved.error_response is not None:
            return resolved.error_response
        # Mutable local: the CustomSource branch below rewrites payload keys before source creation.
        payload = resolved.payload

        source_type_model = ExternalDataSourceType(source_type)
        source = base.SourceRegistry.get_source(source_type_model)

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
                base.capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
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
            base.capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
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
        request=SourcePreviewRequestSerializer,
        responses={200: SourcePreviewResponseSerializer},
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
        serializer = SourcePreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_type = serializer.validated_data["source_type"]
        source = base.SourceRegistry.get_source(ExternalDataSourceType(source_type))
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
        request=DraftCustomManifestRequestSerializer,
        responses={200: DraftCustomManifestResponseSerializer},
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

        serializer = DraftCustomManifestRequestSerializer(data=request.data)
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
            base.capture_exception(e, {"team_id": self.team_id})
            return Response(
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                data={
                    "message": "Couldn't reach the AI service. If you're running locally, the LLM gateway isn't running — author the manifest manually instead."
                },
            )
        except Exception as e:
            base.capture_exception(e, {"team_id": self.team_id})
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
