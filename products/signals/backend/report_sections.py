import re
import math

from markdown_it import MarkdownIt
from markdown_it.token import Token

from posthog.dataclasses import frozen


@frozen
class ReportSections:
    lead: str
    impact: str | None
    solution: str | None


@frozen
class _Section:
    heading: str
    body: str


@frozen
class _Heading:
    line: int
    body_line: int
    text: str


@frozen
class _SplitSummary:
    lead: str
    sections: list[_Section]


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_MARKDOWN = MarkdownIt("commonmark")
_MAX_SECTION_DEPTH = 3
_HEADING_WORD_LIMIT = 6
_SECTION_ALIASES = {
    "problem": "problem",
    "the problem": "problem",
    "impact": "impact",
    "expected impact": "expected impact",
    "solution": "solution",
    "fix": "solution",
    "the fix": "solution",
    "proposed fix": "solution",
    "recommended fix": "solution",
    "recommendation": "solution",
}
_PARAGRAPH_IMPACT_HEADINGS = frozenset({"impact"})
_PARAGRAPH_SOLUTION_HEADINGS = frozenset(
    {
        "solution",
        "the solution",
        "fix",
        "the fix",
        "proposed fix",
        "recommended fix",
        "suggested fix",
        "smallest fix",
        "recommendation",
        "recommendations",
        "recommended action",
        "recommended next step",
        "recommended next steps",
        "next step",
        "next steps",
    }
)
_PARAGRAPH_HEADING = re.compile(r"^\*\*([^*\n]+?):?\*\*:?\s*$")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_TRAILING_CHART_LINK = re.compile(r"(?<=[.!?])\s*\[[^\[\]]*\]\(chart:[^)\[]*\)\.?(?=\s*$|\n)", re.MULTILINE)
_CHART_LINK = re.compile(r"\[([^\[\]]*)\]\(chart:[^)\[]*\)")


def _without_chart_links(markdown: str) -> str:
    return _CHART_LINK.sub(r"\1", _TRAILING_CHART_LINK.sub("", markdown)).strip()


def _first_paragraph(markdown: str) -> str:
    return next((paragraph.strip() for paragraph in _PARAGRAPH_BREAK.split(markdown) if paragraph.strip()), "")


def _clean_section(body: str | None) -> str | None:
    if not body or not body.strip():
        return None
    return _without_chart_links(body) or None


def _heading_text(inline: Token) -> str:
    text = "".join(child.content for child in inline.children or [] if child.type in ("text", "code_inline"))
    return text.strip().removesuffix(":").strip()


def _heading_sections(summary: str) -> _SplitSummary:
    lines = summary.split("\n")
    tokens = _MARKDOWN.parse(summary)
    headings: list[_Heading] = []
    open_depth = math.inf
    for index, token in enumerate(tokens):
        depth = int(token.tag[1:]) if token.type == "heading_open" else math.inf
        if depth > _MAX_SECTION_DEPTH or token.level != 0 or token.map is None:
            continue
        heading = _heading_text(tokens[index + 1])
        if heading.lower() in _SECTION_ALIASES or depth <= open_depth:
            headings.append(_Heading(line=token.map[0], body_line=token.map[1], text=heading))
            open_depth = depth
    if not headings:
        return _SplitSummary(lead=summary.strip(), sections=[])
    ends = [heading.line for heading in headings[1:]] + [len(lines)]
    sections = [
        _Section(heading=heading.text, body="\n".join(lines[heading.body_line : end]).strip())
        for heading, end in zip(headings, ends)
    ]
    return _SplitSummary(lead="\n".join(lines[: headings[0].line]).strip(), sections=sections)


def _paragraph_heading(line: str) -> str | None:
    match = _PARAGRAPH_HEADING.match(line.strip())
    heading = match.group(1).strip() if match else None
    if heading is None or heading.endswith((".", "!", "?")) or len(heading.split()) > _HEADING_WORD_LIMIT:
        return None
    return heading


@frozen
class _OpenSection:
    heading: str
    lines: list[str]


def _paragraph_heading_sections(markdown: str) -> _SplitSummary:
    lead_lines: list[str] = []
    sections: list[_OpenSection] = []
    current = lead_lines
    fence: str | None = None
    for line in markdown.split("\n"):
        marker = _FENCE.match(line)
        if marker and (fence is None or marker.group(1).startswith(fence)):
            fence = marker.group(1)[:3] if fence is None else None
        heading = _paragraph_heading(line) if fence is None and not marker else None
        if heading:
            sections.append(_OpenSection(heading=heading, lines=[]))
            current = sections[-1].lines
        else:
            current.append(line)
    return _SplitSummary(
        lead="\n".join(lead_lines).strip(),
        sections=[_Section(heading=section.heading, body="\n".join(section.lines).strip()) for section in sections],
    )


def _aliased_body(sections: list[_Section], kind: str) -> str | None:
    return next((section.body for section in sections if _SECTION_ALIASES.get(section.heading.lower()) == kind), None)


def _named_body(sections: list[_Section], names: frozenset[str]) -> str | None:
    return next((section.body for section in sections if section.heading.lower() in names and section.body), None)


def _opening_body(sections: list[_Section]) -> str:
    opening = sections[0] if sections else None
    if opening is None or _SECTION_ALIASES.get(opening.heading.lower()) not in (None, "problem"):
        return ""
    return opening.body


def report_sections(summary: str | None) -> ReportSections:
    split = _heading_sections(summary or "")
    if split.sections:
        return ReportSections(
            lead=_without_chart_links(_first_paragraph(split.lead or _opening_body(split.sections))),
            impact=_clean_section(_aliased_body(split.sections, "impact")),
            solution=_clean_section(_aliased_body(split.sections, "solution")),
        )
    paragraphs = _paragraph_heading_sections(split.lead)
    return ReportSections(
        lead=_without_chart_links(_first_paragraph(paragraphs.lead)),
        impact=_clean_section(_named_body(paragraphs.sections, _PARAGRAPH_IMPACT_HEADINGS)),
        solution=_clean_section(_named_body(paragraphs.sections, _PARAGRAPH_SOLUTION_HEADINGS)),
    )
