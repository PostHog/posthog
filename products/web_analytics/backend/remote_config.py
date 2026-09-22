from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import ProgrammingError, transaction

import structlog

from posthog.models.team.team_heatmap_config import TeamHeatmapConfig

from products.web_analytics.backend.capture_settings import EffectiveCaptureSettings, effective_capture_settings

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)


def build_heatmaps_config(team: "Team") -> dict[str, Any]:
    try:
        # The savepoint keeps an outer transaction usable if the query fails.
        with transaction.atomic():
            config = TeamHeatmapConfig.objects.filter(team_id=team.pk).first()
            effective = effective_capture_settings(team, config)
    except ProgrammingError as err:
        # A deploy can go live before its migration, so the heatmap tables are absent for a short
        # window. A missing table must not abort the whole remote config build for the team.
        logger.warning("heatmaps_config_schema_unavailable", team_id=team.pk, exception=err)
        effective = EffectiveCaptureSettings(capture_mode=TeamHeatmapConfig.CaptureMode.ALL, url_allowlist=[])
    return {
        "captureMode": effective.capture_mode,
        "urlAllowlist": effective.url_allowlist,
        "urlAllowlistEnforced": settings.HEATMAP_URL_ALLOWLIST_ENFORCEMENT_ENABLED,
    }
