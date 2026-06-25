"""Resolve which LLM the scout agent runs on, gated by the `scouts-model-selection` flag.

Default posture: leave the agent model unset (`None`) so the sandbox agent server uses its
built-in default. The flag lets scouts be routed onto other models — for no-deploy A/B/n trials of
new models (open-weights GLM, a newer GPT, …) against the default on the real scout workload. The
resolved string is passed straight through `CustomPromptSandboxContext.model` → `Task.create_and_run`
→ the agent server, and per-run model is tagged on each `$ai_generation` so runs are comparable by
model in LLM analytics.

The flag's *release conditions* pick which teams are eligible (target team 2's project group in the
flag UI). Its JSON *payload* is a per-scout model distribution, so within an eligible team each scout
can be split across models per run — a team isn't all-or-nothing, and eager dogfooders on a shared
team aren't all flipped onto an unproven model at once:

    {
        "scouts": {
            "signals-scout-team-self-driving": {"@cf/zai-org/glm-5.2": 0.2, "gpt-5.5": 0.2},
            "signals-scout-signals-dashboards": {"@cf/zai-org/glm-5.2": 0.25},
            "*": {"@cf/zai-org/glm-5.2": 0.1}
        }
    }

- `scouts` — `{skill_name: {model_id: fraction}}`. Each value maps a model id to the fraction of
  that scout's runs (0..1) it should serve. `signals-scout-team-self-driving` above runs 20% on
  glm-5.2, 20% on gpt-5.5, and the remaining 60% on the agent-server default.
- The reserved `"default"` key inside a scout's map names the model the *remaining* (unallocated)
  runs use, instead of the agent-server default — e.g. `{"gpt-5.5": 0.2, "default": "@cf/zai-org/glm-5.2"}`
  runs 20% on gpt-5.5 and 80% on glm-5.2. Its value is a model-id string, not a fraction.
- `"*"` is the fallback distribution applied to any scout not listed explicitly.

Each run is bucketed deterministically on `run_id`, so a scout A/Bs against itself across runs and
the per-run decision is reproducible. An absent payload / disabled flag / read failure all resolve
to `None` — the agent-server default. Gating the model must never be able to fail a scout run.

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

# Per-team gate: release conditions decide which teams are eligible for non-default scout models.
SCOUTS_MODEL_FLAG = "scouts-model-selection"

# Convenience constant for the model we're trialling first; the model ids themselves live entirely
# in the flag payload now, so this is just a well-known id for docs/tests, not special-cased in code.
GLM_MODEL = "@cf/zai-org/glm-5.2"

# Payload key: `{skill_name: {model_id: fraction}}` distribution per scout.
SCOUTS_KEY = "scouts"

# Skill key inside `scouts` that applies to any scout not listed explicitly.
WILDCARD_SKILL = "*"

# Reserved key inside a scout's distribution naming the model for the unallocated remainder
# (instead of the agent-server default). Its value is a model-id string, not a fraction — a model id
# of literally "default" is not addressable, which is fine (real ids look like `@cf/...`, `gpt-5.5`).
DEFAULT_MODEL_KEY = "default"


def _team_flag_kwargs(team: Team) -> dict:
    """Shared evaluation context for the gate + payload reads, so both see the same team match.

    Evaluated against the team's organization + project groups so the rollout can be targeted by
    org or project in the flag UI. `distinct_id` is the stable team uuid; the per-run split is NOT
    expressed via the flag's own rollout % (that would be all-or-nothing per team) — it's the
    payload distribution, bucketed per run in `_select_model`.
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


def _scout_config(payload: object, skill_name: str) -> tuple[dict[str, float], str | None]:
    """The `(distribution, default_model)` for one scout, resolved from the flag payload.

    Looks up `scouts[skill_name]`, falling back to the `"*"` wildcard distribution. The reserved
    `"default"` string key is pulled out as `default_model` (the model for the unallocated
    remainder; `None` = agent-server default); every other entry is a `model_id -> fraction` weight.
    Defensive throughout — a missing/non-object payload, a non-object scout entry, or a malformed
    weight (not a positive number, or a bool) is dropped rather than failing the run, so a typo
    can't crash a scout or silently route it somewhere unintended.
    """
    if not isinstance(payload, dict):
        return {}, None
    scouts = payload.get(SCOUTS_KEY)
    if not isinstance(scouts, dict):
        return {}, None

    raw = scouts.get(skill_name)
    if not isinstance(raw, dict):
        raw = scouts.get(WILDCARD_SKILL)
    if not isinstance(raw, dict):
        return {}, None

    default_value = raw.get(DEFAULT_MODEL_KEY)
    default_model = default_value if isinstance(default_value, str) and default_value else None

    distribution: dict[str, float] = {}
    for model_id, weight in raw.items():
        if model_id == DEFAULT_MODEL_KEY:
            continue
        if not isinstance(model_id, str) or not model_id:
            continue
        if not isinstance(weight, int | float) or isinstance(weight, bool) or weight <= 0:
            continue
        distribution[model_id] = min(1.0, float(weight))
    return distribution, default_model


def _bucket(run_id: str) -> float:
    """A stable value in [0, 1) derived from `run_id` — the per-run draw used for selection.

    A hash of the run id (not a random draw) so the model a run gets is reproducible: the same run
    always resolves the same model, which keeps tests deterministic and lets a run's model be
    re-derived after the fact. Over many runs the buckets are uniform, so observed model shares
    converge on the configured fractions.
    """
    return int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8], "big") / 2**64


def _select_model(run_id: str, distribution: dict[str, float], default_model: str | None) -> str | None:
    """Pick a model for this run from the scout's distribution, deterministically on `run_id`.

    Walks the models in sorted-id order accumulating their fractions; the run's bucket falls into
    exactly one model's slice, or past them all into the remainder → `default_model`. Sorted order
    makes the assignment stable across runs/processes. If the fractions sum to ≥ 1 the remainder is
    empty and `default_model` simply never runs.
    """
    cumulative = 0.0
    for model_id in sorted(distribution):
        cumulative += distribution[model_id]
        if _bucket(run_id) < cumulative:
            return model_id
    return default_model


def resolve_scout_model(team: Team, skill_name: str, run_id: str) -> str | None:
    """The agent-model override for one scout run, or `None` to keep the agent-server default.

    Resolves the team's `scouts-model-selection` gate, then this scout's per-run model from the
    payload distribution. Returns `None` (agent-server default) when the flag is disabled for the
    team, the payload has no distribution for this scout, or the run falls in the unallocated
    remainder with no named `default`. A flag/payload read failure is swallowed and falls back to
    the default model — gating the model must never be able to fail a scout run.
    """
    try:
        kwargs = _team_flag_kwargs(team)
        if not posthoganalytics.feature_enabled(SCOUTS_MODEL_FLAG, **kwargs):
            return None
        payload = posthoganalytics.get_feature_flag_payload(
            SCOUTS_MODEL_FLAG,
            kwargs["distinct_id"],
            groups=kwargs["groups"],
            group_properties=kwargs["group_properties"],
            only_evaluate_locally=False,
        )
    except Exception as error:
        capture_exception(error)
        return None

    distribution, default_model = _scout_config(payload, skill_name)
    return _select_model(run_id, distribution, default_model)
