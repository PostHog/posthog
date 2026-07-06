"""Per-team scout limits + metadata, resolved from the `signals-scout` flag payload.

Single source of truth for "what caps and allowances does this team actually have": the
flag-payload read and three-layer cap resolution that the coordinator enforces at dispatch and
the HTTP surface (`scout_harness/views.py` → the `signals-scout-metadata` endpoint) reports to the
UI. Kept free of the temporalio workflow/scheduler stack so it stays cheap to import on the API
path; both sides import from here so the reported caps never drift from what dispatch allows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.signals.backend.models import SignalScoutRun

logger = structlog.get_logger(__name__)

# Team-level dogfood gate. The single team gate (no per-team model boolean): the flag's JSON
# payload picks which teams run scouts; per-scout SignalScoutConfig rows pick which
# scouts/schedules.
SIGNALS_SCOUT_DOGFOOD_FLAG = "signals-scout"

# Fixed distinct_id for the payload read — enrollment is team-list-in-payload, not per-user.
SIGNALS_SCOUT_DISCOVERY_DISTINCT_ID = "internal_signals_scout_team_discovery"

# Fail-safe allowlist used when the flag payload is missing/invalid — but only on PostHog
# Cloud or local dev (see `_fallback_team_ids`). 1 (local dev), 2 (internal), 148051 (dev).
DEFAULT_ENROLLED_TEAM_IDS: list[int] = [1, 2, 148051]

# Per-team slice of the tick budget. Bounds what one team can consume per tick (and thus
# per day: cap × ticks/day), so a team registering many scouts degrades its own cadence,
# not everyone else's. Sized well above the canonical fleet (~16 scouts) so a fully-enrolled
# team is never trimmed; round-robin allocation still keeps any one team from starving the
# others even when this is close to the global cap.
#
# This is the LAST-RESORT default. Effective per-team cap resolves through three layers,
# most specific first (see `_resolve_max_runs_per_tick`): a team's own `team_configs` entry →
# the fleet-wide `default_team_config` → this code constant. The two flag layers are read
# fresh each tick, so the launch posture (e.g. cap every enrolled team at 1 run/tick via
# `default_team_config`, then hand a close partner more headroom via `team_configs`) is
# tunable in the flag UI with no deploy.
MAX_RUNS_PER_TEAM_PER_TICK = 50

# Key inside a `team_configs` entry (or the `default_team_config` blob) that overrides
# `MAX_RUNS_PER_TEAM_PER_TICK`. Both blobs share the same inner shape — a forward-looking
# override bag — so add more per-team-tunable settings here and each consumer reads + validates
# the key it cares about.
TEAM_CONFIG_MAX_RUNS_PER_TICK = "max_runs_per_tick"

# Per-team DAILY run budget — the cost guarantee the per-tick cap can't express. The tick cap
# bounds bursts (≤ cap per 30-min tick → ≤ cap × 48/day); this bounds the day directly, so a
# launch team that enables many scouts (or cranks their intervals down) still runs at most N
# times a day. Counted over a rolling 24h window of dispatched runs and folded into the per-team
# tick cap (the tighter of the two binds each tick — see `_allocate_tick_budget`).
#
# `None` = no daily cap (the historical behaviour; the per-tick cap stays the only bound). Like
# the tick cap, the effective value resolves most-specific-first (see `_resolve_max_runs_per_day`):
# a team's `team_configs` entry → the fleet-wide `default_team_config` → this code constant. Left
# `None` so existing teams are unchanged; the launch posture sets a small N on
# `default_team_config` in the flag, no deploy.
MAX_RUNS_PER_TEAM_PER_DAY: int | None = None

# Key inside `team_configs` / `default_team_config` that overrides `MAX_RUNS_PER_TEAM_PER_DAY`.
TEAM_CONFIG_MAX_RUNS_PER_DAY = "max_runs_per_day"

# Per-scout holdback denylist. A list of canonical scout skill names a team must NOT get: the
# scout is never seeded into that team's skill namespace, never config-enabled, and never
# dispatched to it. The knob for dogfooding an unreleased scout on a single project (e.g. error
# tracking on project 2) without exposing it fleet-wide.
#
# Lives inside the same `team_configs` / `default_team_config` blobs as the run caps, and resolves
# the same most-specific-first way (`_resolve_withheld_skills`): a fleet-wide default list in
# `default_team_config.withheld_skills` holds a scout back from EVERY team, and a per-team
# `team_configs[<id>].withheld_skills` REPLACES that list for one team (set it to `[]` to release
# the full fleet to a dogfooder). Same replace-not-merge semantics as `enabled_skills`. Absent at
# both layers → nothing withheld (unchanged behaviour).
#
# Unlike `enabled_skills` (a soft seed default a user can still toggle on), this is a HARD gate at
# the seed + dispatch layer — a withheld scout can't be self-enabled into running.
TEAM_CONFIG_WITHHELD_SKILLS = "withheld_skills"

# Rolling window the per-team daily budget is counted over.
DAILY_BUDGET_WINDOW = timedelta(hours=24)

# Flag payload key carrying an alpha/announcement banner for the scout UIs (cloud inbox + the
# Code app). A free-form editorial string set in the flag UI so wording changes need no deploy to
# either app. Absent / non-string / blank → no banner.
SIGNALS_SCOUT_BANNER_KEY = "scouts_banner_message"


def _fallback_team_ids() -> list[int]:
    """Default allowlist when the flag payload is absent/unreadable — gated to PostHog Cloud
    and local dev. A self-hosted instance (where teams 1/2 exist but no one opted into scouts)
    fails closed instead, so the coordinator never starts LLM scout runs for an unintended
    tenant; a self-hoster opts in by setting the payload explicitly."""
    return list(DEFAULT_ENROLLED_TEAM_IDS) if (is_cloud() or settings.DEBUG) else []


def _read_flag_payload() -> dict | None:
    """Read + parse the `signals-scout` flag's JSON payload once.

    The flag must stay 100%-on so the payload is served for the synthetic discovery
    distinct_id — `match_value=True` additionally forces the true-variant payload under local
    evaluation. Returns the parsed dict, or `None` when the payload is absent / not an object /
    unreadable. A read error never breaks dispatch: callers apply their own fallback to `None`.
    Enrollment and per-team configs both derive from a single call to this so they always see
    the same snapshot. Mirrors `posthog/temporal/ai_observability/team_discovery.py`.
    """
    try:
        payload = posthoganalytics.get_feature_flag_payload(
            SIGNALS_SCOUT_DOGFOOD_FLAG, SIGNALS_SCOUT_DISCOVERY_DISTINCT_ID, match_value=True
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as error:
        capture_exception(error)
        return None


# Sentinel inside `guaranteed_team_ids` that enrolls EVERY team which already has scout configs,
# instead of an explicit per-team allowlist. With `"*"` present, enrollment inverts: the gate
# becomes "does this team have enabled scout configs" (created via the product-autonomy-gated UI /
# the on-demand `sync` materialization), not "is this id listed". Explicit numeric ids can still sit
# alongside `"*"` to force-provision teams that haven't self-enrolled yet (the pinned internal
# projects), and `skip_team_ids` still hard-excludes. So `["*"]` flips scouts to "on for everyone
# who turns them on" while keeping per-team control + the kill switch.
ENROLL_ALL_TOKEN = "*"


@dataclass(frozen=True)
class Enrollment:
    """Parsed scout enrollment from the `signals-scout` flag payload.

    `wildcard` → `"*"` was present: every team with enabled scout configs participates.
    `explicit` → the explicit numeric `guaranteed_team_ids` (skip NOT yet removed). Under a
    wildcard these are still force-provisioned (seeded from nothing); without one they ARE the
    allowlist. `skip` → `skip_team_ids`, the override kill-switch applied over both.
    """

    wildcard: bool
    explicit: set[int]
    skip: set[int]


def _parse_enrollment(payload: dict | None) -> Enrollment:
    """Parse enrollment (wildcard + explicit ids + skip) from the flag payload in one pass.

    Flag-driven, no deploy: edit `guaranteed_team_ids` in the flag UI to enroll/drain on the next
    tick; `skip_team_ids` is the override kill-switch. Defensive, matching the historical contract:
    a missing/unreadable payload or a malformed `guaranteed_team_ids` value falls back to
    `_fallback_team_ids` (cloud/dev only). A list may mix the `"*"` wildcard token with integer ids;
    ANY other entry type marks the whole list malformed → fallback, so a typo can't silently widen
    or narrow enrollment. An explicit empty list is honored as an intentional "drain all" (no
    wildcard, no ids) — not coerced to the fallback.
    """
    fallback = _fallback_team_ids()
    if payload is None:
        return Enrollment(wildcard=False, explicit=set(fallback), skip=set())

    raw = payload.get("guaranteed_team_ids", fallback)
    wildcard = False
    explicit: set[int] = set()
    if isinstance(raw, list):
        malformed = False
        for entry in raw:
            if entry == ENROLL_ALL_TOKEN:
                wildcard = True
            elif isinstance(entry, int) and not isinstance(entry, bool):
                explicit.add(entry)
            else:
                malformed = True
                break
        if malformed:
            wildcard, explicit = False, set(fallback)
    else:
        explicit = set(fallback)

    raw_skip = payload.get("skip_team_ids", [])
    if isinstance(raw_skip, list) and all(isinstance(t, int) and not isinstance(t, bool) for t in raw_skip):
        skip = set(raw_skip)
    else:
        skip = set()

    return Enrollment(wildcard=wildcard, explicit=explicit, skip=skip)


def _enrolled_team_ids(payload: dict | None) -> set[int]:
    """Explicit enrolled project ids (skip removed) — the back-compat view of `_parse_enrollment`
    for the metadata path and existing callers.

    Does NOT reflect the `"*"` wildcard: the coordinator reads `_parse_enrollment` directly so it
    can resolve the config-derived wildcard set, while `enrolled` in the UI metadata folds the
    wildcard in via `_resolve_enrolled`.
    """
    enrollment = _parse_enrollment(payload)
    return enrollment.explicit - enrollment.skip


def _team_configs(payload: dict | None) -> dict[int, dict]:
    """Optional per-team config overrides, parsed from the same `signals-scout` flag payload as
    enrollment. Returns `{team_id: config_dict}`.

    Payload key `team_configs` is a `{team_id: {…}}` map — a forward-looking per-team override
    bag. Today the only honored key is `max_runs_per_tick` (overrides `MAX_RUNS_PER_TEAM_PER_TICK`
    for that team — give an important dogfooder more headroom or hold a noisy one lower, no
    deploy); add more per-team settings under the same blob later. The override takes precedence
    over the global default for its team; teams not listed keep the global default.

    Absent/malformed (`None` payload included) → `{}` (everyone on the defaults). Defensive
    parse: JSON object keys arrive as strings so they're coerced to int; entries whose value
    isn't a dict are dropped. Each consumer validates the specific key it reads (see
    `_allocate_tick_budget._team_cap`). Keys are canonicalized to parent projects at planning
    time (see `_canonicalize_team_config_keys`).
    """
    if payload is None:
        return {}

    raw = payload.get("team_configs", {})
    if not isinstance(raw, dict):
        return {}

    configs: dict[int, dict] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            team_id = int(key)
        except (TypeError, ValueError):
            continue
        configs[team_id] = value
    return configs


def _default_team_config(payload: dict | None) -> dict:
    """Fleet-wide default config applied to every enrolled team, parsed from the `signals-scout`
    flag payload key `default_team_config`.

    Same inner shape as a `team_configs` entry (today: `max_runs_per_tick`). It sits between a
    per-team `team_configs` override and the code constant in `_resolve_max_runs_per_tick`, so a
    single fleet-wide cost guardrail (e.g. cap every enrolled team at 1 run/tick for launch) can
    be set in the flag UI with no deploy, while specific teams still get more headroom via
    `team_configs`. Absent/malformed (`None` payload included) → `{}` (everyone falls back to the
    code constants — unchanged behaviour).
    """
    if payload is None:
        return {}
    raw = payload.get("default_team_config", {})
    return raw if isinstance(raw, dict) else {}


def _resolve_max_runs_per_tick(team_id: int, team_configs: dict[int, dict], default_team_config: dict) -> int:
    """Effective per-tick cap for a team, most-specific layer first.

    `team_configs[team_id]` (per-team override) → `default_team_config` (fleet-wide default) →
    `MAX_RUNS_PER_TEAM_PER_TICK` (code constant). Both flag blobs are arbitrary JSON, so the
    `max_runs_per_tick` value is validated at each layer (positive int, not bool); an absent or
    malformed value falls through to the next layer rather than failing the tick.
    """
    for source in ((team_configs.get(team_id) or {}), default_team_config):
        override = source.get(TEAM_CONFIG_MAX_RUNS_PER_TICK)
        if isinstance(override, int) and not isinstance(override, bool) and override > 0:
            return override
    return MAX_RUNS_PER_TEAM_PER_TICK


def _resolve_max_runs_per_day(team_id: int, team_configs: dict[int, dict], default_team_config: dict) -> int | None:
    """Effective per-team daily run budget, most-specific layer first.

    `team_configs[team_id]` (per-team override) → `default_team_config` (fleet-wide default) →
    `MAX_RUNS_PER_TEAM_PER_DAY` (code constant, `None` = unbounded). Same per-layer fallback and
    validation (positive int, not bool) as `_resolve_max_runs_per_tick`: a malformed value at one
    layer falls through to the next rather than failing the tick. `None` means no daily cap — only
    the per-tick cap binds, the historical behaviour.
    """
    for source in ((team_configs.get(team_id) or {}), default_team_config):
        override = source.get(TEAM_CONFIG_MAX_RUNS_PER_DAY)
        if isinstance(override, int) and not isinstance(override, bool) and override > 0:
            return override
    return MAX_RUNS_PER_TEAM_PER_DAY


# Flag payload key overriding the GLOBAL per-tick dispatch ceiling (the coordinator's
# `MAX_RUNS_PER_TICK`). Read fresh each tick like the per-team caps, so the fleet-wide ceiling can
# be raised with no deploy if enrollment grows past the default's headroom (e.g. a launch blast
# enrolls thousands of teams at once via the `"*"` wildcard), or lowered to throttle spend in an
# incident. Absent / malformed / non-positive → the code default the coordinator passes in.
GLOBAL_MAX_RUNS_PER_TICK_KEY = "max_runs_per_tick_global"


def _resolve_global_max_runs_per_tick(payload: dict | None, default: int) -> int:
    """Effective global per-tick dispatch ceiling: the flag override if valid, else `default`.

    `default` is the coordinator's `MAX_RUNS_PER_TICK` constant, passed in to avoid a circular
    import (the coordinator imports this module, not vice versa). A positive-int override wins
    (raise or lower); anything else falls through to the default rather than failing the tick.
    """
    if payload is None:
        return default
    override = payload.get(GLOBAL_MAX_RUNS_PER_TICK_KEY)
    if isinstance(override, int) and not isinstance(override, bool) and override > 0:
        return override
    return default


def _resolve_withheld_skills(team_id: int, team_configs: dict[int, dict], default_team_config: dict) -> set[str]:
    """Skill names held back from a team, resolved most-specific layer first.

    `team_configs[team_id].withheld_skills` (per-team override) → `default_team_config.withheld_skills`
    (fleet-wide default) → none. Replace-not-merge, same as `enabled_skills`: the first layer
    carrying a valid `list[str]` wins outright, so a team can override the fleet default with its
    own list — or with `[]` to release the full fleet (withhold nothing). A malformed value at a
    layer (not a list of strings) falls through to the next, so a typo can't silently un-withhold a
    scout. Absent at both layers → empty set (nothing withheld, unchanged behaviour).
    """
    for source in ((team_configs.get(team_id) or {}), default_team_config):
        raw = source.get(TEAM_CONFIG_WITHHELD_SKILLS)
        if isinstance(raw, list) and all(isinstance(name, str) for name in raw):
            return {name for name in raw if isinstance(name, str)}
    return set()


def withheld_skills_for_team(canonical_team_id: int) -> set[str]:
    """Resolve the holdback denylist for one (canonical) team in a single flag-payload read.

    The coordinator resolves withholding from a payload it already read for the tick; this is the
    one-shot equivalent for request-context callers (the on-demand `signals-scout-config-sync`
    endpoint), so the HTTP path enforces the same holdback as the scheduled path and a held-back
    scout can't be seeded/enabled by a manual fleet materialization. `canonical_team_id` must be
    the parent/project id; `team_configs` keys are canonicalized so a child-keyed override still
    resolves. A missing/unreadable payload yields an empty set (nothing withheld).
    """
    payload = _read_flag_payload()
    team_configs = _canonicalize_team_config_keys(_team_configs(payload))
    return _resolve_withheld_skills(canonical_team_id, team_configs, _default_team_config(payload))


def resolve_sync_seed_inputs(canonical_team_id: int) -> tuple[list[dict], set[str]]:
    """One flag-payload read → `(seed_config_layers, withheld_skills)` for the on-demand `sync` path.

    The `sync` endpoint needs both the seed posture and the holdback denylist; resolving them from a
    single read keeps them on the same snapshot (the same single-read discipline the coordinator
    uses), so the withheld set and the seed layers can't be derived from two different flag states if
    the flag changes mid-request.

    `seed_config_layers` (most-specific first: the team's `team_configs` override over the fleet
    `default_team_config`) mirror what the coordinator builds for the scheduled path, so the on-demand
    materialization (the product-autonomy-gated wizard's self-driving program) seeds the SAME launch
    posture (e.g. general-only, daily) instead of the full fleet enabled — without this the self-serve
    path silently bypassed the launch cost posture. `canonical_team_id` must be the parent/project id;
    `team_configs` keys are canonicalized so a child-keyed override still resolves. A missing/unreadable
    payload yields `([{}, {}], set())` → the historical full-fleet seed, nothing withheld.
    """
    payload = _read_flag_payload()
    team_configs = _canonicalize_team_config_keys(_team_configs(payload))
    default_team_config = _default_team_config(payload)
    seed_config_layers = [team_configs.get(canonical_team_id) or {}, default_team_config]
    withheld = _resolve_withheld_skills(canonical_team_id, team_configs, default_team_config)
    return seed_config_layers, withheld


def _runs_today_by_team(team_ids: set[int], window_start: datetime) -> dict[int, int]:
    """Scout runs dispatched per team within the trailing daily-budget window.

    Counts `SignalScoutRun` bridge rows (created at run start), so the budget tracks runs that
    actually happened — the durable, cost-relevant signal. Uses the unscoped `all_teams` manager,
    matching the coordinator's other cross-team reads. A run dispatched this tick but not yet
    started isn't counted until its row lands; the per-tick cap bounds that brief window.
    """
    if not team_ids:
        return {}
    rows = (
        SignalScoutRun.all_teams.filter(team_id__in=team_ids, created_at__gte=window_start)
        .values("team_id")
        .annotate(n=Count("id"))
    )
    return {row["team_id"]: row["n"] for row in rows}


def _canonicalize_team_config_keys(team_configs: dict[int, dict]) -> dict[int, dict]:
    """Remap child-env config keys to their parent project id so per-team overrides line up with
    the canonical team ids planning uses — `_participating_teams` canonicalizes enrollment the
    same way, so an operator listing a child env id in both `guaranteed_team_ids` and
    `team_configs` keeps its override. If both a parent and one of its child envs are keyed, the
    explicit parent-keyed config wins regardless of dict order."""
    if not team_configs:
        return team_configs
    parent_of = {
        team_id: (parent_id or team_id)
        for team_id, parent_id in Team.objects.filter(id__in=team_configs.keys()).values_list("id", "parent_team_id")
    }
    canonical: dict[int, dict] = {}
    for team_id, config in team_configs.items():
        canonical_id = parent_of.get(team_id, team_id)
        # A parent/standalone key (team_id == canonical_id) always wins; a child remap only
        # fills in when no parent-keyed config is present for that project.
        if team_id == canonical_id or canonical_id not in canonical:
            canonical[canonical_id] = config
    return canonical


def read_banner_message(payload: dict | None) -> str | None:
    """Editorial alpha/announcement banner from the flag payload, or `None` when unset.

    Absent key, non-string value, or a blank/whitespace-only string all collapse to `None` so the
    UIs render nothing rather than an empty banner.
    """
    if payload is None:
        return None
    message = payload.get(SIGNALS_SCOUT_BANNER_KEY)
    if not isinstance(message, str):
        return None
    return message.strip() or None


def _is_team_enrolled(canonical_team_id: int, enrolled_ids: set[int]) -> bool:
    """Whether a canonical project runs scouts, canonicalizing any child-env entries in the
    enrolled set to their parent the same way `_participating_teams` does — so an operator can
    list either the child env id or the parent project id in `guaranteed_team_ids`."""
    if canonical_team_id in enrolled_ids:
        return True
    canonical_enrolled = {
        (parent_id or team_id)
        for team_id, parent_id in Team.objects.filter(id__in=enrolled_ids).values_list("id", "parent_team_id")
    }
    return canonical_team_id in canonical_enrolled


def _resolve_enrolled(canonical_team_id: int, enrollment: Enrollment) -> bool:
    """Whether a project runs scouts, honoring the `"*"` wildcard.

    A skipped team is never enrolled. Otherwise enrolled iff the wildcard is set (everyone is in —
    the UI gates whether they actually HAVE configs) or the team is in the explicit allowlist.
    Canonicalizes child-env ids the same way the coordinator does (`_is_team_enrolled`)."""
    if _is_team_enrolled(canonical_team_id, enrollment.skip):
        return False
    if enrollment.wildcard:
        return True
    return _is_team_enrolled(canonical_team_id, enrollment.explicit)


@dataclass(frozen=True)
class ScoutTeamLimits:
    """A team's effective scout run caps + current usage, all resolved the way dispatch enforces."""

    max_runs_per_tick: int
    max_runs_per_day: int | None
    runs_today: int
    runs_remaining_today: int | None


@dataclass(frozen=True)
class ScoutTeamMetadata:
    """Team-scoped scout metadata for the UI surfaces: enrollment, the editorial banner, and the
    enforced limits/usage. The banner is fleet-wide (one string in the flag); limits are per-team."""

    enrolled: bool
    banner_message: str | None
    limits: ScoutTeamLimits

    def as_dict(self) -> dict:
        return {
            "enrolled": self.enrolled,
            "banner_message": self.banner_message,
            "limits": {
                "max_runs_per_tick": self.limits.max_runs_per_tick,
                "max_runs_per_day": self.limits.max_runs_per_day,
                "runs_today": self.limits.runs_today,
                "runs_remaining_today": self.limits.runs_remaining_today,
            },
        }


def resolve_team_metadata(canonical_team_id: int) -> ScoutTeamMetadata:
    """Resolve a team's enforced scout limits + the announcement banner from the `signals-scout`
    flag, in one flag-payload read.

    `canonical_team_id` must be the parent/project id (the HTTP surface passes
    `_canonical_team_id(view)`). Caps use the exact three-layer resolution the coordinator
    enforces at dispatch (`team_configs[team]` → `default_team_config` → code constant), so the
    reported numbers match what dispatch actually allows — the whole point of the endpoint is to
    show the user the *enforced* throttle, not the value they think they set. `runs_today` is the
    trailing-24h dispatched-run count; `runs_remaining_today` is `None` when the daily budget is
    unbounded.
    """
    payload = _read_flag_payload()
    team_configs = _canonicalize_team_config_keys(_team_configs(payload))
    default_team_config = _default_team_config(payload)

    max_runs_per_day = _resolve_max_runs_per_day(canonical_team_id, team_configs, default_team_config)
    runs_today = _runs_today_by_team({canonical_team_id}, timezone.now() - DAILY_BUDGET_WINDOW).get(
        canonical_team_id, 0
    )
    runs_remaining_today = None if max_runs_per_day is None else max(0, max_runs_per_day - runs_today)

    return ScoutTeamMetadata(
        enrolled=_resolve_enrolled(canonical_team_id, _parse_enrollment(payload)),
        banner_message=read_banner_message(payload),
        limits=ScoutTeamLimits(
            max_runs_per_tick=_resolve_max_runs_per_tick(canonical_team_id, team_configs, default_team_config),
            max_runs_per_day=max_runs_per_day,
            runs_today=runs_today,
            runs_remaining_today=runs_remaining_today,
        ),
    )
