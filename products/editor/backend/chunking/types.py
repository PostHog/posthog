from pydantic import BaseModel


class Chunk(BaseModel):
    line_start: int
    """Starting from zero."""
    line_end: int
    """Starting from zero."""
    context: str | None
    """Headers of the chunk (class declaration, function declaration, etc)."""
    content: str
    """Chunk body."""

    @property
    def text(self) -> str:
        if self.context:
            return f"{self.context}\n{self.content}"
        return self.content
