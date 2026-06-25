"""Resolve which LLM the scout agent runs on, gated by the `scouts-glm` flag.

Default posture: leave the agent model unset (`None`) so the sandbox agent server uses its
built-in default. When `scouts-glm` is enabled for a team, scouts can run on glm-5.2 instead, so an
open-weights model can be compared against the default on the real scout workload with no deploy —
flip the flag and the next dispatched run picks it up. The resolved string is passed straight
through `CustomPromptSandboxContext.model` → `Task.create_and_run` → the agent server.

The flag's *release conditions* pick which teams are eligible (target team 2's project group in the
flag UI). Its JSON *payload* narrows that further so a team isn't all-or-nothing — without exposing
GLM to every eager internal dogfooder on a shared team:

    {
        "enabled_skills": ["signals-scout-team-self-driving", "signals-scout-signals-dashboards"],
        "sample_rate": 0.25
    }

- `enabled_skills` — only these scout skill names get GLM (`"*"` or absent = every scout). Lets a
  trial run on a hand-picked subset of a team's scouts while the rest stay on the default model.
- `sample_rate` — fraction of *runs* (0..1) of an enabled scout that get GLM; absent = all runs.
  Sampled per run (deterministically on `run_id`), so a team can A/B the same scout against itself
  across runs rather than flipping the whole scout at once.

This is a separate gate from the `signals-scout` enrollment/limits payload flag in `team_limits.py`
— that one decides *whether* a team runs scouts; this one decides *on which model*.
"""

from __future__ import annotations

import hashlib

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

# Per-team gate: release conditions decide which teams are eligible for GLM scouts.
SCOUTS_GLM_FLAG = "scouts-glm"

# glm-5.2 as the gateway routes it: the Cloudflare-provider model id, reachable over the Anthropic
# Messages path the sandbox agent speaks (see services/llm-gateway). Passed verbatim as the agent
# model override — the gateway maps it to its Cloudflare backend.
GLM_MODEL = "@cf/zai-org/glm-5.2"

# Payload key: list of scout skill names that may get GLM. `"*"` (or an absent key) means every
# scout on the team. Anything else is treated as an explicit allowlist of `signals-scout-*` names.
ENABLED_SKILLS_KEY = "enabled_skills"

# Payload key: fraction of runs (0..1) of an enabled scout that get GLM. Absent / malformed = all
# runs (1.0). Clamped into [0, 1]; sampled per run on `run_id`.
SAMPLE_RATE_KEY = "sample_rate"

# Wildcard inside `enabled_skills` that opts every scout in, rather than an explicit allowlist.
ENABLE_ALL_SKILLS_TOKEN = "*"


def _team_flag_kwargs(team: Team) -> dict:
    """Shared evaluation context for the gate + payload reads, so both see the same team match.

    Evaluated against the team's organization + project groups so the rollout can be targeted by
    org or project in the flag UI. `distinct_id` is the stable team uuid; per-run percentage is NOT
    expressed here (the flag would then be all-or-nothing per team) — it's the payload's
    `sample_rate`, rolled per run in `_passes_sample`.
    """
    return {
        "distinct_id": str(team.uuid),
        "groups": {"organization": str(team.organization_id), "project": str(team.id)},
        "group_properties": {
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        "only_evaluate_locally": False,
        "send_feature_flag_events": False,
    }


def _skill_enabled(payload: object, skill_name: str) -> bool:
    """Whether `skill_name` is opted into GLM by the flag payload.

    No payload / not an object / absent `enabled_skills` / the `"*"` wildcard → every scout is in
    (the back-compat "all in" posture). An explicit list opts in only its members; a malformed
    `enabled_skills` (not a list of strings) is treated as the wildcard so a typo can't silently
    pin the whole team back to the default model mid-trial.
    """
    if not isinstance(payload, dict):
        return True
    raw = payload.get(ENABLED_SKILLS_KEY)
    if raw is None:
        return True
    if not isinstance(raw, list) or not all(isinstance(name, str) for name in raw):
        return True
    if ENABLE_ALL_SKILLS_TOKEN in raw:
        return True
    return skill_name in raw


def _resolve_sample_rate(payload: object) -> float:
    """The per-run sample rate from the payload, clamped into [0, 1]. Absent / malformed → 1.0."""
    if not isinstance(payload, dict):
        return 1.0
    raw = payload.get(SAMPLE_RATE_KEY)
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        return 1.0
    return max(0.0, min(1.0, float(raw)))


def _passes_sample(run_id: str, rate: float) -> bool:
    """Whether this run falls in the GLM sample, decided deterministically from `run_id`.

    A stable hash of the run id (not a random draw) buckets each run into [0, 1) so the decision is
    reproducible — the same run always resolves the same model, which keeps tests deterministic and
    lets a run's model be re-derived after the fact. Over many runs the buckets are uniform, so the
    GLM share converges on `rate`. `rate >= 1` short-circuits to always-on (the common case).
    """
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    bucket = int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8], "big") / 2**64
    return bucket < rate


def resolve_scout_model(team: Team, skill_name: str, run_id: str) -> str | None:
    """The agent-model override for one scout run, or `None` to keep the agent-server default.

    Returns `GLM_MODEL` only when ALL of: the `scouts-glm` flag is enabled for the team, the
    payload opts `skill_name` in (`enabled_skills`), and this run falls in the payload's
    `sample_rate` bucket. Otherwise `None`. A flag/payload read failure is swallowed and falls back
    to the default model — gating the model must never be able to fail a scout run.
    """
    try:
        kwargs = _team_flag_kwargs(team)
        if not posthoganalytics.feature_enabled(SCOUTS_GLM_FLAG, **kwargs):
            return None
        payload = posthoganalytics.get_feature_flag_payload(
            SCOUTS_GLM_FLAG,
            kwargs["distinct_id"],
            groups=kwargs["groups"],
            group_properties=kwargs["group_properties"],
            only_evaluate_locally=False,
        )
    except Exception as error:
        capture_exception(error)
        return None

    if not _skill_enabled(payload, skill_name):
        return None
    if not _passes_sample(run_id, _resolve_sample_rate(payload)):
        return None
    return GLM_MODEL
