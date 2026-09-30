import ipaddress

from unittest.mock import patch

from django.test import override_settings

from posthog.security.url_validation import PinnedUrlVerdict

from products.mcp_store.backend.url_policy import (
    check_mcp_url_policy,
    is_internal_mcp_url,
    resolve_mcp_url_policy,
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
def test_resolve_mcp_url_policy_pins_public_hosts_and_names_internal_ones() -> None:
    public = PinnedUrlVerdict(allowed=True, reason=None, pinned_ips={ipaddress.ip_address("93.184.216.34")})
    with patch("products.mcp_store.backend.url_policy.validate_url_and_pin_ips", return_value=public):
        assert resolve_mcp_url_policy("https://mcp.example.com/mcp", 42) == public

    # The real SSRF check rejects cluster-local hosts on the internal-domain
    # pattern (no DNS involved), so the override path runs end to end.
    configured = "http://grafana-mcp.monitoring.svc.cluster.local/mcp"
    internal = resolve_mcp_url_policy(configured, 42)
    assert internal == PinnedUrlVerdict(allowed=True, reason=None, pinned_ips=set())
    assert not resolve_mcp_url_policy(configured, 43).allowed
    assert not resolve_mcp_url_policy("http://other.svc.cluster.local/mcp", 42).allowed


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
