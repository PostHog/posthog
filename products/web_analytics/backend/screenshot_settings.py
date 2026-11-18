import re
from typing import TYPE_CHECKING

from django.db import transaction

import idna

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team_heatmap_config import TeamHeatmapConfig

if TYPE_CHECKING:
    from posthog.models import Team, User


def normalize_screenshot_hostname(value: str) -> str:
    try:
        hostname = idna.encode(value.strip(), uts46=True, std3_rules=True).decode("ascii").lower()
    except idna.IDNAError:
        raise ValueError(
            "Enter an exact hostname, such as www.example.com, without a URL, wildcard, or port."
        ) from None
    labels = hostname.split(".")
    if len(hostname) > 253 or len(labels) < 2 or not labels[-1] or re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", labels[-1]):
        raise ValueError("Enter a DNS hostname, such as www.example.com. IP addresses are not supported.")
    return hostname


def save_screenshot_hostnames(
    team: "Team", hostnames: list[str], *, user: "User", was_impersonated: bool
) -> TeamHeatmapConfig:
    config = get_or_create_team_extension(team, TeamHeatmapConfig)
    with transaction.atomic():
        config = TeamHeatmapConfig.objects.select_for_update().get(team_id=team.pk)
        before = config.allowed_hostnames
        if before != hostnames:
            config.allowed_hostnames = hostnames
            config.save(update_fields=["allowed_hostnames"])
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
                            field="heatmaps_screenshot_allowed_hostnames",
                            before=before,
                            after=hostnames,
                        )
                    ],
                ),
            )
    return config
