"""Indexer lens: produces four semantic facets for free-text search via embeddings."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import BaseLens, BaseLensOutput


class IndexerOutput(BaseLensOutput, frozen=True):
    lens_type: Literal[LensType.INDEXER] = LensType.INDEXER
    summary: str = Field(description="One-sentence summary of what happened in the session.")
    user_type: str = Field(description="One-sentence characterization of the user (role, intent, behavior).")
    outcome: str = Field(description="One-sentence summary of how the session ended.")
    keywords: list[str] = Field(min_length=1, description="Distinctive keywords for free-text search (5-15 items).")


class IndexerLens(BaseLens, frozen=True):
    lens_type: Literal[LensType.INDEXER] = LensType.INDEXER
    prompt_template: ClassVar[str] = "indexer.jinja"

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return IndexerOutput
