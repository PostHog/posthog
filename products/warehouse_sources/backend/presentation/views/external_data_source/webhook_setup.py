"""Serializers and endpoints for webhook setup."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action

from products.cdp.backend.facade.api import HogFunctionSerializer
from products.cdp.backend.facade.models import HogFunction
from products.data_warehouse.backend.facade.api import (
    create_and_register_webhook,
    delete_webhook_and_hog_function,
    get_or_create_webhook_hog_function,
    get_webhook_url,
    sync_external_data_job_workflow,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import (
    Config,
    ExternalWebhookInfo,
    SourceSchema,
    WebhookSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

from . import viewset


class SourceSetupWebhookSerializer(serializers.Serializer):
    success = serializers.BooleanField(
        help_text=(
            "Whether the webhook was registered with the external service. When true, webhook-capable tables "
            "(including webhook-only ones) sync via real-time webhooks; when false, tables fall back to the "
            "polling sync defaults and webhook-only tables stay disabled."
        )
    )
    webhook_url = serializers.CharField(
        allow_null=True, help_text="The PostHog endpoint the external service delivers events to."
    )
    error = serializers.CharField(
        allow_null=True, help_text="Why webhook registration failed (e.g. the credentials lack webhook permissions)."
    )
    pending_inputs = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Webhook input names the user still needs to provide (e.g. a signing secret the external API did not "
            "return on create). Submit them via the update_webhook_inputs endpoint."
        ),
    )


class ExternalDataSourceWebhookSetupMixin:
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
            viewset.capture_exception(e, {"source_id": source_id, "team_id": self.team_id})
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
                    viewset.logger.exception(
                        "Could not create sync schedule for webhook schema", exc_info=e, schema_id=str(schema.id)
                    )

        return {
            "success": True,
            "webhook_url": registration.webhook_url,
            "error": None,
            "pending_inputs": list(registration.pending_inputs),
        }

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

    def _webhook_creation_blocked_reason(self, source: WebhookSource, instance: ExternalDataSource) -> str | None:
        """Ask the source whether this connection can never create the provider-side webhook.
        Best-effort: an unparseable config or a source-side failure leaves the button offered,
        which is the behavior before the check existed."""
        if not instance.job_inputs:
            return None
        try:
            return source.webhook_creation_blocked_reason(source.parse_config(instance.job_inputs), self.team_id)
        except Exception as e:
            viewset.capture_exception(e)
            return None

    @action(methods=["GET"], detail=True)
    def webhook_info(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()
        source_type = ExternalDataSourceType(instance.source_type)
        source = viewset.SourceRegistry.get_source(source_type)

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
                viewset.capture_exception(e)

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

    @action(methods=["POST"], detail=True)
    def create_webhook(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        if not instance.job_inputs:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Source has no configuration"},
            )

        source_type = ExternalDataSourceType(instance.source_type)
        source = viewset.SourceRegistry.get_source(source_type)

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
            viewset.capture_exception(e)
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
        source = viewset.SourceRegistry.get_source(source_type)

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
            viewset.capture_exception(e)
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

    @action(methods=["POST"], detail=True)
    def delete_webhook(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSource = self.get_object()

        source_type = ExternalDataSourceType(instance.source_type)
        source = viewset.SourceRegistry.get_source(source_type)

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
            viewset.capture_exception(e)
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
