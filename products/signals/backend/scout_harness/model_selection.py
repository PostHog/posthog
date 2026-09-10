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
  `{"fraction": 0.2, "runtime_adapter": "codex", "reasoning_effort": "high", "service_tier": "flex"}`
  to pin its runtime (and optionally the reasoning effort and the OpenAI service tier) explicitly;
  with the bare-number form the runtime is inferred from the id (`claude-*` → `claude`, everything
  else → `codex`) and the effort and tier are left unset (agent-server default). A tier on a slice
  is what makes a same-model A/B on queueing possible: one explicit `gpt-5.6-terra` slice pinned to
  `flex` against the unallocated remainder falling through to the `signals-pipeline-models` pin for
  the same model on the standard queue.
- The reserved `"default"` key inside a scout's map names the model the *remaining* (unallocated)
  runs use instead of the agent-server default — its value is a model-id string, not a fraction.

Each run is bucketed deterministically on `run_id`, so a scout A/Bs against itself across runs and
the per-run decision is reproducible. An absent payload / no matching team or scout / read failure
all resolve to `None` — the agent-server default. Gating the model must never be able to fail a run.

This is separate from the `signals-scout` enrollment/limits flag — that decides *whether* a team
runs scouts; this decides *on which model*.

One layer sits above the payload: a per-scout `SignalScoutConfig.model` pin, honored only while the
`scouts-model-config` dogfood flag is on for the team (`scout_model_config_enabled`). An explicit
pin routes every run of that scout onto its model deterministically — no bucketing — and beats the
payload's distribution; everything else falls through to the payload as described above.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

from products.signals.backend.agent_runtime import KNOWN_SERVICE_TIERS
from products.tasks.backend.facade.run_config import get_models_for_runtime_adapter

SCOUTS_MODEL_FLAG = "scouts-model-selection"

# Dogfood gate for the per-scout config layer: only while this flag is on for the team does a
# `SignalScoutConfig.model` pin actually route runs. Distinct from `scouts-model-selection` (an
# operator-keyed payload for fleet A/B trials, always-on with the payload as the config): this one
# is a plain boolean flag over teams, because what it gates is whether the team's own stored
# config is honored, not what the config says. Keeping the gate at resolve time (not at write
# time only) makes turning the flag off an immediate kill switch for already-stored pins.
SCOUTS_MODEL_CONFIG_FLAG = "scouts-model-config"

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
# `{"fraction": <0..1>, "runtime_adapter": "claude"|"codex", "reasoning_effort": "high",
# "service_tier": "flex"}`.
FRACTION_KEY = "fraction"
RUNTIME_ADAPTER_KEY = "runtime_adapter"
REASONING_EFFORT_KEY = "reasoning_effort"
SERVICE_TIER_KEY = "service_tier"

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

# The reasoning efforts a payload may pin, mirroring the tasks `ReasoningEffort` enum. Same
# defensive posture as `_KNOWN_RUNTIME_ADAPTERS`: an unknown value is dropped (effort unset,
# agent-server default) rather than threaded into the run state where it could fail the run.
_KNOWN_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})

# The OpenAI service tiers a payload may pin, mirroring the agent server's `ServiceTier` enum. Same
# defensive posture again: an unknown value is dropped (tier unset, standard queue) rather than
# threaded into the run state where it could fail the run. Shared with the pipeline pin parser.
_KNOWN_SERVICE_TIERS = KNOWN_SERVICE_TIERS


@dataclass(frozen=True)
class ScoutModel:
    """The agent-model override resolved for one scout run.

    `model` is the model id; `None` keeps the agent-server default (and `runtime_adapter` /
    `reasoning_effort` are then also `None`). When a model is chosen, `runtime_adapter` names the
    agent runtime that can serve it — it must travel with the model because the agent server derives
    the LLM provider from the runtime, and a model id handed over with no runtime can't be routed
    (it silently falls back to the server default, which is the bug this resolution exists to
    avoid). `reasoning_effort` is the optional per-model effort pin from the payload's object form;
    `None` keeps the agent-server default effort. `service_tier` is the optional OpenAI queue pin
    from the same form (`flex` / `priority` / `default`); `None` means the slice asked for no queue,
    and the tier never crosses from another model's pin, so a slice can A/B queueing against the
    unallocated remainder running the same model on the `signals-pipeline-models` pin's tier.
    """

    model: str | None
    runtime_adapter: str | None
    reasoning_effort: str | None = None
    service_tier: str | None = None


def _infer_runtime_adapter(model_id: str) -> str:
    """The agent runtime that can serve `model_id`, inferred from the id.

    Anthropic ids (`claude-*`, `bedrock/...anthropic.claude-*`) route to the `claude` runtime;
    everything else — GPT ids and the open-weights `@cf/...` GLM ids, all OpenAI-compatible — routes
    to the `codex` runtime. An explicit `runtime_adapter` in the payload overrides this.
    """
    return RUNTIME_ADAPTER_CLAUDE if "claude" in model_id.lower() else RUNTIME_ADAPTER_CODEX


