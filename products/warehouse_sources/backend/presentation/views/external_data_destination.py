from typing import Any, cast

from django.db import transaction
from django.db.models import Q

from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models.integration import Integration
from posthog.permissions import is_service_auth

from products.access_control.backend.facade.user_access_control import access_level_satisfied_for_resource
from products.warehouse_sources.backend.facade.models import ExternalDataDestination, ExternalDataSchema

# Which Integration kind holds the credentials for each destination type. A type absent from
# this map needs no integration; the PostHog warehouse is the only such type today.
#
# Only the types with a writer that has actually run against that warehouse appear here. The
# `Type` enum carries the rest so the column and its data do not change as each one lands, but
# a user cannot select one until its writer ships.
DESTINATION_INTEGRATION_KINDS: dict[str, tuple[str, ...]] = {
    str(ExternalDataDestination.Type.POSTGRES): (str(Integration.IntegrationKind.POSTGRESQL),),
}

# Types a user may create. The PostHog warehouse row is created by the sync itself the first
# time a schema resolves to it, and every team has exactly one, so it is not user-managed.
USER_CREATABLE_TYPES = frozenset(DESTINATION_INTEGRATION_KINDS)


class ExternalDataDestinationSerializer(serializers.ModelSerializer):
    type = serializers.ChoiceField(
        choices=ExternalDataDestination.Type.choices,
        help_text="Where synced rows are written. The PostHog warehouse is managed for you, so you cannot create one here.",
    )
    name = serializers.CharField(
        max_length=400, help_text="Human-readable name shown when picking destinations for a source or table."
    )
    config = serializers.JSONField(
        required=False,
        help_text=(
            "Settings for this destination: target database, schema or dataset, bucket and prefix, file "
            "format. Credentials are not stored here. They live on the linked integration."
        ),
    )
    integration = TeamScopedPrimaryKeyRelatedField(
        queryset=Integration.objects.all(),
        required=False,
        allow_null=True,
        help_text="Integration holding this destination's credentials. Required for every type except the PostHog warehouse.",
    )
    is_posthog_warehouse = serializers.BooleanField(
        read_only=True, help_text="Whether this is the managed PostHog warehouse destination."
    )

    class Meta:
        model = ExternalDataDestination
        fields = [
            "id",
            "type",
            "name",
            "config",
            "integration",
            "is_posthog_warehouse",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = ["id", "is_posthog_warehouse", "created_at", "created_by", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        destination_type = attrs.get("type", getattr(self.instance, "type", None))

        if destination_type not in USER_CREATABLE_TYPES:
            raise ValidationError(
                {"type": "PostHog warehouse destinations are managed for you. Pick a different type."}
            )

        integration = attrs.get("integration", getattr(self.instance, "integration", None))
        if integration is None:
            raise ValidationError(
                {
                    "integration": (
                        f"{destination_type} destinations need an integration. Add one with your "
                        f"{destination_type} credentials, then try again."
                    )
                }
            )

        allowed_kinds = DESTINATION_INTEGRATION_KINDS[destination_type]
        if integration.kind not in allowed_kinds:
            expected = " or ".join(f"'{kind}'" for kind in allowed_kinds)
            raise ValidationError({"integration": f"A {destination_type} destination needs a {expected} integration."})

        if self.instance is not None:
            self._reject_retargeting(attrs)

        return attrs

    # Where a destination points is fixed once it exists. Everything already synced sits at the
    # current server and schema, so repointing one strands that data and needs a full resync of
    # every table that syncs there. A second destination is the supported way to write elsewhere.
    RETARGETING_FIELDS = ("database", "schema")

    def _reject_retargeting(self, attrs: dict[str, Any]) -> None:
        assert self.instance is not None
        if "integration" in attrs and attrs["integration"] != self.instance.integration:
            raise ValidationError(
                {
                    "integration": (
                        "A destination keeps the connection it was created with. Add a second "
                        "destination for the other server."
                    )
                }
            )

        if "config" not in attrs:
            return

        current = self.instance.config or {}
        incoming = attrs["config"] or {}
        for field in self.RETARGETING_FIELDS:
            if field in incoming and incoming[field] != current.get(field):
                raise ValidationError(
                    {
                        "config": (
                            f"A destination keeps the {field} it was created with. Add a second "
                            f"destination for the other {field}."
                        )
                    }
                )

    def create(self, validated_data: dict[str, Any]) -> ExternalDataDestination:
        request = self.context["request"]
        return ExternalDataDestination.objects.for_team(self.context["get_team"]().pk).create(
            team_id=self.context["get_team"]().pk,
            created_by=request.user,
            **validated_data,
        )


class ExternalDataDestinationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Manage where warehouse sources write their synced rows.

    A destination can be attached to several sources, or to a single table on a source.
    Credentials come from an integration, so one connection can be reused across syncs.
    """

    scope_object = "external_data_source"
    # `ExternalDataDestination` has no `model_to_resource` mapping, so object-level RBAC
    # (`check_access_level_for_object`) is a no-op for it and every request would otherwise
    # fall through to "has specific access to *any* external_data_source object", letting a
    # user with narrow write access to one source manage every destination on the team. A
    # destination is shared across sources and tables rather than owned by one of them, so
    # there is no single object to check specific access against here; require resource-level
    # access to `external_data_source` instead.
    requires_resource_level_access = True
    # `.unscoped()` is import-safe (the fail-closed manager raises on `.all()` without team
    # context); the mixin scopes every request by team_id.
    queryset = ExternalDataDestination.objects.unscoped().exclude(deleted=True)
    serializer_class = ExternalDataDestinationSerializer
    ordering = "name"

    def safely_get_queryset(self, queryset: Any) -> Any:
        return queryset.filter(team_id=self.team_id).order_by(self.ordering)

    def _assert_can_mutate(self, instance: ExternalDataDestination) -> None:
        """Per-table gate for changing or deleting a shared destination.

        `requires_resource_level_access` only proves editor access to *some* source; a
        destination is wired to every table on each source it's linked to (directly, or
        through a schema-level override), and a table can be locked below that resource-level
        grant. Changing the destination's integration/config, or deleting it outright, reroutes
        every one of those tables' next sync, so this mirrors
        `ExternalDataSourceViewSet._assert_can_write_schemas` — the same gate a source-level
        destination change goes through — rather than trusting the coarser resource check alone.
        """
        if is_service_auth(self.request):
            return

        source_ids = {link.source_id for link in instance.source_links.filter(enabled=True)}
        direct_schema_ids = {link.schema_id for link in instance.schema_links.filter(enabled=True)}
        schemas = list(
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(team_id=self.team_id)
            .filter(Q(source_id__in=source_ids) | Q(id__in=direct_schema_ids))
            .select_related("table")
        )

        uac = self.user_access_control
        for schema in schemas:
            level = uac.get_user_access_level(schema.table or schema.source)
            if level is None or not access_level_satisfied_for_resource("warehouse_table", level, "editor"):
                raise PermissionDenied("You do not have editor access to every table wired to this destination.")

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        # `.instance` is `Any | None` on the base serializer type, but `update`/`partial_update`
        # always construct this viewset's serializer with the existing instance to update.
        self._assert_can_mutate(cast(ExternalDataDestination, serializer.instance))
        super().perform_update(serializer)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Soft-delete, and detach it from everything that syncs to it.

        Runs already in flight keep their own snapshot of the destination, so deleting one
        never strands a run part-way through. The next run of each affected table resolves
        without it.
        """
        instance = self.get_object()
        if instance.is_posthog_warehouse:
            raise ValidationError({"type": "The PostHog warehouse destination cannot be deleted."})
        self._assert_can_mutate(instance)

        # One edit, so one transaction: detaching without the soft delete leaves a live
        # destination nothing points at, and the reverse leaves links to a deleted one.
        with transaction.atomic():
            instance.source_links.all().delete()
            instance.schema_links.all().delete()
            instance.deleted = True
            instance.save(update_fields=["deleted", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
