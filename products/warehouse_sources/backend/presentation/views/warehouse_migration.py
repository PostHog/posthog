from typing import Any, cast
from uuid import UUID

from django.conf import settings

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.rate_limit import (
    WarehouseMigrationCrawlThrottle,
    WarehouseMigrationUploadStartThrottle,
    WarehouseMigrationUploadThrottle,
)

from products.warehouse_sources.backend.facade import (
    contracts,
    warehouse_migration as migrations,
)
from products.warehouse_sources.backend.presentation.views.external_data_source.migration_apply import (
    MigrationTableOverrideSerializer,
)

_UUID_PATTERN = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
DEFAULT_PAGE_SIZE = 100


class ProposedRowFilterSerializer(serializers.Serializer):
    # A plain string: generated clients cannot name enum members like `>=`.
    operator = serializers.CharField(help_text="One of `>`, `>=`, `<`, `<=`, `=`, `!=`, `IN`, `NOT IN`.")
    column = serializers.CharField(help_text="Column the filter applies to.")
    values = serializers.ListField(
        child=serializers.CharField(), help_text="One value, or several for `IN` and `NOT IN`."
    )


class ProposedSchemaSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="PostHog table name.")
    should_sync = serializers.BooleanField(help_text="Whether the table syncs.")
    sync_type = serializers.CharField(
        allow_null=True, help_text="Planned sync type. Null means PostHog picks its default for the table."
    )
    disabled_columns = serializers.ListField(
        child=serializers.CharField(), help_text="Columns Fivetran skipped, which PostHog skips too."
    )
    row_filters = ProposedRowFilterSerializer(many=True, help_text="Row filters copied from Fivetran.")
    alternative_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Names to try, in order, when the source does not discover a table called `name`.",
    )
    vendor_table = serializers.CharField(
        allow_null=True,
        default=None,
        help_text="The Fivetran table this plan comes from. Apply's `table_overrides` refer to it.",
    )


class TablePairSerializer(serializers.Serializer):
    vendor_table = serializers.CharField(help_text="The Fivetran table.")
    posthog_table = serializers.CharField(help_text="The PostHog table it was paired with.")


class ProposedDestinationSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Destination type, for example `Snowflake` or `BigQuery`.")
    config = serializers.DictField(help_text="Non-secret destination settings copied from Fivetran.")
    vendor_schemas = serializers.ListField(
        child=serializers.CharField(),
        help_text="The schemas Fivetran writes this connection into. Use another schema in the PostHog destination.",
    )


class ItemProposalSerializer(serializers.Serializer):
    source_type = serializers.CharField(help_text="The PostHog source type this connection becomes.")
    prefix = serializers.CharField(
        help_text="Table name prefix for the new source, taken from the Fivetran connection name."
    )
    prefill = serializers.DictField(
        help_text="Non-secret connection settings copied from Fivetran, shaped like the source payload."
    )
    schemas = ProposedSchemaSerializer(
        many=True,
        allow_null=True,
        help_text="Tables to sync, with their planned sync settings. Null means PostHog uses its default tables.",
    )
    sync_frequency = serializers.CharField(help_text="Planned sync frequency, matched to the Fivetran schedule.")
    sync_time_of_day = serializers.CharField(
        allow_null=True, help_text="UTC time of day for daily syncs, in HH:MM:SS format."
    )
    destination = ProposedDestinationSerializer(
        allow_null=True, help_text="Suggested non-PostHog destination, matched to the Fivetran destination."
    )
    start_paused = serializers.BooleanField(
        help_text="Whether every table starts with syncing off, because the connection is paused in Fivetran."
    )
    inferred_tables = TablePairSerializer(
        many=True,
        default=list,
        help_text="Tables that a naming rule paired. Ask the user to confirm each pair before applying.",
    )
    unmatched_tables = serializers.ListField(
        child=serializers.CharField(),
        default=list,
        help_text="Fivetran tables with no PostHog table. Compare them with the source's PostHog tables and "
        "propose one, or leave them out.",
    )
    unused_posthog_tables = serializers.ListField(
        child=serializers.CharField(),
        default=list,
        help_text="The source's PostHog tables that no Fivetran table maps to. Choose from these for the unmatched "
        "tables. Empty when every table matched.",
    )


class WarehouseMigrationCreateSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=migrations.PROVIDER_CHOICES, help_text="The ETL vendor to import from.")
    api_key = serializers.CharField(write_only=True, help_text="Read-only API key for the vendor account.")
    api_secret = serializers.CharField(write_only=True, help_text="Secret that belongs to the API key.")


class WarehouseMigrationStartUploadSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=migrations.PROVIDER_CHOICES, help_text="The ETL vendor to import from.")


MAX_UPLOAD_CONNECTIONS = 25
MAX_UPLOAD_DESTINATIONS = 100


class WarehouseMigrationUploadedConnectionSerializer(serializers.Serializer):
    connection = serializers.DictField(
        help_text="The Fivetran connection details response, unchanged. The `code` and `data` envelope may stay."
    )
    schema_config = serializers.DictField(
        allow_null=True,
        required=False,
        default=None,
        help_text="The Fivetran schema config response for this connection, unchanged. Null when Fivetran has none.",
    )


class WarehouseMigrationUploadConnectionsSerializer(serializers.Serializer):
    account = serializers.DictField(
        allow_null=True,
        required=False,
        default=None,
        help_text="The Fivetran account info response, unchanged. Send it once, with the first upload.",
    )
    destinations = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        max_length=MAX_UPLOAD_DESTINATIONS,
        help_text="Fivetran destination details responses, unchanged. Send them before the connections that use "
        "them, so PostHog reads each connection's sync time in its destination's time zone.",
    )
    connections = serializers.ListField(
        child=WarehouseMigrationUploadedConnectionSerializer(),
        required=False,
        default=list,
        max_length=MAX_UPLOAD_CONNECTIONS,
        help_text=f"At most {MAX_UPLOAD_CONNECTIONS} connections. A connection uploaded again replaces its plan, "
        "unless it is already created in PostHog or skipped.",
    )


class WarehouseMigrationItemCountsSerializer(serializers.Serializer):
    as_is = serializers.IntegerField(help_text="Connections that move to PostHog as they are.")
    caveats = serializers.IntegerField(help_text="Connections that move with differences the user should review.")
    unsupported = serializers.IntegerField(help_text="Connections PostHog cannot create yet.")
    applied = serializers.IntegerField(help_text="Connections already created as PostHog sources.")
    skipped = serializers.IntegerField(help_text="Connections the user chose not to move.")


class WarehouseMigrationSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Migration ID.")
    provider = serializers.ChoiceField(
        choices=migrations.PROVIDER_CHOICES, help_text="The ETL vendor this migration imports from."
    )
    status = serializers.ChoiceField(
        choices=migrations.STATUS_CHOICES,
        help_text="`pending` and `crawling` mean the vendor account is still being read. "
        "`ready` means the items are planned. `failed` means reading the account failed; see `latest_error`.",
    )
    account_name = serializers.CharField(help_text="Name of the vendor account.")
    crawled_at = serializers.DateTimeField(allow_null=True, help_text="When the vendor account was last read.")
    latest_error = serializers.CharField(help_text="Why the last read failed, if it did.")
    created_at = serializers.DateTimeField(help_text="When the migration was started.")
    item_counts = WarehouseMigrationItemCountsSerializer(help_text="How many connections fall into each group.")
    has_vendor_key = serializers.BooleanField(
        help_text="False when an agent uploaded the vendor account. Such a migration cannot be refreshed; "
        "upload the connections again instead."
    )


class WarehouseMigrationCreatorSerializer(serializers.Serializer):
    first_name = serializers.CharField(help_text="First name of the person who prepared the migration.")
    email = serializers.EmailField(help_text="Email of the person who prepared the migration.")


class WarehouseMigrationItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Item ID. Pass it to the apply and skip actions.")
    vendor_connection_id = serializers.CharField(help_text="The connection ID in the vendor account.")
    vendor_service = serializers.CharField(
        help_text="The vendor's connector type, for example `postgres` or `hubspot`."
    )
    name = serializers.CharField(help_text="The connection name in the vendor account.")
    verdict = serializers.ChoiceField(
        choices=migrations.ITEM_VERDICT_CHOICES,
        help_text="Whether the connection moves as it is, moves with caveats, or is not supported.",
    )
    caveats = serializers.ListField(
        child=serializers.CharField(), help_text="Differences between Fivetran and PostHog for this connection."
    )
    proposal = ItemProposalSerializer(
        allow_null=True,
        help_text="What PostHog creates for this connection. Null when the connection is not supported.",
    )
    status = serializers.ChoiceField(
        choices=migrations.ITEM_STATUS_CHOICES,
        help_text="`pending` until the source is created (`applied`) or the user skips it.",
    )
    external_data_source_id = serializers.UUIDField(
        allow_null=True, help_text="The PostHog source created for this connection, if any."
    )
    error = serializers.CharField(help_text="Why the last apply attempt failed, if it did.")
    created_by = WarehouseMigrationCreatorSerializer(
        allow_null=True,
        help_text="Who prepared the migration, and so chose the connection settings in `proposal.prefill`.",
    )


class WarehouseMigrationUploadResponseSerializer(serializers.Serializer):
    items = WarehouseMigrationItemSerializer(many=True, help_text="The planned items for the uploaded connections.")


class WarehouseMigrationSkipItemsSerializer(serializers.Serializer):
    item_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        min_length=1,
        help_text="Items to skip. Pass this or `keep_item_ids`, not both.",
    )
    keep_item_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Items to keep. Every other item is skipped, for example to migrate only one connection.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("item_ids" in attrs) == ("keep_item_ids" in attrs):
            raise serializers.ValidationError("Pass either `item_ids` or `keep_item_ids`.")
        return attrs


class WarehouseMigrationSkipItemsResponseSerializer(serializers.Serializer):
    skipped_item_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="Items that are now skipped, including ones skipped before."
    )
    not_skipped_item_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="Items that stay as they are because they are being created or are already PostHog sources.",
    )


class WarehouseMigrationConnectLinkQuerySerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=migrations.PROVIDER_CHOICES, help_text="The ETL vendor to import from.")


class WarehouseMigrationConnectLinkSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=migrations.PROVIDER_CHOICES, help_text="The ETL vendor.")
    connect_url = serializers.URLField(help_text="Link the user opens to enter their vendor API key in PostHog.")
    instructions = serializers.CharField(help_text="What the agent should tell the user and do next.")


MAX_USAGE_REPORTS = 10_000
# Far above any real table, and small enough that the cost of every report together stays a valid decimal.
MAX_MONTHLY_ROWS = 10**15


class MigrationUsageReportSerializer(serializers.Serializer):
    connection_name = serializers.CharField(
        max_length=400,
        help_text="The Fivetran connection name, which is also its destination schema. "
        "`connection_name` in the Fivetran Platform Connector's `INCREMENTAL_MAR` table.",
    )
    monthly_rows = serializers.IntegerField(
        min_value=0,
        max_value=MAX_MONTHLY_ROWS,
        help_text="Monthly active rows (MAR) Fivetran counted in a typical month, for the table or, without "
        "`table_name`, the whole connection.",
    )
    destination_id = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        default=None,
        help_text="The Fivetran destination (group) id. Needed only when two connections share a name.",
    )
    schema_name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        default=None,
        help_text="The destination schema the table lands in, as `schema_name` in `INCREMENTAL_MAR`.",
    )
    table_name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        default=None,
        help_text="The table. Leave it out when the number covers the whole connection.",
    )


class MigrationCostTableOverrideSerializer(MigrationTableOverrideSerializer):
    item_id = serializers.UUIDField(help_text="The migration item the table belongs to.")


