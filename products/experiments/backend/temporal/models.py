import dataclasses

# Shared by the workflow definition, the schedule, and the management command.
CANARY_WORKFLOW_NAME = "experiment-precompute-canary"

OUTCOME_PASS = "pass"
OUTCOME_DIVERGENCE = "divergence"
OUTCOME_PATH_FLIP = "path_flip"
OUTCOME_ERROR = "error"
OUTCOME_SKIPPED = "skipped"
ALL_OUTCOMES = (OUTCOME_PASS, OUTCOME_DIVERGENCE, OUTCOME_PATH_FLIP, OUTCOME_ERROR, OUTCOME_SKIPPED)

# Cap CanaryMetricResult.detail so a pathological error message can't bloat the Temporal payload.
MAX_CANARY_DETAIL_LENGTH = 1000

# Max attempts per metric before it's marked failed. The workflow's requeue loop owns retries (the activity
# runs with maximum_attempts=1), so this caps how many times a transient failure is requeued. Kept low because
# each extra attempt adds backoff (5s, 10s, 20s, ...) to the tail of a fully-failing run.
MAX_METRIC_ATTEMPTS = 3


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
class ExperimentPrecomputeCanaryInputs:
    """Input to the precompute canary workflow.

    Scheduled runs use the defaults (quota sampling across eligible experiments). On-demand forensics runs
    set experiment_id to canary one specific experiment — all of its eligible metrics, quotas ignored —
    optionally narrowed via metric_uuids. triggered_manually skips the Prometheus push (manual runs would
    distort the scheduled-canary health signal) but still posts to Slack.
    """

    experiment_id: int | None = None
    metric_uuids: list[str] | None = None
    funnel_quota: int = 12
    mean_quota: int = 6
    ratio_quota: int = 4
    per_experiment_cap: int = 3
    time_budget_seconds: int = 5400
    triggered_manually: bool = False


@dataclasses.dataclass
class CanaryMetricTarget:
    """One sampled (experiment, metric) pair. Carries only the uuid — the definition is re-resolved inside
    the run activity so a metric edited/deleted between sampling and execution is seen as it currently is."""

    team_id: int
    experiment_id: int
    metric_uuid: str
    metric_type: str  # "funnel" | "mean" | "ratio"


@dataclasses.dataclass
class CanaryVariantStats:
    sum: float
    number_of_samples: int


@dataclasses.dataclass
class CanaryRunSnapshot:
    """Per-variant aggregates from one execution of the metric query."""

    label: str  # "a" | "b" (forced precomputed) | "c" (forced direct scan)
    query_id: str  # client_query_id, for system.query_log forensics
    is_precomputed: bool
    variants: dict[str, CanaryVariantStats]


@dataclasses.dataclass
class CanaryMetricResult:
    """Verdict for one metric: outcome plus everything needed to investigate without re-running."""

    target: CanaryMetricTarget
    outcome: str  # "pass" | "divergence" | "path_flip" | "error" | "skipped"
    stability_deviation: float | None = None  # max relative deviation, run a vs b
    correctness_deviation: float | None = None  # max relative deviation, run b vs c
    runs: list[CanaryRunSnapshot] = dataclasses.field(default_factory=list)
    detail: str | None = None


@dataclasses.dataclass
class CanaryReportInputs:
    results: list[CanaryMetricResult]
    triggered_manually: bool = False


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
    # Run-level outcome carried on the finish step so the activity can emit the
    # 'experiment results refresh completed' analytics event with real counts.
    succeeded_metrics: int | None = None
    failed_metrics: int | None = None
