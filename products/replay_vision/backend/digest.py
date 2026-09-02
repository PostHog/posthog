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
    return f"Featured digest: {scanner.name}"[:255]


def unique_digest_name(team_id: int, base: str) -> str:
    """A team-unique variant of `base`, suffixing " (2)", " (3)", … when the plain name is taken.
    Scanner names are team-unique, so two scanners can't produce the same derived name; the
    collision source is another VisionAction already holding it, such as a user-named action or a
    digest that was demoted earlier and kept its name."""
    base = base[:255]
    # One query over the team's names beating this base; the count per team is small.
    taken = set(VisionAction.objects.for_team(team_id).filter(name__startswith=base).values_list("name", flat=True))
    if base not in taken:
        return base
    for n in range(2, len(taken) + 3):
        candidate = f"{base[: 255 - len(f' ({n})')]} ({n})"
        if candidate not in taken:
            return candidate
    # Unreachable given the range spans more than the collisions, but stay well-defined; the DB
    # uniqueness constraint is the final backstop.
    return base


def provision_scanner_digest(scanner: "ReplayScanner", user: "User") -> VisionAction | None:
    """Create the scanner's built-in featured digest: a summary action with no delivery targets whose
    runs surface on the scanner overview. Fail-soft; scanner creation must never fail because digest
    provisioning did."""
    try:
        # for_team()'s filter doesn't propagate into create(), so team is still passed explicitly.
        return VisionAction.objects.for_team(scanner.team_id).create(
            team_id=scanner.team_id,
            scanner=scanner,
            name=unique_digest_name(scanner.team_id, digest_name_for_scanner(scanner)),
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
