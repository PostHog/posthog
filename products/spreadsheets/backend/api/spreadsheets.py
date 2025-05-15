from typing import Any
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import Spreadsheet
from posthog.utils import generate_short_id


class SpreadsheetsSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Spreadsheet
        fields = [
            "id",
            "data",
            "data_updated_at",
            "created_at",
            "updated_at",
            "short_id",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "short_id",
            "created_by",
        ]

    def create(self, validated_data: Any) -> Any:
        request = self.context["request"]
        team_id = self.context["team_id"]
        short_id = generate_short_id()

        instance = Spreadsheet.objects.create(
            **validated_data, short_id=short_id, team_id=team_id, created_by=request.user
        )
        return instance


class SpreadsheetsViewSet(
    TeamAndOrgViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"

    serializer_class = SpreadsheetsSerializer
    queryset = Spreadsheet.objects.all()
    filterset_fields = ["short_id"]
    lookup_field = "short_id"

    def safely_get_queryset(self, queryset):
        return queryset.filter(
            deleted=False,
        )
