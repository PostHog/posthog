from typing import Any, cast
from uuid import UUID

from django.conf import settings

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.warehouse_sources.backend.facade import (
    contracts,
    warehouse_migration as migrations,
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


_ITEM_ID = OpenApiParameter("item_id", str, OpenApiParameter.PATH, description="Item ID.")


class WarehouseMigrationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Import a team's Fivetran setup and plan the PostHog sources that replace it."""

    scope_object = "external_data_source"
    # Like destinations, a migration spans many sources rather than belonging to one.
    requires_resource_level_access = True
    scope_object_write_actions = ["create", "destroy", "refresh", "skip_item", "skip_items"]
    scope_object_read_actions = ["list", "retrieve", "items", "connect_link"]
    # A non-UUID id gets a 404 instead of a lookup error.
    lookup_value_regex = _UUID_PATTERN
    pagination_class = PrecountedLimitOffsetPagination

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
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
        return Response(WarehouseMigrationSerializer(migration).data, status=status.HTTP_201_CREATED)

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
        if migration is None:
            raise exceptions.NotFound()
        return Response(WarehouseMigrationSerializer(migration).data)

    @extend_schema(responses={200: WarehouseMigrationItemSerializer(many=True)})
    @action(methods=["GET"], detail=True, pagination_class=None)
    def items(self, request: Request, pk: str, *args: Any, **kwargs: Any) -> Response:
        items = migrations.list_migration_items(self.team_id, UUID(pk))
        if items is None:
            raise exceptions.NotFound()
        return Response(WarehouseMigrationItemSerializer(items, many=True).data)

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

    @validated_request(
        request_serializer=WarehouseMigrationSkipItemsSerializer,
        responses={200: WarehouseMigrationSkipItemsResponseSerializer},
    )
    @action(methods=["POST"], detail=True, url_path="items/skip")
    def skip_items(self, request: ValidatedRequest, pk: str, *args: Any, **kwargs: Any) -> Response:
        """Skip many connections at once, or all but the ones to keep."""
        data = request.validated_data
        result = migrations.skip_migration_items(
            self.team_id, UUID(pk), item_ids=data.get("item_ids"), keep_item_ids=data.get("keep_item_ids")
        )
        if result is None:
            raise exceptions.NotFound()
        return Response(WarehouseMigrationSkipItemsResponseSerializer(result).data)

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