def scout_model_pin_catalog() -> tuple[str, ...]:
    """The model ids a `SignalScoutConfig.model` pin may carry: the canonical Tasks catalog, both
    runtimes. The config API validates pins against this, unlike the free-form payload path — a pin
    has no runtime-pinning escape hatch, so an off-catalog id would be stored with nothing
    authoritative to route it by."""
    return (
        *get_models_for_runtime_adapter(RUNTIME_ADAPTER_CLAUDE),
        *get_models_for_runtime_adapter(RUNTIME_ADAPTER_CODEX),
    )


def _runtime_adapter_for_pin(model_id: str) -> str:
    """The runtime for a config-pinned model: the canonical Tasks catalog first, name inference as
    the fallback.

    The catalog is what knows the ids whose runtime can't be read off the name — the
    Cloudflare-served `@cf/...` and `moonshotai/...` models run on the `claude` runtime (the
    gateway serves them over its Anthropic-Messages surface), where name inference would say
    `codex`. The fallback only covers stored pins that have since left the catalog; the payload
    path keeps pure name inference, because changing it would reroute live trial distributions and
    the payload's object form can already pin a runtime explicitly.
    """
    if model_id in get_models_for_runtime_adapter(RUNTIME_ADAPTER_CLAUDE):
        return RUNTIME_ADAPTER_CLAUDE
    if model_id in get_models_for_runtime_adapter(RUNTIME_ADAPTER_CODEX):
        return RUNTIME_ADAPTER_CODEX
    return _infer_runtime_adapter(model_id)


def scout_model_config_enabled(team: Team) -> bool:
    """Whether this team's per-scout `SignalScoutConfig.model` pins are honored (dogfood gate).

    Keyed on the `project` group the same way the web app registers it (group key = the team's
    uuid, `id` = the numeric project id), so one flag definition — a project-group condition on
    `id` — serves both this server-side check and the frontend's gated settings UI. `id` carries
    the canonical parent id so a child environment follows its project's enrollment server-side;
    the frontend registers a child environment's own id, so a condition that should also show the
    UI inside child environments must list their ids too. Fails closed on a flag-read error: an
    unhonored pin just means the default resolution chain, never a broken run.
    """
    try:
        canonical_team_id = team.parent_team_id or team.id
        return (
            posthoganalytics.feature_enabled(
                SCOUTS_MODEL_CONFIG_FLAG,
                str(team.uuid),
                groups={"project": str(team.uuid)},
                group_properties={"project": {"id": canonical_team_id, "uuid": str(team.uuid)}},
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception as error:
        capture_exception(error)
        return False


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


@frozen
class _ModelSpec:
    """One parsed model entry: its fraction plus whichever pins the object form carried.

    `fraction` is `None` for a malformed weight so the caller drops the entry. The pins are `None`
    when absent or unrecognized, never a value the agent server can't honor.
    """

    fraction: float | None
    runtime_adapter: str | None = None
    reasoning_effort: str | None = None
    service_tier: str | None = None


def _known_str(value: object, known: frozenset[str]) -> str | None:
    # `isinstance` first: an unhashable value (JSON array/object) would raise from the set
    # membership test, and that escapes `_read_payload`'s guard and would fail the run.
    return value if isinstance(value, str) and value in known else None


def _parse_model_spec(spec: object) -> _ModelSpec:
    """The fraction and pins from one model entry's value.

    A model entry's value is either a bare number (its fraction; runtime inferred from the id,
    effort and tier unset) or an object `{"fraction": <0..1>, "runtime_adapter": "claude"|"codex",
    "reasoning_effort": "high", "service_tier": "flex"}` that pins the runtime (and optionally the
    effort and the OpenAI queue) explicitly. A malformed fraction (not a positive number, or a bool)
    yields `fraction=None` so the caller drops the entry rather than failing the run. A pin that
    isn't one of the known values (non-string, typo, unsupported) is ignored (treated as unset), so
    a payload typo can't route the run onto a runtime, effort, or queue the agent server can't honor.
    """
    if not isinstance(spec, dict):
        return _ModelSpec(fraction=_parse_fraction(spec))
    return _ModelSpec(
        fraction=_parse_fraction(spec.get(FRACTION_KEY)),
        runtime_adapter=_known_str(spec.get(RUNTIME_ADAPTER_KEY), _KNOWN_RUNTIME_ADAPTERS),
        reasoning_effort=_known_str(spec.get(REASONING_EFFORT_KEY), _KNOWN_REASONING_EFFORTS),
        service_tier=_known_str(spec.get(SERVICE_TIER_KEY), _KNOWN_SERVICE_TIERS),
    )


def _parse_fraction(weight: object) -> float | None:
    if not isinstance(weight, int | float) or isinstance(weight, bool) or weight <= 0:
        return None
    return min(1.0, float(weight))


def _scout_config(scouts: dict, skill_name: str) -> tuple[dict[str, _ModelSpec], str | None]:
    """The `(specs, default_model)` for one scout from a team's scout map.

    Looks up `scouts[skill_name]`, falling back to the `"*"` scout wildcard. The reserved `"default"`
    string key is pulled out as `default_model` (the model for the unallocated remainder; `None` =
    agent-server default); every other entry is a `model_id -> fraction | {fraction, runtime_adapter,
    reasoning_effort, service_tier}` weight, parsed into a `_ModelSpec`. Unpinned runtimes are
    inferred from the id at resolve time; unpinned efforts and tiers stay unset. Defensive — a
    missing/non-object scout entry, or a malformed weight (not a positive number, or a bool) is
    dropped rather than failing the run, so a typo can't crash a scout or route it unintended.
    """
    raw = scouts.get(skill_name)
    if not isinstance(raw, dict):
        raw = scouts.get(WILDCARD)
    if not isinstance(raw, dict):
        return {}, None

    default_value = raw.get(DEFAULT_MODEL_KEY)
    default_model = default_value if isinstance(default_value, str) and default_value else None

    specs: dict[str, _ModelSpec] = {}
    for model_id, spec in raw.items():
        if model_id == DEFAULT_MODEL_KEY:
            continue
        if not isinstance(model_id, str) or not model_id:
            continue
        parsed = _parse_model_spec(spec)
        if parsed.fraction is None:
            continue
        specs[model_id] = parsed
    return specs, default_model


def _bucket(run_id: str) -> float:
    """A stable value in [0, 1) derived from `run_id` — the per-run draw used for selection.

    A hash of the run id (not a random draw) so the model a run gets is reproducible: the same run
    always resolves the same model, which keeps tests deterministic and lets a run's model be
    re-derived after the fact. Over many runs the buckets are uniform, so observed model shares
    converge on the configured fractions.
    """
    return int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8], "big") / 2**64


