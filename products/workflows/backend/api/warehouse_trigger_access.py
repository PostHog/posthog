from typing import cast

from django.db import models

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.models import Team

from products.workflows.backend.service_jwt import WORKFLOW_WAREHOUSE_ACCESS_PURPOSE
from products.workflows.backend.services.warehouse_trigger_access import allowed_warehouse_flows


class WarehouseTriggerJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_WAREHOUSE_ACCESS_PURPOSE


class WarehouseTriggerAccessRequestSerializer(serializers.Serializer):
    class TriggerType(models.TextChoices):
        TABLE = "data-warehouse-table"
        VIEW = "data-warehouse-view"

    trigger_type = serializers.ChoiceField(
        choices=TriggerType.choices, help_text="Kind of warehouse row being delivered."
    )
    table_name = serializers.CharField(max_length=512, help_text="Actual source table or view name from the event.")
    flow_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=500, help_text="Candidate workflows in this project."
    )


class WarehouseTriggerAccessResponseSerializer(serializers.Serializer):
    allowed_flow_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="Workflows whose creators can read this source table or view."
    )


class WarehouseTriggerAccessViewSet(viewsets.GenericViewSet):
    authentication_classes = [WarehouseTriggerJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WarehouseTriggerAccessRequestSerializer

    @extend_schema(
        request=WarehouseTriggerAccessRequestSerializer, responses={200: WarehouseTriggerAccessResponseSerializer}
    )
    def create(self, request: Request, **kwargs: object) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = cast(InternalAPIUser, request.user)
        team = Team.objects.get(id=user.current_team_id)
        allowed = allowed_warehouse_flows(team, **serializer.validated_data)
        return Response(WarehouseTriggerAccessResponseSerializer({"allowed_flow_ids": allowed}).data)