class WarehouseMigrationCostEstimateRequestSerializer(serializers.Serializer):
    usage = serializers.ListField(
        child=MigrationUsageReportSerializer(),
        required=False,
        default=list,
        max_length=MAX_USAGE_REPORTS,
        help_text="Monthly active rows the user reported, per connection or per table. Send it empty to get "
        "`usage_query` and the prices before the user has numbers.",
    )
    table_overrides = serializers.ListField(
        child=MigrationCostTableOverrideSerializer(),
        required=False,
        default=list,
        max_length=MAX_USAGE_REPORTS,
        help_text="The table choices the user confirmed for apply, so the estimate prices the tables apply creates. "
        "Same shape as apply's `table_overrides`, with the item each one belongs to.",
    )


class WarehouseMigrationCostItemSerializer(serializers.Serializer):
    item_id = serializers.UUIDField(help_text="The migration item.")
    name = serializers.CharField(help_text="The Fivetran connection name.")
    source_type = serializers.CharField(help_text="The PostHog source type this connection becomes.")
    confidence = serializers.ChoiceField(
        choices=contracts.WarehouseMigrationCostConfidence.choices,
        help_text="`reported`: every planned table has a reported number and a known sync type. `estimated`: "
        "some numbers were reported, and `notes` say what was assumed. `unknown`: nothing was reported, so "
        "rows and cost are null.",
    )
    monthly_rows = serializers.IntegerField(
        allow_null=True, help_text="Estimated rows PostHog syncs each month after the first sync."
    )
    monthly_cost_usd = serializers.DecimalField(
        max_digits=28,
        decimal_places=2,
        allow_null=True,
        help_text="This connection's share of the monthly cost at list price. Null when rows or prices are unknown.",
    )
    notes = serializers.ListField(
        child=serializers.CharField(), help_text="What the estimate assumed for this connection."
    )


class WarehouseMigrationPriceTierSerializer(serializers.Serializer):
    up_to = serializers.IntegerField(allow_null=True, help_text="Rows a month this tier ends at. Null for the last.")
    unit_amount_usd = serializers.DecimalField(
        max_digits=20, decimal_places=9, help_text="Price per row synced in this tier, in USD."
    )
    flat_amount_usd = serializers.DecimalField(
        max_digits=20, decimal_places=2, help_text="Flat price once usage reaches this tier, in USD."
    )


class WarehouseMigrationCostEstimateSerializer(serializers.Serializer):
    items = WarehouseMigrationCostItemSerializer(
        many=True, help_text="One estimate per connection that moves. Skipped and unsupported ones are left out."
    )
    monthly_rows = serializers.IntegerField(
        help_text="Estimated rows synced each month, across the connections with an estimate. `unknown` ones count "
        "as nothing, so check `unknown_count` before reading this as a total."
    )
    monthly_cost_usd = serializers.DecimalField(
        max_digits=28,
        decimal_places=2,
        allow_null=True,
        help_text="Monthly cost of `monthly_rows` at PostHog's list price, free tier included. Ignores discounts, "
        "credits, and rows the project already syncs. Null when PostHog could not read its prices.",
    )
    reported_count = serializers.IntegerField(help_text="Connections with a `reported` estimate.")
    estimated_count = serializers.IntegerField(help_text="Connections with an `estimated` estimate.")
    unknown_count = serializers.IntegerField(help_text="Connections with no usage reported.")
    free_first_sync_days = serializers.IntegerField(
        help_text="Days after a source is created during which its syncs are free. A first sync that finishes "
        "inside them costs nothing."
    )
    unmatched_usage = MigrationUsageReportSerializer(
        many=True, help_text="Reported usage that matches no connection. Check the names with the user."
    )
    price_tiers = WarehouseMigrationPriceTierSerializer(
        many=True, allow_null=True, help_text="PostHog's list price per row synced, by monthly volume."
    )
    usage_query = serializers.CharField(
        help_text="SQL the user runs on the Fivetran Platform Connector's tables in their warehouse to get "
        "`usage`. Replace `<fivetran_platform_schema>` with that connector's schema, and the date functions "
        "for BigQuery."
    )


