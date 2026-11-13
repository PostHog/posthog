"""Serializers for the timeseries results and the metrics recalculation runs of an experiment."""

from django.db import models

from rest_framework import serializers

from products.experiments.backend.facade.enums import ExperimentResultConfigurationStatus
from products.experiments.backend.models.experiment import ExperimentMetricsRecalculation


class MetricRecalculationResultSerializer(serializers.Serializer):
    """One metric's recalculated result row, read back from ExperimentMetricResult."""

    configuration_status = serializers.ChoiceField(
        choices=ExperimentResultConfigurationStatus.choices,
        read_only=True,
        help_text="Whether this result uses current settings, earlier settings, or settings that were not recorded.",
    )

    metric_uuid = serializers.CharField(read_only=True, help_text="UUID of the metric this result belongs to")
    # nosemgrep: choices-need-a-class -- moved unchanged from presentation/serializers.py
    status = serializers.ChoiceField(
        choices=["pending", "completed", "failed"],
        read_only=True,
        help_text="Status of this metric's calculation in the run",
    )
    # JSONField mirrors the ExperimentMetricResult.result column; concrete shape comes from
    # posthog.schema.ExperimentQueryResponse (baseline, variant_results, and breakdown_results for a breakdown).
    result = serializers.JSONField(
        read_only=True,
        allow_null=True,
        help_text="The computed metric result (ExperimentQueryResponse shape); null when status is pending or failed",
    )
    error_message = serializers.CharField(
        read_only=True, allow_null=True, help_text="Error message when status is failed; otherwise null"
    )


class ExperimentTimeseriesResultsStatus(models.TextChoices):
    PENDING = "pending"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ExperimentTimeseriesResultsSerializer(serializers.Serializer):
    """Day-by-day results of one metric under the experiment's current settings."""

    experiment_id = serializers.IntegerField(help_text="Experiment id.")
    metric_uuid = serializers.CharField(help_text="UUID of the metric the series belongs to.")
    status = serializers.ChoiceField(
        choices=ExperimentTimeseriesResultsStatus.choices,
        help_text=(
            "'completed' when every day has a result, 'partial' when some do, 'failed' when no day has a result "
            "and some failed, 'pending' when no day was calculated yet."
        ),
    )
    timeseries = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        help_text=(
            "Result per day (YYYY-MM-DD, project timezone) in the ExperimentQueryResponse shape, from the start "
            "date to the end date or today. Null for a day without a completed result."
        ),
    )
    configuration_by_day = serializers.DictField(
        child=serializers.ChoiceField(choices=ExperimentResultConfigurationStatus.choices),
        help_text="Configuration provenance for each stored day: current, previous, or unknown.",
    )
    computed_at = serializers.DateTimeField(
        allow_null=True, help_text="When the most recent day's result was computed, or null."
    )
    created_at = serializers.DateTimeField(help_text="When the oldest stored day was written.")
    updated_at = serializers.DateTimeField(help_text="When the newest stored day was last written.")
    recalculation_status = serializers.CharField(
        allow_null=True,
        help_text="'pending' or 'in_progress' while a backfill of this series runs, otherwise null.",
    )
    recalculation_created_at = serializers.DateTimeField(
        allow_null=True, help_text="When the running backfill was requested, or null."
    )
    formatted_results = serializers.CharField(
        help_text="The series as a compact text table, one row per day, for language model consumers."
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        # A declared `errors` attribute would shadow `Serializer.errors`.
        fields = super().get_fields()
        fields["errors"] = serializers.DictField(
            child=serializers.CharField(),
            allow_null=True,
            help_text="Error message per day (YYYY-MM-DD) whose calculation failed, or null when none failed.",
        )
        return fields


class RecalculateMetricsRequestSerializer(serializers.Serializer):
    """Request body for triggering a metrics recalculation."""

    trigger = serializers.ChoiceField(
        choices=ExperimentMetricsRecalculation.RequestTrigger.choices,
        required=False,
        default="manual",
        help_text=(
            "What triggered this recalculation (manual is the default for user-initiated runs). Only client "
            "triggers are accepted; agent_mcp, timeseries_sync and scheduled are set by the server."
        ),
    )


class ActiveRecalculationRunSerializer(serializers.Serializer):
    """Pointer to a recalculation run that is still executing, surfaced alongside the latest terminal results."""

    id = serializers.UUIDField(read_only=True, help_text="Identifier of the run that is still executing")
    status = serializers.ChoiceField(
        choices=ExperimentMetricsRecalculation.Status.choices,
        read_only=True,
        help_text="Status of the executing run (pending or in_progress)",
    )


class _ExperimentMetricsRecalculationBaseSerializer(serializers.Serializer):
    """Identity, counters and timestamps of one recalculation job row.

    Never a response on its own. Each endpoint serializes with the subclass that matches what it fills, so the
    generated client types carry only the fields that endpoint returns.
    """

    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this recalculation job")
    experiment_id = serializers.IntegerField(read_only=True, help_text="ID of the experiment being recalculated")
    status = serializers.ChoiceField(
        choices=ExperimentMetricsRecalculation.Status.choices,
        read_only=True,
        help_text="Current status of the recalculation job",
    )
    total_metrics = serializers.IntegerField(read_only=True, help_text="Total number of metrics to recalculate")
    completed_metrics = serializers.IntegerField(
        read_only=True,
        help_text="Number of metrics with a COMPLETED result row that did not fail in this run (derived, not stored)",
    )
    failed_metrics = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Number of failed metrics in this run (derived): metrics with a FAILED result row or a metric_errors "
            "entry. A metric that fails keeps its earlier completed result, so it can count here and still have a "
            "completed row in results. The error of a rejected run counts only for a metric without a row"
        ),
    )
    # Named metric_errors (not errors) to avoid shadowing DRF's reserved Serializer.errors property.
    metric_errors = serializers.JSONField(
        read_only=True,
        help_text=(
            "Terminal failure per metric_uuid: {step, message, error_type, retriable, timestamp, exposures_path}. "
            "retriable is true when a transient error exhausted its attempts, so a heal_latest_run or manual_retry "
            "can succeed; false when the metric config, the data, or a resource limit must change first. "
            "exposures_path is where the query read the exposures, and is missing when the query failed before it "
            "was built"
        ),
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the job was created")
    started_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="When processing started")
    completed_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="When processing completed")
    query_to = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Upper time bound the metrics in this run were calculated against (the data freshness cutoff). "
            "Shared by every metric in the run; null until processing starts"
        ),
    )


