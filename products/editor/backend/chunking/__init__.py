from typing import cast

from .code import chunk_code as _chunk_code
from .exceptions import UnsupportedLanguage
from .parser import ProgrammingLanguage, guess_language
from .text import chunk_text as _chunk_text


def chunk_text(
    content: str, language: ProgrammingLanguage | None = None, chunk_size: int = 300, chunk_overlap: float = 0.2
):
    if language is not None:
        return _chunk_code(language, content, chunk_size, chunk_overlap)
    return _chunk_text(content, chunk_size, chunk_overlap)


__all__ = ["ProgrammingLanguage", "chunk_text", "guess_language"]
