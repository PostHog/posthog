import logging

from pydantic import BaseModel, Field

# Configure logging
logger = logging.getLogger(__name__)


class ChunkMeta(BaseModel):
    """Metadata about a chunk."""

    chunk_id: int = Field(description="Chunk ID")
    files_in_this_chunk: list[str] = Field(
        description="List of files included in this chunk"
    )


class ChunkAnalysis(BaseModel):
    """Complete analysis for a chunk."""

    goal: str = Field(
        description="2-3 paragraphs explaining in detail what this chunk accomplishes, including technical implementation details"
    )
    chunk_meta: ChunkMeta
