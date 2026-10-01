"""The shape the briefing agent answers in, and how it becomes a stored briefing."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from posthog.models import User

from ..facade.enums import ItemGroup, ItemReason, ItemSource
from ..models import DailyBriefing
from .checks import check_content
from .content import BriefingContent, ContentSegment
from .fact_sheet import FactSheet, FactSheetCounts, FactSheetItem

MAX_ITEMS = 5


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
    """The model's JSON schema in the strict form OpenAI structured outputs accept: every object
    closed with `additionalProperties: false` and every property required."""

    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for value in node:
                close(value)

    schema = model.model_json_schema()
    close(schema)
    return schema


def to_fact_sheet(output: BriefingOutput, briefing: DailyBriefing, user: User) -> FactSheet:
    return FactSheet(
        first_name=user.first_name,
        local_day=briefing.local_day,
        counts=FactSheetCounts(items_in_text=len(output.items)),
        failed_sources=[],
        reason_glossary={},
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
                in_text=True,
                top=rank == 1,
                source_product=item.source_product,
                facts={fact.name: fact.value for fact in item.facts},
            )
            for rank, item in enumerate(output.items, start=1)
        ],
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


def problems_with(output: BriefingOutput, briefing: DailyBriefing, user: User) -> list[str]:
    """Every rule the answer breaks. The agent gathered the facts itself, so the number check stays off."""
    problems = []
    if len(output.items) > MAX_ITEMS:
        problems.append(f"at most {MAX_ITEMS} items, got {len(output.items)}")
    return problems + check_content(to_fact_sheet(output, briefing, user), to_content(output), check_numbers=False)
