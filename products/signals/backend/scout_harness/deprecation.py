"""The retirement lifecycle of a canonical scout: the marker on disk, and the pause it drives.

Retiring a `signals-scout-*` scout used to mean one of two things that were built for something
else. The `withheld_skills` denylist hides an unreleased scout, so using it for a retirement makes
a scout teams already run disappear with no reason shown. Deleting the skill directory tombstones
the `LLMSkill` row and leaves the `SignalScoutConfig` enabled behind it, so the roster keeps a row
that looks healthy and can never run.

So a retirement is a state instead. A canonical SKILL.md declares `scout-status: deprecated` with
a `scout-deprecation` block, the sync copies that marker into every team's skill row metadata, and
once the sunset passes the team's config moves to a `retired` pause like any other system
transition: activity-logged, visible in the roster, and owned by a reason no other writer can
clear. `retire_scout_configs` is also what the prune pass calls, so a scout deleted from disk
without a marker leaves no ghost either.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from django.utils import timezone

import structlog

from posthog.models.activity_logging.activity_log import Trigger
from posthog.models.activity_logging.model_activity import ActivityTriggerContext

from products.signals.backend.models import SignalScoutConfig

logger = structlog.get_logger(__name__)

# Frontmatter keys a canonical scout declares its retirement with.
SCOUT_STATUS_KEY = "scout-status"
SCOUT_DEPRECATION_KEY = "scout-deprecation"

SCOUT_STATUS_ACTIVE = "active"
SCOUT_STATUS_DEPRECATED = "deprecated"

# `LLMSkill.metadata` key the sync copies the marker into, so every per-team surface reads the
# retirement without a disk read.
DEPRECATION_METADATA_KEY = "deprecation"

# Cap on the author-written sentence a banner shows. Generous enough for a reason plus what
# replaces the scout, tight enough that the marker stays a marker rather than a document.
MAX_DEPRECATION_REASON_LENGTH = 500

_RETIREMENT_JOB_TYPE = "signals_scout_retirement"


class ScoutDeprecationParseError(ValueError):
    """A canonical SKILL.md declares a retirement the harness cannot act on."""


@dataclass(frozen=True)
class ScoutDeprecation:
    """PostHog is retiring this canonical scout, and what a person should be told about it.

    `reason` is the sentence every surface shows, so it is required: a retirement a person cannot
    read the reason for is the failure this lifecycle exists to fix. `superseded_by` names the
    scout that takes over, when one does. `sunset_at` is when the scout stops running; absent
    means the next reconcile retires it, so a marker is never half-applied.
    """

    reason: str
    superseded_by: str = ""
    sunset_at: datetime | None = None

    def is_past_sunset(self, now: datetime) -> bool:
        return self.sunset_at is None or self.sunset_at <= now

    def as_metadata(self) -> dict[str, str | None]:
        """The marker as it is stored on `LLMSkill.metadata`, and read back by every surface."""
        return {
            "reason": self.reason,
            "superseded_by": self.superseded_by,
            "sunset_at": self.sunset_at.isoformat() if self.sunset_at else None,
        }


def _parse_sunset_at(raw: object, skill_file: Path) -> datetime | None:
    """Read the sunset instant from frontmatter, accepting a bare date as midnight UTC.

    YAML resolves `2026-10-01` to a `date` and `2026-10-01T00:00:00Z` to an aware `datetime`, and
    an author writes whichever reads better. A naive datetime is read as UTC rather than rejected,
    because a sunset is a fleet-wide moment and the fleet runs on UTC.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if timezone.is_aware(raw) else raw.replace(tzinfo=UTC)
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day, tzinfo=UTC)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as error:
            raise ScoutDeprecationParseError(
                f"SKILL.md frontmatter '{SCOUT_DEPRECATION_KEY}.sunset_at' is not an ISO-8601 date: {skill_file}"
            ) from error
        return parsed if timezone.is_aware(parsed) else parsed.replace(tzinfo=UTC)
    raise ScoutDeprecationParseError(
        f"SKILL.md frontmatter '{SCOUT_DEPRECATION_KEY}.sunset_at' must be a date or datetime: {skill_file}"
    )


