"""Sanitization helpers for survey summarization.

Survey responses are arbitrary user input and can contain null bytes (``\\u0000``).
Postgres ``text``/``jsonb`` columns cannot store a null byte and raise
``UntranslatableCharacter`` on write, so any user-derived string must be stripped
before it is persisted (or echoed back by an LLM into something persisted).
"""

NULL_BYTE = "\x00"


def strip_null_bytes(value: str) -> str:
    """Remove null bytes that Postgres text/jsonb columns cannot store."""
    if NULL_BYTE not in value:
        return value
    return value.replace(NULL_BYTE, "")
