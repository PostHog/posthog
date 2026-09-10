"""Serializers and endpoints for source schema operations."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from typing import Any, cast

from django.db import connection, transaction

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action
from posthog.permissions import is_service_auth

from products.access_control.backend.facade.user_access_control import access_level_satisfied_for_resource
from products.data_warehouse.backend.facade.api import get_direct_query_engine, get_namespaced_resource_adapter
from products.warehouse_sources.backend.facade.models import (
    ExternalDataSchema,
    ExternalDataSource,
    auto_enable_new_schemas,
    sync_old_schemas_with_new_schemas,
)
from products.warehouse_sources.backend.facade.source_management import (
    AnySource,
    ClickHouseSource,
    Config,
    CustomSource,
    MySQLSource,
    PostgresSource,
    SQLSource,
    build_default_sync_settings,
    new_source_requires_ssl,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.presentation.views.external_data_schema import (
    ExternalDataSchemaSerializer,
    RowFiltersField,
)

from . import base, credential_store, helpers


class ExternalDataSourceBulkUpdateSchemaSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Schema identifier to update.")
    should_sync = serializers.BooleanField(required=False, help_text="Whether the schema should be queryable/synced.")
    sync_type = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=ExternalDataSchema.SyncType.choices,
        help_text="Requested sync mode for the schema (incremental, full_refresh, append, cdc, or xmin).",
    )
    incremental_field = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Incremental cursor field for incremental or append syncs.",
    )
    incremental_field_type = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Type of the incremental cursor field.",
    )
    sync_frequency = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Human-readable sync frequency value.",
    )
    sync_time_of_day = serializers.TimeField(
        required=False,
        allow_null=True,
        help_text="UTC anchor time for scheduled syncs.",
    )
    primary_key_columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="Column names for primary key deduplication.",
    )
    cdc_table_mode = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=["consolidated", "cdc_only", "both"],
        help_text="How CDC-backed tables should be exposed.",
    )
    enabled_columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        allow_empty=True,
        help_text="Columns to sync. Null means sync all columns.",
    )
    row_filters = RowFiltersField(
        required=False,
        allow_null=True,
        help_text="Row-filter predicates ANDed onto the source query. Null/empty means sync all rows.",
    )
    apply_sync_defaults = serializers.BooleanField(
        required=False,
        help_text=(
            "When true and the schema has no sync method configured yet (and this update does not set "
            "one), discover the table on the source and fill in default sync settings: incremental sync "
            "with an auto-selected tracking column where supported, otherwise append, otherwise full "
            "refresh. Ignored for schemas that already have a sync method."
        ),
    )


class ExternalDataSourceBulkUpdateSchemasSerializer(serializers.Serializer):
    schemas = ExternalDataSourceBulkUpdateSchemaSerializer(
        many=True,
        allow_empty=False,
        help_text="Schema updates to apply in a single batch.",
    )


def _validation_error_message(error: ValidationError) -> str:
    # DRF normalizes ValidationError.detail to a list or dict (never a bare string).
    detail = error.detail
    if isinstance(detail, dict):
        return " ".join(f"{field}: {value}" for field, value in detail.items())
    return " ".join(str(item) for item in detail)


class BulkSchemaSaveError(APIException):
    default_code = "bulk_schema_save_failed"

    def __init__(self, failures: dict[str, tuple[str, str]], *, only_validation_errors: bool) -> None:
        # Pure input problems are the caller's to fix (400). A database/infra error is ours and is
        # retryable (503); treat a mix as a server problem so it surfaces as retryable.
        self.status_code = (
            status.HTTP_400_BAD_REQUEST if only_validation_errors else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        reasons = "; ".join(f"{name} ({reason})" for name, reason in failures.values())
        super().__init__(
            detail=(
                f"These schemas in the batch could not be saved: {reasons}. "
                "Any other schemas in the batch were saved successfully — retry the ones listed here."
            )
        )


class ExternalDataSourceSchemaOperationsMixin(base.ExternalDataSourceViewSetBase):
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
        base.logger.debug(
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
            source = base.SourceRegistry.get_source(source_type)
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
            base.logger.info(
                "refresh_schemas fetched from source",
                source_id=str(instance.id),
                schema_count=len(schema_names),
                schema_names=schema_names,
            )
        except Exception as e:
            error_message, is_expected_source_error = helpers._classify_refresh_schemas_error(source, e)
            base.logger.exception(
                "Could not fetch schemas from source",
                exc_info=e,
                source_id=str(instance.id),
                team_id=self.team_id,
                source_type=instance.source_type,
                error_type=type(e).__name__,
                is_expected_source_error=is_expected_source_error,
            )
            if not is_expected_source_error:
                base.capture_exception(
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

        base.logger.debug(
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

    @extend_schema(request=credential_store.DatabaseSchemaRequestSerializer)
    @action(methods=["POST"], detail=False)
    def database_schema(self, request: Request, *arg: Any, **kwargs: Any):
        source_type = request.data.get("source_type", None)

        if source_type is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Missing required parameter: source_type"},
            )

        secret_ref_response = credential_store._unresolved_secret_ref_response(request.data)
        if secret_ref_response is not None:
            return secret_ref_response

        try:
            source_type_model = ExternalDataSourceType(source_type)
        except ValueError:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Unknown source_type '{source_type}'"},
            )
        source = base.SourceRegistry.get_source(source_type_model)
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
                base.capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
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
            base.capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
            endpoint_permissions = {schema.name: None for schema in schemas}

        # Cache the CDC flag once: in non-DEBUG environments this calls posthoganalytics.feature_enabled,
        # which makes a network round-trip per call. With large schema lists (e.g. Slack workspaces with
        # thousands of channels) the per-iteration call inflated the response loop past the 120s gateway.
        cdc_enabled = base.is_cdc_enabled_for_team(self.team)
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

    def _fill_default_sync_settings(
        self,
        source: ExternalDataSource,
        schema_updates: list[dict[str, Any]],
        source_schemas_by_id: dict[uuid.UUID, ExternalDataSchema],
        # nosemgrep: tuple-return-prefer-dataclass -- grandfathered backlog
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
            source_impl = base.SourceRegistry.get_source(ExternalDataSourceType(source.source_type))
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
                base.capture_exception(e)
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
        request=ExternalDataSourceBulkUpdateSchemasSerializer,
        responses={200: ExternalDataSchemaSerializer(many=True)},
    )
    @action(methods=["PATCH"], detail=True)
    def bulk_update_schemas(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source = self.get_object()
        serializer = ExternalDataSourceBulkUpdateSchemasSerializer(data=request.data)
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
                    reason = _validation_error_message(e)
                    base.logger.warning(
                        "bulk_update_schemas validation error during save",
                        source_id=str(source.id),
                        schema_id=str(schema.id),
                    )
                else:
                    only_validation_errors = False
                    reason = "a database error occurred while saving"
                    base.capture_exception(e)
                    base.logger.exception(
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
                base.capture_exception(e)
                base.logger.warning(
                    "bulk_update_schemas saved the schema but its Temporal schedule update failed",
                    source_id=str(source.id),
                    schema_id=str(action_schema.id),
                    exc_info=e,
                )

        # Report save failures first so a schedule-update failure can't mask which schemas didn't
        # save, then fail the request on the schedule-update failure.
        if failed_schemas:
            raise BulkSchemaSaveError(failed_schemas, only_validation_errors=only_validation_errors)
        if post_commit_error is not None:
            raise post_commit_error

        return Response(
            ExternalDataSchemaSerializer(updated_schemas, many=True, context=serializer_context).data,
            status=status.HTTP_200_OK,
        )
