from pydantic import BaseModel, Field


class ChunkPerspectiveSelection(BaseModel):
    chunk_id: int = Field(description="The chunk this selection applies to")
    perspectives: list[str] = Field(
        description="Exact skill names of the perspectives worth running on this chunk; may be empty"
    )
    reason: str = Field(
        description="One line: why the skipped perspectives don't apply to this chunk, or why all are needed"
    )


class PerspectiveSelection(BaseModel):
    chunks: list[ChunkPerspectiveSelection] = Field(description="One selection per chunk, covering every chunk")
