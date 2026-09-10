"""Endpoints for change data capture."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from drf_spectacular.utils import OpenApiResponse, extend_schema
from psycopg import OperationalError
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.api.utils import action

from products.data_warehouse.backend.facade.api import delete_cdc_extraction_schedule
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.facade.source_management import (
    DEFAULT_LAG_CRITICAL_THRESHOLD_MB,
    DEFAULT_LAG_WARNING_THRESHOLD_MB,
    CDCRepairError,
    CDCRepairInProgress,
    CDCSourceAdapter,
    PostgresSource,
    SSLRequiredError,
    get_cdc_adapter,
    repair_cdc_source,
    source_type_supports_cdc,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

from . import base


class ExternalDataSourceCDCMixin(base.ExternalDataSourceViewSetBase):
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
        base.logger.info(
            "Setting up CDC resources for source",
            source_id=str(source_model.pk),
            source_type=source_model.source_type,
            management_mode=management_mode,
        )

        resource_fields, error = adapter.setup_resources(source_model, payload)
        if error is not None:
            base.logger.warning(
                "CDC resource setup failed",
                source_id=str(source_model.pk),
                source_type=source_model.source_type,
                management_mode=management_mode,
                error=error,
            )
            return error

        base.logger.info(
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
        source_impl = base.SourceRegistry.get_source(ExternalDataSourceType(source_type))
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
            base.capture_exception(e, {"source_type": source_type, "team_id": self.team_id})
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
            base.capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
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

        if not base.is_cdc_enabled_for_team(self.team):
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
            base.capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
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
        # picks sync_type=cdc per schema afterward), so `base.sync_cdc_extraction_schedule` is a
        # no-op here — the extraction schedule is authoritatively (re)created when a schema is
        # switched to CDC. A failure here therefore can't leave a "CDC on, never runs" state:
        # the slot + config are valid and the schedule self-heals on the first CDC schema
        # toggle. Surface failures (capture, not just log) and flag them in the response.
        schedules_ok = True
        try:
            base.sync_cdc_extraction_schedule(instance, create=True)
            base.ensure_cdc_slot_cleanup_schedule()
        except Exception as e:
            schedules_ok = False
            base.logger.exception("Could not create CDC schedules after enable_cdc", exc_info=e)
            base.capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})

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
                base.cancel_external_data_workflow(running_job.workflow_id)
            except Exception as e:
                base.capture_exception(e, {"source_id": str(instance.id), "workflow_id": running_job.workflow_id})

        # Generic schedule teardown: schedule lives on our side, independent of engine.
        try:
            delete_cdc_extraction_schedule(str(instance.id))
        except Exception:
            base.logger.exception("Failed to delete CDC extraction schedule", extra={"source_id": str(instance.id)})

        # Engine-side teardown: best-effort, never blocks the disable.
        try:
            adapter.cleanup_resources(instance)
        except Exception as e:
            base.logger.exception("Failed engine-side CDC cleanup during disable_cdc", exc_info=e)
            base.capture_exception(e, {"source_id": str(instance.id)})

        # Drop each schema's S3 change buffer: the shadow lane's files are raw customer
        # change data with no consumer once CDC is off, and nothing else expires them.
        for schema_id in cdc_schema_ids:
            base.purge_buffer_prefix(instance.team_id, str(schema_id), base.logger)

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
            base.capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
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
            base.capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
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
            base.sync_cdc_extraction_schedule(instance)
            base.unpause_cdc_extraction_schedule(str(instance.id))
        except Exception as e:
            base.capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
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
                base.capture_exception(e, {"source_id": str(instance.id), "team_id": self.team_id})
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not connect to source to read CDC status: {e}"},
            )

        # Paused-but-slot-intact means a non-retryable failure stopped the schedule; the UI offers
        # Resume (vs Repair) so the user can restart without a full re-sync. Best-effort: a Temporal
        # hiccup must not 500 this otherwise DB-only status read, so degrade to not-paused.
        try:
            schedule_paused = base.is_cdc_extraction_schedule_paused(str(instance.id))
        except Exception:
            base.logger.warning("cdc_status_schedule_paused_lookup_failed", source_id=str(instance.id), exc_info=True)
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
