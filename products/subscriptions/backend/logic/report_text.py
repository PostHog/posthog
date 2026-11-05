import re
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


class ReportText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReportTextItem | ReportLinkItem | ReportChangeItem]

    def render(self, bold_marker: str = "**") -> str:
        markers = {
            "text": ("", ""),
            "name": (bold_marker, bold_marker),
            "value": (bold_marker, bold_marker),
            "change": (bold_marker, bold_marker),
            "time": ("_", "_"),
            "link": ("", ""),
        }
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
            opening, closing = markers[item.kind]
            if item.kind == "link" and item.url:
                label = item.text.replace("`", "")
                if label.startswith(("http://", "https://")):
                    try:
                        parsed = urlsplit(item.url)
                        label = "/".join(parsed.path.strip("/").split("/")[-2:]) or parsed.hostname or "Page"
                    except ValueError:
                        label = "Page"
                parts.append(f"[{label}]({item.url})")
            elif item.kind == "change":
                triangle = "▲" if item.direction == "increase" else "▼"
                parts.append(f"{opening}{triangle} {item.text}{closing}")
            else:
                parts.append(f"{opening}{item.text}{closing}")
            previous_text = item.text
        return "".join(parts)

    def render_bullet(self, marker: str = "-", bold_marker: str = "**") -> str:
        content = re.sub(r"^(?:[ \t]*(?:[-+*•]|\d+[.)])[ \t]+)+", "", self.render(bold_marker).strip())
        if not content:
            return ""
        return f"{marker} {content}"


class ReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[ReportText]

    def render(self, *, slack_formatting: bool = False) -> str:
        if slack_formatting:
            return "\n\n".join(finding.render_bullet("•", "*") for finding in self.findings)
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
        description="Use only when the user explicitly requests a fixed output template. Otherwise return an empty list."
    )

    def render(self) -> str:
        if self.custom_layout:
            return "".join(part.render() for part in self.custom_layout)
        parts = [f"# {self.topic}"] if self.topic else []
        parts.extend(section.render() for section in self.sections)
        return "\n\n".join(parts)


REPORT_TEXT_INSTRUCTIONS = """Return structured text items. The renderer applies inline styles from their kinds.
- Use kind=link for a page or referrer with a supplied URL. Put a short descriptive label in text and the complete original destination in url. Do not put link brackets or Markdown link syntax in text. Do not replace a supplied URL with an unlinked name item. Do not include url for other kinds.
- Use kind=name for every event name and metric name, including repeated mentions.
- Use kind=value for each measured count, amount, and percentage. Include its unit in the same item.
- Use kind=change for a measured increase or decrease against an explicit comparable baseline. Set direction to increase or decrease and put the change amount with its unit in text. The renderer adds a direction triangle. Do not add arrows to the text.
- Use change items only for differences, not absolute values, dates, incomplete periods, or funnel step drop-offs. If the baseline or change is uncertain, use plain text. An increase is not automatically good and a decrease is not automatically bad.
- Use kind=time for every date, clock time, duration, and reporting window, even when it contains numbers.
- Use kind=text for connecting words, punctuation, and Markdown structure. Never include event names, measured values, or dates inside a text item.
- Do not include bold, italic, or underline markers in item text. Keep each styled item to the relevant name, value, or time expression.
- Preserve sentence order, spaces, and line breaks across items. Write complete sentences; do not rearrange a sentence to group items by kind.
- Keep inline code and code blocks literal; do not style their contents.
- Review every mention before returning the report. Use the same kind for the same item throughout the report."""
