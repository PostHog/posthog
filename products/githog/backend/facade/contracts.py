"""
Contract types for githog.

Stable, framework-free frozen dataclasses that define what this
product exposes to the rest of the codebase.

Characteristics:
- No Django imports
- Immutable (frozen=True)
- Used by facade as inputs/outputs

Do NOT depend on Django models, DRF serializers, or request objects.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FlagReference:
    """A feature flag key found in a diff, with where it was referenced."""

    key: str
    file_paths: tuple[str, ...]
    occurrences: int


@dataclass(frozen=True)
class FlagReach:
    """Empirical reach of a single flag, measured from $feature_flag_called events."""

    key: str
    users_affected: int
    sessions_affected: int
    call_count: int
    variants: tuple["VariantReach", ...] = ()
    # True iff the flag key appears in $feature_flag_called events in the window.
    # When False, the flag exists in code but has no recorded evaluations — reach
    # is "unknown," not "zero" (likely a brand-new flag).
    has_data: bool = True


@dataclass(frozen=True)
class VariantReach:
    """Per-variant reach for multivariate flags."""

    variant: str
    users_affected: int


@dataclass(frozen=True)
class PRImpactRequest:
    """Input for computing PR impact.

    Caller supplies the diff text directly — this keeps the facade
    decoupled from any specific GitHub fetching layer. A thin wrapper
    elsewhere can pull diffs from gh/git and feed them in.
    """

    diff_text: str
    lookback_days: int = 30


@dataclass(frozen=True)
class PRImpactReport:
    """Result of impact analysis."""

    flag_references: tuple[FlagReference, ...]
    per_flag_reach: tuple[FlagReach, ...]
    # Users who had EVERY referenced flag evaluated truthy in the window.
    # This is the empirical intersection — the correct answer to
    # "how many users will see this code path," modulo flags outside the diff.
    intersection_users: int
    intersection_sessions: int
    lookback_days: int
    notes: tuple[str, ...] = field(default_factory=tuple)
