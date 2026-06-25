from __future__ import annotations

from types import SimpleNamespace

from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.scout_harness.model_selection import GLM_MODEL, resolve_scout_model

_ENABLED_PATH = "products.signals.backend.scout_harness.model_selection.posthoganalytics.feature_enabled"
_PAYLOAD_PATH = "products.signals.backend.scout_harness.model_selection.posthoganalytics.get_feature_flag_payload"

_SKILL = "signals-scout-team-self-driving"
_OTHER_SKILL = "signals-scout-errors"
_RUN_ID = "0190a000-0000-7000-8000-000000000001"


def _fake_team() -> SimpleNamespace:
    # resolve_scout_model only reads these three attributes; no DB row needed.
    return SimpleNamespace(uuid="00000000-0000-0000-0000-0000000000aa", organization_id=7, id=42)


def _resolve(skill: str = _SKILL, run_id: str = _RUN_ID, *, enabled: bool = True, payload: object = None) -> str | None:
    with patch(_ENABLED_PATH, return_value=enabled), patch(_PAYLOAD_PATH, return_value=payload):
        return resolve_scout_model(_fake_team(), skill, run_id)


class TestResolveScoutModel:
    def test_flag_off_keeps_agent_default(self) -> None:
        assert _resolve(enabled=False) is None

    def test_flag_on_no_payload_routes_all_scouts_to_glm(self) -> None:
        # Back-compat: enabled flag with no payload behaves like the original "all in" gate.
        assert _resolve(payload=None) == GLM_MODEL

    def test_locks_flag_key(self) -> None:
        # A rename mustn't silently detach the gate.
        with patch(_ENABLED_PATH, return_value=False) as mock_flag, patch(_PAYLOAD_PATH, return_value=None):
            resolve_scout_model(_fake_team(), _SKILL, _RUN_ID)
        assert mock_flag.call_args.args[0] == "scouts-glm"

    @parameterized.expand(
        [
            ("wildcard", {"enabled_skills": ["*"]}, GLM_MODEL),
            ("explicit_member", {"enabled_skills": [_SKILL]}, GLM_MODEL),
            ("explicit_non_member", {"enabled_skills": [_OTHER_SKILL]}, None),
            ("empty_list_opts_nobody_in", {"enabled_skills": []}, None),
            ("malformed_falls_back_to_all", {"enabled_skills": [123]}, GLM_MODEL),
        ]
    )
    def test_enabled_skills_selects_subset(self, _name: str, payload: dict, expected: str | None) -> None:
        assert _resolve(payload=payload) == expected

    @parameterized.expand(
        [
            ("rate_zero_keeps_default", 0, None),
            ("rate_one_routes_to_glm", 1, GLM_MODEL),
        ]
    )
    def test_sample_rate_bounds(self, _name: str, rate: float, expected: str | None) -> None:
        assert _resolve(payload={"sample_rate": rate}) == expected

    def test_sample_rate_is_deterministic_per_run(self) -> None:
        # The same run id always resolves the same model — the decision is a stable hash, not a draw.
        payload = {"sample_rate": 0.5}
        assert _resolve(payload=payload) == _resolve(payload=payload)

    def test_sample_rate_splits_runs(self) -> None:
        # Across many run ids a 0.5 rate routes a non-trivial fraction each way (not all-or-nothing).
        payload = {"sample_rate": 0.5}
        glm = sum(1 for i in range(200) if _resolve(run_id=f"run-{i}", payload=payload) == GLM_MODEL)
        assert 0 < glm < 200

    def test_flag_read_failure_keeps_agent_default(self) -> None:
        # A scout must never fail to run because the gate was unreachable — fall back to the default.
        with patch(_ENABLED_PATH, side_effect=RuntimeError("flag service down")):
            assert resolve_scout_model(_fake_team(), _SKILL, _RUN_ID) is None