def parse_scout_deprecation(frontmatter: dict, skill_file: Path, *, is_scout: bool) -> ScoutDeprecation | None:
    """Read the optional retirement marker, or None when the scout is not being retired.

    The two keys are required to agree. A `scout-deprecation` block without
    `scout-status: deprecated` is a marker nobody meant to apply yet, and `scout-status:
    deprecated` without a block is a retirement with no reason to show — both fail the parse
    rather than resolving to a half-state the fleet would act on.

    Only a scout can be retired this way, so the keys are rejected on a companion skill.
    """
    raw_status = frontmatter.get(SCOUT_STATUS_KEY)
    raw_deprecation = frontmatter.get(SCOUT_DEPRECATION_KEY)
    if raw_status is None and raw_deprecation is None:
        return None
    if not is_scout:
        raise ScoutDeprecationParseError(
            f"Only a signals-scout-* skill may declare '{SCOUT_STATUS_KEY}' or '{SCOUT_DEPRECATION_KEY}': {skill_file}"
        )
    if raw_status is not None and raw_status not in (SCOUT_STATUS_ACTIVE, SCOUT_STATUS_DEPRECATED):
        raise ScoutDeprecationParseError(
            f"SKILL.md frontmatter '{SCOUT_STATUS_KEY}' must be '{SCOUT_STATUS_ACTIVE}' or "
            f"'{SCOUT_STATUS_DEPRECATED}': got {raw_status!r} in {skill_file}"
        )
    if raw_status != SCOUT_STATUS_DEPRECATED:
        if raw_deprecation is not None:
            raise ScoutDeprecationParseError(
                f"SKILL.md frontmatter has '{SCOUT_DEPRECATION_KEY}' without "
                f"'{SCOUT_STATUS_KEY}: {SCOUT_STATUS_DEPRECATED}': {skill_file}"
            )
        return None
    if not isinstance(raw_deprecation, dict):
        raise ScoutDeprecationParseError(
            f"A deprecated scout must declare a '{SCOUT_DEPRECATION_KEY}' mapping with a reason: {skill_file}"
        )
    unknown = set(raw_deprecation) - {"reason", "superseded_by", "sunset_at"}
    if unknown:
        raise ScoutDeprecationParseError(
            f"SKILL.md frontmatter '{SCOUT_DEPRECATION_KEY}' has unknown keys {sorted(unknown)}: {skill_file}"
        )
    raw_reason = raw_deprecation.get("reason")
    if not isinstance(raw_reason, str) or not (reason := raw_reason.strip()):
        raise ScoutDeprecationParseError(
            f"SKILL.md frontmatter '{SCOUT_DEPRECATION_KEY}.reason' must be a non-empty string: {skill_file}"
        )
    if len(reason) > MAX_DEPRECATION_REASON_LENGTH:
        raise ScoutDeprecationParseError(
            f"SKILL.md frontmatter '{SCOUT_DEPRECATION_KEY}.reason' exceeds the "
            f"{MAX_DEPRECATION_REASON_LENGTH} character limit: {skill_file}"
        )
    raw_superseded_by = raw_deprecation.get("superseded_by")
    if raw_superseded_by is not None and not isinstance(raw_superseded_by, str):
        raise ScoutDeprecationParseError(
            f"SKILL.md frontmatter '{SCOUT_DEPRECATION_KEY}.superseded_by' must be a string: {skill_file}"
        )
    return ScoutDeprecation(
        reason=reason,
        superseded_by=(raw_superseded_by or "").strip(),
        sunset_at=_parse_sunset_at(raw_deprecation.get("sunset_at"), skill_file),
    )


def deprecation_metadata_of(metadata: dict | None) -> dict | None:
    """The retirement marker stored on a team's skill row, if the sync ever wrote one."""
    stored = (metadata or {}).get(DEPRECATION_METADATA_KEY)
    return stored if isinstance(stored, dict) else None


def retire_scout_configs(team_id: int, skill_names: Collection[str]) -> tuple[str, ...]:
    """Move each still-running config for these scouts to a retired pause, and say which moved.

    The transition goes through `transition_status_by_system` under `PauseReason.RETIRED`, so it
    obeys the same ownership rule every system writer does: a pause a person made stands, and a
    pause another writer owns (a tripped failure breaker) is left as it is — neither is a scout
    that runs, so neither is the ghost this pass exists to prevent. Nothing but this writer can
    clear a retired pause afterwards.

    Idempotent: a config already retired is not runnable, so a later pass skips it.
    """
    names = list(set(skill_names))
    if not names:
        return ()
    retired: list[str] = []
    configs = SignalScoutConfig.objects.for_team(team_id).filter(
        skill_name__in=names, status__in=SignalScoutConfig.RUNNABLE_STATUSES
    )
    for config in configs:
        trigger = Trigger(
            job_type=_RETIREMENT_JOB_TYPE,
            job_id=str(config.id),
            payload={"skill_name": config.skill_name},
        )
        with ActivityTriggerContext(trigger):
            moved = config.transition_status_by_system(
                SignalScoutConfig.Status.PAUSED_BY_SYSTEM,
                pause_reason=SignalScoutConfig.PauseReason.RETIRED,
            )
        if moved:
            retired.append(config.skill_name)
            logger.info(
                "signals_scout: retired a scout PostHog no longer ships",
                team_id=team_id,
                skill_name=config.skill_name,
            )
    return tuple(sorted(retired))