class ExperimentMetricsRecalculationJobSerializer(_ExperimentMetricsRecalculationBaseSerializer):
    """POST response: the job just queued, or the one already active. It carries no results or live progress yet."""

    is_existing = serializers.BooleanField(
        read_only=True, required=False, help_text="True if returning an existing job rather than a newly created one"
    )


class ExperimentMetricsRecalculationRunSerializer(_ExperimentMetricsRecalculationBaseSerializer):
    """GET by id: one run with its per-metric results, retry state and live query progress."""

    metric_retries = serializers.JSONField(
        read_only=True,
        required=False,
        help_text=(
            "Transient retry state per metric_uuid: {attempt, max_attempts, error_type, message, "
            "next_retry_at}. message is a user-safe description of the error that triggered the retry. "
            "Present only while a metric is between failed attempts; cleared when it succeeds or "
            "fails terminally, so treat entries for metrics that already have a result as stale."
        ),
    )
    results = MetricRecalculationResultSerializer(
        many=True,
        read_only=True,
        required=False,
        help_text=(
            "Per-metric results of this run, scoped by the run's recalc fingerprint. When a metric fails, its earlier "
            "completed result at the same window stays here and the failure is in metric_errors"
        ),
    )
    rows_read = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "Rows read by the run's metric queries so far, both finished and currently running. Cumulative "
            "and roughly monotonic across the run; the primary live progress signal"
        ),
    )
    estimated_rows_total = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "ClickHouse's total_rows_approx across running queries plus the final read_rows of finished ones. "
            "A soft ceiling revised mid-scan, so it can exceed or trail rows_read; treat rows_read as the "
            "reliable signal"
        ),
    )


class ExperimentMetricsRecalculationLatestSerializer(ExperimentMetricsRecalculationRunSerializer):
    """GET latest: the newest terminal run, or the timeseries fallback, plus a pointer to any active run."""

    active_run = ActiveRecalculationRunSerializer(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="Run currently executing for this experiment, if any; poll it by id for live progress",
    )
    # nosemgrep: choices-need-a-class -- moved unchanged from presentation/serializers.py
    result_source = serializers.ChoiceField(
        choices=["recalculation", "timeseries_fallback"],
        required=False,
        default="recalculation",
        read_only=True,
        help_text=(
            "Where these results came from: 'recalculation' for a real metrics-recalculation run, "
            "'timeseries_fallback' for a cold-start placeholder built from the latest daily timeseries data."
        ),
    )
    exceeds_recalculation_age_limit = serializers.BooleanField(
        read_only=True,
        help_text=(
            "True when the experiment started too long ago for its metrics to be recalculated. A recalculation "
            "request then returns a rejected run with the recalculation_window_too_long error, and the saved "
            "results stay as they are"
        ),
    )
