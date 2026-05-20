"""Indexer lens: produces four semantic facets for free-text search via embeddings."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import BaseLens, BaseLensOutput


class IndexerLlmResponse(BaseLensOutput, frozen=True):
    """LLM-facing schema: the model decides these fields; `lens_type` is stamped by the workflow in `finalize`."""

    intent: str = Field(
        description=(
            "One sentence describing what the user was trying to accomplish at the start of the session "
            "(their goal), regardless of whether they succeeded."
        )
    )
    summary: str = Field(
        description=(
            "One or two sentences describing the overall arc — what the user actually did and how the session progressed."
        )
    )
    outcome: str = Field(
        description=(
            "One sentence describing the final state — where the user ended up and whether they accomplished "
            "their intent. Do not restate the summary."
        )
    )
    friction_points: list[str] = Field(
        default_factory=list,
        description=(
            "Named blockers, errors, or frustrations encountered, lowercase phrases "
            "(e.g. 'login failure', 'buffering during replay', 'empty logs page'). Empty list if friction-free."
        ),
    )
    keywords: list[str] = Field(
        min_length=1,
        description=(
            "5-15 distinctive lowercase keywords for free-text search. Favor concrete action verbs "
            "(clicked, abandoned, retried, submitted) and specific feature names. "
            "Avoid generic terms that apply to most sessions ('user', 'session', 'navigation', 'interaction'); "
            "avoid the team or product brand name."
        ),
    )


class IndexerOutput(IndexerLlmResponse, frozen=True):
    """Persisted output: adds the discriminator for the `AnyLensOutput` union."""

    lens_type: Literal[LensType.INDEXER] = LensType.INDEXER


class IndexerLens(BaseLens, frozen=True):
    lens_type: Literal[LensType.INDEXER] = LensType.INDEXER
    prompt_template: ClassVar[str] = "indexer.jinja"

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return IndexerLlmResponse

    def finalize(self, llm_response: BaseModel) -> BaseLensOutput:
        data = llm_response.model_dump()
        # Lowercase the list fields so embedding similarity isn't fragmented by mixed casing.
        data["keywords"] = [k.lower() for k in data.get("keywords", []) if isinstance(k, str)]
        data["friction_points"] = [f.lower() for f in data.get("friction_points", []) if isinstance(f, str)]
        return IndexerOutput(**data)
