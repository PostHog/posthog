from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team.team import Team
from posthog.products import Products
from posthog.schema_enums import ProductKey

from products.growth.backend.models import ProductPushCampaign
from products.growth.backend.product_push.selection import PUSH_PRODUCT_PATHS, project_uses_product


class ProductPushCampaignSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(
        read_only=True,
        help_text="Campaign id. Stable for the campaign's lifetime — key per-user dismissal state on it.",
    )
    product_key = serializers.CharField(
        read_only=True,
        help_text="ProductKey value of the product being pushed (e.g. 'session_replay').",
    )
    product_path = serializers.SerializerMethodField(
        help_text="Sidebar path of the pushed product in the product catalog, for display resolution. "
        "Null when the key maps to no released catalog item.",
    )
    reason_text = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Custom promo copy written by the TAM. Null means the client should use its default copy.",
    )
    started_at = serializers.DateTimeField(read_only=True, help_text="When this campaign started.")
    ends_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When this campaign is planned to end."
    )

    class Meta:
        model = ProductPushCampaign
        fields = ["id", "product_key", "product_path", "reason_text", "started_at", "ends_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_product_path(self, campaign: ProductPushCampaign) -> str | None:
        try:
            product_key = ProductKey(campaign.product_key)
        except ValueError:
            return None
        # Curated mapping first — intent→product inference is ambiguous for
        # several keys (see PUSH_PRODUCT_PATHS). The inference fallback covers
        # TAM-scheduled keys outside the push lists.
        curated_path = PUSH_PRODUCT_PATHS.get(product_key)
        if curated_path is not None:
            return curated_path
        products = Products.get_products_by_intent(product_key)
        return products[0].path if products else None


class ProductPushCampaignViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Read-only view of an organization's product push campaign state.

    The organization_id parent lookup scopes the queryset; org membership is
    enforced by the mixin's default permissions.
    """

    scope_object = "INTERNAL"
    serializer_class = ProductPushCampaignSerializer
    queryset = ProductPushCampaign.objects.all()

    @extend_schema(
        description="The organization's currently active product push campaign. 204 when no campaign is "
        "active, or when the given project already uses the campaign's product.",
        parameters=[
            OpenApiParameter(
                name="team_id",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Team id of the project the caller is viewing. When that project already uses "
                "the campaign's product, the response is 204 so the promo isn't shown there.",
            )
        ],
        responses={200: ProductPushCampaignSerializer, 204: None, 404: None},
    )
    @action(detail=False, methods=["GET"])
    def active(self, request: Request, **kwargs) -> Response:
        campaign = self.get_queryset().filter(status=ProductPushCampaign.Status.ACTIVE).order_by("-started_at").first()
        if campaign is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        team_id_param = request.query_params.get("team_id")
        if team_id_param is not None:
            try:
                team_id = int(team_id_param)
            except ValueError:
                raise ValidationError({"team_id": "Must be an integer team id."})
            team = Team.objects.filter(id=team_id, organization=self.organization).only("id", "project_id").first()
            if team is None or not self.user_access_control.check_access_level_for_object(team, "member"):
                raise NotFound({"team_id": "Team not found."})
            if project_uses_product(team.project_id, campaign.product_key):
                return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(self.get_serializer(campaign).data)
