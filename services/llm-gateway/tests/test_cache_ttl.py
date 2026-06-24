from llm_gateway.cache_ttl import upgrade_cache_ttl


def test_upgrades_system_and_tools_ephemeral_breakpoints() -> None:
    body = {
        "system": [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}],
        "tools": [{"name": "t", "cache_control": {"type": "ephemeral"}}],
    }
    out = upgrade_cache_ttl(body, product="posthog_code")
    assert out["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert out["tools"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_upgrades_message_content_blocks() -> None:
    body = {
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]}
        ]
    }
    out = upgrade_cache_ttl(body, product="posthog_code")
    assert out["messages"][0]["content"][0]["cache_control"]["ttl"] == "1h"


def test_noop_for_async_products() -> None:
    body = {"system": [{"type": "text", "cache_control": {"type": "ephemeral"}}]}
    out = upgrade_cache_ttl(body, product="background_agents")
    assert "ttl" not in out["system"][0]["cache_control"]


def test_preserves_an_explicit_ttl() -> None:
    body = {"system": [{"type": "text", "cache_control": {"type": "ephemeral", "ttl": "5m"}}]}
    out = upgrade_cache_ttl(body, product="posthog_code")
    assert out["system"][0]["cache_control"]["ttl"] == "5m"


def test_ignores_blocks_without_cache_control() -> None:
    body = {"system": [{"type": "text", "text": "x"}], "tools": [{"name": "t"}]}
    out = upgrade_cache_ttl(body, product="posthog_code")
    assert "cache_control" not in out["system"][0]
    assert "cache_control" not in out["tools"][0]


def test_handles_string_system_and_empty_body() -> None:
    assert upgrade_cache_ttl({"system": "plain string"}, product="posthog_code") == {"system": "plain string"}
    assert upgrade_cache_ttl({}, product="posthog_code") == {}
