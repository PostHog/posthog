import re
from typing import Any, Optional

import structlog
import posthoganalytics

from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

WORKFLOWS_TIMING_RESCHEDULE_FLAG = "workflows-timing-reschedule"

# Steps whose parked runs a timing edit can strand: delays park up to 30 days out and time
# windows up to a week. wait_until_condition currently re-parks on a 10-minute polling cap
# (so a sweep is a cheap no-op re-park), but the poll is slated for removal in favor of
# matcher wakes - after which its max-wait deadline parks for the full duration like a
# delay and shortening it strands runs without a sweep.
TIMING_ACTION_TYPES = {"delay", "wait_until_time_window", "wait_until_condition"}

# Only jobs parked on this many steps or fewer get swept; a diff touching more than this is
# pathological (the sweep endpoint caps action_ids at 100 too).
MAX_RESCHEDULE_ACTION_IDS = 100

# Mirrors the worker's duration parsing (nodejs delay.ts calculatedScheduledAt): value like
# "10d" / "1.5h" / "10m", with per-unit clamps applied before comparison so a 45d -> 35d edit
# (both clamped to 30d) doesn't trigger a pointless sweep.
_DURATION_RE = re.compile(r"^(\d*\.?\d+)([dhms])$")
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_UNIT_MAX = {"d": 30, "h": 24, "m": 60, "s": 60}

_TIME_WINDOW_CONFIG_KEYS = ("day", "time", "timezone", "use_person_timezone", "fallback_timezone")


def use_workflows_timing_reschedule(team: Team) -> bool:
    """Gates the reschedule sweep for parked runs after a timing edit; off means today's
    behavior (shortened delays only take effect at each run's old wake time).

    A raised exception is treated as "flag off" - skipping the sweep is the safe fallback,
    making the flag a kill switch for the whole feature.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                WORKFLOWS_TIMING_RESCHEDULE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
            )
        )
    except Exception:
        logger.warning(
            "workflows.timing_reschedule.feature_flag_check_failed_defaulting_off",
            team_id=team.id,
            flag=WORKFLOWS_TIMING_RESCHEDULE_FLAG,
            exc_info=True,
        )
        return False


def parse_delay_duration_seconds(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    match = _DURATION_RE.match(value)
    if not match:
        return None
    amount, unit = match.groups()
    return min(float(amount), _UNIT_MAX[unit]) * _UNIT_SECONDS[unit]


def get_all_timing_action_ids(actions: Optional[list[dict]]) -> list[str]:
    """Every timing step's id — used when a flow is re-enabled. Runs parked during a prior active
    period survive a disable (they're only cancelled lazily, at wake, while the flow is inactive),
    and timing edits made while inactive never sweep, so there is no trustworthy diff base at
    enable time. Sweeping every timing step converges them all: early wake is a no-op re-park for
    unchanged steps."""
    action_ids = {
        a["id"] for a in actions or [] if isinstance(a, dict) and a.get("id") and a.get("type") in TIMING_ACTION_TYPES
    }
    if len(action_ids) > MAX_RESCHEDULE_ACTION_IDS:
        logger.warning(
            "workflows.timing_reschedule.too_many_timing_actions",
            changed=len(action_ids),
            cap=MAX_RESCHEDULE_ACTION_IDS,
        )
        return []
    return sorted(action_ids)


def get_timing_reschedule_action_ids(
    before_actions: Optional[list[dict]], after_actions: Optional[list[dict]]
) -> list[str]:
    """Action ids whose timing edit could move a parked run's wake time EARLIER - the only
    case the sweep exists for. Lengthened timings self-heal: the job wakes at its old
    (earlier) time and re-parks at the recomputed later target.

    Per action id present on both sides:
    - delay: trigger on a shortened effective duration; unparseable durations trigger
      conservatively (the worker throws on them at wake, and a spurious sweep is a cheap
      no-op re-park).
    - wait_until_condition: trigger on a shortened max_wait_duration, same comparison as
      delay. Condition edits never trigger - they don't move a parked run's wake time
      (the matcher and the poll both evaluate live config at wake).
    - wait_until_time_window: trigger on any timing-config change - whether a window edit
      moves a given run's wake earlier depends on each person's timezone and position in
      the week, so it isn't statically decidable.
    - type changed across the timing boundary: parked runs' action_id still points at the
      step, and the new handler should run on the sweep's schedule, not the old wake time.
    - added/deleted actions never trigger: nothing is parked on a new step, and deleted
      steps are the graceful-exit path's concern.
    """
    before_by_id = {a["id"]: a for a in (before_actions or []) if isinstance(a, dict) and a.get("id")}
    action_ids: set[str] = set()

    for action in after_actions or []:
        if not isinstance(action, dict) or not action.get("id"):
            continue
        before = before_by_id.get(action["id"])
        if not before:
            continue

        before_type = before.get("type")
        after_type = action.get("type")
        if before_type not in TIMING_ACTION_TYPES and after_type not in TIMING_ACTION_TYPES:
            continue

        if before_type != after_type:
            action_ids.add(action["id"])
            continue

        before_config = before.get("config") or {}
        after_config = action.get("config") or {}
        if after_type in ("delay", "wait_until_condition"):
            duration_key = "delay_duration" if after_type == "delay" else "max_wait_duration"
            before_seconds = parse_delay_duration_seconds(before_config.get(duration_key))
            after_seconds = parse_delay_duration_seconds(after_config.get(duration_key))
            if before_seconds is None or after_seconds is None:
                if before_config.get(duration_key) != after_config.get(duration_key):
                    action_ids.add(action["id"])
            elif after_seconds < before_seconds:
                action_ids.add(action["id"])
        elif after_type == "wait_until_time_window":
            if any(before_config.get(key) != after_config.get(key) for key in _TIME_WINDOW_CONFIG_KEYS):
                action_ids.add(action["id"])

    if len(action_ids) > MAX_RESCHEDULE_ACTION_IDS:
        logger.warning(
            "workflows.timing_reschedule.too_many_changed_actions",
            changed=len(action_ids),
            cap=MAX_RESCHEDULE_ACTION_IDS,
        )
        return []

    return sorted(action_ids)
