from temporalio import activity, workflow
from temporalio.common import MetricCounter, MetricGaugeFloat, MetricHistogramFloat, MetricMeter


def _activity_meter() -> MetricMeter:
    return activity.metric_meter() if activity.in_activity() else MetricMeter.noop


def _registration_attributes(team_id: int, schema_id: str) -> dict[str, str]:
    return {"team_id": str(team_id), "schema_id": schema_id}


def get_ducklake_copy_data_modeling_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "ducklake_copy_data_modeling_finished",
            "Number of DuckLake data modeling copy workflows finished, including failures.",
        )
    )


def get_ducklake_copy_data_modeling_verification_metric(check: str, status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"check": check, "status": status})
        .create_counter(
            "ducklake_copy_data_modeling_verification",
            "Number of DuckLake data modeling verification checks executed grouped by status.",
        )
    )


def get_ducklake_copy_data_imports_finished_metric(status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "ducklake_copy_data_imports_finished",
            "Number of DuckLake data imports copy workflows finished, including failures.",
        )
    )


def get_ducklake_copy_data_imports_verification_metric(check_name: str, status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({"check": check_name, "status": status})
        .create_counter(
            "ducklake_copy_data_imports_verification",
            "Number of DuckLake data imports verification checks completed.",
        )
    )


def get_ducklake_register_data_imports_finished_metric(*, team_id: int, schema_id: str, status: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes({**_registration_attributes(team_id, schema_id), "status": status})
        .create_counter(
            "ducklake_register_data_imports_finished",
            "Number of DuckLake prepared data import registration workflows finished, including failures.",
        )
    )


def get_ducklake_register_data_imports_duration_metric(
    *, team_id: int, schema_id: str, status: str
) -> MetricHistogramFloat:
    return (
        workflow.metric_meter()
        .with_additional_attributes({**_registration_attributes(team_id, schema_id), "status": status})
        .create_histogram_float(
            "ducklake_register_data_imports_duration_seconds",
            "End-to-end duration of DuckLake prepared data import registration workflows that passed the feature flag gate.",
            "s",
        )
    )


def get_ducklake_register_data_imports_started_metric(*, team_id: int, schema_id: str) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes(_registration_attributes(team_id, schema_id))
        .create_counter(
            "ducklake_register_data_imports_started",
            "Number of DuckLake prepared data import registration workflows that passed the feature flag gate.",
        )
    )


def get_ducklake_register_data_imports_last_success_metric(*, team_id: int, schema_id: str) -> MetricGaugeFloat:
    return (
        workflow.metric_meter()
        .with_additional_attributes(_registration_attributes(team_id, schema_id))
        .create_gauge_float(
            "ducklake_register_data_imports_last_success_timestamp_seconds",
            "Unix timestamp of the last successful DuckLake prepared data import registration workflow.",
            "s",
        )
    )


def get_ducklake_register_data_imports_stale_metric(*, team_id: int, schema_id: str, stage: str) -> MetricCounter:
    return (
        _activity_meter()
        .with_additional_attributes({**_registration_attributes(team_id, schema_id), "stage": stage})
        .create_counter(
            "ducklake_register_data_imports_stale",
            "Number of post-gate DuckLake registrations skipped because their prepared generation became stale.",
        )
    )


def get_ducklake_register_data_imports_files_metric(*, team_id: int, schema_id: str) -> MetricHistogramFloat:
    return (
        _activity_meter()
        .with_additional_attributes(_registration_attributes(team_id, schema_id))
        .create_histogram_float(
            "ducklake_register_data_imports_files_registered",
            "Number of Parquet files in a successful DuckLake data import registration.",
        )
    )


def get_ducklake_register_data_imports_rows_metric(*, team_id: int, schema_id: str) -> MetricHistogramFloat:
    return (
        _activity_meter()
        .with_additional_attributes(_registration_attributes(team_id, schema_id))
        .create_histogram_float(
            "ducklake_register_data_imports_rows_registered",
            "Number of rows in a successful DuckLake data import registration.",
        )
    )


def get_ducklake_register_data_imports_bytes_metric(*, team_id: int, schema_id: str) -> MetricHistogramFloat:
    return (
        _activity_meter()
        .with_additional_attributes(_registration_attributes(team_id, schema_id))
        .create_histogram_float(
            "ducklake_register_data_imports_bytes_copied",
            "Number of prepared Parquet bytes copied by a successful DuckLake data import registration.",
            "By",
        )
    )
