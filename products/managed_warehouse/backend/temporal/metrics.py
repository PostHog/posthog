from typing import Self

from temporalio import activity, workflow
from temporalio.common import MetricAttributes, MetricCounter, MetricGaugeFloat, MetricHistogramFloat, MetricMeter

from products.managed_warehouse.backend.metrics import record_counter, record_gauge, record_histogram


def _temporal_context_active() -> bool:
    return activity.in_activity() or workflow.in_workflow()


def _posthog_metric_name(temporal_metric_name: str) -> str:
    normalized_name = temporal_metric_name.removesuffix("_seconds")
    return f"warehouse.{normalized_name.replace('_', '.')}"


class _CounterTwin(MetricCounter):
    def __init__(self, temporal_metric: MetricCounter, attributes: MetricAttributes) -> None:
        self._temporal_metric = temporal_metric
        self._attributes = dict(attributes)

    @property
    def name(self) -> str:
        return self._temporal_metric.name

    @property
    def description(self) -> str | None:
        return self._temporal_metric.description

    @property
    def unit(self) -> str | None:
        return self._temporal_metric.unit

    def with_additional_attributes(self, additional_attributes: MetricAttributes) -> Self:
        return type(self)(
            self._temporal_metric.with_additional_attributes(additional_attributes),
            {**self._attributes, **additional_attributes},
        )

    def add(self, value: int, additional_attributes: MetricAttributes | None = None) -> None:
        self._temporal_metric.add(value, additional_attributes)
        if _temporal_context_active():
            record_counter(
                _posthog_metric_name(self.name),
                value,
                {**self._attributes, **(additional_attributes or {})},
                unit=self.unit,
            )


class _HistogramTwin(MetricHistogramFloat):
    def __init__(self, temporal_metric: MetricHistogramFloat, attributes: MetricAttributes) -> None:
        self._temporal_metric = temporal_metric
        self._attributes = dict(attributes)

    @property
    def name(self) -> str:
        return self._temporal_metric.name

    @property
    def description(self) -> str | None:
        return self._temporal_metric.description

    @property
    def unit(self) -> str | None:
        return self._temporal_metric.unit

    def with_additional_attributes(self, additional_attributes: MetricAttributes) -> Self:
        return type(self)(
            self._temporal_metric.with_additional_attributes(additional_attributes),
            {**self._attributes, **additional_attributes},
        )

    def record(self, value: float, additional_attributes: MetricAttributes | None = None) -> None:
        self._temporal_metric.record(value, additional_attributes)
        if _temporal_context_active():
            record_histogram(
                _posthog_metric_name(self.name),
                value,
                {**self._attributes, **(additional_attributes or {})},
                unit=self.unit or "1",
            )


class _GaugeTwin(MetricGaugeFloat):
    def __init__(self, temporal_metric: MetricGaugeFloat, attributes: MetricAttributes) -> None:
        self._temporal_metric = temporal_metric
        self._attributes = dict(attributes)

    @property
    def name(self) -> str:
        return self._temporal_metric.name

    @property
    def description(self) -> str | None:
        return self._temporal_metric.description

    @property
    def unit(self) -> str | None:
        return self._temporal_metric.unit

    def with_additional_attributes(self, additional_attributes: MetricAttributes) -> Self:
        return type(self)(
            self._temporal_metric.with_additional_attributes(additional_attributes),
            {**self._attributes, **additional_attributes},
        )

    def set(self, value: float, additional_attributes: MetricAttributes | None = None) -> None:
        self._temporal_metric.set(value, additional_attributes)
        if _temporal_context_active():
            record_gauge(
                _posthog_metric_name(self.name),
                value,
                {**self._attributes, **(additional_attributes or {})},
                unit=self.unit,
            )


def _counter_twin(metric: MetricCounter, attributes: MetricAttributes) -> MetricCounter:
    return _CounterTwin(metric, attributes)


def _histogram_twin(metric: MetricHistogramFloat, attributes: MetricAttributes) -> MetricHistogramFloat:
    return _HistogramTwin(metric, attributes)


def _gauge_twin(metric: MetricGaugeFloat, attributes: MetricAttributes) -> MetricGaugeFloat:
    return _GaugeTwin(metric, attributes)


