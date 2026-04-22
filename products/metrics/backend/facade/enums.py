"""
Exported enums and constants for metrics.

Small products can keep enums in contracts.py instead. Split
into this file when contracts.py gets crowded.

Rule: if an enum appears in a contract dataclass field, it
belongs here (or in contracts.py). Shared types that other
products need to interpret contract objects also belong here.

Internal-only constants (DB magic values, feature flags, etc.)
should stay in the implementation (logic.py, models.py).
"""
