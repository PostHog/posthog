"""Indexer scanner: produces semantic facets for free-text search via embeddings."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import BaseScanner, BaseScannerOutput


class IndexerLlmResponse(BaseScannerOutput, frozen=True):
    """LLM-facing schema: the model decides these fields; `scanner_type` is stamped by the workflow in `finalize`."""

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

    @field_validator("keywords", "friction_points", mode="after")
    @classmethod
    def _lowercase(cls, value: list[str]) -> list[str]:
        # Lowercase so embedding similarity isn't fragmented by mixed casing.
        return [v.lower() for v in value]


class IndexerOutput(IndexerLlmResponse, frozen=True):
    """Persisted output: adds the discriminator for the `AnyScannerOutput` union."""

    scanner_type: Literal[ScannerType.INDEXER] = ScannerType.INDEXER


class IndexerScanner(BaseScanner, frozen=True, extra="forbid"):
    # `extra='forbid'` surfaces stale config (e.g. legacy `prompt`) instead of ignoring it.
    scanner_type: Literal[ScannerType.INDEXER] = ScannerType.INDEXER
    prompt_template: ClassVar[str] = "indexer.jinja"
    output_cls: ClassVar[type[BaseScannerOutput]] = IndexerOutput

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return IndexerLlmResponse
