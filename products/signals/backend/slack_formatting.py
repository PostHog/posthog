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

# A summary places a chart inline with a markdown link targeting `chart:<chart_id>`. Slack cannot
# place an image mid-sentence and degrades the link badly either way: the mrkdwn converter emits a
# `<chart:id|label>` token that `_defang_unsafe_slack_tokens` escapes into visible `&lt;…&gt;`, and
# the excerpt path shows the raw `[label](chart:id)` syntax. So the link is reduced to its label
# first; report delivery renders the charts as image blocks after the prose instead.
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


# A top-of-line ATX heading (`# `…`###### `). The scout writes its summary in Markdown, so its own
# headings are the natural seams to split a long report on for threaded Slack delivery.
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}[ \t]+\S")
# Opens or closes a fenced code block (``` or ~~~, up to three leading spaces per CommonMark). A
# `# ` line inside a fence is code, not a heading: splitting there would orphan the fence and hand
# the snippet to the mrkdwn converter as prose.
_MARKDOWN_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _heading_line_offsets(text: str) -> list[int]:
    """Character offsets of the ATX heading lines, skipping any inside a fenced code block."""
    offsets: list[int] = []
    fence: str | None = None  # marker of the currently open fence, else None
    offset = 0
    for line in text.split("\n"):
        fence_match = _MARKDOWN_FENCE_RE.match(line)
        if fence is not None:
            # Close only on the same fence character, at least as long as the opener (CommonMark).
            if fence_match and fence_match.group(1)[0] == fence[0] and len(fence_match.group(1)) >= len(fence):
                fence = None
        elif fence_match:
            fence = fence_match.group(1)
        elif _MARKDOWN_HEADING_RE.match(line):
            offsets.append(offset)
        offset += len(line) + 1  # +1 for the "\n" that split dropped
    return offsets


def split_markdown_by_headings(text: str) -> list[str]:
    """Split a Markdown summary into the lead and one segment per heading.

    The first element is the text before the first heading (empty when the summary opens with one).
    Each later element is a heading and the body under it. Headings inside fenced code blocks are
    left in place, so a snippet is never split mid-fence. No content is dropped."""
    text = text.strip()
    if not text:
        return []
    starts = _heading_line_offsets(text)
    if not starts:
        return [text]
    segments = [text[: starts[0]]]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        segments.append(text[start:end])
    return segments


# End of a sentence, allowing a closing quote or bracket before the space that follows it.
_SENTENCE_END_RE = re.compile(r"[.!?…][\"')\]]*\s")
_WHITESPACE_RUN_RE = re.compile(r"\s+")
# A converter-emitted angle token left open at the end of a candidate chunk, as in `<https://ex`.
# Slack renders each half of a broken link as visible junk, so a cut here moves back before the `<`.
_TRAILING_OPEN_ANGLE_RE = re.compile(r"<[^<>]*$")
# A break earlier than this share of the limit spends a whole reply on a stub, so the ladder in
# `_line_break_index` prefers the next (later-breaking) rung over an early sentence or word end.
_MIN_LINE_BREAK_FILL = 0.6


def _pull_back_before_open_angle(window: str, index: int) -> int:
    """Move a cut back before an angle token it would otherwise split, or leave it alone."""
    match = _TRAILING_OPEN_ANGLE_RE.search(window[:index])
    return match.start() if match else index


def _line_break_index(line: str, limit: int) -> int:
    """Index to cut a line that exceeds the limit on its own, preferring the most readable boundary.

    Tries a sentence end, then any whitespace, so a reply never opens mid-word. Falls back to the
    limit only for an unbreakable run such as a long URL or an encoded blob. Every rung stays out of
    an angle token, because half a link is worse to read than an early break."""
    window = line[:limit]
    floor = int(limit * _MIN_LINE_BREAK_FILL)
    for pattern in (_SENTENCE_END_RE, _WHITESPACE_RUN_RE):
        matches = list(pattern.finditer(window))
        if not matches:
            continue
        index = _pull_back_before_open_angle(window, matches[-1].end())
        if index >= floor:
            return index
    hard_cut = _pull_back_before_open_angle(window, limit)
    # A token longer than the whole window has nowhere safe to break, so the link is split anyway.
    return hard_cut if hard_cut > 0 else limit


def chunk_slack_mrkdwn(text: str) -> list[str]:
    """Split converted mrkdwn into chunks that each fit one Slack section, breaking on line ends.

    A line longer than the limit on its own breaks at the best boundary `_line_break_index` finds,
    so a report written as unbroken prose still reads as sentences. Returns no empty chunks, so the
    tail of a long report reaches the channel instead of being clipped at the section cap."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= SLACK_SECTION_TEXT_MAX_LEN:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > SLACK_SECTION_TEXT_MAX_LEN:
            if current:
                chunks.append(current.rstrip())
                current = ""
            cut = _line_break_index(line, SLACK_SECTION_TEXT_MAX_LEN)
            chunks.append(line[:cut].rstrip())
            line = line[cut:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > SLACK_SECTION_TEXT_MAX_LEN:
            if current:
                chunks.append(current.rstrip())
            current = line
        else:
            current = candidate
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def slack_channel_id_from_target(value: str) -> str:
    """Extract the Slack channel ID from the frontend picker's `id|#name` value."""
    return value.split("|", 1)[0].strip()
