from typing import Any

from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models.integration import Integration

from products.warehouse_sources.backend.facade.models import ExternalDataDestination

# Which Integration kind holds the credentials for each destination type. A type absent from
# this map needs no integration; the PostHog warehouse is the only such type today.
DESTINATION_INTEGRATION_KINDS: dict[str, tuple[str, ...]] = {
    # Redshift is Postgres-wire, and the aws-redshift kind is itself a PostgreSQL-server
    # integration, so it carries the cluster's host, user and password.
    ExternalDataDestination.Type.REDSHIFT: (Integration.IntegrationKind.AWS_REDSHIFT,),
    ExternalDataDestination.Type.SNOWFLAKE: (Integration.IntegrationKind.SNOWFLAKE,),
    ExternalDataDestination.Type.BIGQUERY: (Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT,),
    ExternalDataDestination.Type.POSTGRES: (Integration.IntegrationKind.POSTGRESQL,),
    ExternalDataDestination.Type.DATABRICKS: (Integration.IntegrationKind.DATABRICKS,),
    ExternalDataDestination.Type.AZURE_BLOB: (Integration.IntegrationKind.AZURE_BLOB,),
    ExternalDataDestination.Type.S3: (
        Integration.IntegrationKind.AWS_S3,
        Integration.IntegrationKind.S3_COMPATIBLE,
    ),
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
        ]
        read_only_fields = ["id", "is_posthog_warehouse", "created_at", "created_by"]

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

        return attrs

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

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Soft-delete, and detach it from everything that syncs to it.

        Runs already in flight keep their own snapshot of the destination, so deleting one
        never strands a run part-way through. The next run of each affected table resolves
        without it.
        """
        instance = self.get_object()
        if instance.is_posthog_warehouse:
            raise ValidationError({"type": "The PostHog warehouse destination cannot be deleted."})

        instance.source_links.all().delete()
        instance.schema_links.all().delete()
        instance.deleted = True
        instance.save(update_fields=["deleted", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
