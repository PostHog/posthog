from __future__ import annotations

from types import SimpleNamespace

from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.scout_harness.model_selection import GLM_MODEL, resolve_scout_model

_FLAG_PATH = "products.signals.backend.scout_harness.model_selection.posthoganalytics.feature_enabled"


def _fake_team() -> SimpleNamespace:
    # resolve_scout_model only reads these three attributes; no DB row needed.
    return SimpleNamespace(uuid="00000000-0000-0000-0000-0000000000aa", organization_id=7, id=42)


class TestResolveScoutModel:
    @parameterized.expand(
        [
            ("flag_on_routes_to_glm", True, GLM_MODEL),
            ("flag_off_keeps_agent_default", False, None),
        ]
    )
    def test_resolves_model_from_scouts_glm_flag(self, _name: str, flag_enabled: bool, expected: str | None) -> None:
        with patch(_FLAG_PATH, return_value=flag_enabled) as mock_flag:
            assert resolve_scout_model(_fake_team()) == expected
        # Lock the flag key so a rename can't silently detach the gate.
        assert mock_flag.call_args.args[0] == "scouts-glm"

    def test_flag_read_failure_keeps_agent_default(self) -> None:
        # A scout must never fail to run because the gate was unreachable — fall back to the default.
        with patch(_FLAG_PATH, side_effect=RuntimeError("flag service down")):
            assert resolve_scout_model(_fake_team()) is None
