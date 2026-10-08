"""The shape the LLM answers in, and how it becomes the stored text."""

from typing import Any

import openai
from pydantic import BaseModel, ConfigDict

from .content import BriefingContent, ContentSegment
from .fact_sheet import FactSheet


# Strict structured output accepts only required fields, so every field is required.
class OutputSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    item_key: str | None


class OutputItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    signal: str


class BriefingOutput(BaseModel):
    """The LLM's answer: the text about the items PostHog picked. The LLM does not choose the items."""

    model_config = ConfigDict(frozen=True)

    headline: str
    paragraphs: list[list[OutputSegment]]
    items: list[OutputItem]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema in the strict form OpenAI structured outputs accept."""
    return openai.pydantic_function_tool(model)["function"]["parameters"]


def to_content(output: BriefingOutput, fact_sheet: FactSheet) -> BriefingContent:
    """The stored text. A link, label or signal for a key that is not on the fact sheet becomes plain
    text or is dropped, so the page never links to an item it does not show. Links to the top item
    are highlighted."""
    keys = {item.key for item in fact_sheet.items}
    top_key = fact_sheet.items[0].key if fact_sheet.items else None
    return BriefingContent(
        headline=output.headline,
        paragraphs=[
            [
                ContentSegment(text=s.text, item_key=s.item_key, highlight=s.item_key == top_key)
                if s.item_key in keys
                else ContentSegment(text=s.text)
                for s in paragraph
            ]
            for paragraph in output.paragraphs
        ],
        labels={item.key: item.label for item in output.items if item.key in keys},
        signals={item.key: item.signal for item in output.items if item.key in keys},
    )
