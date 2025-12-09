from typing import Any, cast

from django.db import transaction
from django.utils.text import slugify

from loginas.utils import is_impersonated_session
from nanoid import generate
from rest_framework import filters, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.feature_flag import FeatureFlagSerializer, MinimalFeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import TemporaryTokenAuthentication
from posthog.constants import PRODUCT_TOUR_TARGETING_FLAG_PREFIX
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.user import User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.product_tours.backend.models import ProductTour


class ProductTourSerializer(serializers.ModelSerializer):
    """Read-only serializer for ProductTour."""

    internal_targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    feature_flag_key = serializers.SerializerMethodField()

    class Meta:
        model = ProductTour
        fields = [
            "id",
            "name",
            "description",
            "internal_targeting_flag",
            "feature_flag_key",
            "content",
            "start_date",
            "end_date",
            "created_at",
            "created_by",
            "updated_at",
            "archived",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]

    def get_feature_flag_key(self, tour: ProductTour) -> str | None:
        if tour.internal_targeting_flag:
            return tour.internal_targeting_flag.key
        return None


class ProductTourSerializerCreateUpdateOnly(serializers.ModelSerializer):
    """Serializer for creating and updating ProductTour."""

    internal_targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ProductTour
        fields = [
            "id",
            "name",
            "description",
            "internal_targeting_flag",
            "content",
            "start_date",
            "end_date",
            "created_at",
            "created_by",
            "updated_at",
            "archived",
        ]
        read_only_fields = ["id", "internal_targeting_flag", "created_at", "created_by", "updated_at"]

    def validate_content(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Content must be an object")
        return value

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        team = self.context["get_team"]()

        validated_data["team"] = team
        validated_data["created_by"] = request.user

        instance = super().create(validated_data)

        # Create internal targeting flag
        self._create_internal_targeting_flag(instance)

        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        # Update internal targeting flag if start_date or end_date changed
        start_date_changed = "start_date" in validated_data and validated_data["start_date"] != instance.start_date
        end_date_changed = "end_date" in validated_data and validated_data["end_date"] != instance.end_date
        archived_changed = "archived" in validated_data and validated_data["archived"] != instance.archived

        instance = super().update(instance, validated_data)

        if start_date_changed or end_date_changed or archived_changed:
            self._update_internal_targeting_flag_state(instance)

        return instance

    def _create_internal_targeting_flag(self, instance: ProductTour) -> None:
        """Create the internal targeting flag for a product tour."""
        random_id = generate("0123456789abcdef", 8)
        flag_key = f"{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}{slugify(instance.name)}-{random_id}"

        # Filter conditions: exclude users who have completed or dismissed the tour
        tour_key = str(instance.id)
        filters = {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": [
                        {
                            "key": f"$product_tour_completed/{tour_key}",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                        {
                            "key": f"$product_tour_dismissed/{tour_key}",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                    ],
                }
            ]
        }

        flag_data = {
            "key": flag_key,
            "name": f"Product Tour: {instance.name}",
            "filters": filters,
            "active": bool(instance.start_date) and not instance.archived,
            "creation_context": "product_tours",
        }

        # Use self.context to pass through project_id and other context
        flag_serializer = FeatureFlagSerializer(
            data=flag_data,
            context=self.context,
        )
        flag_serializer.is_valid(raise_exception=True)
        flag = flag_serializer.save()

        instance.internal_targeting_flag = flag
        instance.save(update_fields=["internal_targeting_flag"])

    def _update_internal_targeting_flag_state(self, instance: ProductTour) -> None:
        """Update the internal targeting flag active state based on tour state."""
        flag = instance.internal_targeting_flag
        if not flag:
            return

        should_be_active = bool(instance.start_date) and not instance.archived
        if flag.active != should_be_active:
            flag.active = should_be_active
            flag.save(update_fields=["active"])


class ProductTourViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "product_tour"
    queryset = ProductTour.objects.select_related("internal_targeting_flag", "created_by").all()
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "description"]
    authentication_classes = [TemporaryTokenAuthentication]

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.request.method in ("POST", "PATCH"):
            return ProductTourSerializerCreateUpdateOnly
        return ProductTourSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id)

    def perform_destroy(self, instance: ProductTour) -> None:
        """Soft delete: archive the tour instead of deleting."""
        # Delete the internal targeting flag
        if instance.internal_targeting_flag:
            instance.internal_targeting_flag.delete()
            instance.internal_targeting_flag = None

        instance.archived = True
        instance.save(update_fields=["archived", "internal_targeting_flag", "updated_at"])

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, self.request.user),
            was_impersonated=is_impersonated_session(self.request),
            item_id=str(instance.id),
            scope="ProductTour",
            activity="deleted",
            detail=Detail(name=instance.name),
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=204)
