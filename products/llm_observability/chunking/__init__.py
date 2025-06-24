from typing import cast

from .code import chunk_code as _chunk_code
from .exceptions import UnsupportedLanguage
from .parser import ProgrammingLanguage
from .text import chunk_text as _chunk_text


def chunk_text(language: str, content: str, chunk_size: int = 300, chunk_overlap: float = 0.2):
    try:
        if language in {member.value for member in ProgrammingLanguage}:
            return _chunk_code(cast(ProgrammingLanguage, language), content, chunk_size, chunk_overlap)
    except UnsupportedLanguage:
        pass
    return _chunk_text(content, chunk_size, chunk_overlap)


__all__ = ["ProgrammingLanguage", "chunk_text"]
