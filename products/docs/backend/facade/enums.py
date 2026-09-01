"""
Exported enums for docs.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic.py, models.py).
"""

from enum import StrEnum


class SplineStatus(StrEnum):
    PENDING = "pending"
    RETICULATED = "reticulated"
