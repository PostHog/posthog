import dataclasses


@dataclasses.dataclass
class ExperimentMetricsRecalculationWorkflowInputs:
    """Input to the batch metrics recalculation workflow."""

    recalculation_id: str  # UUID as string


@dataclasses.dataclass
class ExperimentMetricToRecalculate:
    """A single metric to recalculate.

    The recalc fingerprint is derived inside the calculate activity from the recalculation_id,
    so it is intentionally not carried here.
    """

    experiment_id: int
    metric_uuid: str
    metric_type: str  # "primary" or "secondary"


@dataclasses.dataclass
class MetricRecalculationResult:
    """Result from calculating a single metric.

    Lightweight by design: carries only success/error metadata, never the computed result blob. The blob is
    written to ExperimentMetricResult (Postgres) inside the activity and read back by the API, so it never
    crosses the Temporal payload boundary (~2 MiB cap). error_message is capped by the activity before being set.
    """

    metric_uuid: str
    success: bool
    error_step: str | None = None
    error_message: str | None = None


@dataclasses.dataclass
class RecalculationProgressUpdate:
    """Input for the start and finish lifecycle steps.

    Start step: status=in_progress, total_metrics, metric_uuids, mark_started=True. The activity itself
    stamps query_to and started_at under a first-write-wins guard.

    Finish step: status=completed|failed, mark_completed=True. The activity stamps completed_at, also
    first-write-wins.

    Per-metric counters and error entries are not carried here — they're written by the calculate activity
    in the same transaction as the result row.
    """

    recalculation_id: str
    status: str | None = None
    total_metrics: int | None = None
    metric_uuids: list[str] | None = None
    mark_started: bool = False
    mark_completed: bool = False
