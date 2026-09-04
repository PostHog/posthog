from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

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
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+\S")
# Opens a fenced code block (``` or ~~~, up to three leading spaces per CommonMark), with anything
# after the marker read as the info string. A `# ` line inside a fence is code, not a heading:
# splitting there would orphan the fence and hand the snippet to the mrkdwn converter as prose.
_MARKDOWN_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# Closes one. CommonMark allows only trailing whitespace after a closing fence, so a marker line
# carrying other text stays code. Reading it as the close resumes seam detection inside the
# snippet, which splits the report mid-fence.
_MARKDOWN_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")

# A line that opens with a bold run (`**Label**` or `__Label__`), keeping the rest of the line so
# `_bold_seam_level` can read what follows the label. The label itself cannot hold the marker, so
# `**one** and **two**` reads as inline bold instead of one long label.
_LEADING_BOLD_RUN_RE = re.compile(r"^(\*\*|__)(?=\S)((?:(?!\1).)+)(?<!\s)\1(.*)$")
# What separates a bold label from the prose it leads: `**Label**: prose`, or `**Label** - prose`
# with a hyphen, an en dash, or an em dash.
_BOLD_LEAD_SEPARATOR_RE = re.compile(r"^(?::[ \t]+|[ \t]+[-–—][ \t]+)\S")
# `**Label:** prose` keeps the colon inside the bold run, so there the space alone separates them.
_BOLD_LEAD_SPACE_RE = re.compile(r"^[ \t]+\S")
# A label longer than this is a sentence bolded for emphasis rather than a section label. Slack
# renders the two the same way, so length is what tells them apart.
_MAX_BOLD_LABEL_LENGTH = 80
# Bold seams rank below every ATX level (1 to 6), so a summary that also has real headings splits
# at those and keeps its bold labels inside their section. A label on a line of its own marks a
# section more strongly than one leading a paragraph, so it ranks ahead of it.
_STANDALONE_BOLD_LEVEL = 7
_BOLD_LEAD_PARAGRAPH_LEVEL = 8


@frozen
class _MarkdownSeam:
    """Where a section starts in the text, and how deep the seam that opens it is. Both fields are
    plain ints, so a tuple would let a call site read the level as an offset."""

    offset: int
    level: int


def _bold_seam_level(line: str) -> int | None:
    """The pseudo-heading level of a bold-labelled line, or None when the line is not a seam.

    Scouts label their sections in bold much more often than they write an ATX heading, and Slack
    renders `**Evidence**` and `## Evidence` identically, so a bold label has to count as a seam or
    threading does nothing for those reports. Two shapes count: a label standing alone on its line,
    and a label leading its paragraph's prose. A bold run with prose after it but no separator, as
    in `**31** organizations reported this`, is emphasis rather than a label."""
    match = _LEADING_BOLD_RUN_RE.match(line)
    if not match:
        return None
    label, rest = match.group(2), match.group(3)
    if len(label) > _MAX_BOLD_LABEL_LENGTH:
        return None
    if rest.strip() in ("", ":"):
        return _STANDALONE_BOLD_LEVEL
    if _BOLD_LEAD_SEPARATOR_RE.match(rest) or (label.endswith(":") and _BOLD_LEAD_SPACE_RE.match(rest)):
        return _BOLD_LEAD_PARAGRAPH_LEVEL
    return None


def _markdown_seams(text: str) -> list[_MarkdownSeam]:
    """Every seam the text can split at: its ATX headings, and its bold section labels.

    Anything inside a fenced code block is code rather than a seam. A bold label counts only when a
    blank line or the start of the text comes before it, so bold inside a paragraph is left alone
    and a label a list item continues onto stays part of that list."""
    seams: list[_MarkdownSeam] = []
    fence: str | None = None  # marker of the currently open fence, else None
    preceded_by_blank = True  # the start of the text opens a block the same way a blank line does
    offset = 0
    for line in text.split("\n"):
        if fence is not None:
            # Close only on the same fence character, at least as long as the opener (CommonMark).
            close_match = _MARKDOWN_FENCE_CLOSE_RE.match(line)
            if close_match and close_match.group(1)[0] == fence[0] and len(close_match.group(1)) >= len(fence):
                fence = None
        elif fence_match := _MARKDOWN_FENCE_RE.match(line):
            fence = fence_match.group(1)
        else:
            heading_match = _MARKDOWN_HEADING_RE.match(line)
            if heading_match:
                seams.append(_MarkdownSeam(offset=offset, level=len(heading_match.group(1))))
            elif preceded_by_blank:
                bold_level = _bold_seam_level(line)
                if bold_level is not None:
                    seams.append(_MarkdownSeam(offset=offset, level=bold_level))
        preceded_by_blank = not line.strip()
        offset += len(line) + 1  # +1 for the "\n" that split dropped
    return seams


def _split_seam_level(levels: list[int]) -> int:
    """The shallowest seam level the text repeats at, else the shallowest level present.

    A level that appears once is the summary's own title rather than a seam between sections, so
    splitting there would return the whole summary as one segment."""
    counts = Counter(levels)
    repeated = sorted(level for level, count in counts.items() if count > 1)
    return repeated[0] if repeated else min(levels)


def split_markdown_by_headings(text: str) -> list[str]:
    """Split a Markdown summary into the lead and one segment per top-level section.

    A section is opened by an ATX heading or by a bold label, whichever the summary uses. The first
    element is the text before the first split point (empty when the summary opens with a seam of
    that level). Each later element is a seam and everything under it, including its sub-sections,
    so a segment holds the same block a reader folds shut. Seams inside fenced code blocks are left
    in place, so a snippet is never split mid-fence. No content is dropped."""
    text = text.strip()
    if not text:
        return []
    seams = _markdown_seams(text)
    if not seams:
        return [text]
    split_level = _split_seam_level([seam.level for seam in seams])
    starts = [seam.offset for seam in seams if seam.level == split_level]
    segments = [text[: starts[0]]]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        segments.append(text[start:end])
    return segments


# A threaded delivery posts one Slack message per segment, in sequence. A well-formed report has a
# handful of sections, so a summary that yields more than this labelled every paragraph or repeated
# one label. Grouping the overflow keeps the thread readable and bounds the requests one delivery
# makes to Slack, which it sends one after another with every failure swallowed.
MAX_THREAD_SEGMENTS = 12


def group_segments_to_limit(segments: list[str], limit: int = MAX_THREAD_SEGMENTS) -> list[str]:
    """Merge neighboring segments until at most `limit` remain, leaving the lead on its own.

    The lead is the channel message, so it keeps exactly what the summary put before its first
    section. The sections after it are grouped in even runs, so the thread still follows the
    report's order. No content is dropped."""
    if len(segments) <= limit:
        return segments
    lead, sections = segments[0], segments[1:]
    per_group = -(-len(sections) // max(1, limit - 1))  # ceiling division
    return [lead] + ["".join(sections[index : index + per_group]) for index in range(0, len(sections), per_group)]


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
