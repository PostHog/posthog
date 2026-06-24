from llm_gateway.cost_controls import COST_CONTROLS_FLAG, cost_controls_enabled


def test_off_by_default() -> None:
    assert cost_controls_enabled(None) is False
    assert cost_controls_enabled({}) is False


def test_on_when_alpha_flag_true() -> None:
    assert cost_controls_enabled({COST_CONTROLS_FLAG: "true"}) is True
    assert cost_controls_enabled({COST_CONTROLS_FLAG: "TRUE"}) is True


def test_other_flag_values_stay_off() -> None:
    assert cost_controls_enabled({COST_CONTROLS_FLAG: "false"}) is False
    assert cost_controls_enabled({COST_CONTROLS_FLAG: "control"}) is False
    assert cost_controls_enabled({"some-other-flag": "true"}) is False


def test_cost_controls_enabled_via_env_var(monkeypatch: object) -> None:
    monkeypatch.setenv("COST_CONTROLS_ENABLED", "true")
    assert cost_controls_enabled() is True
    assert cost_controls_enabled(flags={}) is True
    assert cost_controls_enabled(flags={COST_CONTROLS_FLAG: "false"}) is True


def test_cost_controls_env_var_case_insensitive(monkeypatch: object) -> None:
    monkeypatch.setenv("COST_CONTROLS_ENABLED", "True")
    assert cost_controls_enabled() is True
