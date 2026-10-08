from typing import cast

from django.conf import settings

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.team.team_heatmap_config import TeamHeatmapConfig
from posthog.permissions import TeamMemberStrictManagementPermission

from products.web_analytics.backend.facade.capture_settings import (
    HEATMAP_FREE_CAPTURE_URL_LIMIT,
    effective_capture_settings,
    is_capture_all_urls_entitled,
    normalize_capture_url,
    save_capture_settings,
    top_heatmap_pages,
)


class HeatmapCapturePageSerializer(serializers.Serializer):
    url = serializers.CharField(help_text="A page URL that currently sends heatmap data.")
    count = serializers.IntegerField(help_text="Heatmap events captured on this page in the last 30 days.")


class HeatmapCapturePagesSerializer(serializers.Serializer):
    pages = HeatmapCapturePageSerializer(many=True, help_text="Top pages by recent heatmap volume, most active first.")


CAPTURE_MODE_HELP_TEXT = (
    "Whether to capture heatmap data from every page ('all') or only listed URLs ('url_allowlist')."
)
URL_ALLOWLIST_HELP_TEXT = "Full http(s) URLs that may send heatmap data. Use * to match any characters."


class HeatmapCaptureSettingsRequestSerializer(serializers.Serializer):
    capture_mode = serializers.ChoiceField(
        choices=TeamHeatmapConfig.CaptureMode.choices, required=False, help_text=CAPTURE_MODE_HELP_TEXT
    )
    url_allowlist = serializers.ListField(
        child=serializers.CharField(max_length=2000),
        max_length=100,
        required=False,
        help_text=URL_ALLOWLIST_HELP_TEXT,
    )

    def validate_url_allowlist(self, value: list[str]) -> list[str]:
        try:
            return sorted({normalize_capture_url(url) for url in value})
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from None


class HeatmapCaptureSettingsSerializer(serializers.Serializer):
    capture_mode = serializers.ChoiceField(
        choices=TeamHeatmapConfig.CaptureMode.choices, help_text=CAPTURE_MODE_HELP_TEXT
    )
    url_allowlist = serializers.ListField(
        child=serializers.CharField(max_length=2000), help_text=URL_ALLOWLIST_HELP_TEXT
    )
    enforcement_enabled = serializers.BooleanField(
        read_only=True, help_text="Whether this installation enforces the URL allow-list for heatmap capture."
    )
    can_capture_all_urls = serializers.BooleanField(
        read_only=True, help_text="Whether this organization's plan may capture heatmaps on every page."
    )
    capture_url_limit = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="How many URLs this plan may capture, or null when the plan captures all pages.",
    )


def capture_settings_response(team: Team, config: TeamHeatmapConfig | None) -> Response:
    entitled = is_capture_all_urls_entitled(team)
    effective = effective_capture_settings(team, config)
    return Response(
        HeatmapCaptureSettingsSerializer(
            {
                "capture_mode": effective.capture_mode,
                "url_allowlist": effective.url_allowlist,
                "enforcement_enabled": settings.HEATMAP_URL_ALLOWLIST_ENFORCEMENT_ENABLED,
                "can_capture_all_urls": entitled,
                "capture_url_limit": None if entitled else HEATMAP_FREE_CAPTURE_URL_LIMIT,
            }
        ).data
    )


class HeatmapCaptureSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "project"
    permission_classes = [TeamMemberStrictManagementPermission]
    serializer_class = HeatmapCaptureSettingsSerializer
    scope_object_read_actions = ["configuration", "pages"]
    scope_object_write_actions = ["update_settings"]

    @extend_schema(operation_id="heatmap_capture_settings_retrieve", responses=HeatmapCaptureSettingsSerializer)
    @action(detail=False, methods=["GET"], url_path="settings")
    def configuration(self, request: Request, **kwargs: object) -> Response:
        return capture_settings_response(self.team, TeamHeatmapConfig.objects.filter(team_id=self.team_id).first())

    @extend_schema(operation_id="heatmap_capture_pages_retrieve", responses=HeatmapCapturePagesSerializer)
    @action(detail=False, methods=["GET"], url_path="pages")
    def pages(self, request: Request, **kwargs: object) -> Response:
        return Response(HeatmapCapturePagesSerializer({"pages": top_heatmap_pages(self.team)}).data)

    @extend_schema(
        operation_id="heatmap_capture_settings_update",
        request=HeatmapCaptureSettingsRequestSerializer,
        responses=HeatmapCaptureSettingsSerializer,
    )
    @configuration.mapping.patch
    def update_settings(self, request: Request, **kwargs: object) -> Response:
        serializer = HeatmapCaptureSettingsRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        config = TeamHeatmapConfig.objects.filter(team_id=self.team_id).first()
        if not serializer.validated_data:
            return capture_settings_response(self.team, config)

        effective = effective_capture_settings(self.team, config)
        capture_mode = serializer.validated_data.get("capture_mode", effective.capture_mode)
        url_allowlist = serializer.validated_data.get("url_allowlist", effective.url_allowlist)

        if not is_capture_all_urls_entitled(self.team):
            if capture_mode == TeamHeatmapConfig.CaptureMode.ALL:
                raise serializers.ValidationError(
                    {
                        "capture_mode": f"Your plan captures up to {HEATMAP_FREE_CAPTURE_URL_LIMIT} URLs. "
                        "Upgrade to capture heatmaps on every page."
                    }
                )
            if len(url_allowlist) > HEATMAP_FREE_CAPTURE_URL_LIMIT:
                raise serializers.ValidationError(
                    {
                        "url_allowlist": f"Your plan captures up to {HEATMAP_FREE_CAPTURE_URL_LIMIT} URLs. "
                        "Remove some, or upgrade to capture all pages."
                    }
                )

        config = save_capture_settings(
            self.team,
            capture_mode,
            url_allowlist,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        return capture_settings_response(self.team, config)
