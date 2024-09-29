use chrono::Utc;
use common_kafka::kafka_messages::app_metrics2::{
    AppMetric2, Kind as AppMetric2Kind, Source as AppMetric2Source,
};

use common_kafka::kafka_producer::{send_iter_to_kafka, KafkaProduceError};
use common_kafka::APP_METRICS2_TOPIC;
use cyclotron_core::{AggregatedDelete, QueueError};

use tracing::{error, info, warn};

use crate::app_context::{AppContext, JanitorStatus};
use crate::metrics_constants::*;

pub async fn run_once(context: &AppContext) -> JanitorStatus {
    match run_once_inner(context).await {
        Ok(status) => status,
        Err(e) => {
            error!("Janitor loop failed: {:?}", e);
            let mut status = context.state.get_status().await;
            status.last_error = Some(e.to_string());
            status.last_error_time = Some(Utc::now());
            status
        }
    }
}

async fn run_once_inner(context: &AppContext) -> Result<JanitorStatus, QueueError> {
    info!("Running janitor loop");

    // Grab a snapshot of the control state at the instant we started this
    // run
    let control_state = context.state.get_control().await;

    if control_state
        .paused_until
        .map(|t| t > Utc::now())
        .unwrap_or(false)
    {
        info!("Janitor is paused, skipping cleanup");
        return Ok(context.state.get_status().await); // No status update, we didn't run.
    }

    let labels = &context.metrics_labels;

    let _loop_start = common_metrics::timing_guard(RUN_TIME, labels);
    common_metrics::inc(RUN_STARTS, &context.metrics_labels, 1);

    let delete_set = {
        let _time = common_metrics::timing_guard(CLEANUP_TIME, labels);
        context.janitor.delete_completed_and_failed_jobs().await?
    };

    common_metrics::inc(COMPLETED_COUNT, labels, delete_set.total_completed() as u64);
    common_metrics::inc(FAILED_COUNT, labels, delete_set.total_failed() as u64);

    match send_iter_to_kafka(
        &context.kafka_producer,
        APP_METRICS2_TOPIC,
        delete_set
            .deletes
            .clone()
            .into_iter()
            .map(aggregated_delete_to_app_metric2),
    )
    .await
    {
        Ok(()) => {}
        Err(KafkaProduceError::SerializationError { error }) => {
            error!("Failed to serialize app_metrics2: {error}");
        }
        Err(KafkaProduceError::KafkaProduceError { error }) => {
            error!("Failed to produce to app_metrics2 kafka: {error}");
        }
        Err(KafkaProduceError::KafkaProduceCanceled) => {
            error!("Failed to produce to app_metrics2 kafka (timeout)");
        }
    }

    let poisoned = {
        let _time = common_metrics::timing_guard(POISONED_TIME, labels);
        context
            .janitor
            .delete_poison_pills(control_state.stall_timeout, control_state.max_touches)
            .await?
    };
    common_metrics::inc(POISONED_COUNT, labels, poisoned);

    if poisoned > 0 {
        warn!("Deleted {} poison pills", poisoned);
    }

    let stalled = {
        let _time = common_metrics::timing_guard(STALLED_TIME, labels);
        context
            .janitor
            .reset_stalled_jobs(control_state.stall_timeout)
            .await?
    };
    common_metrics::inc(STALLED_COUNT, labels, stalled);

    if stalled > 0 {
        warn!("Reset {} stalled jobs", stalled);
    }

    let available = {
        let _time = common_metrics::timing_guard(AVAILABLE_DEPTH_TIME, labels);
        context.janitor.waiting_jobs().await?
    };

    let mut available_labels = labels.clone();
    for (count, queue_name) in available.clone() {
        available_labels.push(("queue_name".to_string(), queue_name));
        common_metrics::gauge(AVAILABLE_DEPTH, &available_labels, count as f64);
        available_labels.pop();
    }

    let dlq_depth = {
        let _time = common_metrics::timing_guard(DLQ_DEPTH_TIME, labels);
        context.janitor.count_dlq_depth().await?
    };
    common_metrics::gauge(DLQ_DEPTH, labels, dlq_depth as f64);

    common_metrics::inc(RUN_ENDS, labels, 1);
    info!("Janitor loop complete");

    let mut status = context.state.get_status().await;

    status.last_delete = Some(delete_set);
    status.last_poisoned = Some(poisoned);
    status.last_stalled = Some(stalled);
    status.last_available = Some(available);
    status.last_dlq_count = Some(dlq_depth);
    status.last_successful_run = Some(Utc::now());

    Ok(status)
}

fn aggregated_delete_to_app_metric2(delete: AggregatedDelete) -> AppMetric2 {
    let kind = match delete.state.as_str() {
        "completed" => AppMetric2Kind::Success,
        "failed" => AppMetric2Kind::Failure,
        _ => AppMetric2Kind::Unknown,
    };

    AppMetric2 {
        team_id: delete.team_id as u32,
        timestamp: delete.hour,
        app_source: AppMetric2Source::Cyclotron,
        app_source_id: delete.function_id.unwrap_or("".to_owned()),
        instance_id: None,
        metric_kind: kind,
        metric_name: "finished_state".to_owned(),
        count: delete.count as u32,
    }
}
