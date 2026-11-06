from typing import TYPE_CHECKING, Any

from django.conf import settings

from posthog.models.team.team_heatmap_config import TeamHeatmapConfig

from products.web_analytics.backend.capture_settings import effective_capture_settings

if TYPE_CHECKING:
    from posthog.models import Team


def build_heatmaps_config(team: "Team") -> dict[str, Any]:
    config = TeamHeatmapConfig.objects.filter(team_id=team.pk).first()
    effective = effective_capture_settings(team, config)
    return {
        "captureMode": effective.capture_mode,
        "urlAllowlist": effective.url_allowlist,
        "urlAllowlistEnforced": settings.HEATMAP_URL_ALLOWLIST_ENFORCEMENT_ENABLED,
    }
