from typing import TYPE_CHECKING, Any

from django.conf import settings

from posthog.models.team.team_heatmap_config import TeamHeatmapConfig

from products.web_analytics.backend.capture_settings import default_capture_mode

if TYPE_CHECKING:
    from posthog.models import Team


def build_heatmaps_config(team: "Team") -> dict[str, Any]:
    config = TeamHeatmapConfig.objects.filter(team_id=team.pk).first()
    return {
        "captureMode": config.capture_mode if config else default_capture_mode(team),
        "urlAllowlist": config.capture_url_allowlist if config else [],
        "urlAllowlistEnforced": settings.HEATMAP_URL_ALLOWLIST_ENFORCEMENT_ENABLED,
    }
