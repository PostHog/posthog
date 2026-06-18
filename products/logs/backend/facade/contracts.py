"""Contract types for logs.

Stable, framework-free frozen dataclasses that define what this product exposes to the
rest of the codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
shape and ``is_dataclass()`` compatibility, but with runtime validation on
construction, so a malformed mapper or caller surfaces at the facade boundary instead
of producing a bad payload downstream.
"""

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TeamLogsConfig:
    """A team's logs configuration (env-scoped, keyed by team_id)."""

    logs_distinct_id_attribute_key: str
