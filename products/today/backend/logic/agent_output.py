"""The shape the briefing agent answers in, and how it becomes a stored briefing."""

from typing import Any

import openai
from pydantic import BaseModel, ConfigDict

from ..facade.enums import ItemGroup, ItemReason, ItemSource
from .checks import check_content
from .content import BriefingContent, ContentSegment
from .fact_sheet import FactSheet, FactSheetItem

MAX_ITEMS = 5
# An item opens inside this project or on GitHub; anything else the agent was talked into is refused.
_ALLOWED_URL_HOSTS = ("https://github.com/",)


# The runtime enforces this schema on the agent's final message, so every field is required.
class OutputSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    item_key: str | None
    highlight: bool


class OutputFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: str


class OutputItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    group: ItemGroup
    source: ItemSource
    reason: ItemReason
    title: str
    label: str
    signal: str
    url: str
    urgency: int
    source_product: str | None
    facts: list[OutputFact]


class BriefingOutput(BaseModel):
    """The agent's answer: the text and the items it names, most urgent first."""

    model_config = ConfigDict(frozen=True)

    headline: str
    paragraphs: list[list[OutputSegment]]
    items: list[OutputItem]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema in the strict form OpenAI structured outputs accept."""
    return openai.pydantic_function_tool(model)["function"]["parameters"]


def to_fact_sheet(output: BriefingOutput) -> FactSheet:
    return FactSheet(
        items=[
            FactSheetItem(
                key=item.key,
                group=item.group,
                source=item.source,
                reason=item.reason,
                title=item.title,
                url=item.url,
                rank=rank,
                urgency=item.urgency,
                source_product=item.source_product,
                facts={fact.name: fact.value for fact in item.facts},
            )
            for rank, item in enumerate(output.items, start=1)
        ]
    )


def to_content(output: BriefingOutput) -> BriefingContent:
    return BriefingContent(
        headline=output.headline,
        paragraphs=[
            [ContentSegment(text=s.text, item_key=s.item_key, highlight=s.highlight) for s in paragraph]
            for paragraph in output.paragraphs
        ],
        labels={item.key: item.label for item in output.items},
        signals={item.key: item.signal for item in output.items},
    )


def _allowed_url(url: str, team_id: int) -> bool:
    return url.startswith(f"/project/{team_id}/") or url.startswith(_ALLOWED_URL_HOSTS)


def problems_with(output: BriefingOutput, team_id: int) -> list[str]:
    """Every rule the answer breaks."""
    problems = []
    if len(output.items) > MAX_ITEMS:
        problems.append(f"at most {MAX_ITEMS} items, got {len(output.items)}")
    keys = [item.key for item in output.items]
    for key in sorted({key for key in keys if keys.count(key) > 1}):
        problems.append(f"item {key} appears {keys.count(key)} times, expected once")
    for item in output.items:
        if not _allowed_url(item.url, team_id):
            problems.append(
                f"url of {item.key} must start with /project/{team_id}/ or https://github.com/, got {item.url!r}"
            )
    return problems + check_content(to_fact_sheet(output), to_content(output))
