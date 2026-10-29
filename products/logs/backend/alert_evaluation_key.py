"""The window end a logs evaluation key carries.

Kept out of the evaluation module so the message wording, which loads at startup, can read a key
without importing the query layer.
"""

from datetime import datetime
from typing import Final

WINDOW_MARKER: Final = "window:"


def window_end_of(evaluation_key: str) -> datetime | None:
    """The window end the logs adapter put in a key, for a reader that has only the key.

    The adapter mints keys with `WINDOW_MARKER`, so a change to one breaks the round trip test
    rather than silently returning None to a reader in another module.
    """
    _, marker, tail = evaluation_key.rpartition(WINDOW_MARKER)
    if not marker:
        return None
    try:
        return datetime.fromisoformat(tail)
    except ValueError:
        return None
