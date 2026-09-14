from django.test import override_settings

from products.mcp_store.backend.url_policy import (
    allow_internal_mcp_url,
    check_mcp_url_policy,
    is_internal_mcp_url,
    trust_environment_proxy,
)


@override_settings(
    MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM={"42": ["http://grafana-mcp.monitoring.svc.cluster.local/mcp"]}
)
def test_internal_mcp_url_requires_an_exact_match() -> None:
    configured = "http://grafana-mcp.monitoring.svc.cluster.local/mcp"

    assert is_internal_mcp_url(configured, 42)
    assert not is_internal_mcp_url(configured, 43)
    assert not is_internal_mcp_url(configured, None)
    assert not is_internal_mcp_url(f"{configured}/", 42)
    assert not is_internal_mcp_url("http://grafana-mcp.monitoring.svc.cluster.local/other", 42)
    assert not is_internal_mcp_url("http://other.monitoring.svc.cluster.local/mcp", 42)


@override_settings(
    MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM={"42": ["http://grafana-mcp.monitoring.svc.cluster.local/mcp"]}
)
def test_internal_mcp_url_can_override_a_failed_public_ssrf_check() -> None:
    configured = "http://grafana-mcp.monitoring.svc.cluster.local/mcp"

    assert allow_internal_mcp_url(configured, 42, False, "Internal domain") == (True, None)
    assert allow_internal_mcp_url(configured, 43, False, "Internal domain") == (False, "Internal domain")
    assert allow_internal_mcp_url("http://other.svc.cluster.local/mcp", 42, False, "Internal domain") == (
        False,
        "Internal domain",
    )


@override_settings(
    MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM={"42": ["http://grafana-mcp.monitoring.svc.cluster.local/mcp"]}
)
def test_check_mcp_url_policy_is_the_single_entry_point() -> None:
    # The real SSRF check rejects cluster-local hosts on the internal-domain
    # pattern (no DNS involved), so these exercise the composed path end to end.
    configured = "http://grafana-mcp.monitoring.svc.cluster.local/mcp"

    assert check_mcp_url_policy(configured, 42) == (True, None)

    allowed, reason = check_mcp_url_policy(configured, 43)
    assert not allowed
    assert reason is not None

    allowed, reason = check_mcp_url_policy(f"{configured}/", 42)
    assert not allowed
    assert reason is not None


@override_settings(
    MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM={"42": ["http://grafana-mcp.monitoring.svc.cluster.local/mcp"]}
)
def test_internal_mcp_url_bypasses_environment_proxy_only_for_exact_match() -> None:
    configured = "http://grafana-mcp.monitoring.svc.cluster.local/mcp"

    assert not trust_environment_proxy(configured, 42)
    assert trust_environment_proxy(configured, 43)
    assert trust_environment_proxy("https://mcp.example.com/mcp", 42)
