from typing import Any


def clean_text(value: Any) -> str:
    """A value as stripped text, with `None` as an empty string."""
    return "" if value is None else str(value).strip()
