from collections import Counter
from typing import Any, cast

from django.conf import settings
from django.db.models import Count, QuerySet

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.warehouse_sources.backend.migration.fivetran.client import (
    FivetranAPIError,
    FivetranAuthError,
    FivetranClient,
    FivetranCredentials,
)
from products.warehouse_sources.backend.migration.flags import is_migration_import_enabled
from products.warehouse_sources.backend.migration.types import (
    ItemProposal,
    ProposedDestination,
    ProposedRowFilter,
    ProposedSchema,
)
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.crawl_warehouse_migration import (
    start_crawl,
)


class ProposedRowFilterSerializer(DataclassSerializer):
    # A plain string: generated clients cannot name enum members like `>=`.
    operator = serializers.CharField(help_text="One of `>`, `>=`, `<`, `<=`, `=`, `!=`, `IN`, `NOT IN`.")

    class Meta:
        dataclass = ProposedRowFilter
        extra_kwargs = {
            "column": {"help_text": "Column the filter applies to."},
            "values": {"help_text": "One value, or several for `IN` and `NOT IN`."},
        }


class ProposedSchemaSerializer(DataclassSerializer):
    row_filters = ProposedRowFilterSerializer(many=True, help_text="Row filters copied from Fivetran.")

    class Meta:
        dataclass = ProposedSchema
        extra_kwargs = {
            "name": {"help_text": "PostHog table name."},
            "should_sync": {"help_text": "Whether the table syncs."},
            "sync_type": {"help_text": "Planned sync type. Null means PostHog picks its default for the table."},
            "disabled_columns": {"help_text": "Columns Fivetran skipped, which PostHog skips too."},
        }


class ProposedDestinationSerializer(DataclassSerializer):
    class Meta:
        dataclass = ProposedDestination
        extra_kwargs = {
            "type": {"help_text": "Destination type, for example `Snowflake` or `BigQuery`."},
            "config": {"help_text": "Non-secret destination settings copied from Fivetran."},
        }


class ItemProposalSerializer(DataclassSerializer):
    schemas = ProposedSchemaSerializer(many=True, help_text="Tables to sync, with their planned sync settings.")
    destination = ProposedDestinationSerializer(
        allow_null=True, help_text="Suggested non-PostHog destination, matched to the Fivetran destination."
    )

    class Meta:
        dataclass = ItemProposal
        extra_kwargs = {
            "source_type": {"help_text": "The PostHog source type this connection becomes."},
            "prefix": {"help_text": "Table name prefix for the new source, taken from the Fivetran connection name."},
            "prefill": {
                "help_text": "Non-secret connection settings copied from Fivetran, keyed by PostHog field name."
            },
            "sync_frequency": {"help_text": "Planned sync frequency, matched to the Fivetran schedule."},
            "sync_time_of_day": {"help_text": "UTC time of day for daily syncs, in HH:MM:SS format."},
        }


class WarehouseMigrationCreateSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(
        choices=WarehouseMigration.Provider.choices, help_text="The ETL vendor to import from."
    )
    api_key = serializers.CharField(write_only=True, help_text="Read-only API key for the vendor account.")
    api_secret = serializers.CharField(write_only=True, help_text="Secret that belongs to the API key.")


class WarehouseMigrationItemCountsSerializer(serializers.Serializer):
    as_is = serializers.IntegerField(help_text="Connections that move to PostHog as they are.")
    caveats = serializers.IntegerField(help_text="Connections that move with differences the user should review.")
    unsupported = serializers.IntegerField(help_text="Connections PostHog cannot create yet.")
    applied = serializers.IntegerField(help_text="Connections already created as PostHog sources.")
    skipped = serializers.IntegerField(help_text="Connections the user chose not to move.")


