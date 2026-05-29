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
    """Input for updating recalculation progress.

    Used only for the start step (status=in_progress, total_metrics, metric_uuids, query_to, mark_started)
    and the finish step (final status, mark_completed). Per-metric counter/error updates are folded into the
    calculate activity's own transaction instead.
    """

    recalculation_id: str
    status: str | None = None
    total_metrics: int | None = None
    metric_uuids: list[str] | None = None
    query_to: str | None = None  # ISO datetime string; the single data-window end shared by all metrics in the run
    increment_completed: bool = False
    increment_failed: bool = False
    error_info: dict[str, str | None] | None = None
    mark_started: bool = False
    mark_completed: bool = False
