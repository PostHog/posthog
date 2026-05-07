"""Tests for the deterministic pattern matcher."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patterns import Finding, find, has_blockers, redact, summarize  # noqa: E402


@pytest.mark.parametrize(
    "text,expected_category",
    [
        # Slack
        (
            "discussed in https://posthog.slack.com/archives/C0123456/p1234567890",
            "slack-permalink",
        ),
        # Zendesk
        (
            "see https://posthog.zendesk.com/agent/tickets/12345 for the user report",
            "zendesk-ticket-url",
        ),
        ("Reported in ZD-12345 by the customer", "zendesk-ticket-id"),
        # Linear
        (
            "tracked in https://linear.app/posthog/issue/ENG-1234",
            "linear-ticket-url",
        ),
        # Notion
        (
            "details in https://www.notion.so/posthog/Some-Doc-abc123def456ghi789jkl0",
            "notion-internal-url",
        ),
        # Google Doc
        (
            "spec at https://docs.google.com/document/d/abc123def456ghi789jkl012mnop345q",
            "google-doc-url",
        ),
        # Intercom
        (
            "https://app.intercom.com/a/inbox/foo/conversations/12345",
            "intercom-conversation",
        ),
        # Atlassian / Jira
        (
            "see https://posthog.atlassian.net/browse/POST-123",
            "jira-ticket-url",
        ),
        # AWS access key
        ("Found AKIAIOSFODNN7EXAMPLE in the env", "aws-access-key"),
        # GitHub PAT — synthesize prefix so push protection doesn't flag.
        ("Token: " + "ghp_" + ("a" * 36), "github-token"),
        # Anthropic key — same trick.
        ("sk-" + "ant-" + ("Z" * 30), "anthropic-key"),
        # Stripe key — synthesize the prefix programmatically so push
        # protection doesn't flag this fixture as a real secret.
        ("Stripe: " + "sk_" + "test_" + ("z" * 28), "stripe-key"),
        # JWT
        (
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5.eyJzdWIiOiIxMjM0NTY3ODkw.SflKxwRJSMeKKF",
            "jwt-token",
        ),
        # PEM private key
        (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----",
            "private-key-pem",
        ),
        # Database connection
        (
            "postgres://user:pass@db.internal.posthog.com:5432/foo",
            "database-conn-string",
        ),
        # Phone number
        ("Call them at +1 555 123 4567", "phone-number"),
        # SSN
        ("SSN 123-45-6789 in the report", "ssn"),
        # Internal IP
        ("Hit 10.0.0.42 directly to debug", "internal-ip"),
        # Internal hostname
        ("Failed on web1.prod.posthog.com", "internal-hostname"),
        # Email (non-allowlisted)
        ("Reported by jane@bigbank.com via support", "internal-email"),
        # Customer mention
        ("Customer Acme reported they hit this", "customer-mention"),
    ],
)
def test_finds_expected_category(text: str, expected_category: str) -> None:
    findings = find(text)
    assert findings, f"no findings for {text!r}"
    assert any(f.category == expected_category for f in findings), (
        f"{expected_category!r} not in {[f.category for f in findings]} for {text!r}"
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "a normal description with no sensitive bits",
        "use posthog/posthog issue #12345 to track this",
        "support@posthog.com is fine",
        "see example.com for an example",
        "Refactor the function name from `foo` to `bar`",
        "address: noreply@github.com (the bot)",
        # Public version-style strings should not match
        "Bumped to v1.2.3 and v10.0.0",
    ],
)
def test_clean_text_has_no_findings(text: str) -> None:
    findings = find(text)
    assert findings == [], f"unexpected findings: {findings!r}"


def test_overlapping_findings_dedupe() -> None:
    text = "url https://posthog.zendesk.com/agent/tickets/9999 ticket"
    findings = find(text)
    starts = [f.start for f in findings]
    assert len(set(starts)) == len(starts), f"overlapping spans: {findings}"


def test_redact_replaces_findings() -> None:
    text = (
        "Customer reported via https://posthog.zendesk.com/agent/tickets/123 — "
        "see slack at https://posthog.slack.com/archives/C012/p1"
    )
    redacted = redact(text)
    assert "zendesk.com" not in redacted
    assert "slack.com" not in redacted
    assert "[redacted: zendesk ticket]" in redacted
    assert "[redacted: slack link]" in redacted


def test_redact_preserves_unmatched_text() -> None:
    text = "completely innocuous text with nothing inside"
    assert redact(text) == text


def test_redact_with_explicit_findings() -> None:
    text = "abc def ghi"
    custom = [
        Finding(
            category="custom",
            start=4,
            end=7,
            snippet="def",
            replacement="<X>",
            severity="redact",
        )
    ]
    assert redact(text, custom) == "abc <X> ghi"


def test_has_blockers_distinguishes_severity() -> None:
    secret_text = "AKIAIOSFODNN7EXAMPLE"
    findings = find(secret_text)
    assert has_blockers(findings)

    soft_text = "the customer Acme was very loud"
    assert not has_blockers(find(soft_text))


def test_summarize_counts_categories() -> None:
    text = "AKIAIOSFODNN7EXAMPLE and AKIAQQQQQQQQQQQQ7777"
    summary = summarize(find(text))
    assert summary["total"] == 2
    assert summary["by_category"]["aws-access-key"] == 2
    assert summary["by_severity"]["block"] == 2


def test_jwt_min_length_avoids_random_dotted_strings() -> None:
    # We want JWTs but not random "a.b.c" strings.
    findings = find("foo.bar.baz")
    assert all(f.category != "jwt-token" for f in findings)


def test_internal_email_skips_allowlisted_domains() -> None:
    text = "ping @posthog: alice@posthog.com or someone@example.com"
    findings = find(text)
    assert all(f.category != "internal-email" for f in findings), findings


def test_basic_auth_url_blocks() -> None:
    findings = find("connect via https://admin:hunter2@db.example.com/foo")
    assert any(f.severity == "block" and f.category == "basic-auth-url" for f in findings)


def test_findings_sorted_by_position() -> None:
    text = "AKIA0000000000000000 ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    findings = find(text)
    starts = [f.start for f in findings]
    assert starts == sorted(starts)


def test_does_not_redact_inside_findings_replacement() -> None:
    """Ensure redact() doesn't recursively match its own replacement tokens."""
    text = "AKIAIOSFODNN7EXAMPLE"
    redacted = redact(text)
    assert redacted == "[redacted: aws access key]"
    assert find(redacted) == []
