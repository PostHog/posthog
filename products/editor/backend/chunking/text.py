from langchain.text_splitter import RecursiveCharacterTextSplitter

from ..llm.token_counter import get_token_count
from .types import Chunk


def chunk_text(content: str, chunk_size: int, chunk_overlap: float) -> list[Chunk]:
    chunker = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=round(chunk_size * chunk_overlap),
        length_function=get_token_count,
    )
    chunks = chunker.split_text(content)
    chunks_with_positions: list[Chunk] = []

    # In case chunks are exactly the same, but their enclosing context is different.
    current_pos = 0

    for chunk in chunks:
        pos = content.find(chunk, current_pos)
        current_pos = pos + 1

        line_number = content[:pos].count("\n")
        line_end = line_number + chunk.count("\n")

        chunks_with_positions.append(
            Chunk(
                line_start=line_number,
                line_end=line_end,
                context=None,
                content=chunk,
            )
        )

    return chunks_with_positions
