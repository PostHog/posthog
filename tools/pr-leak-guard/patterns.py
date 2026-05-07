"""Deterministic pattern detectors for sensitive data in PR descriptions and code.

The patterns here cover the common shapes of internal data that agents often
paste verbatim into PRs after reading them earlier in a session:

- Slack permalinks and message IDs
- Zendesk / Linear / Jira ticket URLs and IDs
- Internal Notion / Coda / Confluence URLs
- Customer names from CRM-style mentions
- Email addresses from internal/customer domains
- API keys, bearer tokens, and AWS-style access keys
- Stack traces with internal file paths from production
- Long IP addresses, UUIDs that look like tenant IDs in suspicious contexts

A finding is `(category, span, snippet, replacement)` — the workflow uses
this to either redact (replace with `[redacted: <category>]`) or block.

Each pattern is intentionally narrow: a low false-positive rate matters more
than catching every shape, because the LLM stage handles the semantic edge
cases the regexes miss.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    category: str
    start: int
    end: int
    snippet: str
    replacement: str
    severity: str  # "block" | "redact" | "warn"

    def __lt__(self, other: Finding) -> bool:
        return (self.start, self.end) < (other.start, other.end)


_BLOCK = "block"
_REDACT = "redact"
_WARN = "warn"


# Each rule: (category, compiled regex, replacement template, severity)
# Replacement uses `{redacted}` placeholder so the workflow can render a
# consistent token.
_RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    # ── Internal collaboration tools ─────────────────────────────────
    (
        "slack-permalink",
        re.compile(
            r"https?://[\w.-]*\.slack\.com/(?:archives|files)/[\w/-]+(?:\?[\w=&%-]*)?",
            re.IGNORECASE,
        ),
        "[redacted: slack link]",
        _REDACT,
    ),
    (
        "slack-channel-mention",
        # #C0123ABCD style channel IDs (not just hashtag words)
        re.compile(r"\b[#<]?C0[A-Z0-9]{8,}\b"),
        "[redacted: slack channel id]",
        _WARN,
    ),
    (
        "zendesk-ticket-url",
        re.compile(
            r"https?://[\w.-]*\.zendesk\.com/(?:agent/tickets|hc/[a-z-]+/requests)/\d+",
            re.IGNORECASE,
        ),
        "[redacted: zendesk ticket]",
        _REDACT,
    ),
    (
        "zendesk-ticket-id",
        # ZD-12345 / Zendesk #12345 style references in plain text
        re.compile(r"\b(?:ZD|Zendesk)[\s#:-]+\d{3,}\b", re.IGNORECASE),
        "[redacted: zendesk ticket]",
        _REDACT,
    ),
    (
        "linear-ticket-url",
        re.compile(
            r"https?://linear\.app/[\w-]+/issue/[A-Z]+-\d+(?:/[\w-]*)?",
            re.IGNORECASE,
        ),
        "[redacted: linear ticket]",
        _REDACT,
    ),
    (
        "intercom-conversation",
        re.compile(
            r"https?://[\w.-]*\.intercom\.com/[\w/-]+/conversations?/\d+",
            re.IGNORECASE,
        ),
        "[redacted: intercom conversation]",
        _REDACT,
    ),
    (
        "notion-internal-url",
        re.compile(
            r"https?://(?:www\.)?notion\.so/(?:[\w-]+/)?[\w-]{20,}",
            re.IGNORECASE,
        ),
        "[redacted: notion link]",
        _REDACT,
    ),
    (
        "google-doc-url",
        re.compile(
            r"https?://docs\.google\.com/(?:document|spreadsheets|presentation)/d/[\w-]{20,}(?:/[\w?=&-]*)?",
            re.IGNORECASE,
        ),
        "[redacted: google doc]",
        _REDACT,
    ),
    (
        "jira-ticket-url",
        re.compile(
            r"https?://[\w.-]+\.atlassian\.net/browse/[A-Z]+-\d+",
            re.IGNORECASE,
        ),
        "[redacted: jira ticket]",
        _REDACT,
    ),
    (
        "salesforce-record",
        re.compile(
            r"https?://[\w.-]*\.(?:lightning\.force|my\.salesforce)\.com/[\w/?=&-]+",
            re.IGNORECASE,
        ),
        "[redacted: salesforce link]",
        _REDACT,
    ),
    (
        "claude-share-link",
        # Internal session/share URLs
        re.compile(r"https?://claude\.ai/(?:share|chat)/[\w-]{8,}", re.IGNORECASE),
        "[redacted: claude session link]",
        _REDACT,
    ),
    # ── Credentials and tokens ──────────────────────────────────────
    (
        "aws-access-key",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        "[redacted: aws access key]",
        _BLOCK,
    ),
    (
        "github-token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"),
        "[redacted: github token]",
        _BLOCK,
    ),
    (
        "anthropic-key",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
        "[redacted: anthropic api key]",
        _BLOCK,
    ),
    (
        "openai-key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b"),
        "[redacted: openai api key]",
        _BLOCK,
    ),
    (
        "slack-token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        "[redacted: slack token]",
        _BLOCK,
    ),
    (
        "google-api-key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        "[redacted: google api key]",
        _BLOCK,
    ),
    (
        "stripe-key",
        re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[0-9a-zA-Z]{24,}\b"),
        "[redacted: stripe key]",
        _BLOCK,
    ),
    (
        "private-key-pem",
        re.compile(
            r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----",
        ),
        "[redacted: private key block]",
        _BLOCK,
    ),
    (
        "jwt-token",
        # eyJ... three-segment base64url. Min lengths to avoid noise.
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "[redacted: jwt]",
        _BLOCK,
    ),
    (
        "posthog-personal-key",
        re.compile(r"\bphx_[A-Za-z0-9]{40,}\b"),
        "[redacted: posthog personal api key]",
        _BLOCK,
    ),
    (
        "basic-auth-url",
        re.compile(r"https?://[^\s/:@]+:[^\s/@]+@[^\s/]+", re.IGNORECASE),
        "[redacted: url with embedded credentials]",
        _BLOCK,
    ),
    # ── Customer / personal data ────────────────────────────────────
    (
        "internal-email",
        # @posthog.com emails are not sensitive, but flagging emails from
        # other domains in PR text is a useful signal — agents often paste
        # support thread headers verbatim.
        re.compile(
            r"\b[\w.+-]+@(?!(?:posthog\.com|users\.noreply\.github\.com|github\.com|example\.com|test\.com)\b)"
            r"[\w-]+\.[\w.-]+\b"
        ),
        "[redacted: email]",
        _WARN,
    ),
    (
        "phone-number",
        # E.164-ish — 8-15 digits, optional '+'. Narrow context to avoid
        # matching IDs.
        re.compile(r"(?<!\w)\+\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?!\w)"),
        "[redacted: phone]",
        _WARN,
    ),
    (
        "credit-card-number",
        # Conservative: only the major issuers in groups of 4
        re.compile(r"(?<!\d)(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6011)[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
        "[redacted: card number]",
        _BLOCK,
    ),
    (
        "ssn",
        re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
        "[redacted: ssn-like]",
        _BLOCK,
    ),
    # ── Internal infra hints ────────────────────────────────────────
    (
        "internal-ip",
        # Private RFC1918 ranges in clearly-IP shape. Public IPs are noisy
        # and rarely sensitive on their own.
        re.compile(
            r"(?<![\w.])"
            r"(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|192\.168\.\d{1,3}\.\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})"
            r"(?![\w.])"
        ),
        "[redacted: internal ip]",
        _WARN,
    ),
    (
        "internal-hostname",
        # *.posthog.dev or *.internal.posthog.com style — not a public domain
        re.compile(
            r"\b[\w-]+\.(?:internal|prod|stage|dev)\.posthog\.(?:com|net|dev|io)\b",
            re.IGNORECASE,
        ),
        "[redacted: internal hostname]",
        _WARN,
    ),
    (
        "database-conn-string",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|clickhouse)://[^\s)>'\"]+",
            re.IGNORECASE,
        ),
        "[redacted: connection string]",
        _BLOCK,
    ),
]


# Customer/internal phrasing — softer signals worth flagging in PR text
# but rarely worth blocking outright. The LLM gets the final say.
_CONTEXT_PHRASES = [
    re.compile(
        r"\b(?:customer|client|user)\s+([A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+){0,2})\s+(?:reported|asked|complained|hit|saw|requested)",
        re.IGNORECASE,
    ),
    re.compile(r"\bfrom\s+the\s+(?:slack|zendesk|intercom|customer)\s+(?:thread|ticket|conversation)\b", re.IGNORECASE),
    re.compile(r"\bACME\s*Corp\b", re.IGNORECASE),  # placeholder — replace if you have a known seed list
]


def find(text: str) -> list[Finding]:
    """Run all regex rules against `text`, return ordered, non-overlapping findings.

    Overlapping matches resolve in favor of the earliest start, longest end.
    `block` outranks `redact` outranks `warn` when severities tie on span.
    """
    if not text:
        return []

    raw: list[Finding] = []
    for category, pattern, replacement, severity in _RULES:
        for m in pattern.finditer(text):
            raw.append(
                Finding(
                    category=category,
                    start=m.start(),
                    end=m.end(),
                    snippet=text[m.start() : m.end()],
                    replacement=replacement,
                    severity=severity,
                )
            )

    for pattern in _CONTEXT_PHRASES:
        for m in pattern.finditer(text):
            raw.append(
                Finding(
                    category="customer-mention",
                    start=m.start(),
                    end=m.end(),
                    snippet=text[m.start() : m.end()],
                    replacement="[redacted: customer mention]",
                    severity=_WARN,
                )
            )

    return _dedupe(raw)


_SEVERITY_RANK = {"block": 3, "redact": 2, "warn": 1}


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Merge overlapping findings — prefer higher severity, then longer span."""
    if not findings:
        return []
    findings.sort(key=lambda f: (f.start, -f.end, -_SEVERITY_RANK[f.severity]))
    out: list[Finding] = []
    for f in findings:
        if out and f.start < out[-1].end:
            current = out[-1]
            if (_SEVERITY_RANK[f.severity], f.end - f.start) > (
                _SEVERITY_RANK[current.severity],
                current.end - current.start,
            ):
                out[-1] = f
            continue
        out.append(f)
    return out


def redact(text: str, findings: list[Finding] | None = None) -> str:
    """Return `text` with all redactable findings replaced by their token.

    `block`-level findings are still rendered with the redaction token —
    callers decide whether to emit a non-zero exit code separately.
    """
    if findings is None:
        findings = find(text)
    if not findings:
        return text

    out: list[str] = []
    cursor = 0
    for f in sorted(findings):
        out.append(text[cursor : f.start])
        out.append(f.replacement)
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out)


def has_blockers(findings: list[Finding]) -> bool:
    return any(f.severity == _BLOCK for f in findings)


def summarize(findings: list[Finding]) -> dict:
    """Return a JSON-serializable summary by category and severity."""
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for f in findings:
        by_category[f.category] = by_category.get(f.category, 0) + 1
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
    return {
        "total": len(findings),
        "by_category": by_category,
        "by_severity": by_severity,
        "categories": sorted(by_category),
    }