class WarehouseMigrationSerializer(serializers.ModelSerializer):
    item_counts = serializers.SerializerMethodField(help_text="How many connections fall into each group.")

    class Meta:
        model = WarehouseMigration
        fields = ["id", "provider", "status", "account_name", "crawled_at", "latest_error", "created_at", "item_counts"]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Migration ID."},
            "provider": {"help_text": "The ETL vendor this migration imports from."},
            "status": {
                "help_text": "`pending` and `crawling` mean the vendor account is still being read. "
                "`ready` means the items are planned. `failed` means reading the account failed; see `latest_error`."
            },
            "account_name": {"help_text": "Name of the vendor account."},
            "crawled_at": {"help_text": "When the vendor account was last read."},
            "latest_error": {"help_text": "Why the last read failed, if it did."},
            "created_at": {"help_text": "When the migration was started."},
        }

    @extend_schema_field(WarehouseMigrationItemCountsSerializer)
    def get_item_counts(self, migration: WarehouseMigration) -> dict[str, int]:
        counts: Counter[str] = Counter()
        rows = (
            WarehouseMigrationItem.objects.for_team(migration.team_id)
            .filter(migration=migration)
            .values("status", "verdict")
            .annotate(count=Count("id"))
        )
        for row in rows:
            counts[row["status"]] += row["count"]
            # Verdict counts cover only the connections still left to move.
            if row["status"] not in (WarehouseMigrationItem.Status.APPLIED, WarehouseMigrationItem.Status.SKIPPED):
                counts[row["verdict"]] += row["count"]
        return {key: counts[key] for key in ("as_is", "caveats", "unsupported", "applied", "skipped")}


class WarehouseMigrationItemSerializer(serializers.ModelSerializer):
    caveats = serializers.ListField(
        child=serializers.CharField(), help_text="Differences between Fivetran and PostHog for this connection."
    )
    proposal = serializers.SerializerMethodField(
        help_text="What PostHog creates for this connection. Null when the connection is not supported."
    )

    class Meta:
        model = WarehouseMigrationItem
        fields = [
            "id",
            "vendor_connection_id",
            "vendor_service",
            "name",
            "verdict",
            "caveats",
            "proposal",
            "status",
            "external_data_source_id",
            "error",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Item ID. Pass it to the apply and skip actions."},
            "vendor_connection_id": {"help_text": "The connection ID in the vendor account."},
            "vendor_service": {"help_text": "The vendor's connector type, for example `postgres` or `hubspot`."},
            "name": {"help_text": "The connection name in the vendor account."},
            "verdict": {"help_text": "Whether the connection moves as it is, moves with caveats, or is not supported."},
            "status": {"help_text": "`pending` until the source is created (`applied`) or the user skips it."},
            "external_data_source_id": {"help_text": "The PostHog source created for this connection, if any."},
            "error": {"help_text": "Why the last apply attempt failed, if it did."},
        }

    @extend_schema_field(ItemProposalSerializer(allow_null=True))
    def get_proposal(self, item: WarehouseMigrationItem) -> dict[str, Any] | None:
        if item.proposal is None:
            return None
        return cast(dict[str, Any], ItemProposalSerializer(ItemProposal.from_json(item.proposal)).data)


class WarehouseMigrationConnectLinkSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=WarehouseMigration.Provider.choices, help_text="The ETL vendor.")
    connect_url = serializers.URLField(help_text="Link the user opens to enter their vendor API key in PostHog.")
    instructions = serializers.CharField(help_text="What the agent should tell the user and do next.")


class WarehouseMigrationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Import a team's Fivetran setup and plan the PostHog sources that replace it."""

    scope_object = "external_data_source"
    # Like destinations, a migration spans many sources rather than belonging to one.
    requires_resource_level_access = True
    scope_object_write_actions = ["create", "destroy", "refresh", "skip_item"]
    scope_object_read_actions = ["list", "retrieve", "items", "connect_link"]
    # `.unscoped()` is import-safe; the mixin scopes every request by team_id.
    queryset = WarehouseMigration.objects.unscoped().all()
    serializer_class = WarehouseMigrationSerializer

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not is_migration_import_enabled(self.team):
            raise exceptions.NotFound()

    def safely_get_queryset(self, queryset: QuerySet[WarehouseMigration]) -> QuerySet[WarehouseMigration]:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    @extend_schema(request=WarehouseMigrationCreateSerializer, responses={201: WarehouseMigrationSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = WarehouseMigrationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = FivetranCredentials(
            api_key=serializer.validated_data["api_key"], api_secret=serializer.validated_data["api_secret"]
        )
        try:
            FivetranClient(credentials).get_account_info()
        except FivetranAuthError:
            raise exceptions.ValidationError(
                {"api_key": "Fivetran rejected this key. Check that it is active and can read the account."}
            )
        except FivetranAPIError:
            raise exceptions.ValidationError({"api_key": "Fivetran could not be reached with this key. Try again."})

        migration = WarehouseMigration.objects.for_team(self.team_id).create(
            team_id=self.team_id,
            created_by=cast(User, request.user),
            provider=serializer.validated_data["provider"],
            credentials={"api_key": credentials.api_key, "api_secret": credentials.api_secret},
        )
        self._start_crawl(migration)
        return Response(self.get_serializer(migration).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: WarehouseMigrationSerializer})
    @action(methods=["POST"], detail=True)
    def refresh(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        migration = self.get_object()
        if migration.status in (WarehouseMigration.Status.PENDING, WarehouseMigration.Status.CRAWLING):
            raise exceptions.ValidationError("This migration is already reading the vendor account.")
        migration.status = WarehouseMigration.Status.PENDING
        migration.latest_error = ""
        migration.save(update_fields=["status", "latest_error", "updated_at"])
        self._start_crawl(migration)
        return Response(self.get_serializer(migration).data)

    @extend_schema(responses={200: WarehouseMigrationItemSerializer(many=True)})
    @action(methods=["GET"], detail=True, pagination_class=None)
    def items(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        migration = self.get_object()
        items = (
            WarehouseMigrationItem.objects.for_team(self.team_id)
            .filter(migration=migration)
            .order_by("verdict", "name")
        )
        return Response(WarehouseMigrationItemSerializer(items, many=True).data)

    @extend_schema(
        request=None,
        responses={200: WarehouseMigrationItemSerializer},
        parameters=[OpenApiParameter("item_id", str, OpenApiParameter.PATH, description="Item ID.")],
    )
    @action(methods=["POST"], detail=True, url_path=r"items/(?P<item_id>[^/.]+)/skip")
    def skip_item(self, request: Request, item_id: str, *args: Any, **kwargs: Any) -> Response:
        migration = self.get_object()
        item = WarehouseMigrationItem.objects.for_team(self.team_id).filter(migration=migration, id=item_id).first()
        if item is None:
            raise exceptions.NotFound()
        if item.status == WarehouseMigrationItem.Status.APPLIED:
            raise exceptions.ValidationError("This connection is already a PostHog source.")
        item.status = WarehouseMigrationItem.Status.SKIPPED
        item.save(update_fields=["status", "updated_at"])
        return Response(WarehouseMigrationItemSerializer(item).data)

    @extend_schema(
        responses={200: WarehouseMigrationConnectLinkSerializer},
        parameters=[
            OpenApiParameter(
                "provider",
                str,
                OpenApiParameter.QUERY,
                required=True,
                enum=WarehouseMigration.Provider.values,
                description="The ETL vendor to import from.",
            )
        ],
    )
    @action(methods=["GET"], detail=False)
    def connect_link(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        provider = request.query_params.get("provider")
        if provider not in WarehouseMigration.Provider.values:
            raise exceptions.ValidationError({"provider": "Unknown provider."})
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

    def _start_crawl(self, migration: WarehouseMigration) -> None:
        migration.workflow_id = start_crawl(team_id=self.team_id, migration_id=migration.id)
        migration.save(update_fields=["workflow_id", "updated_at"])
