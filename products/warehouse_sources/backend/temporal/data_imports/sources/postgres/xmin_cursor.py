from collections.abc import Mapping
from typing import Any, ClassVar

from posthog.dataclasses import frozen

# Where xmin state was stored before `source_cursor`. Read only when a schema has no `source_cursor`.
XMIN_LEGACY_KEYS = ("xmin_last_value", "xmin_ceiling", "xmin_num_wraparound")


@frozen
class XminCursor:
    """The xmin ceiling of the last run that completed, and the lower bound of the next run."""

    cursor_kind: ClassVar[str] = "postgres_xmin"

    # Bare 32-bit xid, compared against tuple `xmin`.
    ceiling_xid: int
    # Full 64-bit `xid8`, the wraparound-safe form of the ceiling.
    ceiling_xid8: int
    # Epoch of the ceiling, which is the high 32 bits of `ceiling_xid8`.
    num_wraparound: int


def xmin_cursor_from_legacy(sync_type_config: Mapping[str, Any]) -> XminCursor | None:
    ceiling_xid, ceiling_xid8, num_wraparound = (sync_type_config.get(key) for key in XMIN_LEGACY_KEYS)
    if not isinstance(ceiling_xid, int) or not isinstance(ceiling_xid8, int) or not isinstance(num_wraparound, int):
        return None
    return XminCursor(ceiling_xid=ceiling_xid, ceiling_xid8=ceiling_xid8, num_wraparound=num_wraparound)