def record_ducklake_copy_data_imports_stage_duration(value: float, attributes: MetricAttributes) -> None:
    record_histogram(
        "warehouse.ducklake.copy.data.imports.stage.duration",
        value,
        attributes,
        unit="ms",
    )


def record_ducklake_register_data_imports_stage_duration(value: float, attributes: MetricAttributes) -> None:
    record_histogram(
        "warehouse.ducklake.register.data.imports.stage.duration",
        value,
        attributes,
        unit="ms",
    )


def _activity_meter() -> MetricMeter:
    return activity.metric_meter() if activity.in_activity() else MetricMeter.noop


def _registration_attributes(team_id: int, schema_id: str) -> dict[str, str]:
    return {"team_id": str(team_id), "schema_id": schema_id}


def _copy_data_imports_attributes(team_id: int, schema_id: str | None = None) -> dict[str, str]:
    attributes = {"team_id": str(team_id)}
    if schema_id is not None:
        attributes["schema_id"] = schema_id
    return attributes


def get_ducklake_copy_data_modeling_finished_metric(status: str) -> MetricCounter:
    attributes = {"status": status}
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_counter(
            "ducklake_copy_data_modeling_finished",
            "Number of DuckLake data modeling copy workflows finished, including failures.",
        )
    )
    return _counter_twin(metric, attributes)


def get_ducklake_copy_data_modeling_verification_metric(check: str, status: str) -> MetricCounter:
    attributes = {"check": check, "status": status}
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_counter(
            "ducklake_copy_data_modeling_verification",
            "Number of DuckLake data modeling verification checks executed grouped by status.",
        )
    )
    return _counter_twin(metric, attributes)


def get_ducklake_copy_data_imports_finished_metric(*, team_id: int, status: str) -> MetricCounter:
    attributes = {**_copy_data_imports_attributes(team_id), "status": status}
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_counter(
            "ducklake_copy_data_imports_finished",
            "Number of DuckLake data import copy workflows finished after passing the feature flag gate.",
        )
    )
    return _counter_twin(metric, attributes)


def get_ducklake_copy_data_imports_started_metric(*, team_id: int) -> MetricCounter:
    attributes = _copy_data_imports_attributes(team_id)
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_counter(
            "ducklake_copy_data_imports_started",
            "Number of DuckLake data import copy workflows that passed the feature flag gate.",
        )
    )
    return _counter_twin(metric, attributes)


def get_ducklake_copy_data_imports_duration_metric(*, team_id: int, status: str) -> MetricHistogramFloat:
    attributes = {**_copy_data_imports_attributes(team_id), "status": status}
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_histogram_float(
            "ducklake_copy_data_imports_duration_seconds",
            "End-to-end duration of DuckLake data import copy workflows after passing the feature flag gate.",
            "s",
        )
    )
    return _histogram_twin(metric, attributes)


def get_ducklake_copy_data_imports_last_success_metric(*, team_id: int, schema_id: str) -> MetricGaugeFloat:
    attributes = _copy_data_imports_attributes(team_id, schema_id)
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_gauge_float(
            "ducklake_copy_data_imports_last_success_timestamp_seconds",
            "Unix timestamp of the last successful DuckLake data import copy for a schema.",
            "s",
        )
    )
    return _gauge_twin(metric, attributes)


def get_ducklake_copy_data_imports_verification_metric(
    *, team_id: int, schema_id: str, check_name: str, status: str
) -> MetricCounter:
    attributes = {**_copy_data_imports_attributes(team_id, schema_id), "check": check_name, "status": status}
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_counter(
            "ducklake_copy_data_imports_verification",
            "Number of DuckLake data import verification checks completed.",
        )
    )
    return _counter_twin(metric, attributes)


def get_ducklake_copy_data_imports_files_metric(*, team_id: int, schema_id: str) -> MetricHistogramFloat:
    attributes = _copy_data_imports_attributes(team_id, schema_id)
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_histogram_float(
            "ducklake_copy_data_imports_data_files_copied",
            "Number of Delta data files in a successful DuckLake data import copy.",
        )
    )
    return _histogram_twin(metric, attributes)


def get_ducklake_copy_data_imports_rows_metric(*, team_id: int, schema_id: str) -> MetricHistogramFloat:
    attributes = _copy_data_imports_attributes(team_id, schema_id)
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_histogram_float(
            "ducklake_copy_data_imports_rows_copied",
            "Number of rows in a successful DuckLake data import copy.",
        )
    )
    return _histogram_twin(metric, attributes)


