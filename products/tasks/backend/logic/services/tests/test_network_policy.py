import pytest

from parameterized import parameterized

from products.tasks.backend.logic.services.network_policy import (
    NetworkPolicyValidationError,
    compile_network_policy,
    domain_pattern_matches,
    normalize_requested_domains,
)


@parameterized.expand(
    [
        ("empty", ""),
        ("localhost", "localhost"),
        ("docker_host", "host.docker.internal"),
        ("scheme", "https://example.com"),
        ("path", "example.com/path"),
        ("port", "example.com:443"),
        ("rooted", "example.com."),
        ("unicode_rooted", "example.com。"),
        ("ipv4", "127.0.0.1"),
        ("ipv6", "2001:db8::1"),
        ("single_label", "example"),
        ("wildcard_only", "*"),
        ("misplaced_wildcard", "api.*.example.com"),
        ("malformed_label", "-api.example.com"),
    ]
)
def test_requested_domains_reject_values_modal_cannot_enforce(_name: str, domain: str) -> None:
    with pytest.raises(NetworkPolicyValidationError):
        normalize_requested_domains([domain])


@parameterized.expand(
    [
        ("case_whitespace_and_duplicates", [" EXAMPLE.com ", "example.com"], ("example.com",)),
        ("idna_label", ["täst.example"], ("xn--tst-qla.example",)),
        ("idna_2008_deviation", ["faß.de"], ("xn--fa-hia.de",)),
        ("unicode_label_separator", ["example。com"], ("example.com",)),
    ]
)
def test_requested_domains_are_canonicalized_without_changing_host_coverage(
    _name: str, domains: list[str], expected: tuple[str, ...]
) -> None:
    assert normalize_requested_domains(domains) == expected


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
