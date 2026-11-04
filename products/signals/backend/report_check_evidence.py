"""Evidence qualification for future Monitoring evaluators, independent of target comparisons.

Source adapters must establish the aggregation semantics and relevant population. A display format,
interim match, or historical baseline cannot establish either. Callers own the organization gate,
fixed final window, data readiness, and attempt/version checks.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from posthog.dataclasses import frozen

EvidenceSource = Literal["count", "sum", "rate", "average", "unsupported"]
EvidenceStatus = Literal["sufficient", "insufficient", "unsupported", "errored"]
EvidenceReason = Literal[
    "positive_total",
    "relevant_activity",
    "qualifying_denominator",
    "measurement_unavailable",
    "empty_window",
    "activity_unavailable",
    "no_activity",
    "denominator_unavailable",
    "empty_denominator",
    "minimum_denominator_unspecified",
    "insufficient_denominator",
    "scope_mismatch",
    "unsupported_source",
    "unsupported_value",
    "query_error",
]


@frozen
class EvidenceScope:
    """The caller's relevant-population key and existing check window, shared by related queries."""

    team_id: int
    population: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not self.population.strip():
            raise ValueError("Evidence needs a relevant population.")
        if self.start.utcoffset() is None or self.end.utcoffset() is None or self.end < self.start:
            raise ValueError("Evidence needs timezone-aware, ordered window bounds.")


@frozen
class EvidenceCount:
    scope: EvidenceScope
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 0:
            raise ValueError("An evidence count must be a non-negative integer.")


@frozen
class MetricEvidence:
    scope: EvidenceScope
    source: EvidenceSource
    value: float | None = None
    activity: EvidenceCount | None = None
    denominator: EvidenceCount | None = None
    query_error: bool = False

    def __post_init__(self) -> None:
        if self.value is not None and (
            isinstance(self.value, bool) or not isinstance(self.value, int | float) or not math.isfinite(self.value)
        ):
            raise ValueError("A measured value must be a finite number.")
        if self.query_error and self.value is not None:
            raise ValueError("A query error cannot carry a measured value.")
        if self.source == "count" and self.value is not None and (self.value < 0 or self.value % 1 != 0):
            raise ValueError("A measured count must be a non-negative integer.")


@frozen
class EvidenceQualification:
    status: EvidenceStatus
    reason: EvidenceReason


def _qualify_total(evidence: MetricEvidence) -> EvidenceQualification:
    assert evidence.value is not None
    if evidence.value > 0:
        return EvidenceQualification(status="sufficient", reason="positive_total")
    if evidence.value < 0:
        return EvidenceQualification(status="unsupported", reason="unsupported_value")
    if evidence.activity is None:
        return EvidenceQualification(status="insufficient", reason="activity_unavailable")
    if evidence.activity.scope != evidence.scope:
        return EvidenceQualification(status="insufficient", reason="scope_mismatch")
    if evidence.activity.value == 0:
        return EvidenceQualification(status="insufficient", reason="no_activity")
    return EvidenceQualification(status="sufficient", reason="relevant_activity")


def _qualify_denominator(evidence: MetricEvidence, minimum: int | None) -> EvidenceQualification:
    if evidence.denominator is None:
        return EvidenceQualification(status="insufficient", reason="denominator_unavailable")
    if evidence.denominator.scope != evidence.scope:
        return EvidenceQualification(status="insufficient", reason="scope_mismatch")
    if evidence.denominator.value == 0:
        return EvidenceQualification(status="insufficient", reason="empty_denominator")
    if minimum is None:
        return EvidenceQualification(status="insufficient", reason="minimum_denominator_unspecified")
    if evidence.denominator.value < minimum:
        return EvidenceQualification(status="insufficient", reason="insufficient_denominator")
    return EvidenceQualification(status="sufficient", reason="qualifying_denominator")


def qualify_metric_evidence(
    evidence: MetricEvidence, *, minimum_denominator: int | None = None
) -> EvidenceQualification:
    """Qualify one final measurement without deciding whether its target holds.

    Counts are raw event/action counts. Sums are supported property sums, without formulas or
    session-level aggregation. Activity for a sum counts valid property contributions. Rate
    denominators count eligible opportunities; average denominators count valid contributing
    property values. Adapters must supply these facts explicitly because
    MetricMeasurement supplies neither counts nor denominators. Unsupported formulas and agent
    evidence need their own adapters/policy and cannot qualify through a scalar alone.
    """
    if minimum_denominator is not None and (
        isinstance(minimum_denominator, bool) or not isinstance(minimum_denominator, int) or minimum_denominator <= 0
    ):
        raise ValueError("A minimum denominator must be a positive integer.")
    if evidence.query_error:
        return EvidenceQualification(status="errored", reason="query_error")
    if evidence.source not in {"count", "sum", "rate", "average"}:
        return EvidenceQualification(status="unsupported", reason="unsupported_source")
    if evidence.value is None:
        return EvidenceQualification(status="insufficient", reason="measurement_unavailable")
    if evidence.scope.start == evidence.scope.end:
        return EvidenceQualification(status="insufficient", reason="empty_window")
    if evidence.source in {"count", "sum"}:
        return _qualify_total(evidence)
    return _qualify_denominator(evidence, minimum_denominator)
