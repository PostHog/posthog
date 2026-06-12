"""Contract types for logs.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant —
same syntax, but with runtime validation on construction, so structural
mistakes from mappers or callers surface at the facade boundary.
"""

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TeamLogsConfigData:
    """Per-environment logs configuration."""

    team_id: int
    logs_distinct_id_attribute_key: str
