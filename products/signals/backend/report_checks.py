"""Forward-looking checks attached to a signal report.

A report states what was true when it was written. A check states what must stay true afterwards:
one bounded measurement, one comparison, and a time to run it. The coordinator runs the due ones and
appends the verdict to the report's artefact log, so "did the fix hold?" becomes a stored fact
instead of a person re-deriving it.

The soak window is the check's own clock. A fix does not always arrive as a merged pull request —
plenty land in the skills store with nothing to date the window from — so the author says when the
check runs rather than the system reading it off a merge.

This module stays Django-free and schema-free for the same reason as ``report_metrics``: model and
Temporal payload modules import it during process setup.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from products.signals.backend.report_metrics import validate_live_metric_query, validate_metric_id

CheckOutcome = Literal["passed", "failed", "errored"]
CheckOperator = Literal["lte", "gte", "between"]

MAX_ACTIVE_CHECKS_PER_REPORT = 5
MAX_CHECK_TITLE_LENGTH = 200
MAX_CHECK_RATIONALE_LENGTH = 2_000
# A check is a soak, not a monitor: a lane that re-measures more than four times a day is an alert
# and belongs in the alerts product, which has the notification and deduplication machinery for it.
MIN_CHECK_INTERVAL_MINUTES = 6 * 60
MAX_CHECK_RUNS = 10
MAX_CHECK_HORIZON = timedelta(days=90)
# The horizon bounds the gap as well as the schedule. A gap wider than the horizon can never produce
# a second run, and an unbounded one overflows the date arithmetic that plans the runs.
MAX_CHECK_INTERVAL_MINUTES = int(MAX_CHECK_HORIZON.total_seconds() // 60)
# A soak needs the fix to have been live a while. A week is the default first look; an author who
# knows the window says so.
DEFAULT_FIRST_RUN_AFTER = timedelta(days=7)
DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN = timedelta(days=30)
# A check whose query keeps failing is misconfigured, not unlucky. Three errored runs retire it so a
# broken lane stops costing a query per tick.
MAX_CONSECUTIVE_CHECK_ERRORS = 3


class CheckThresholdBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lower: float
    upper: float

    @model_validator(mode="after")
    def lower_must_not_exceed_upper(self) -> CheckThresholdBounds:
        if self.lower > self.upper:
            raise ValueError("lower must not exceed upper")
        return self


class CheckComparison(BaseModel):
    """What the measured value must satisfy for the check to pass.

    The operators are the ones the shared alerts comparator expresses exactly. Strict `lt` / `gt`
    would need a second comparison engine for a distinction a soak window does not make, so they are
    not offered: "stays at or below 10 a day" is the same expectation.
    """

    model_config = ConfigDict(extra="forbid")

    operator: CheckOperator = Field(description="`lte`, `gte`, or `between`.")
    value: float | None = Field(
        default=None,
        description="The bound for `lte` and `gte`; unused by `between`.",
    )
    bounds: CheckThresholdBounds | None = Field(
        default=None,
        description="The inclusive range for `between`; unused by `lte` and `gte`.",
    )

    @field_validator("value", mode="before")
    @classmethod
    def value_must_be_a_plain_number(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("must be a number, not a boolean")
        return value

    @model_validator(mode="after")
    def operator_must_match_its_bound(self) -> CheckComparison:
        if self.operator == "between":
            if self.bounds is None:
                raise ValueError("a `between` comparison needs bounds")
            if self.value is not None:
                raise ValueError("a `between` comparison takes bounds, not a value")
        else:
            if self.value is None:
                raise ValueError(f"a `{self.operator}` comparison needs a value")
            if self.bounds is not None:
                raise ValueError(f"a `{self.operator}` comparison takes a value, not bounds")
        return self


class MetricThresholdConfig(BaseModel):
    """A deterministic check: measure one number, compare it, record the verdict.

    The number comes either from a metric the report already shows (``metric_id``) or from a query
    the author supplies. Both end up in the same runner, so a supplied query must satisfy the live
    metric contract — the node allowlist, the bounded window, and the single-output-series rule.

    A caller names one source. When it names a metric, the create path copies that metric's query
    into ``query`` before the row is stored, so the check keeps measuring what its author saw even if
    the report's metric is later rewritten under the same id; ``metric_id`` stays as provenance.

    Unknown keys are refused rather than ignored, so a misspelled field name is reported instead of
    being dropped in silence and stored as it arrived.
    """

    model_config = ConfigDict(extra="forbid")

    metric_id: str | None = Field(
        default=None,
        description=(
            "Identifier of a metric on the report whose query this check measures. The metric's query is "
            "copied into `query` when the check is created."
        ),
    )
    query: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Live InsightVizNode wrapping one TrendsQuery: supplied by the caller, or copied from the named "
            "metric when the check is created."
        ),
    )
    comparison: CheckComparison = Field(description="What the measured value must satisfy to pass.")
    baseline_value: float | None = Field(
        default=None,
        description="The value observed when the check was written, recorded on each result for context.",
    )

    @field_validator("baseline_value", mode="before")
    @classmethod
    def baseline_must_be_a_plain_number(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("must be a number, not a boolean")
        return value

    @field_validator("metric_id")
    @classmethod
    def metric_id_must_be_reference_safe(cls, value: str | None) -> str | None:
        return None if value is None else validate_metric_id(value)

    @field_validator("query")
    @classmethod
    def query_must_be_a_live_trends_node(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if value is None else validate_live_metric_query(value)

    @model_validator(mode="after")
    def source_must_name_a_metric_or_carry_a_query(self) -> MetricThresholdConfig:
        if self.metric_id is None and self.query is None:
            raise ValueError("provide a metric_id or a query")
        return self


CHECK_CONFIG_SCHEMAS: Mapping[str, type[BaseModel]] = {
    "metric_threshold": MetricThresholdConfig,
}


class CheckConfigValidationError(ValueError):
    """A check config that does not match its kind's schema."""


def parse_check_config(kind: str, config: object) -> BaseModel:
    """Parse a raw config payload into its kind's model.

    The single boundary parser: the REST write path and the executor both come through here, so a
    stored config can never mismatch the kind on its row.
    """
    schema = CHECK_CONFIG_SCHEMAS.get(kind)
    if schema is None:
        raise CheckConfigValidationError(f"Unknown check kind {kind!r}")
    try:
        return schema.model_validate(config)
    except ValidationError as error:
        raise CheckConfigValidationError(str(error)) from error
