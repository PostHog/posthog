from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from markdown_to_mrkdwn import SlackMarkdownConverter

_SLACK_MRKDWN_CONVERTER: SlackMarkdownConverter | None = None
SLACK_SECTION_TEXT_MAX_LEN = 2900

# Matches a converter-emitted Slack angle token: `<dest>` or `<dest|label>`. Input `<`/`>`
# are escaped before conversion, so any literal angle bracket here was produced by the converter.
_SLACK_ANGLE_TOKEN_RE = re.compile(r"<([^<>|]*)(\|[^<>]*)?>")

# A report summary places a chart inline with a markdown link whose target is `chart:<chart_id>`.
# Slack has no chart to render, and the two Slack paths degrade it differently badly: the mrkdwn
# converter turns it into a `<chart:id|label>` token that `_defang_unsafe_slack_tokens` escapes into
# visible `&lt;…&gt;`, while the excerpt path escapes it and leaves the raw `[label](chart:id)` syntax
# on screen. Any target is matched, not just the id charset `ChartArtefact` enforces: a typo'd
# reference is just as unrenderable here, and pinning the charset would leave it showing as markup.
# A markdown link title (`[label](chart:id "a note")`) is a form the inbox renders — mdast parses the
# title off the destination and resolves the reference — so the title is matched as its own quoted
# run rather than by scanning to the first `)`. A title is allowed to contain parens (`"signups
# (UTC)"`), and scanning to the first one would end the match inside it and leave the tail (`")`) in
# the prose, which reads worse than the raw link it replaced.
# `![…]` is an image and `\[…]` is an escaped bracket, neither of which the inbox resolves as a
# reference, so a fixed-width lookbehind leaves both as the author wrote them. A reference inside a
# code span is the one literal form still rewritten: the renderer shows it verbatim while Slack gets
# the label. Telling them apart needs a markdown parse, which this module deliberately doesn't have,
# and the result is prose that reads oddly rather than prose that misleads.
# Every class excludes `[`, which keeps the scan linear. Without it, a summary of `[a](chart:` over
# and over makes every start position scan the whole remaining suffix before failing, and a summary
# is long enough for that to cost seconds of a Celery worker.
_CHART_REF_LINK_RE = re.compile(r"""(?<![!\\])\[([^\[\]\n]*)\]\(chart:[^\s)\[]*(?:\s+"[^"\n]*"|\s+'[^'\n]*')?\s*\)""")


def strip_chart_references(text: str) -> str:
    """Reduce a summary's `[label](chart:<id>)` links to their label, leaving the prose intact."""
    return _CHART_REF_LINK_RE.sub(r"\1", text)


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


def _get_slack_mrkdwn_converter() -> SlackMarkdownConverter:
    """Lazily import and cache the converter so it stays off the django.setup() path."""
    global _SLACK_MRKDWN_CONVERTER
    if _SLACK_MRKDWN_CONVERTER is None:
        from markdown_to_mrkdwn import (
            SlackMarkdownConverter,  # noqa: PLC0415 — keeps the dep off the app-registry startup path
        )

        _SLACK_MRKDWN_CONVERTER = SlackMarkdownConverter()
    return _SLACK_MRKDWN_CONVERTER


def markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert untrusted Markdown to Slack mrkdwn without allowing mention injection."""
    return _defang_unsafe_slack_tokens(_get_slack_mrkdwn_converter().convert(escape_slack_mrkdwn(text)))


def truncate_slack_section(text: str) -> str:
    """Keep mrkdwn below Slack's 3000-character section limit with headroom."""
    if len(text) <= SLACK_SECTION_TEXT_MAX_LEN:
        return text
    return text[: SLACK_SECTION_TEXT_MAX_LEN - 1].rstrip() + "…"


def slack_channel_id_from_target(value: str) -> str:
    """Extract the Slack channel ID from the frontend picker's `id|#name` value."""
    return value.split("|", 1)[0].strip()
