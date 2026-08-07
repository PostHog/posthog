import pytest

from products.tasks.backend.logic.services.network_policy import (
    NetworkPolicyValidationError,
    compile_network_policy,
    domain_pattern_matches,
    normalize_requested_domains,
)


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "localhost",
        "host.docker.internal",
        "https://example.com",
        "example.com/path",
        "example.com:443",
        "example.com.",
        "127.0.0.1",
        "2001:db8::1",
        "example",
        "*",
        "api.*.example.com",
        "-api.example.com",
    ],
)
def test_requested_domains_reject_values_modal_cannot_enforce(domain: str) -> None:
    with pytest.raises(NetworkPolicyValidationError):
        normalize_requested_domains([domain])


def test_requested_domains_are_canonicalized_without_changing_host_coverage() -> None:
    assert normalize_requested_domains([" EXAMPLE.com ", "example.com", "täst.example"]) == (
        "example.com",
        "xn--tst-qla.example",
    )


def test_effective_policy_matches_external_host_coverage_across_layers() -> None:
    policy = compile_network_policy(
        ["*.example.com", "api.service.test"],
        infrastructure_domains=["*.posthog.com", "api.anthropic.com", "gateway.us.posthog.com"],
    )

    assert policy.modal_domains == ("*.example.com", "api.service.test", "*.posthog.com", "api.anthropic.com")
    assert "example.com" in policy.agentsh_domains
    assert "posthog.com" in policy.agentsh_domains

    for hostname in (
        "example.com",
        "api.example.com",
        "deep.api.example.com",
        "api.service.test",
        "posthog.com",
        "gateway.us.posthog.com",
        "api.anthropic.com",
        "notexample.com",
        "example.org",
    ):
        modal_allows = any(domain_pattern_matches(pattern, hostname) for pattern in policy.modal_domains)
        agentsh_allows = any(domain_pattern_matches(pattern, hostname) for pattern in policy.agentsh_domains)
        assert modal_allows is agentsh_allows


def test_empty_requested_policy_still_contains_infrastructure_domains() -> None:
    policy = compile_network_policy([], infrastructure_domains=["api.example.com"])

    assert policy.requested_domains == ()
    assert policy.modal_domains == ("api.example.com",)
    assert policy.agentsh_domains == ("api.example.com",)
