"""Per-team, per-step agent runtime/model overrides for the signals agentic steps, resolved from
the `signals-pipeline-models` flag payload.

Each agentic step (report research, repo selection, scout, custom-agent loops) can be pinned to a
different runtime/model/effort per team, with no deploy — e.g. trial Codex + gpt-5.5 on `research`
for one team while everyone else stays on the default Claude runtime. Mirrors the `signals-scout`
payload pattern in `scout_harness/team_limits.py`: one 100%-on payload flag, read for a synthetic
discovery distinct_id, parsed defensively so a malformed payload falls back to the agent-server
default rather than breaking a run.

Payload shape (`team_configs` maps team id — or the `*` wildcard — to per-step overrides):

    {
      "team_configs": {
        "2": {
          "steps": {
            "research": {"runtime_adapter": "codex", "model": "gpt-5.5", "reasoning_effort": "xhigh"},
            "repo_selection": {"runtime_adapter": "codex", "model": "gpt-5.5"},
            "*": {"model": "claude-sonnet-4-6"}
          }
        },
        "*": {"steps": {"research": {"runtime_adapter": "codex", "model": "gpt-5.5", "reasoning_effort": "xhigh"}}}
      }
    }

Resolution for `(team_id, step)` is most-specific-first, first match wins (atomic — a step block's
fields are taken as a set so a Codex runtime never pairs with a Claude model):

    team_configs[team_id].steps[step]
    → team_configs[team_id].steps["*"]
    → team_configs["*"].steps[step]
    → team_configs["*"].steps["*"]
    → default (agent-server Claude runtime)

A resolved override threads through `CustomPromptSandboxContext`
(runtime_adapter/model/reasoning_effort) → `Task.create_and_run` → the run state → the agent server
(see `products/tasks` RuntimeAdapter). A step config may set only `model` (swap the model within the
default Claude runtime) or `runtime_adapter` + `model` together (switch the whole harness, e.g.
Codex). Missing fields stay `None` (agent-server default).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import posthoganalytics

from posthog.exceptions_capture import capture_exception

# Must stay 100%-on so the payload is served for the synthetic discovery distinct_id.
SIGNALS_PIPELINE_MODELS_FLAG = "signals-pipeline-models"

# Config is team-keyed in the payload, not per-user, so the read uses a fixed distinct_id.
PIPELINE_MODELS_DISCOVERY_DISTINCT_ID = "internal_signals_pipeline_models_discovery"

WILDCARD = "*"

# Step names match the `ai_stage` tags on $ai_generation so payload authors target the
# vocabulary they see in LLM analytics.
STEP_SCOUT = "scout"
STEP_RESEARCH = "research"
STEP_REPO_SELECTION = "repo_selection"
STEP_CUSTOM_AGENT = "custom_agent"


@dataclass(frozen=True)
class AgentRuntime:
    """The runtime/model/effort override for one signals agentic sandbox run.

    All-`None` keeps the agent server's built-in default (the Claude runtime). The three move as a
    set — a Codex runtime with a Claude model id would mis-route — so a payload step block resolves
    them together, atomically.
    """

    runtime_adapter: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


DEFAULT_RUNTIME = AgentRuntime()

# The Codex trial config (used by the local `analyze_report --codex` override).
CODEX_RUNTIME = AgentRuntime(runtime_adapter="codex", model="gpt-5.5", reasoning_effort="xhigh")


def _read_flag_payload() -> dict | None:
    """Read + parse the `signals-pipeline-models` flag payload once.

    The flag must stay 100%-on so the payload is served for the synthetic discovery distinct_id;
    `match_value=True` forces the true-variant payload under local evaluation. Returns the parsed
    dict, or `None` when the payload is absent / not an object / unreadable — a read error never
    breaks a run, callers fall back to the default. Mirrors `scout_harness/team_limits._read_flag_payload`.
    """
    try:
        payload = posthoganalytics.get_feature_flag_payload(
            SIGNALS_PIPELINE_MODELS_FLAG, PIPELINE_MODELS_DISCOVERY_DISTINCT_ID, match_value=True
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as error:
        capture_exception(error)
        return None


def _parse_runtime(step_block: object) -> AgentRuntime:
    """Parse one step's config blob into an `AgentRuntime`; anything malformed → default.

    Fields are optional and independently typed-checked: a non-string (or empty) value for a field
    is dropped to `None` rather than failing the whole block, so a typo in `reasoning_effort` can't
    silently un-set the `model`. A non-dict block (or empty) yields the default — the "fail to
    parse → fall back to defaults" contract."""
    if not isinstance(step_block, dict):
        return DEFAULT_RUNTIME

    def _str_or_none(key: str) -> str | None:
        value = step_block.get(key)
        return value if isinstance(value, str) and value else None

    return AgentRuntime(
        runtime_adapter=_str_or_none("runtime_adapter"),
        model=_str_or_none("model"),
        reasoning_effort=_str_or_none("reasoning_effort"),
    )


def _resolve_from_payload(payload: dict | None, team_id: int, step: str) -> AgentRuntime:
    """Resolve `(team_id, step)` against an already-read payload, most-specific-first.

    Walks team layers (`team_id` then `*`) and, within each, step layers (`step` then `*`); the
    first present step block wins and is parsed atomically. A present-but-malformed block parses to
    the default (and stops the walk) — a deliberate config of that exact slot. Absent everywhere →
    default."""
    if not isinstance(payload, dict):
        return DEFAULT_RUNTIME
    team_configs = payload.get("team_configs")
    if not isinstance(team_configs, dict):
        return DEFAULT_RUNTIME

    for team_key in (str(team_id), WILDCARD):
        team_block = team_configs.get(team_key)
        if not isinstance(team_block, dict):
            continue
        steps = team_block.get("steps")
        if not isinstance(steps, dict):
            continue
        for step_key in (step, WILDCARD):
            step_block = steps.get(step_key)
            if step_block is not None:
                return _parse_runtime(step_block)
    return DEFAULT_RUNTIME


def resolve_agent_runtime(team_id: int, step: str) -> AgentRuntime:
    """The runtime/model/effort override for `(team_id, step)`, or the default when unconfigured.

    Reads the `signals-pipeline-models` payload once and resolves most-specific-first (see
    `_resolve_from_payload`). Any failure — unreadable/malformed payload — falls back to the
    default; gating the runtime must never be able to fail an agentic run. Blocking network I/O
    (the payload read), so async callers wrap this in `database_sync_to_async`."""
    return _resolve_from_payload(_read_flag_payload(), team_id, step)
