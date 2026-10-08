from typing import TYPE_CHECKING
from urllib.parse import urlparse

from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team_heatmap_config import TeamHeatmapConfig

from products.web_analytics.backend.models.heatmap_capture_config_version import HeatmapCaptureConfigVersion
from products.web_analytics.backend.models.heatmap_saved import SavedHeatmap

if TYPE_CHECKING:
    from posthog.models import Team, User

HEATMAP_FREE_CAPTURE_URL_LIMIT = 3


@frozen
class EffectiveCaptureSettings:
    capture_mode: str
    url_allowlist: list[str]


def is_capture_all_urls_entitled(team: "Team") -> bool:
    return team.organization.has_active_subscription is not False


def default_capture_mode(team: "Team") -> str:
    if is_capture_all_urls_entitled(team):
        return TeamHeatmapConfig.CaptureMode.ALL
    return TeamHeatmapConfig.CaptureMode.URL_ALLOWLIST


def oldest_saved_heatmap_urls(team: "Team", limit: int = HEATMAP_FREE_CAPTURE_URL_LIMIT) -> list[str]:
    return list(
        SavedHeatmap.objects.filter(team=team, deleted=False)
        .exclude(url="")
        .values("url")
        .annotate(first_created_at=Min("created_at"))
        .order_by("first_created_at", "url")
        .values_list("url", flat=True)[:limit]
    )


def effective_capture_settings(team: "Team", config: TeamHeatmapConfig | None) -> EffectiveCaptureSettings:
    if is_capture_all_urls_entitled(team):
        if config is None:
            return EffectiveCaptureSettings(capture_mode=TeamHeatmapConfig.CaptureMode.ALL, url_allowlist=[])
        return EffectiveCaptureSettings(
            capture_mode=config.capture_mode, url_allowlist=list(config.capture_url_allowlist)
        )

    if config is not None and config.capture_mode == TeamHeatmapConfig.CaptureMode.URL_ALLOWLIST:
        url_allowlist = list(config.capture_url_allowlist)
    else:
        url_allowlist = oldest_saved_heatmap_urls(team)
    return EffectiveCaptureSettings(
        capture_mode=TeamHeatmapConfig.CaptureMode.URL_ALLOWLIST,
        url_allowlist=url_allowlist[:HEATMAP_FREE_CAPTURE_URL_LIMIT],
    )


def normalize_capture_url(value: str) -> str:
    url = value.strip()
    if not url:
        raise ValueError("Enter a URL, such as https://example.com/pricing.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Enter a full URL that starts with http:// or https://. Use * to match any characters.")
    return url


def save_capture_settings(
    team: "Team", capture_mode: str, url_allowlist: list[str], *, user: "User", was_impersonated: bool
) -> TeamHeatmapConfig:
    get_or_create_team_extension(team, TeamHeatmapConfig)
    with transaction.atomic():
        config = TeamHeatmapConfig.objects.select_for_update().get(team_id=team.pk)
        before_mode = config.capture_mode
        before_allowlist = config.capture_url_allowlist
        if before_mode == capture_mode and before_allowlist == url_allowlist:
            return config

        config.capture_mode = capture_mode
        config.capture_url_allowlist = url_allowlist
        config.save(update_fields=["capture_mode", "capture_url_allowlist"])

        now = timezone.now()
        versions = HeatmapCaptureConfigVersion.objects.for_team(team.pk)
        versions.filter(effective_to__isnull=True).update(effective_to=now)
        versions.create(
            team=team,
            mode=capture_mode,
            patterns=url_allowlist if capture_mode == TeamHeatmapConfig.CaptureMode.URL_ALLOWLIST else [],
            effective_from=now,
            created_by=user,
        )

        log_activity(
            organization_id=team.organization_id,
            team_id=team.pk,
            user=user,
            was_impersonated=was_impersonated,
            scope="Team",
            item_id=team.pk,
            activity="updated",
            detail=Detail(
                name=str(team.name),
                changes=[
                    Change(
                        type="Team",
                        action="changed",
                        field="heatmaps_capture_mode",
                        before=before_mode,
                        after=capture_mode,
                    ),
                    Change(
                        type="Team",
                        action="changed",
                        field="heatmaps_capture_url_allowlist",
                        before=before_allowlist,
                        after=url_allowlist,
                    ),
                ],
            ),
        )
    return config
