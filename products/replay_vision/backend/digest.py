from typing import TYPE_CHECKING

import structlog

from products.replay_vision.backend.models.vision_action import VisionAction

if TYPE_CHECKING:
    from posthog.models.user import User

    from products.replay_vision.backend.models.replay_scanner import ReplayScanner

logger = structlog.get_logger(__name__)

# Every morning at 8:00 in the team's timezone; the sweep skips days with no new observations.
SCANNER_DIGEST_RRULE = "FREQ=DAILY;BYHOUR=8;BYMINUTE=0"


def digest_name_for_scanner(scanner: "ReplayScanner") -> str:
    # VisionAction names are unique per team, so the scanner name (itself team-unique) is baked in.
    return f"Daily digest: {scanner.name}"[:255]


def provision_scanner_digest(scanner: "ReplayScanner", user: "User") -> VisionAction | None:
    """Create the scanner's built-in daily digest: a summary action with no delivery targets whose
    runs surface on the scanner overview. Fail-soft; scanner creation must never fail because digest
    provisioning did."""
    try:
        # for_team()'s filter doesn't propagate into create(), so team is still passed explicitly.
        return VisionAction.objects.for_team(scanner.team_id).create(
            team_id=scanner.team_id,
            scanner=scanner,
            name=digest_name_for_scanner(scanner),
            created_by=user,
            is_scanner_digest=True,
            trigger_config={
                "rrule": SCANNER_DIGEST_RRULE,
                "timezone": scanner.team.timezone or "UTC",
            },
            delivery_config=[],
        )
    except Exception:
        logger.exception(
            "replay_vision.digest.provision_failed",
            scanner_id=str(scanner.id),
            team_id=scanner.team_id,
        )
        return None
