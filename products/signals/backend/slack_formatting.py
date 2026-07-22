from __future__ import annotations

import re

from markdown_to_mrkdwn import SlackMarkdownConverter

_SLACK_MRKDWN_CONVERTER = SlackMarkdownConverter()
SLACK_SECTION_TEXT_MAX_LEN = 2900

# Matches a converter-emitted Slack angle token: `<dest>` or `<dest|label>`. Input `<`/`>`
# are escaped before conversion, so any literal angle bracket here was produced by the converter.
_SLACK_ANGLE_TOKEN_RE = re.compile(r"<([^<>|]*)(\|[^<>]*)?>")


def escape_slack_mrkdwn(text: str) -> str:
    """Neutralize Slack control syntax so untrusted text cannot inject mentions or links."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def is_safe_slack_http_url(value: object) -> bool:
    """Allow only URL forms that cannot break out of a Slack `<url|label>` token."""
    if not isinstance(value, str):
        return False
    if not (value.startswith("http://") or value.startswith("https://")):
        return False
    return not any(char in value for char in ("<", ">", "|"))


def _defang_unsafe_slack_tokens(text: str) -> str:
    """Render converter-created non-URL angle tokens as inert literal text."""

    def _replace(match: re.Match[str]) -> str:
        if is_safe_slack_http_url(match.group(1)):
            return match.group(0)
        return match.group(0).replace("<", "&lt;").replace(">", "&gt;")

    return _SLACK_ANGLE_TOKEN_RE.sub(_replace, text)


def markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert untrusted Markdown to Slack mrkdwn without allowing mention injection."""
    return _defang_unsafe_slack_tokens(_SLACK_MRKDWN_CONVERTER.convert(escape_slack_mrkdwn(text)))


def truncate_slack_section(text: str) -> str:
    """Keep mrkdwn below Slack's 3000-character section limit with headroom."""
    if len(text) <= SLACK_SECTION_TEXT_MAX_LEN:
        return text
    return text[: SLACK_SECTION_TEXT_MAX_LEN - 1].rstrip() + "…"


def slack_channel_id_from_target(value: str) -> str:
    """Extract the Slack channel ID from the frontend picker's `id|#name` value."""
    return value.split("|", 1)[0].strip()
