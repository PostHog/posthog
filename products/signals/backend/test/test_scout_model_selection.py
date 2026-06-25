from __future__ import annotations

from types import SimpleNamespace

from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.scout_harness.model_selection import GLM_MODEL, resolve_scout_model

_ENABLED_PATH = "products.signals.backend.scout_harness.model_selection.posthoganalytics.feature_enabled"
_PAYLOAD_PATH = "products.signals.backend.scout_harness.model_selection.posthoganalytics.get_feature_flag_payload"

_SKILL = "signals-scout-team-self-driving"
_OTHER_SKILL = "signals-scout-errors"
_GPT = "gpt-5.5"
_RUN_ID = "0190a000-0000-7000-8000-000000000001"


def _fake_team() -> SimpleNamespace:
    # resolve_scout_model only reads these three attributes; no DB row needed.
    return SimpleNamespace(uuid="00000000-0000-0000-0000-0000000000aa", organization_id=7, id=42)


def _resolve(skill: str = _SKILL, run_id: str = _RUN_ID, *, enabled: bool = True, payload: object = None) -> str | None:
    with patch(_ENABLED_PATH, return_value=enabled), patch(_PAYLOAD_PATH, return_value=payload):
        return resolve_scout_model(_fake_team(), skill, run_id)


def _share(payload: object, skill: str = _SKILL, n: int = 400) -> dict[str | None, int]:
    # Empirical model split across many run ids — buckets are uniform, so shares track the config.
    counts: dict[str | None, int] = {}
    for i in range(n):
        model = _resolve(skill=skill, run_id=f"run-{i}", payload=payload)
        counts[model] = counts.get(model, 0) + 1
    return counts


class TestResolveScoutModel:
    def test_flag_off_keeps_agent_default(self) -> None:
        assert _resolve(enabled=False, payload={"scouts": {_SKILL: {GLM_MODEL: 1}}}) is None

    @parameterized.expand(
        [
            ("no_payload", None),
            ("no_scouts_key", {}),
            ("scout_not_listed", {"scouts": {_OTHER_SKILL: {GLM_MODEL: 1}}}),
            ("empty_distribution", {"scouts": {_SKILL: {}}}),
        ]
    )
    def test_keeps_agent_default_when_unconfigured(self, _name: str, payload: object) -> None:
        assert _resolve(payload=payload) is None

    def test_full_weight_routes_every_run(self) -> None:
        assert _resolve(payload={"scouts": {_SKILL: {GLM_MODEL: 1}}}) == GLM_MODEL

    def test_locks_flag_key(self) -> None:
        with patch(_ENABLED_PATH, return_value=False) as mock_flag, patch(_PAYLOAD_PATH, return_value=None):
            resolve_scout_model(_fake_team(), _SKILL, _RUN_ID)
        assert mock_flag.call_args.args[0] == "scouts-model-selection"

    def test_wildcard_applies_to_unlisted_scout(self) -> None:
        # A scout with no explicit entry falls back to the "*" distribution.
        payload = {"scouts": {"*": {GLM_MODEL: 1}}}
        assert _resolve(skill=_OTHER_SKILL, payload=payload) == GLM_MODEL

    def test_explicit_entry_wins_over_wildcard(self) -> None:
        payload = {"scouts": {_SKILL: {GLM_MODEL: 1}, "*": {_GPT: 1}}}
        assert _resolve(payload=payload) == GLM_MODEL

    def test_named_default_takes_the_remainder(self) -> None:
        # 20% gpt, the remaining 80% pinned to a named default model (not the agent-server default).
        payload = {"scouts": {_SKILL: {_GPT: 0.2, "default": GLM_MODEL}}}
        shares = _share(payload)
        assert set(shares) == {_GPT, GLM_MODEL}
        assert None not in shares

    def test_multi_model_split_is_proportional(self) -> None:
        # 30% glm, 30% gpt, 40% agent-server default — all three buckets are non-trivially populated.
        payload = {"scouts": {_SKILL: {GLM_MODEL: 0.3, _GPT: 0.3}}}
        shares = _share(payload)
        assert shares.get(GLM_MODEL, 0) > 0
        assert shares.get(_GPT, 0) > 0
        assert shares.get(None, 0) > 0
        # The remainder (default) is the largest slice here (0.4 vs 0.3 each).
        assert shares[None] == max(shares.values())

    def test_selection_is_deterministic_per_run(self) -> None:
        payload = {"scouts": {_SKILL: {GLM_MODEL: 0.5, _GPT: 0.5}}}
        assert _resolve(payload=payload) == _resolve(payload=payload)

    @parameterized.expand(
        [
            ("malformed_weight_dropped", {GLM_MODEL: "lots"}, None),
            ("zero_weight_dropped", {GLM_MODEL: 0}, None),
            ("bool_weight_dropped", {GLM_MODEL: True}, None),
        ]
    )
    def test_malformed_weights_keep_agent_default(self, _name: str, dist: dict, expected: str | None) -> None:
        assert _resolve(payload={"scouts": {_SKILL: dist}}) == expected

    def test_flag_read_failure_keeps_agent_default(self) -> None:
        # A scout must never fail to run because the gate was unreachable — fall back to the default.
        with patch(_ENABLED_PATH, side_effect=RuntimeError("flag service down")):
            assert resolve_scout_model(_fake_team(), _SKILL, _RUN_ID) is None