_ACTION_THROTTLES: dict[str, type[BaseThrottle]] = {
    "create": WarehouseMigrationCrawlThrottle,
    "refresh": WarehouseMigrationCrawlThrottle,
    "upload": WarehouseMigrationUploadStartThrottle,
    "connections": WarehouseMigrationUploadThrottle,
}

_ITEM_ID = OpenApiParameter("item_id", str, OpenApiParameter.PATH, description="Item ID.")


class WarehouseMigrationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Import a team's Fivetran setup and plan the PostHog sources that replace it."""

    scope_object = "external_data_source"
    # Like destinations, a migration spans many sources rather than belonging to one.
    requires_resource_level_access = True
    scope_object_write_actions = ["create", "destroy", "refresh", "skip_item", "skip_items", "upload", "connections"]
    # The cost estimate is a POST for its body, but it changes nothing.
    scope_object_read_actions = ["list", "retrieve", "items", "item", "connect_link", "cost_estimate"]
    # A non-UUID id gets a 404 instead of a lookup error.
    lookup_value_regex = _UUID_PATTERN
    pagination_class = PrecountedLimitOffsetPagination

    def get_throttles(self) -> list[BaseThrottle]:
        # Appended to the global limits, which do not apply to session callers.
        throttle = _ACTION_THROTTLES.get(self.action or "")
        return [*super().get_throttles(), throttle()] if throttle else super().get_throttles()

    def check_permissions(self, request: Request) -> None:
        super().check_permissions(request)
        # Here, not in initial(), so it runs before the throttles: a user without the flag spends no crawl budget.
        if not migrations.is_migration_import_enabled(self.team, getattr(request.user, "distinct_id", None)):
            raise exceptions.NotFound()

    @extend_schema(responses={200: WarehouseMigrationSerializer(many=True)})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        paginator = cast(PrecountedLimitOffsetPagination, self.paginator)
        page, count = migrations.list_migrations(
            self.team_id, limit=paginator.get_limit(request) or DEFAULT_PAGE_SIZE, offset=paginator.get_offset(request)
        )
        paginator.set_count(count)
        return self.get_paginated_response(WarehouseMigrationSerializer(self.paginate_queryset(page), many=True).data)

    @extend_schema(responses={200: WarehouseMigrationSerializer})
    def retrieve(self, request: Request, pk: str, *args: Any, **kwargs: Any) -> Response:
        migration = migrations.get_migration(self.team_id, UUID(pk))
        if migration is None:
            raise exceptions.NotFound()
        return Response(WarehouseMigrationSerializer(migration).data)

    @validated_request(
        request_serializer=WarehouseMigrationCreateSerializer, responses={201: WarehouseMigrationSerializer}
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        try:
            migration = migrations.create_migration(
                team_id=self.team_id,
                user_id=cast(User, request.user).id,
                provider=data["provider"],
                api_key=data["api_key"],
                api_secret=data["api_secret"],
            )
        except contracts.WarehouseMigrationKeyRejectedError:
            raise exceptions.ValidationError(
                {"api_key": "Fivetran rejected this key. Check that it is active and can read the account."}
            )
        except contracts.WarehouseMigrationVendorUnreachableError:
            raise exceptions.ValidationError({"api_key": "Fivetran could not be reached with this key. Try again."})
        self._report_started(request, migration, origin="api_key")
        return Response(WarehouseMigrationSerializer(migration).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=WarehouseMigrationStartUploadSerializer, responses={201: WarehouseMigrationSerializer}
    )
    @action(methods=["POST"], detail=False)
    def upload(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        """Start a migration that an agent fills with what it reads from the vendor, without a vendor key."""
        migration = migrations.start_migration_upload(
            team_id=self.team_id, user_id=cast(User, request.user).id, provider=request.validated_data["provider"]
        )
        self._report_started(request, migration, origin="agent_upload")
        return Response(WarehouseMigrationSerializer(migration).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=WarehouseMigrationUploadConnectionsSerializer,
        responses={200: WarehouseMigrationUploadResponseSerializer},
    )
    @action(methods=["POST"], detail=True)
    def connections(self, request: ValidatedRequest, pk: str, *args: Any, **kwargs: Any) -> Response:
        """Plan vendor connections an agent read, and add them to an uploaded migration."""
        data = request.validated_data
        try:
            result = migrations.upload_migration_connections(
                self.team_id,
                UUID(pk),
                account=data["account"],
                destinations=data["destinations"],
                connections=[
                    contracts.MigrationConnectionUpload(
                        connection=connection["connection"], schema_config=connection["schema_config"]
                    )
                    for connection in data["connections"]
                ],
            )
        except contracts.WarehouseMigrationHasVendorKeyError:
            raise exceptions.ValidationError("PostHog reads this migration with an API key. Refresh it instead.")
        except contracts.WarehouseMigrationUploadTooLargeError:
            raise exceptions.ValidationError(
                "This Fivetran account is too large to upload through the chat. Start a migration with an API key."
            )
        if result is None:
            raise exceptions.NotFound()
        if result.errors:
            raise exceptions.ValidationError(
                {
                    "connections": f"Saved {len(result.items)} connections. Fix these and upload them again: "
                    + " ".join(result.errors)
                }
            )
        return Response(WarehouseMigrationUploadResponseSerializer(result).data)

    def _report_started(self, request: Request, migration: contracts.WarehouseMigration, *, origin: str) -> None:
        report_user_action(
            cast(User, request.user),
            "warehouse migration started",
            {"migration_id": str(migration.id), "provider": migration.provider, "origin": origin},
            team=self.team,
            request=request,
        )

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: str, *args: Any, **kwargs: Any) -> Response:
        if not migrations.delete_migration(self.team_id, UUID(pk)):
            raise exceptions.NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={200: WarehouseMigrationSerializer})
    @action(methods=["POST"], detail=True)
    def refresh(self, request: Request, pk: str, *args: Any, **kwargs: Any) -> Response:
        try:
            migration = migrations.refresh_migration(self.team_id, UUID(pk))
        except contracts.WarehouseMigrationBusyError:
            raise exceptions.ValidationError("This migration is already reading the vendor account.")
        except contracts.WarehouseMigrationUploadedError:
            raise exceptions.ValidationError(
                "This migration was uploaded by an agent. Upload again, or start one with an API key."
            )
        if migration is None:
            raise exceptions.NotFound()
        return Response(WarehouseMigrationSerializer(migration).data)

    @extend_schema(responses={200: WarehouseMigrationItemSerializer(many=True)})
    @action(methods=["GET"], detail=True)
    def items(self, request: Request, pk: str, *args: Any, **kwargs: Any) -> Response:
        paginator = cast(PrecountedLimitOffsetPagination, self.paginator)
        result = migrations.list_migration_items(
            self.team_id,
            UUID(pk),
            limit=paginator.get_limit(request) or DEFAULT_PAGE_SIZE,
            offset=paginator.get_offset(request),
        )
        if result is None:
            raise exceptions.NotFound()
        page, count = result
        paginator.set_count(count)
        return self.get_paginated_response(
            WarehouseMigrationItemSerializer(self.paginate_queryset(page), many=True).data
        )

    @extend_schema(responses={200: WarehouseMigrationItemSerializer}, parameters=[_ITEM_ID])
    @action(methods=["GET"], detail=True, url_path=rf"items/(?P<item_id>{_UUID_PATTERN})")
    def item(self, request: Request, pk: str, item_id: str, *args: Any, **kwargs: Any) -> Response:
        item = migrations.find_migration_item(self.team_id, UUID(item_id))
        if item is None or item.migration_id != UUID(pk):
            raise exceptions.NotFound()
        return Response(WarehouseMigrationItemSerializer(item).data)

    @extend_schema(request=None, responses={200: WarehouseMigrationItemSerializer}, parameters=[_ITEM_ID])
    @action(methods=["POST"], detail=True, url_path=rf"items/(?P<item_id>{_UUID_PATTERN})/skip")
    def skip_item(self, request: Request, pk: str, item_id: str, *args: Any, **kwargs: Any) -> Response:
        try:
            item = migrations.skip_migration_item(self.team_id, UUID(pk), UUID(item_id))
        except contracts.WarehouseMigrationItemClaimedError:
            raise exceptions.ValidationError("This connection is already being created or is a PostHog source.")
        if item is None:
            raise exceptions.NotFound()
        return Response(WarehouseMigrationItemSerializer(item).data)

    # The single-item skip already uses the generated `items_skip_create` id.
    @extend_schema(operation_id="warehouse_migrations_items_bulk_skip_create")
    @validated_request(
        request_serializer=WarehouseMigrationSkipItemsSerializer,
        responses={200: WarehouseMigrationSkipItemsResponseSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="items/skip")
    def skip_items(self, request: ValidatedRequest, pk: str, *args: Any, **kwargs: Any) -> Response:
        """Skip many connections at once, or all but the ones to keep."""
        data = request.validated_data
        try:
            result = migrations.skip_migration_items(
                self.team_id, UUID(pk), item_ids=data.get("item_ids"), keep_item_ids=data.get("keep_item_ids")
            )
        except contracts.WarehouseMigrationUnknownItemsError as error:
            raise exceptions.ValidationError(str(error))
        if result is None:
            raise exceptions.NotFound()
        return Response(WarehouseMigrationSkipItemsResponseSerializer(result).data)

    @validated_request(
        request_serializer=WarehouseMigrationCostEstimateRequestSerializer,
        responses={200: WarehouseMigrationCostEstimateSerializer},
    )
    @action(methods=["POST"], detail=True)
    def cost_estimate(self, request: ValidatedRequest, pk: str, *args: Any, **kwargs: Any) -> Response:
        """Estimate the monthly rows and cost of moving the connections, from the usage the user reported."""
        data = request.validated_data
        overrides: dict[UUID, list[contracts.MigrationTableOverride]] = {}
        for override in data["table_overrides"]:
            overrides.setdefault(override["item_id"], []).append(
                contracts.MigrationTableOverride(
                    vendor_table=override["vendor_table"], posthog_table=override["posthog_table"]
                )
            )
        try:
            estimate = migrations.estimate_migration_cost(
                self.team_id,
                UUID(pk),
                [contracts.MigrationUsageReport(**report) for report in data["usage"]],
                overrides,
            )
        except (contracts.WarehouseMigrationTableOverrideError, contracts.WarehouseMigrationUnknownItemsError) as error:
            raise exceptions.ValidationError({"table_overrides": str(error)})
        if estimate is None:
            raise exceptions.NotFound()
        report_user_action(
            cast(User, request.user),
            "warehouse migration cost estimated",
            {
                "migration_id": pk,
                "usage_reports": len(data["usage"]),
                "table_overrides": len(data["table_overrides"]),
                "reported_count": estimate.reported_count,
                "estimated_count": estimate.estimated_count,
                "unknown_count": estimate.unknown_count,
                "unmatched_usage_count": len(estimate.unmatched_usage),
                "monthly_rows": estimate.monthly_rows,
                "has_prices": estimate.price_tiers is not None,
            },
            team=self.team,
            request=request,
        )
        return Response(WarehouseMigrationCostEstimateSerializer(estimate).data)

    @validated_request(
        query_serializer=WarehouseMigrationConnectLinkQuerySerializer,
        responses={200: WarehouseMigrationConnectLinkSerializer},
    )
    @action(methods=["GET"], detail=False)
    def connect_link(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        provider = request.validated_query_data["provider"]
        data = {
            "provider": provider,
            "connect_url": f"{settings.SITE_URL}/project/{self.team_id}/data-warehouse/migrate/connect?provider={provider}",
            "instructions": (
                "Share this link with the user. They create a read-only API key in their Fivetran account settings "
                "and enter it on this page. Never ask them to paste the key into the chat. Once they confirm, list "
                "migrations, wait until the newest one is `ready`, then read its items."
            ),
        }
        return Response(WarehouseMigrationConnectLinkSerializer(data).data)
