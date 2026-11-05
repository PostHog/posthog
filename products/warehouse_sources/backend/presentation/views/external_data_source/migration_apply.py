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
from products.warehouse_sources.backend.facade.contracts import (
    MigrationTableOverride,
    PlannedMigrationSchemas,
    WarehouseMigrationEmptySourceError,
    WarehouseMigrationTableOverrideError,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.presentation.views.destination_links import EMPTY_SET_MESSAGE

from .schema_operations import ExternalDataSourceSchemaOperationsMixin
from .source_setup import ExternalDataSourceCreateCreatedVia, ExternalDataSourceSetupMixin


class MigrationTableOverrideSerializer(serializers.Serializer):
    vendor_table = serializers.CharField(
        help_text="A Fivetran table from the item: a planned table's `vendor_table`, or one of `unmatched_tables`."
    )
    posthog_table = serializers.CharField(
        allow_null=True,
        help_text="The PostHog table to sync it as. Null leaves the table out.",
    )


class ApplyMigrationItemSerializer(serializers.Serializer):
    item_id = serializers.UUIDField(help_text="The migration item to create a PostHog source for.")
    credential_id = serializers.UUIDField(
        help_text="Stored credential from the source connect page, for the item's PostHog source type."
    )
    prefix = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text="Table name prefix to use instead of the planned one, for example when the planned one is taken.",
    )
    destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Destinations to write the new source to. Omit to write to the PostHog warehouse.",
    )
    table_overrides = MigrationTableOverrideSerializer(
        many=True,
        required=False,
        help_text="Changes to the planned tables that the user confirmed: rename an inferred pair, map an unmatched "
        "table, or leave a table out.",
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
    # Declared so an action can turn it on: DRF only accepts action kwargs that name a class attribute.
    requires_resource_level_access = False

    @extend_schema(request=ApplyMigrationItemSerializer, responses={201: ApplyMigrationItemResponseSerializer})
    # Creating a source needs project-wide source access, not a grant on one existing source.
    @action(methods=["POST"], detail=False, requires_resource_level_access=True)
    def apply_migration_item(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create the planned PostHog source for one migration item, then set its sync schedule."""
        if not migrations.is_migration_import_enabled(self.team, getattr(request.user, "distinct_id", None)):
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = ApplyMigrationItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            item = migrations.claim_migration_item(
                self.team_id,
                data["item_id"],
                prefix_override=data.get("prefix"),
                table_overrides=[
                    MigrationTableOverride(vendor_table=o["vendor_table"], posthog_table=o["posthog_table"])
                    for o in data.get("table_overrides", [])
                ],
            )
        except (WarehouseMigrationTableOverrideError, WarehouseMigrationEmptySourceError) as error:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": str(error)})
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
        webhook = response.data.get("webhook") if isinstance(response.data, dict) else None
        webhook_registered = isinstance(webhook, dict) and bool(webhook.get("success"))
        caveats = [*item.caveats, *self._new_caveats(planned, webhook_registered=webhook_registered)]

        migrations.finish_migration_item(self.team_id, item.id, source_id=source.id, caveats=caveats)
        return Response(
            ApplyMigrationItemResponseSerializer({"source_id": source.id, "caveats": caveats}).data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _new_caveats(planned: PlannedMigrationSchemas | None, *, webhook_registered: bool) -> list[str]:
        if planned is None:
            return []
        return [
            *(f"PostHog could not find or read the table `{name}`." for name in planned.unavailable),
            *(
                f"`{name}` syncs only through a webhook, and PostHog could not register one, so it stays off."
                for name in planned.webhook_only
                if not webhook_registered
            ),
            *(
                f"Fivetran skips columns of `{name}` that PostHog would still read, so it stays off."
                for name in planned.kept_off
            ),
        ]
