"""
Contract types for review_hog's facade.

Frozen dataclasses that define what this product exposes to other products
(e.g. Foundry's ReviewHog gate). No Django imports.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TriggerReviewResult:
    started: bool
    review_id: str | None
    reason: str | None


@dataclass(frozen=True)
class ReviewViolation:
    code: str
    message: str
    severity: str


@dataclass(frozen=True)
class ReviewReportStatus:
    review_id: str
    in_progress: bool
    violations: list[ReviewViolation] = field(default_factory=list)
