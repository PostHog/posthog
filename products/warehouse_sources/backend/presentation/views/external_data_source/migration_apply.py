"""Create a PostHog source from one planned Fivetran connection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action

from products.warehouse_sources.backend.facade import warehouse_migration as migrations
from products.warehouse_sources.backend.facade.contracts import ClaimedWarehouseMigrationItem, PlannedMigrationSchemas
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.presentation.views.destination_links import EMPTY_SET_MESSAGE

from . import base
from .schema_operations import ExternalDataSourceSchemaOperationsMixin
from .source_setup import ExternalDataSourceCreateCreatedVia, ExternalDataSourceSetupMixin

# Source creation gives every table this cadence, so a plan that matches it needs no second pass.
_CREATED_SYNC_FREQUENCY = "6hour"


class ApplyMigrationItemSerializer(serializers.Serializer):
    item_id = serializers.UUIDField(help_text="The migration item to create a PostHog source for.")
    credential_id = serializers.UUIDField(
        help_text="Stored credential from the source connect page, for the item's PostHog source type."
    )
    prefix = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Table name prefix to use instead of the planned one, for example when the planned one is taken.",
    )
    destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Destinations to write the new source to. Omit to write to the PostHog warehouse.",
    )
    created_via = serializers.ChoiceField(
        choices=ExternalDataSourceCreateCreatedVia.choices,
        default=ExternalDataSource.CreatedVia.API,
        help_text="Where the request came from: `web`, `api`, or `mcp`. Defaults to `api`.",
    )

    def validate_destination_ids(self, destination_ids: list) -> list:
        # Same rule as source creation: an empty list would leave the source syncing nowhere.
        if not destination_ids:
            raise serializers.ValidationError(EMPTY_SET_MESSAGE)
        return destination_ids


class ApplyMigrationItemResponseSerializer(serializers.Serializer):
    source_id = serializers.UUIDField(help_text="The PostHog source created for the item.")
    caveats = serializers.ListField(
        child=serializers.CharField(), help_text="Every difference from the Fivetran connection, including new ones."
    )


class ExternalDataSourceMigrationApplyMixin(ExternalDataSourceSetupMixin, ExternalDataSourceSchemaOperationsMixin):
    @extend_schema(request=ApplyMigrationItemSerializer, responses={201: ApplyMigrationItemResponseSerializer})
    @action(methods=["POST"], detail=False)
    def apply_migration_item(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create the planned PostHog source for one migration item, then set its sync schedule."""
        if not migrations.is_migration_import_enabled(self.team):
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = ApplyMigrationItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        item = migrations.claim_migration_item(self.team_id, data["item_id"], prefix_override=data.get("prefix"))
        if item is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "This item is not supported, already applied, skipped, or being applied right now."},
            )
        if item.recovered_source_id is not None:
            return Response(
                ApplyMigrationItemResponseSerializer(
                    {"source_id": item.recovered_source_id, "caveats": item.caveats}
                ).data,
                status=status.HTTP_201_CREATED,
            )

        planned: PlannedMigrationSchemas | None = None

        def build_schemas(
            source_schemas: list[SourceSchema], permission_errors: Mapping[str, str | None]
        ) -> list[dict]:
            nonlocal planned
            planned = migrations.plan_migration_schemas(item.proposal, source_schemas, permission_errors)
            return planned.schemas

        try:
            response = self._setup_source(
                request,
                source_type=item.source_type,
                payload={"credential_id": str(data["credential_id"])},
                build_schemas=build_schemas,
                prefix=item.prefix,
                description=item.description,
                created_via=data["created_via"],
                destination_ids=data.get("destination_ids"),
                webhook_tables=lambda: planned.planned if planned else (),
            )
        except Exception:
            migrations.fail_migration_item(self.team_id, item.id, "Creating the source failed unexpectedly.")
            raise
        if response.status_code != status.HTTP_201_CREATED:
            message = response.data.get("message") if isinstance(response.data, dict) else None
            migrations.fail_migration_item(self.team_id, item.id, str(message or "Creating the source failed."))
            return response

        source = ExternalDataSource.objects.get(id=response.data["id"], team_id=self.team_id)
        caveats = [*item.caveats, *self._new_caveats(planned)]
        try:
            self._apply_schedule(source, item)
        except Exception as e:
            base.capture_exception(e, {"team_id": self.team_id, "source_id": str(source.id)})
            caveats.append("The source was created, but its sync schedule could not be set. Set it on the source.")

        migrations.finish_migration_item(self.team_id, item.id, source_id=source.id, caveats=caveats)
        return Response(
            ApplyMigrationItemResponseSerializer({"source_id": source.id, "caveats": caveats}).data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _new_caveats(planned: PlannedMigrationSchemas | None) -> list[str]:
        if planned is None:
            return []
        return [
            *(f"PostHog could not find or read the table `{name}`." for name in planned.unavailable),
            *(
                f"`{name}` syncs only through a webhook. It stays off unless PostHog could register the webhook."
                for name in planned.webhook_only
            ),
        ]

    def _apply_schedule(self, source: ExternalDataSource, item: ClaimedWarehouseMigrationItem) -> None:
        # The time of day is already set at creation, and a paused plan has no syncing table.
        if item.start_paused or item.sync_frequency == _CREATED_SYNC_FREQUENCY:
            return
        schemas = ExternalDataSchema.objects.filter(team_id=self.team_id, source=source, should_sync=True)
        updates = [{"id": schema.id, "sync_frequency": item.sync_frequency} for schema in schemas]
        if updates:
            self._apply_schema_updates(source, updates, self.get_serializer_context())