def _select_model(
    run_id: str, specs: dict[str, _ModelSpec], default_model: str | None
) -> tuple[str | None, _ModelSpec | None]:
    """Pick a model for this run from the scout's distribution, deterministically on `run_id`.

    Walks the models in sorted-id order accumulating their fractions; the run's bucket falls into
    exactly one model's slice, or past them all into the remainder → `default_model`. Sorted order
    makes the assignment stable across runs/processes. If the fractions sum to ≥ 1 the remainder is
    empty and `default_model` simply never runs. Returns the selected slice's spec alongside the
    model, and `None` for the remainder: which branch picked the model is decided here, not
    recovered from the model id, so a remainder that names the same model as a weighted slice
    (`{"gpt-5.6-terra": {"fraction": 0.05, "service_tier": "flex"}, "default": "gpt-5.6-terra"}`)
    stays the pin-free control instead of inheriting the slice's tier.
    """
    cumulative = 0.0
    for model_id in sorted(specs):
        spec = specs[model_id]
        cumulative += spec.fraction if spec.fraction is not None else 0.0
        if _bucket(run_id) < cumulative:
            return model_id, spec
    return default_model, None


def resolve_scout_model(team: Team, skill_name: str, run_id: str, configured_model: str | None = None) -> ScoutModel:
    """The agent-model override for one scout run, with the runtime that can serve it.

    `configured_model` is the scout's own `SignalScoutConfig.model` pin. It is the top layer: while
    the `scouts-model-config` dogfood flag is on for the team, an explicit per-scout pin beats the
    `scouts-model-selection` experiment distribution — a user deliberately configured that scout,
    and an operator trial must not silently reroute it. With the flag off (or no pin) resolution
    falls through unchanged: this team's scout map from the `scouts-model-selection` payload, then
    this scout's per-run model from its distribution, then the runtime adapter for the chosen model
    (pinned in the payload, else inferred from the id). Returns `ScoutModel(None, None)`
    (agent-server default) when nothing applies. A flag or payload read failure is swallowed and
    falls back to the next layer — gating the model must never be able to fail a scout run.
    """
    if configured_model and scout_model_config_enabled(team):
        return ScoutModel(model=configured_model, runtime_adapter=_runtime_adapter_for_pin(configured_model))
    payload = _read_payload()
    scouts = _team_scouts(payload, team.id, team.parent_team_id or team.id)
    specs, default_model = _scout_config(scouts, skill_name)
    model, spec = _select_model(run_id, specs, default_model)
    if model is None:
        return ScoutModel(model=None, runtime_adapter=None)
    if spec is None:
        # The `default` remainder carries no pins, even when a weighted slice names the same model.
        return ScoutModel(model=model, runtime_adapter=_infer_runtime_adapter(model))
    return ScoutModel(
        model=model,
        runtime_adapter=spec.runtime_adapter or _infer_runtime_adapter(model),
        reasoning_effort=spec.reasoning_effort,
        service_tier=spec.service_tier,
    )
