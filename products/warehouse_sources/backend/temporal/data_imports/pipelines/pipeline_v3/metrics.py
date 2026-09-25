from temporalio import activity
from temporalio.common import MetricCounter, MetricHistogram, MetricHistogramFloat


def get_rows_extracted_metric(team_id: str, schema_id: str, source_type: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"team_id": team_id, "schema_id": schema_id, "source_type": source_type})
        .create_counter("warehouse_producer_rows_extracted_total", "Total rows extracted by the producer")
    )


def get_batches_produced_metric(team_id: str, schema_id: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"team_id": team_id, "schema_id": schema_id})
        .create_counter("warehouse_producer_batches_produced_total", "Total batches produced")
    )


def get_s3_write_duration_metric() -> MetricHistogramFloat:
    return activity.metric_meter().create_histogram_float(
        "warehouse_producer_s3_write_duration_seconds", "Duration of S3 batch writes", "s"
    )


def get_s3_write_errors_metric(error_type: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"error_type": error_type})
        .create_counter("warehouse_producer_s3_write_errors_total", "Total S3 write errors")
    )


def get_pipeline_run_duration_metric(
    team_id: str, source_type: str, sync_type: str, status: str
) -> MetricHistogramFloat:
    return (
        activity.metric_meter()
        .with_additional_attributes(
            {"team_id": team_id, "source_type": source_type, "sync_type": sync_type, "status": status}
        )
        .create_histogram_float("warehouse_pipeline_run_duration_seconds", "Duration of full pipeline runs", "s")
    )


def get_run_attempt_metric(source_type: str) -> MetricHistogram:
    """Temporal activity attempt number, recorded once as each attempt starts extracting.

    Every attempt of a run stages a fresh set of batches under its own ``run_uuid`` (see
    ``pipeline.py``), and the idempotency key is keyed on that ``run_uuid`` — so a retried run
    re-extracts and re-loads work its earlier attempts already did. Batches drain serially per
    ``(team_id, schema_id)``, so a run that keeps retrying enqueues faster than its group can
    drain and holds the queue head for hours.

    Nothing else measures that: ``warehouse_pg_consumer_batch_retry_total`` counts *batch*
    retries, not workflow attempts. Read this as a distribution — a p99 above a handful means
    runs are being restarted repeatedly and paying for the same extraction each time.

    Labelled by ``source_type`` only. Attempts are a per-run property, so team/schema labels would
    add cardinality without telling you anything the distribution does not.
    """
    return (
        activity.metric_meter()
        .with_additional_attributes({"source_type": source_type})
        .create_histogram(
            "warehouse_pipeline_run_attempt",
            "Temporal activity attempt number at the start of a pipeline run",
        )
    )
