import re
from itertools import islice
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


class ReportTextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["text", "name", "value", "time"]
    text: str


class ReportLinkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["link"]
    text: str
    url: str = Field(description="The complete original URL from the query results. Never shorten or rewrite it.")


class ReportChangeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["change"]
    text: str
    direction: Literal["increase", "decrease"]


# Templates mark an empty line with a literal "\n", and the model sometimes copies it as text.
_LITERAL_NEWLINE_LINE = re.compile(r"^[ \t]*(?:\\n[ \t]*)+$", re.MULTILINE)

_EMPHASIS_MARKER = re.compile(r"\*\*|__|~~|\*|_")


def _is_word_or_marker(char: str) -> bool:
    return char.isalnum() or char in "*_~"


def _trim_emphasis_padding(line: str) -> str:
    """Remove spaces just inside each pair of emphasis markers on one line.

    Item joining puts a space between a template's marker item and the next item, as in
    "** Total **", and a space just inside a pair of markers stops it rendering as bold, italic, or
    struck through. This is one pass over the markers, because report text has no length limit
    and a backtracking regex took seconds on a long line.
    """
    open_ends: dict[str, int] = {}
    removed: set[int] = set()
    for marker in _EMPHASIS_MARKER.finditer(line):
        start, end = marker.span()
        token = marker.group()
        opened_at = open_ends.get(token)
        if opened_at is not None and (end == len(line) or not _is_word_or_marker(line[end])):
            del open_ends[token]
            if not line[opened_at:start].strip():
                continue
            index = opened_at
            while line[index] in " \t":
                removed.add(index)
                index += 1
            index = start - 1
            while line[index] in " \t":
                removed.add(index)
                index -= 1
        elif opened_at is None and (start == 0 or not _is_word_or_marker(line[start - 1])):
            open_ends[token] = end
    if not removed:
        return line
    return "".join(char for index, char in enumerate(line) if index not in removed)


_TABLE_SEPARATOR_ROW = re.compile(r"^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?$")


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|")


def _next_lines(lines: list[str], count: int) -> list[str]:
    return list(islice((line for line in lines if line.strip()), count))


def _join_table_rows(markdown: str) -> str:
    """Remove the blank lines between rows of one Markdown table.

    The model often returns a table as one visual per row. A blank line between rows ends the
    table, so Slack and email would show every row, separator included, as its own paragraph.
    A blank line stays before a header row whose next line is a separator row, which keeps two
    tables in a row apart.
    """
    lines = markdown.split("\n")
    kept: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() or not kept or not _is_table_row(kept[-1]):
            kept.append(line)
            continue
        following = _next_lines(lines[index + 1 :], 2)
        next_row = following[0] if following else ""
        starts_new_table = len(following) > 1 and bool(_TABLE_SEPARATOR_ROW.match(following[1].strip()))
        if not _is_table_row(next_row) or starts_new_table:
            kept.append(line)
    return "\n".join(kept)


class ReportText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReportTextItem | ReportLinkItem | ReportChangeItem]

    def render(self, *, styled: bool = True) -> str:
        parts: list[str] = []
        previous_text = ""
        for item in self.items:
            if (
                previous_text
                and item.text
                and not previous_text[-1].isspace()
                and not item.text[0].isspace()
                and item.text[0] not in ".,;:!?)]}"
                and previous_text[-1] not in "([{"
            ):
                parts.append(" ")
            if item.kind == "link" and item.url:
                label = item.text.replace("`", "")
                if label.startswith(("http://", "https://")):
                    try:
                        parsed = urlsplit(item.url)
                        label = "/".join(parsed.path.strip("/").split("/")[-2:]) or parsed.hostname or "Page"
                    except ValueError:
                        label = "Page"
                parts.append(f"[{label}]({item.url})")
            elif not styled:
                parts.append(f"{_change_prefix(item)}{item.text}")
            elif item.kind == "change":
                parts.append(_inline_code(item.text, prefix=_change_prefix(item)))
            elif item.kind in ("name", "value"):
                parts.append(_inline_code(item.text))
            elif item.kind == "time":
                parts.append(_wrap(item.text, "_"))
            else:
                parts.append(item.text)
            previous_text = item.text
        return "".join(parts)

    def render_bullet(self) -> str:
        content = re.sub(r"^(?:[ \t]*(?:[-+*•]|\d+[.)])[ \t]+)+", "", self.render().strip())
        if not content:
            return ""
        return f"- {content}"


