"""The atomic CI Signals configuration surface (read and toggle-all)."""

from typing import TypedDict, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.models.user import User

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.ci_signals import (
    CISignalsConfigSerializer,
    CISignalsConfigUpdateSerializer,
)
from products.engineering_analytics.backend.presentation.views._base import EngineeringAnalyticsViewSetBase


class _CISignalsConfigUpdateData(TypedDict):
    enabled: bool


class CISignalsConfigMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = ["ci_signals_config"]
    WRITE_ACTIONS = ["update_ci_signals_config"]

    @extend_schema(
        operation_id="engineering_analytics_ci_signals_config_retrieve",
        responses={200: CISignalsConfigSerializer},
        description="Return the atomic CI Signals configuration and aggregate GitHub warehouse sync status.",
    )
    @action(detail=False, methods=["get"], url_path="ci-signals-config", pagination_class=None)
    def ci_signals_config(self, request: Request, **kwargs) -> Response:
        result = api.get_ci_signals_config(team=self.team, user_access_control=self.user_access_control)
        return Response(CISignalsConfigSerializer(instance=result).data)

    @validated_request(
        request_serializer=CISignalsConfigUpdateSerializer,
        operation_id="engineering_analytics_ci_signals_config_update",
        responses={200: OpenApiResponse(response=CISignalsConfigSerializer)},
        description="Enable or disable all CI signal detectors in one transaction.",
    )
    @ci_signals_config.mapping.put
    def update_ci_signals_config(self, request: TypedRequest[_CISignalsConfigUpdateData], **kwargs) -> Response:
        result = api.update_ci_signals_config(
            team=self.team,
            enabled=request.validated_data["enabled"],
            # Authenticated endpoint, so this is a real User, not AnonymousUser.
            created_by_id=cast(User, request.user).id,
            user_access_control=self.user_access_control,
        )
        return Response(CISignalsConfigSerializer(instance=result).data)
