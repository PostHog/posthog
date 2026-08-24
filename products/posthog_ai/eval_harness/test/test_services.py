from products.posthog_ai.eval_harness.harness.services import _gateway_environment


def test_gateway_environment_maps_standard_provider_keys(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "standard-anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "standard-openai")
    monkeypatch.delenv("LLM_GATEWAY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_GATEWAY_OPENAI_API_KEY", raising=False)

    env = _gateway_environment()

    assert env["LLM_GATEWAY_ANTHROPIC_API_KEY"] == "standard-anthropic"
    assert env["LLM_GATEWAY_OPENAI_API_KEY"] == "standard-openai"


def test_gateway_environment_preserves_explicit_gateway_keys(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "standard")
    monkeypatch.setenv("LLM_GATEWAY_ANTHROPIC_API_KEY", "gateway")

    env = _gateway_environment()

    assert env["LLM_GATEWAY_ANTHROPIC_API_KEY"] == "gateway"