def get_ducklake_copy_data_imports_bytes_metric(*, team_id: int, schema_id: str) -> MetricHistogramFloat:
    attributes = _copy_data_imports_attributes(team_id, schema_id)
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_histogram_float(
            "ducklake_copy_data_imports_data_bytes_copied",
            "Number of Delta data file bytes in a successful DuckLake data import copy.",
            "By",
        )
    )
    return _histogram_twin(metric, attributes)


def get_ducklake_register_data_imports_finished_metric(*, team_id: int, schema_id: str, status: str) -> MetricCounter:
    attributes = {**_registration_attributes(team_id, schema_id), "status": status}
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_counter(
            "ducklake_register_data_imports_finished",
            "Number of DuckLake prepared data import registration workflows finished, including failures.",
        )
    )
    return _counter_twin(metric, attributes)


def get_ducklake_register_data_imports_duration_metric(
    *, team_id: int, schema_id: str, status: str
) -> MetricHistogramFloat:
    attributes = {**_registration_attributes(team_id, schema_id), "status": status}
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_histogram_float(
            "ducklake_register_data_imports_duration_seconds",
            "End-to-end duration of DuckLake prepared data import registration workflows that passed the feature flag gate.",
            "s",
        )
    )
    return _histogram_twin(metric, attributes)


def get_ducklake_register_data_imports_started_metric(*, team_id: int, schema_id: str) -> MetricCounter:
    attributes = _registration_attributes(team_id, schema_id)
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_counter(
            "ducklake_register_data_imports_started",
            "Number of DuckLake prepared data import registration workflows that passed the feature flag gate.",
        )
    )
    return _counter_twin(metric, attributes)


def get_ducklake_register_data_imports_last_success_metric(*, team_id: int, schema_id: str) -> MetricGaugeFloat:
    attributes = _registration_attributes(team_id, schema_id)
    metric = (
        workflow.metric_meter()
        .with_additional_attributes(attributes)
        .create_gauge_float(
            "ducklake_register_data_imports_last_success_timestamp_seconds",
            "Unix timestamp of the last successful DuckLake prepared data import registration workflow.",
            "s",
        )
    )
    return _gauge_twin(metric, attributes)


def get_ducklake_register_data_imports_stale_metric(*, team_id: int, schema_id: str, stage: str) -> MetricCounter:
    attributes = {**_registration_attributes(team_id, schema_id), "stage": stage}
    metric = (
        _activity_meter()
        .with_additional_attributes(attributes)
        .create_counter(
            "ducklake_register_data_imports_stale",
            "Number of post-gate DuckLake registrations skipped because their prepared generation became stale.",
        )
    )
    return _counter_twin(metric, attributes)


def get_ducklake_register_data_imports_files_metric(*, team_id: int, schema_id: str) -> MetricHistogramFloat:
    attributes = _registration_attributes(team_id, schema_id)
    metric = (
        _activity_meter()
        .with_additional_attributes(attributes)
        .create_histogram_float(
            "ducklake_register_data_imports_files_registered",
            "Number of Parquet files in a successful DuckLake data import registration.",
        )
    )
    return _histogram_twin(metric, attributes)


def get_ducklake_register_data_imports_rows_metric(*, team_id: int, schema_id: str) -> MetricHistogramFloat:
    attributes = _registration_attributes(team_id, schema_id)
    metric = (
        _activity_meter()
        .with_additional_attributes(attributes)
        .create_histogram_float(
            "ducklake_register_data_imports_rows_registered",
            "Number of rows in a successful DuckLake data import registration.",
        )
    )
    return _histogram_twin(metric, attributes)


def get_ducklake_register_data_imports_bytes_metric(*, team_id: int, schema_id: str) -> MetricHistogramFloat:
    attributes = _registration_attributes(team_id, schema_id)
    metric = (
        _activity_meter()
        .with_additional_attributes(attributes)
        .create_histogram_float(
            "ducklake_register_data_imports_bytes_copied",
            "Number of prepared Parquet bytes copied by a successful DuckLake data import registration.",
            "By",
        )
    )
    return _histogram_twin(metric, attributes)
