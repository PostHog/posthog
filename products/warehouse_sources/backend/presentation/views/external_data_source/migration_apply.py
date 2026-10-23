"""Create a PostHog source from one planned Fivetran connection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Q

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.utils import action

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.migration.apply import build_planned_schemas
from products.warehouse_sources.backend.migration.flags import is_migration_import_enabled
from products.warehouse_sources.backend.migration.types import ItemProposal
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigrationItem

from . import base
from .schema_operations import ExternalDataSourceSchemaOperationsMixin
from .source_setup import ExternalDataSourceSetupMixin

_APPLICABLE = (WarehouseMigrationItem.Status.PENDING, WarehouseMigrationItem.Status.FAILED)


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
        choices=ExternalDataSource.CreatedVia.choices,
        default=ExternalDataSource.CreatedVia.API,
        help_text="Where the request came from.",
    )


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
        if not is_migration_import_enabled(self.team):
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = ApplyMigrationItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        items = WarehouseMigrationItem.objects.for_team(self.team_id).filter(id=data["item_id"])
        # A conditional claim, so two requests for one item cannot both create a source.
        claimed = (
            items.filter(status__in=_APPLICABLE)
            .exclude(Q(proposal__isnull=True))
            .update(status=WarehouseMigrationItem.Status.APPLYING)
        )
        if not claimed:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "This item is not supported, already applied, skipped, or being applied right now."},
            )
        item = items.get()
        proposal = ItemProposal.from_json(item.proposal or {})

        unavailable: list[str] = []

        def build_schemas(
            source_schemas: list[SourceSchema], permission_errors: Mapping[str, str | None]
        ) -> list[dict]:
            planned = build_planned_schemas(proposal, source_schemas, permission_errors)
            unavailable.extend(planned.unavailable)
            return planned.schemas

        try:
            response = self._setup_source(
                request,
                source_type=proposal.source_type,
                payload={"credential_id": str(data["credential_id"])},
                build_schemas=build_schemas,
                prefix=data.get("prefix", proposal.prefix) or None,
                description=f"Imported from the Fivetran connection {item.name}.",
                created_via=data["created_via"],
                destination_ids=data.get("destination_ids"),
            )
        except Exception:
            self._fail(item, "Creating the source failed unexpectedly.")
            raise
        if response.status_code != status.HTTP_201_CREATED:
            message = response.data.get("message") if isinstance(response.data, dict) else None
            self._fail(item, str(message or "Creating the source failed."))
            return response

        source = ExternalDataSource.objects.get(id=response.data["id"], team_id=self.team_id)
        caveats = [*item.caveats, *(f"PostHog could not find or read the table `{name}`." for name in unavailable)]
        try:
            self._apply_schedule(source, proposal)
        except Exception as e:
            base.capture_exception(e, {"team_id": self.team_id, "source_id": str(source.id)})
            caveats.append("The source was created, but its sync schedule could not be set. Set it on the source.")

        item.status = WarehouseMigrationItem.Status.APPLIED
        item.external_data_source_id = source.id
        item.caveats = caveats
        item.error = ""
        item.save(update_fields=["status", "external_data_source_id", "caveats", "error", "updated_at"])
        return Response(
            ApplyMigrationItemResponseSerializer({"source_id": source.id, "caveats": caveats}).data,
            status=status.HTTP_201_CREATED,
        )

    def _apply_schedule(self, source: ExternalDataSource, proposal: ItemProposal) -> None:
        schedule: dict[str, Any] = {"sync_frequency": proposal.sync_frequency}
        if proposal.sync_time_of_day:
            schedule["sync_time_of_day"] = proposal.sync_time_of_day
        schemas = ExternalDataSchema.objects.filter(team_id=self.team_id, source=source, should_sync=True)
        updates = [{"id": schema.id, **schedule} for schema in schemas]
        if updates:
            self._apply_schema_updates(source, updates)

    @staticmethod
    def _fail(item: WarehouseMigrationItem, error: str) -> None:
        item.status = WarehouseMigrationItem.Status.FAILED
        item.error = error
        item.save(update_fields=["status", "error", "updated_at"])
