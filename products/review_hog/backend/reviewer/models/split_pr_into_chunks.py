import logging
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


# Pydantic models matching the chunking schema
class FileInfo(BaseModel):
    filename: str = Field(description="Path to the file")


class Chunk(BaseModel):
    chunk_id: int = Field(description="Unique identifier for the chunk, ordered by review priority")
    files: list[FileInfo] = Field(description="List of files that belong to this chunk", min_length=1)
    chunk_type: (
        Literal[
            "infrastructure",
            "data_model",
            "business_logic",
            "api",
            "frontend",
            "tests",
            "documentation",
            "configuration",
            "refactoring",
            "feature",
            "bugfix",
        ]
        | None
    ) = Field(None, description="Type of changes in this chunk")
    key_changes: list[str] | None = Field(
        default_factory=lambda: [],
        description="Bullet points highlighting the most important changes",
    )


class ChunksList(BaseModel):
    chunks: list[Chunk] = Field(description="List of chunks")

    @model_validator(mode="after")
    def _chunk_ids_must_be_unique(self) -> "ChunksList":
        # Downstream fan-out and resume look chunks up by id, keeping only the first match — a
        # duplicate id from the chunking LLM would silently drop a whole chunk from review, so a
        # colliding response must fail validation (and be retried) instead.
        counts = Counter(c.chunk_id for c in self.chunks)
        duplicates = sorted(chunk_id for chunk_id, n in counts.items() if n > 1)
        if duplicates:
            raise ValueError(f"chunk_id values must be unique; duplicated: {duplicates}")
        return self