def _change_prefix(item: ReportTextItem | ReportLinkItem | ReportChangeItem) -> str:
    if not isinstance(item, ReportChangeItem):
        return ""
    return "▲ " if item.direction == "increase" else "▼ "


def _wrap(text: str, marker: str, prefix: str = "") -> str:
    # Markers go inside the item's surrounding spaces, because "` 18s`" or "_ Nov 4_" do not render as code or italic.
    core = text.strip()
    if not core:
        return text
    start = text.index(core)
    return f"{text[:start]}{marker}{prefix}{core}{marker}{text[start + len(core) :]}"


def _inline_code(text: str, prefix: str = "") -> str:
    # A backtick inside the item would end the code span early.
    return _wrap(text.replace("`", ""), "`", prefix)


class ReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[ReportText]

    def render(self) -> str:
        return "\n\n".join(finding.render_bullet() for finding in self.findings)


class ReportSubsection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(
        description="A complete topic label of two to five words. Do not truncate words. Put findings and dates in bullets."
    )
    findings: list[ReportText]
    visuals: list[ReportText]

    def render(self) -> str:
        parts = [f"### {self.heading}"]
        parts.extend(finding.render_bullet() for finding in self.findings)
        parts.extend(visual.render() for visual in self.visuals)
        return "\n\n".join(parts)


class ReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(
        description="A complete topic label of two to five words. Do not truncate words. Put findings and dates in bullets."
    )
    findings: list[ReportText]
    subsections: list[ReportSubsection]
    visuals: list[ReportText]

    def render(self) -> str:
        parts = [f"## {self.heading}"]
        parts.extend(finding.render_bullet() for finding in self.findings)
        parts.extend(subsection.render() for subsection in self.subsections)
        parts.extend(visual.render() for visual in self.visuals)
        return "\n\n".join(parts)


class ReportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str | None = Field(
        description="A complete major topic label of two to five words, or null for a short report. Do not truncate words. Put dates and reporting periods in findings instead of the topic."
    )
    sections: list[ReportSection] = Field(
        description="Sections in decreasing order of importance. The first gives the main result, key evidence, and any necessary action or caveat. Later sections add supporting detail."
    )
    custom_layout: list[ReportText] = Field(
        description="Use only when the user explicitly requests a fixed output template. Otherwise return an empty list. One part per template line. Copy the template's own Markdown, such as bold markers, into text items exactly where the template has them."
    )

    def render(self) -> str:
        if self.custom_layout:
            parts: list[str] = []
            for part in self.custom_layout:
                if parts and not parts[-1].endswith("\n"):
                    parts.append("\n")
                # The user's template decides the formatting, so item kinds add no code or italic styles here.
                parts.append(part.render(styled=False))
            markdown = _LITERAL_NEWLINE_LINE.sub("", "".join(parts))
            return _join_table_rows("\n".join(_trim_emphasis_padding(line) for line in markdown.split("\n")))
        parts = [f"# {self.topic}"] if self.topic else []
        parts.extend(section.render() for section in self.sections)
        return _join_table_rows("\n\n".join(parts))


REPORT_TEXT_INSTRUCTIONS = """Return structured text items. The renderer applies inline styles from their kinds.
- Use kind=link for a page or referrer with a supplied URL. Put a short descriptive label in text and the complete original destination in url. Do not put link brackets or Markdown link syntax in text. Do not replace a supplied URL with an unlinked name item. Do not include url for other kinds.
- Use kind=name for every event name and metric name, including repeated mentions.
- Use kind=value for each measured count, amount, and percentage. Include its unit in the same item.
- Use kind=change for a measured increase or decrease against an explicit comparable baseline. Set direction to increase or decrease and put the change amount with its unit in text. The renderer adds a direction triangle. Do not add arrows to the text.
- Use change items only for differences, not absolute values, dates, incomplete periods, or funnel step drop-offs. If the baseline or change is uncertain, use plain text. An increase is not automatically good and a decrease is not automatically bad.
- Use kind=time for every date, clock time, duration, and reporting window, even when it contains numbers.
- Use kind=text for connecting words, punctuation, and Markdown structure. Never include event names, measured values, or dates inside a text item.
- Outside a user's fixed template, do not include bold, italic, or underline markers in item text. Keep each styled item to the relevant name, value, or time expression.
- Preserve sentence order, spaces, and line breaks across items. Write complete sentences; do not rearrange a sentence to group items by kind.
- Keep inline code and code blocks literal; do not style their contents.
- Review every mention before returning the report. Use the same kind for the same item throughout the report."""
