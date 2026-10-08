from typing import cast

from django.conf import settings

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.impersonation import is_impersonated
from posthog.models import User
from posthog.models.team.team_heatmap_config import TeamHeatmapConfig
from posthog.permissions import TeamMemberStrictManagementPermission

from products.web_analytics.backend.facade.screenshot_settings import (
    normalize_screenshot_hostname,
    save_screenshot_hostnames,
)


class HeatmapScreenshotSettingsRequestSerializer(serializers.Serializer):
    allowed_hostnames = serializers.ListField(
        child=serializers.CharField(max_length=253),
        max_length=100,
        help_text="Exact DNS hostnames approved to receive the screenshot cookie. No URLs, wildcards, or IP addresses.",
    )

    def validate_allowed_hostnames(self, value: list[str]) -> list[str]:
        try:
            return sorted({normalize_screenshot_hostname(hostname) for hostname in value})
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from None


class HeatmapScreenshotSettingsSerializer(HeatmapScreenshotSettingsRequestSerializer):
    cookie_delivery_enabled = serializers.BooleanField(
        read_only=True, help_text="Whether this installation permits screenshot cookie delivery to its renderer."
    )
    has_secret = serializers.BooleanField(
        read_only=True, help_text="Whether a screenshot bypass secret has been generated."
    )


def screenshot_settings_response(config: TeamHeatmapConfig | None) -> Response:
    return Response(
        HeatmapScreenshotSettingsSerializer(
            {
                "cookie_delivery_enabled": settings.HEATMAP_BROWSERLESS_SCREENSHOT_COOKIES_ENABLED,
                "allowed_hostnames": config.allowed_hostnames if config else [],
                "has_secret": bool(config and config.screenshot_secret),
            }
        ).data
    )


class HeatmapScreenshotSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "project"
    permission_classes = [TeamMemberStrictManagementPermission]
    serializer_class = HeatmapScreenshotSettingsSerializer
    scope_object_read_actions = ["configuration"]
    scope_object_write_actions = ["update_settings"]

    @extend_schema(operation_id="heatmap_screenshot_settings_retrieve", responses=HeatmapScreenshotSettingsSerializer)
    @action(detail=False, methods=["GET"], url_path="settings")
    def configuration(self, request: Request, **kwargs: object) -> Response:
        return screenshot_settings_response(TeamHeatmapConfig.objects.filter(team_id=self.team_id).first())

    @extend_schema(
        operation_id="heatmap_screenshot_settings_update",
        request=HeatmapScreenshotSettingsRequestSerializer,
        responses=HeatmapScreenshotSettingsSerializer,
    )
    @configuration.mapping.patch
    def update_settings(self, request: Request, **kwargs: object) -> Response:
        serializer = HeatmapScreenshotSettingsRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "allowed_hostnames" not in serializer.validated_data:
            return screenshot_settings_response(TeamHeatmapConfig.objects.filter(team_id=self.team_id).first())
        config = save_screenshot_hostnames(
            self.team,
            serializer.validated_data["allowed_hostnames"],
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        return screenshot_settings_response(config)
