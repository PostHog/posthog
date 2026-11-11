"""Rendering arms and deterministic scorers for the summary styling eval.

Every scorer reads what Slack would show: the rendered summary goes through
`slack_rich_text`, and a span counts as styled only when every character of it
lands in a bold (or italic) rich-text element.

The value and name lists come from the case input, not from the normaliser's
patterns, so the normalised arm cannot score well by construction. The date
detector below is independent of `report_text._TIME_PATTERNS` on purpose, and
it also matches relative words ("yesterday", "this week") that the normaliser
does not style.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from posthog.slack.markdown import slack_rich_text

from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.subscriptions.backend.logic.report_text import ReportSummary, ReportText, ReportTextItem

SLACK_ALLOWED_ROOT = "https://app.example.com/"

ARM_RAW = "raw"
ARM_NORMALISED = "normalised"
ARM_MARKDOWN = "markdown"
ARM_MARKDOWN_NORMALISED = "markdown_normalised"
ARMS = (ARM_RAW, ARM_NORMALISED, ARM_MARKDOWN, ARM_MARKDOWN_NORMALISED)

# Each normalised arm is compared with the arm it was rendered from.
NORMALISED_ARM_SOURCES = {ARM_NORMALISED: ARM_RAW, ARM_MARKDOWN_NORMALISED: ARM_MARKDOWN}

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_DATE_PATTERN = re.compile(
    "|".join(
        [
            r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?",
            rf"\b{_MONTH} \d{{1,2}}(?:st|nd|rd|th)?(?:\s?[-–]\s?(?:{_MONTH} )?\d{{1,2}})?(?:,? \d{{4}})?\b",
            rf"\b\d{{1,2}} {_MONTH}(?: \d{{4}})?\b",
            r"\b(?:Mon|Tue|Tues|Wed|Wednes|Thu|Thurs|Fri|Sat|Satur|Sun)(?:day)s?\b",
            r"\b(?:the )?(?:last|past|previous|prior|next) (?:\d+ )?(?:hours?|days?|weeks?|months?|quarters?|years?)\b",
            r"\b(?:today|yesterday|this (?:week|month|quarter|year))\b",
        ]
    ),
    re.IGNORECASE,
)
_DURATION_VALUE = re.compile(r"^\d+(?:\.\d+)?\s?[a-z]+(?: \d+(?:\.\d+)?\s?[a-z]+)*$")
_MARKDOWN_LINK = re.compile(r"\[[^\]\n]*\]\(([^()\s]+)\)")
_BARE_URL = re.compile(r"https?://[^\s)\]>]+")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_LINK_LABEL = re.compile(r"\[([^\]\n]*)\]\([^)\s]+\)")
_EMPHASIS_MARKER = re.compile(r"\*|(?<!\w)_\S|\S_(?!\w)")


@dataclass(frozen=True)
class StyledSegment:
    start: int
    end: int
    bold: bool
    italic: bool
    code: bool


@dataclass(frozen=True)
class SlackView:
    """The plain text Slack would show, with the style of each character range."""

    text: str
    segments: tuple[StyledSegment, ...]

    def covered(self, start: int, end: int, *, bold: bool = False, italic: bool = False) -> bool:
        for position in range(start, end):
            segment = next((s for s in self.segments if s.start <= position < s.end), None)
            if segment is None:
                return False
            if bold and italic:
                if not (segment.bold or segment.italic):
                    return False
            elif bold and not segment.bold:
                return False
            elif italic and not segment.italic:
                return False
        return True

    def in_code(self, start: int, end: int) -> bool:
        return any(s.code and s.start < end and start < s.end for s in self.segments)


def slack_view(rendered: str) -> SlackView:
    block = slack_rich_text(rendered, allowed_root=SLACK_ALLOWED_ROOT)
    text_parts: list[str] = []
    segments: list[StyledSegment] = []
    cursor = 0
    for index, element in enumerate(block["elements"]):
        sections = element["elements"] if element["type"] == "rich_text_list" else [element]
        for section_index, section in enumerate(sections):
            if index or section_index:
                text_parts.append("\n")
                cursor += 1
            for inline in section["elements"]:
                piece = inline.get("text", "")
                style = inline.get("style", {})
                segments.append(
                    StyledSegment(
                        start=cursor,
                        end=cursor + len(piece),
                        bold=bool(style.get("bold")),
                        italic=bool(style.get("italic")),
                        code=bool(style.get("code")),
                    )
                )
                text_parts.append(piece)
                cursor += len(piece)
    return SlackView(text="".join(text_parts), segments=tuple(segments))


def render_structured(summary: ReportSummary, *, normalised: bool) -> str:
    return "\n\n".join(finding.render_bullet("•", "*", style_untagged_text=normalised) for finding in summary.findings)


def normalise_markdown(markdown: str) -> str:
    return "\n".join(
        ReportText(items=[ReportTextItem(kind="text", text=line)]).render(style_untagged_text=True) if line else line
        for line in markdown.splitlines()
    )


def single_text_finding_rate(summary: ReportSummary) -> float | None:
    if not summary.findings:
        return None
    untagged = sum(
        1
        for finding in summary.findings
        if all(item.kind == "text" for item in finding.items) and any(item.text.strip() for item in finding.items)
    )
    return untagged / len(summary.findings)


def render_arms(summary: ReportSummary | None, markdown: str | None) -> dict[str, str]:
    arms: dict[str, str] = {}
    if summary is not None:
        arms[ARM_RAW] = render_structured(summary, normalised=False)
        arms[ARM_NORMALISED] = render_structured(summary, normalised=True)
    if markdown is not None:
        arms[ARM_MARKDOWN] = markdown.strip()
        arms[ARM_MARKDOWN_NORMALISED] = normalise_markdown(markdown.strip())
    return arms


_INPUT_VALUE = re.compile(
    r"=(?:up |down )?(?P<value>\d+(?:\.\d+)?[a-z]+(?: \d+(?:\.\d+)?[a-z]+)*(?![\w-])"
    r"|[$€£]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![\w-]))"
)


def extract_input_values(results_summaries: list[str]) -> list[str]:
    """Values exactly as the summarizer formatted them, e.g. `2,340`, `18%`, `$1,200`, `4d 4h`."""
    values = {match.group("value") for summary in results_summaries for match in _INPUT_VALUE.finditer(summary)}
    return sorted(values, key=len, reverse=True)


def _occurrences(text: str, needle: str, *, ignore_case: bool = False) -> list[tuple[int, int]]:
    flags = re.IGNORECASE if ignore_case else 0
    pattern = rf"(?<![\w$€£.,]){re.escape(needle)}(?![\w%]|[.,]\d)"
    return [(m.start(), m.end()) for m in re.finditer(pattern, text, flags)]


def _without_overlaps(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    kept: list[tuple[int, int]] = []
    for start, end in sorted(spans, key=lambda span: (span[0], -(span[1] - span[0]))):
        if kept and start < kept[-1][1]:
            continue
        kept.append((start, end))
    return kept


@dataclass(frozen=True)
class Ratio:
    hits: int
    total: int
    misses: tuple[str, ...]

    @property
    def score(self) -> float | None:
        return None if self.total == 0 else self.hits / self.total


def values_styled(view: SlackView, values: list[str]) -> Ratio:
    hits, misses, spans = 0, [], []
    for value in values:
        spans.extend(_occurrences(view.text, value))
    kept = _without_overlaps([span for span in spans if not view.in_code(*span)])
    for start, end in kept:
        value = view.text[start:end]
        # The report instructions call a duration a time, so a duration in italic counts as styled.
        is_duration = bool(_DURATION_VALUE.match(value))
        if view.covered(start, end, bold=True, italic=is_duration):
            hits += 1
        else:
            misses.append(value)
    return Ratio(hits=hits, total=len(kept), misses=tuple(misses))


def _date_matches(view: SlackView, names: list[str]) -> list[re.Match[str]]:
    # A date word inside a name ("Upgrades this week") belongs to the name, so it is not a date.
    name_spans = [span for name in names for span in _occurrences(view.text, name, ignore_case=True)]
    return [
        match
        for match in _DATE_PATTERN.finditer(view.text)
        if not view.in_code(match.start(), match.end())
        and not any(start < match.end() and match.start() < end for start, end in name_spans)
    ]


def dates_styled(view: SlackView, names: list[str]) -> Ratio:
    hits, misses = 0, []
    matches = _date_matches(view, names)
    for match in matches:
        if view.covered(match.start(), match.end(), italic=True):
            hits += 1
        else:
            misses.append(match.group())
    return Ratio(hits=hits, total=len(matches), misses=tuple(misses))


def names_tagged(view: SlackView, names: list[str]) -> Ratio:
    spans = []
    for name in sorted(names, key=len, reverse=True):
        spans.extend(_occurrences(view.text, name, ignore_case=True))
    kept = _without_overlaps([span for span in spans if not view.in_code(*span)])
    hits, misses = 0, []
    for start, end in kept:
        if view.covered(start, end, bold=True):
            hits += 1
        else:
            misses.append(view.text[start:end])
    return Ratio(hits=hits, total=len(kept), misses=tuple(misses))


def misstyled(view: SlackView, rendered: str, names: list[str]) -> Ratio:
    """Bold dates, and emphasis markers inside inline code or link labels.

    The total is the number of places a mistake can happen, so a summary with no
    dates, code, or links has no rate.
    """
    mistakes: list[str] = []
    dates = _date_matches(view, names)
    for match in dates:
        if any(s.bold and s.start < match.end() and match.start() < s.end for s in view.segments):
            mistakes.append(f"bold date: {match.group()}")
    literals = [m.group(1) for m in _CODE_SPAN.finditer(rendered)] + [
        m.group(1) for m in _LINK_LABEL.finditer(rendered)
    ]
    for literal in literals:
        if _EMPHASIS_MARKER.search(literal):
            mistakes.append(f"styled literal: {literal}")
    total = len(dates) + len(literals)
    return Ratio(hits=total - len(mistakes), total=total, misses=tuple(mistakes))


def rendered_links(rendered: str) -> list[str]:
    urls = [m.group(1) for m in _MARKDOWN_LINK.finditer(rendered)]
    without_links = _MARKDOWN_LINK.sub("", rendered)
    urls.extend(m.group().rstrip(".,;:") for m in _BARE_URL.finditer(without_links))
    return urls


def link_integrity(rendered: str, input_text: str) -> Ratio:
    urls = rendered_links(rendered)
    misses = tuple(url for url in urls if url not in input_text)
    return Ratio(hits=len(urls) - len(misses), total=len(urls), misses=misses)


def text_preserved(source: str, normalised: str) -> bool:
    return slack_view(source).text == slack_view(normalised).text


def _arm_output(output: dict | None, arm: str) -> str | None:
    if not output:
        return None
    rendered = (output.get("arms") or {}).get(arm)
    return rendered if isinstance(rendered, str) else None


class _ArmScorer(Scorer):
    metric = ""

    def __init__(self, arm: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.arm = arm

    def _name(self) -> str:
        return f"{self.arm}__{self.metric}"

    def _ratio_score(self, ratio: Ratio) -> Score:
        return Score(
            name=self._name(),
            score=ratio.score,
            metadata={"hits": ratio.hits, "total": ratio.total, "misses": list(ratio.misses)},
        )

    def _missing(self, output: dict | None) -> Score:
        reason = (output or {}).get("error") or f"No {self.arm} output"
        return Score(name=self._name(), score=0.0, metadata={"reason": reason})


class ValuesStyled(_ArmScorer):
    metric = "values_styled"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        rendered = _arm_output(output, self.arm)
        if output is None or rendered is None:
            return self._missing(output)
        return self._ratio_score(values_styled(slack_view(rendered), output.get("input_values") or []))


class DatesStyled(_ArmScorer):
    metric = "dates_styled"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        rendered = _arm_output(output, self.arm)
        if output is None or rendered is None:
            return self._missing(output)
        return self._ratio_score(dates_styled(slack_view(rendered), output.get("input_names") or []))


class NotMisstyled(_ArmScorer):
    metric = "not_misstyled"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        rendered = _arm_output(output, self.arm)
        if output is None or rendered is None:
            return self._missing(output)
        return self._ratio_score(misstyled(slack_view(rendered), rendered, output.get("input_names") or []))


class NamesTagged(_ArmScorer):
    metric = "names_tagged"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        rendered = _arm_output(output, self.arm)
        if output is None or rendered is None:
            return self._missing(output)
        return self._ratio_score(names_tagged(slack_view(rendered), output.get("input_names") or []))


class LinkIntegrity(_ArmScorer):
    metric = "link_integrity"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        rendered = _arm_output(output, self.arm)
        if output is None or rendered is None:
            return self._missing(output)
        return self._ratio_score(link_integrity(rendered, output.get("input_text") or ""))


class TextPreserved(_ArmScorer):
    metric = "text_preserved"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        normalised = _arm_output(output, self.arm)
        source = _arm_output(output, NORMALISED_ARM_SOURCES[self.arm])
        if output is None or normalised is None or source is None:
            return self._missing(output)
        preserved = text_preserved(source, normalised)
        metadata = {} if preserved else {"source": slack_view(source).text, "normalised": slack_view(normalised).text}
        return Score(name=self._name(), score=1.0 if preserved else 0.0, metadata=metadata)


class FindingsTagged(Scorer):
    """1 minus the share of structured findings that came back as one plain text item."""

    def _name(self) -> str:
        return "structured__findings_tagged"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if not output or output.get("single_text_finding_rate") is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No structured findings"})
        rate = output["single_text_finding_rate"]
        return Score(name=self._name(), score=1.0 - rate, metadata={"single_text_finding_rate": rate})


def all_scorers() -> list[Scorer]:
    scorers: list[Scorer] = [FindingsTagged()]
    for arm in ARMS:
        scorers.extend([ValuesStyled(arm), DatesStyled(arm), NotMisstyled(arm), NamesTagged(arm), LinkIntegrity(arm)])
        if arm in NORMALISED_ARM_SOURCES:
            scorers.append(TextPreserved(arm))
    return scorers
