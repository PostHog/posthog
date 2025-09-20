from rest_framework import serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MessageCategory


class MessageCategorySerializer(serializers.ModelSerializer):
    def validate(self, data):
        if self.instance is None:
            # Ensure key is unique per team for new instances
            if MessageCategory.objects.filter(team_id=self.context["team_id"], key=data["key"], deleted=False).exists():
                raise serializers.ValidationError({"key": "A message category with this key already exists."})
        else:
            if "key" in data and hasattr(self.instance, "key") and data["key"] != self.instance.key:
                raise serializers.ValidationError({"key": "The key field cannot be updated after creation."})
        return data

    class Meta:
        model = MessageCategory
        fields = (
            "id",
            "key",
            "name",
            "description",
            "public_description",
            "category_type",
            "created_at",
            "updated_at",
            "created_by",
            "deleted",
        )
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
            "created_by",
        )

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class MessageCategoryViewSet(
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"

    serializer_class = MessageCategorySerializer
    queryset = MessageCategory.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(
            deleted=False,
        )
