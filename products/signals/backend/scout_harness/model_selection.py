"""Resolve which LLM the scout agent runs on, from the `scouts-model-selection` flag payload.

Default posture: leave the agent model unset (`None`) so the sandbox agent server uses its
built-in default. The flag lets scouts be routed onto other models — for no-deploy A/B/n trials of
new models (open-weights GLM, a newer GPT, …) against the default on the real scout workload. The
resolved model is passed — together with the runtime adapter that can serve it — straight through
`CustomPromptSandboxContext` → `Task.create_and_run` → the agent server, and per-run model is tagged
on each `$ai_generation` so runs are comparable by model in LLM analytics. The runtime adapter must
travel with the model: the agent server only knows two runtimes (`claude` → Anthropic, `codex` →
OpenAI) and derives the provider from the runtime, so a model id handed over with no runtime can't be
routed and silently falls back to the server default.

Everything is driven by the flag's JSON payload, keyed by team → scout → model, so a single payload
configures any number of teams (team 2, internal side projects, …) with a different model mix each —
no per-team release-condition fiddling and no deploy. Like the sibling `signals-scout` flag in
`team_limits.py`, the flag is kept 100%-on and the payload (read once via a synthetic discovery
distinct_id) is the single source of truth; a team with no entry runs entirely on the default model.

    {
        "teams": {
            "2": {
                "scouts": {
                    "signals-scout-team-self-driving": {"@cf/zai-org/glm-5.2": 0.2, "gpt-5.5": 0.2},
                    "signals-scout-signals-dashboards": {"@cf/zai-org/glm-5.2": 0.25}
                }
            },
            "112495": {"scouts": {"*": {"@cf/zai-org/glm-5.2": 0.5}}}
        }
    }

- `teams` — `{team_id: {"scouts": {...}}}`. A team is configured iff it has an entry (or the `"*"`
  team wildcard applies); either the canonical project id or a child-env id key resolves.
- `scouts` — `{skill_name: {model_id: fraction}}`. Each value maps a model id to the fraction of
  that scout's runs (0..1) it serves. `signals-scout-team-self-driving` above runs 20% on glm-5.2,
  20% on gpt-5.5, and the remaining 60% on the agent-server default. `"*"` is the fallback
  distribution for scouts not listed explicitly. A model's value may instead be an object
  `{"fraction": 0.2, "runtime_adapter": "codex"}` to pin its runtime explicitly; with the bare-number
  form the runtime is inferred from the id (`claude-*` → `claude`, everything else → `codex`).
- The reserved `"default"` key inside a scout's map names the model the *remaining* (unallocated)
  runs use instead of the agent-server default — its value is a model-id string, not a fraction.

Each run is bucketed deterministically on `run_id`, so a scout A/Bs against itself across runs and
the per-run decision is reproducible. An absent payload / no matching team or scout / read failure
all resolve to `None` — the agent-server default. Gating the model must never be able to fail a run.

This is separate from the `signals-scout` enrollment/limits flag — that decides *whether* a team
runs scouts; this decides *on which model*.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

SCOUTS_MODEL_FLAG = "scouts-model-selection"

# Fixed distinct_id for the payload read — config is team-keyed in the payload, not per-user. Matches
# the `signals-scout` discovery pattern: the flag stays 100%-on so the payload is always served, and
# `match_value=True` forces the true-variant payload under local evaluation.
SCOUTS_MODEL_DISCOVERY_DISTINCT_ID = "internal_scouts_model_selection_discovery"

# Convenience constant for the model we're trialling first; the model ids themselves live entirely
# in the flag payload now, so this is just a well-known id for docs/tests, not special-cased in code.
GLM_MODEL = "@cf/zai-org/glm-5.2"

# Payload structure keys.
TEAMS_KEY = "teams"
SCOUTS_KEY = "scouts"

# Wildcard token, used at both the team level (`teams["*"]`) and the scout level
# (`scouts["*"]`): the fallback applied to any team / scout not listed explicitly.
WILDCARD = "*"

# Reserved key inside a scout's distribution naming the model for the unallocated remainder (instead
# of the agent-server default). Its value is a model-id string, not a fraction — a model id of
# literally "default" is not addressable, which is fine (real ids look like `@cf/...`, `gpt-5.5`).
DEFAULT_MODEL_KEY = "default"

# Keys recognized in the object form of a model entry (the alternative to a bare fraction):
# `{"fraction": <0..1>, "runtime_adapter": "claude"|"codex"}`.
FRACTION_KEY = "fraction"
RUNTIME_ADAPTER_KEY = "runtime_adapter"

# The two agent runtimes the agent server exposes. A model id alone can't be routed — the server
# derives its provider (Anthropic / OpenAI) from the runtime — so every routed model also carries a
# runtime, either pinned in the payload or inferred from the id by `_infer_runtime_adapter`.
RUNTIME_ADAPTER_CLAUDE = "claude"
RUNTIME_ADAPTER_CODEX = "codex"

# The runtimes a payload may pin explicitly. An unknown value (typo, unsupported runtime) is dropped
# back to id inference rather than threaded onward: it would otherwise be written into the run state
# and blow up downstream when cast to the `RuntimeAdapter` enum — failing the run the gate must never
# be able to break.
_KNOWN_RUNTIME_ADAPTERS = frozenset({RUNTIME_ADAPTER_CLAUDE, RUNTIME_ADAPTER_CODEX})


@dataclass(frozen=True)
class ScoutModel:
    """The agent-model override resolved for one scout run.

    `model` is the model id; `None` keeps the agent-server default (and `runtime_adapter` is then
    also `None`). When a model is chosen, `runtime_adapter` names the agent runtime that can serve it
    — it must travel with the model because the agent server derives the LLM provider from the
    runtime, and a model id handed over with no runtime can't be routed (it silently falls back to
    the server default, which is the bug this resolution exists to avoid).
    """

    model: str | None
    runtime_adapter: str | None


def _infer_runtime_adapter(model_id: str) -> str:
    """The agent runtime that can serve `model_id`, inferred from the id.

    Anthropic ids (`claude-*`, `bedrock/...anthropic.claude-*`) route to the `claude` runtime;
    everything else — GPT ids and the open-weights `@cf/...` GLM ids, all OpenAI-compatible — routes
    to the `codex` runtime. An explicit `runtime_adapter` in the payload overrides this.
    """
    return RUNTIME_ADAPTER_CLAUDE if "claude" in model_id.lower() else RUNTIME_ADAPTER_CODEX


def _read_payload() -> dict | None:
    """Read + parse the `scouts-model-selection` flag's JSON payload once.

    The flag must stay 100%-on so the payload is served for the synthetic discovery distinct_id;
    `match_value=True` forces the true-variant payload under local evaluation. Returns the parsed
    dict, or `None` when the payload is absent / not an object / unreadable. A read error never
    breaks a run — the caller falls back to the default model.
    """
    try:
        payload = posthoganalytics.get_feature_flag_payload(
            SCOUTS_MODEL_FLAG, SCOUTS_MODEL_DISCOVERY_DISTINCT_ID, match_value=True
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as error:
        capture_exception(error)
        return None


def _team_scouts(payload: object, team_id: int, canonical_team_id: int) -> dict:
    """The `{skill_name: {...}}` scout map configured for a team, or `{}` when none applies.

    Looks up `teams[team_id]`, then `teams[canonical_team_id]` (so an operator can key by either the
    child-env id or the parent project id), then the `"*"` team wildcard. Returns the entry's
    `scouts` map. Defensive — a non-object payload / `teams` / team entry / `scouts` value yields
    `{}` (the team runs on the default model).
    """
    if not isinstance(payload, dict):
        return {}
    teams = payload.get(TEAMS_KEY)
    if not isinstance(teams, dict):
        return {}

    entry: object = None
    for key in (str(team_id), str(canonical_team_id), WILDCARD):
        candidate = teams.get(key)
        if isinstance(candidate, dict):
            entry = candidate
            break
    if not isinstance(entry, dict):
        return {}

    scouts = entry.get(SCOUTS_KEY)
    return scouts if isinstance(scouts, dict) else {}


def _parse_model_spec(spec: object) -> tuple[float | None, str | None]:
    """A `(fraction, runtime_adapter)` from one model entry's value.

    A model entry's value is either a bare number (its fraction; runtime inferred from the id) or an
    object `{"fraction": <0..1>, "runtime_adapter": "claude"|"codex"}` that pins the runtime
    explicitly. Returns `(None, ...)` for a malformed fraction (not a positive number, or a bool) so
    the caller drops the entry rather than failing the run. A `runtime_adapter` that isn't one of the
    known runtimes (non-string, typo, unsupported) is ignored (treated as unset → inferred from the
    id), so a payload typo can't route the run onto a runtime the agent server can't honor.
    """
    if isinstance(spec, dict):
        weight = spec.get(FRACTION_KEY)
        adapter_value = spec.get(RUNTIME_ADAPTER_KEY)
        # `isinstance` first: an unhashable value (JSON array/object) would raise from the set
        # membership test, and that escapes `_read_payload`'s guard and would fail the run.
        adapter = adapter_value if isinstance(adapter_value, str) and adapter_value in _KNOWN_RUNTIME_ADAPTERS else None
    else:
        weight = spec
        adapter = None
    if not isinstance(weight, int | float) or isinstance(weight, bool) or weight <= 0:
        return None, adapter
    return min(1.0, float(weight)), adapter


def _scout_config(scouts: dict, skill_name: str) -> tuple[dict[str, float], dict[str, str], str | None]:
    """The `(distribution, adapters, default_model)` for one scout from a team's scout map.

    Looks up `scouts[skill_name]`, falling back to the `"*"` scout wildcard. The reserved `"default"`
    string key is pulled out as `default_model` (the model for the unallocated remainder; `None` =
    agent-server default); every other entry is a `model_id -> fraction | {fraction, runtime_adapter}`
    weight. `adapters` carries only the model ids whose runtime was pinned explicitly in the payload;
    the rest are inferred from the id at resolve time. Defensive — a missing/non-object scout entry,
    or a malformed weight (not a positive number, or a bool) is dropped rather than failing the run,
    so a typo can't crash a scout or route it unintended.
    """
    raw = scouts.get(skill_name)
    if not isinstance(raw, dict):
        raw = scouts.get(WILDCARD)
    if not isinstance(raw, dict):
        return {}, {}, None

    default_value = raw.get(DEFAULT_MODEL_KEY)
    default_model = default_value if isinstance(default_value, str) and default_value else None

    distribution: dict[str, float] = {}
    adapters: dict[str, str] = {}
    for model_id, spec in raw.items():
        if model_id == DEFAULT_MODEL_KEY:
            continue
        if not isinstance(model_id, str) or not model_id:
            continue
        fraction, adapter = _parse_model_spec(spec)
        if fraction is None:
            continue
        distribution[model_id] = fraction
        if adapter is not None:
            adapters[model_id] = adapter
    return distribution, adapters, default_model


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


def resolve_scout_model(team: Team, skill_name: str, run_id: str) -> ScoutModel:
    """The agent-model override for one scout run, with the runtime that can serve it.

    Resolves this team's scout map from the `scouts-model-selection` payload, then this scout's
    per-run model from its distribution, then the runtime adapter for the chosen model (pinned in the
    payload, else inferred from the id). Returns `ScoutModel(None, None)` (agent-server default) when
    the team has no entry, the scout has no distribution, or the run falls in the unallocated
    remainder with no named `default`. A payload read failure is swallowed and falls back to the
    default model — gating the model must never be able to fail a scout run.
    """
    payload = _read_payload()
    scouts = _team_scouts(payload, team.id, team.parent_team_id or team.id)
    distribution, adapters, default_model = _scout_config(scouts, skill_name)
    model = _select_model(run_id, distribution, default_model)
    if model is None:
        return ScoutModel(model=None, runtime_adapter=None)
    return ScoutModel(model=model, runtime_adapter=adapters.get(model) or _infer_runtime_adapter(model))
