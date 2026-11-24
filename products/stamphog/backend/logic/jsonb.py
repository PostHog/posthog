from typing import Any


def without_nul(value: Any) -> Any:
    """Drop NUL characters from every string in ``value``.

    Run output holds PR text, and Postgres refuses ``\\u0000`` in jsonb. One NUL in a PR body or
    comment fails the whole write, and every retry and re-review of that PR fails the same way.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {without_nul(key): without_nul(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [without_nul(item) for item in value]
    return value
