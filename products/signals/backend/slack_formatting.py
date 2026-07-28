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

# A summary places a chart inline with a markdown link targeting `chart:<chart_id>`. Slack has no
# chart to render and degrades it badly either way: the mrkdwn converter emits a `<chart:id|label>`
# token that `_defang_unsafe_slack_tokens` escapes into visible `&lt;…&gt;`, and the excerpt path
# shows the raw `[label](chart:id)` syntax. So the link is reduced to its label first.
#
# The shapes matched are the ones the inbox's markdown parse resolves and therefore draws a chart
# for: any target rather than the id charset (a typo is just as unrenderable), all three CommonMark
# title delimiters, the angle-bracket destination form, and a label holding balanced or escaped
# brackets. `![…]` and `\[…]` are neither, so the lookbehind leaves them alone.
#
# Load-bearing: every destination class excludes `[`. Without it a summary of `[a](chart:` repeated
# to the 20,000-character bound makes each start position rescan the whole suffix, costing seconds
# inside the Celery worker that sends the notification. Covered by a timing test.
_CHART_REF_LINK_RE = re.compile(
    r"""(?<![!\\])\[((?:[^\[\]\n\\]|\\.|\[[^\[\]\n]*\])*)\]"""
    r"""\((?:chart:[^\s)\[]*|<chart:[^<>\n\[]*>)"""
    r"""(?:\s+"[^"\n]*"|\s+'[^'\n]*'|\s+\([^()\n]*\))?\s*\)"""
)


# The reference form the inbox also resolves: `[Daily][daily]` with `[daily]: chart:signups-drop`
# somewhere in the summary. Both halves have to go — the reference, or Slack shows brackets around a
# label that points nowhere, and the definition line, or it shows the raw `chart:` target. The
# reference covers all three shapes (full, collapsed, shortcut); a match followed by `(` is an
# inline link whose destination isn't a chart, so it keeps its brackets.
_CHART_REF_DEFINITION_RE = re.compile(
    r"""^[ ]{0,3}\[([^\[\]\n]+)\]:[ \t]*<?chart:[^\s>]*>?"""
    r"""[ \t]*(?:"[^"\n]*"|'[^'\n]*'|\([^()\n]*\))?[ \t]*\n?""",
    re.MULTILINE,
)
_REFERENCE_LINK_RE = re.compile(r"""(?<![!\\])\[((?:[^\[\]\n\\]|\\.)*)\](\[([^\[\]\n]*)\])?(?!\()""")


def _normalized_label(label: str) -> str:
    """A CommonMark link label as matching compares it: case-folded, with runs of space collapsed."""
    return " ".join(label.split()).casefold()


def strip_chart_references(text: str) -> str:
    """Reduce a summary's chart references to their label, leaving the prose intact.

    Covers the inline form (`[Daily](chart:daily)`) and the reference form the inbox resolves through
    a definition. Everything else is left exactly as the author wrote it."""
    text = _CHART_REF_LINK_RE.sub(r"\1", text)

    identifiers = {_normalized_label(m.group(1)) for m in _CHART_REF_DEFINITION_RE.finditer(text)}
    if not identifiers:
        return text

    def _reduce(match: re.Match[str]) -> str:
        label, bracketed, identifier = match.group(1), match.group(2), match.group(3)
        # Full form points at its own identifier; collapsed and shortcut point at the label.
        target = identifier if bracketed and identifier else label
        return label if _normalized_label(target) in identifiers else match.group(0)

    # Definitions go first: a definition opens with a bracketed label of its own, and reducing that
    # to bare text would leave the line behind as `daily: chart:signups-drop` for Slack to show.
    return _REFERENCE_LINK_RE.sub(_reduce, _CHART_REF_DEFINITION_RE.sub("", text))


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
