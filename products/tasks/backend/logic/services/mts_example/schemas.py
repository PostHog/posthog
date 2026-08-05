from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CursedItem(BaseModel):
    kind: Literal["identifier", "comment"] = Field(
        description=("Whether this is an identifier (variable/function/class/constant name) or a stale/bad comment."),
    )
    content: str = Field(
        description="Exact identifier name or exact comment text.",
    )
    file_path: str = Field(
        description="Repo-relative path to the file containing the cursed item.",
    )
    line_number: int = Field(
        ge=1,
        description="1-based line number where the cursed item appears.",
    )
    cursedness_reason: str = Field(
        description="One-sentence explanation of why this item is cursed.",
    )


class CursedItemCandidates(BaseModel):
    items: list[CursedItem] = Field(
        max_length=10,
        description="Up to 10 cursed items, ordered most-cursed first.",
    )
