from __future__ import annotations

import json

from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.agent_runtime import DEFAULT_RUNTIME, AgentRuntime, resolve_agent_runtime

_READ_PATH = "products.signals.backend.agent_runtime._read_flag_payload"
_PAYLOAD_FN_PATH = "products.signals.backend.agent_runtime.posthoganalytics.get_feature_flag_payload"

# Team 2: research → full Codex swap; every other step → model-only (sonnet, still Claude runtime).
# Wildcard team: only `scout` is overridden (no step wildcard).
_PAYLOAD = {
    "team_configs": {
        "2": {
            "steps": {
                "research": {"runtime_adapter": "codex", "model": "gpt-5.5", "reasoning_effort": "xhigh"},
                "*": {"model": "claude-sonnet-4-6"},
            }
        },
        "*": {"steps": {"scout": {"runtime_adapter": "codex", "model": "gpt-5.5"}}},
    }
}

_CODEX = AgentRuntime(runtime_adapter="codex", model="gpt-5.5", reasoning_effort="xhigh")
_SONNET_MODEL_ONLY = AgentRuntime(runtime_adapter=None, model="claude-sonnet-4-6", reasoning_effort=None)
_CODEX_NO_EFFORT = AgentRuntime(runtime_adapter="codex", model="gpt-5.5", reasoning_effort=None)


class TestResolveAgentRuntime:
    @parameterized.expand(
        [
            # team-specific + step-specific wins
            ("team_step_exact", 2, "research", _CODEX),
            # team-specific step-wildcard beats the wildcard team's specific step
            ("team_step_wildcard_over_wildcard_team", 2, "scout", _SONNET_MODEL_ONLY),
            ("team_step_wildcard_for_unlisted_step", 2, "repo_selection", _SONNET_MODEL_ONLY),
            # wildcard team applies when the team isn't listed
            ("wildcard_team_step_exact", 999, "scout", _CODEX_NO_EFFORT),
            # unlisted step under wildcard team with no step-wildcard → default
            ("wildcard_team_step_missing", 999, "research", DEFAULT_RUNTIME),
        ]
    )
    def test_resolution_precedence(self, _name: str, team_id: int, step: str, expected: AgentRuntime) -> None:
        with patch(_READ_PATH, return_value=_PAYLOAD):
            assert resolve_agent_runtime(team_id, step) == expected

    @parameterized.expand(
        [
            ("payload_none", None),
            ("payload_not_dict", ["nope"]),
            ("missing_team_configs", {"other": {}}),
            ("team_configs_not_dict", {"team_configs": ["nope"]}),
            ("step_block_not_dict", {"team_configs": {"2": {"steps": {"research": "codex"}}}}),
        ]
    )
    def test_malformed_payload_falls_back_to_default(self, _name: str, payload: object) -> None:
        with patch(_READ_PATH, return_value=payload):
            assert resolve_agent_runtime(2, "research") == DEFAULT_RUNTIME

    def test_non_string_field_is_dropped_not_fatal(self) -> None:
        # A bad reasoning_effort must not un-set the otherwise-valid model/runtime.
        payload = {
            "team_configs": {
                "2": {"steps": {"research": {"runtime_adapter": "codex", "model": "gpt-5.5", "reasoning_effort": 5}}}
            }
        }
        with patch(_READ_PATH, return_value=payload):
            assert resolve_agent_runtime(2, "research") == _CODEX_NO_EFFORT

    def test_payload_served_as_json_string_is_parsed(self) -> None:
        with patch(_PAYLOAD_FN_PATH, return_value=json.dumps(_PAYLOAD)):
            assert resolve_agent_runtime(2, "research") == _CODEX

    def test_flag_read_failure_falls_back_to_default(self) -> None:
        with patch(_PAYLOAD_FN_PATH, side_effect=RuntimeError("flag service down")):
            assert resolve_agent_runtime(2, "research") == DEFAULT_RUNTIME
