use common_kafka::kafka_messages::app_metrics2::{
    AppMetric2, Kind as AppMetric2Kind, Source as AppMetric2Source,
};
use common_kafka::kafka_producer::create_kafka_producer;
use common_kafka::kafka_producer::{send_iter_to_kafka, KafkaContext, KafkaProduceError};
use common_kafka::APP_METRICS2_TOPIC;
use cyclotron_core::{AggregatedDelete, QueueError, SHARD_ID_KEY};
use health::HealthRegistry;
use tracing::{error, info, warn};

use rdkafka::producer::FutureProducer;

use crate::{
    config::{JanitorConfig, JanitorSettings},
    metrics_constants::*,
};

// The janitor reports it's own metrics, this is mostly for testing purposes
#[derive(Debug, Clone, Eq, PartialEq)]
pub struct CleanupResult {
    pub completed: u64,
    pub failed: u64,
    pub poisoned: u64,
    pub stalled: u64,
}

pub struct Janitor {
    pub inner: cyclotron_core::Janitor,
    pub kafka_producer: FutureProducer<KafkaContext>,
    pub settings: JanitorSettings,
    pub metrics_labels: Vec<(String, String)>,
}

impl Janitor {
    pub async fn new(
        config: JanitorConfig,
        health_registry: &HealthRegistry,
    ) -> Result<Self, QueueError> {
        let settings = config.settings;
        let inner = cyclotron_core::Janitor::new(config.pool).await?;

        let metrics_labels = vec![
            ("janitor_id".to_string(), settings.id.clone()),
            (SHARD_ID_KEY.to_string(), settings.shard_id.clone()),
        ];

        let kafka_liveness = health_registry
            .register("rdkafka".to_string(), time::Duration::seconds(30))
            .await;

        let kafka_producer = create_kafka_producer(&config.kafka, kafka_liveness)
            .await
            .expect("failed to create kafka producer");

        Ok(Self {
            inner,
            kafka_producer,
            settings,
            metrics_labels,
        })
    }

    pub async fn run_migrations(&self) {
        self.inner.run_migrations().await;
    }

    pub async fn run_once(&self) -> Result<CleanupResult, QueueError> {
        info!("Running janitor loop");
        let _loop_start = common_metrics::timing_guard(RUN_TIME, &self.metrics_labels);
        common_metrics::inc(RUN_STARTS, &self.metrics_labels, 1);

        let aggregated_deletes = {
            let _time = common_metrics::timing_guard(CLEANUP_TIME, &self.metrics_labels);
            self.inner.delete_completed_and_failed_jobs().await?
        };

        let mut completed_count = 0u64;
        let mut failed_count = 0u64;
        for delete in &aggregated_deletes {
            if delete.state == "completed" {
                completed_count += delete.count as u64;
            } else if delete.state == "failed" {
                failed_count += delete.count as u64;
            }
        }
        common_metrics::inc(COMPLETED_COUNT, &self.metrics_labels, completed_count);
        common_metrics::inc(FAILED_COUNT, &self.metrics_labels, failed_count);

        match send_iter_to_kafka(
            &self.kafka_producer,
            APP_METRICS2_TOPIC,
            aggregated_deletes
                .into_iter()
                .map(aggregated_delete_to_app_metric2),
        )
        .await
        .into_iter()
        .collect::<Result<Vec<_>, _>>()
        {
            Ok(_) => {}
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
            let _time = common_metrics::timing_guard(POISONED_TIME, &self.metrics_labels);
            self.inner
                .delete_poison_pills(self.settings.stall_timeout, self.settings.max_touches)
                .await?
        };
        common_metrics::inc(POISONED_COUNT, &self.metrics_labels, poisoned);

        if poisoned > 0 {
            warn!("Deleted {} poison pills", poisoned);
        }

        let stalled = {
            let _time = common_metrics::timing_guard(STALLED_TIME, &self.metrics_labels);
            self.inner
                .reset_stalled_jobs(self.settings.stall_timeout)
                .await?
        };
        common_metrics::inc(STALLED_COUNT, &self.metrics_labels, stalled);

        if stalled > 0 {
            warn!("Reset {} stalled jobs", stalled);
        }

        let available = {
            let _time = common_metrics::timing_guard(AVAILABLE_DEPTH_TIME, &self.metrics_labels);
            self.inner.waiting_jobs().await?
        };

        let mut available_labels = self.metrics_labels.clone();
        for (count, queue_name) in available {
            available_labels.push(("queue_name".to_string(), queue_name));
            common_metrics::gauge(AVAILABLE_DEPTH, &available_labels, count as f64);
            available_labels.pop();
        }

        let dlq_depth = {
            let _time = common_metrics::timing_guard(DLQ_DEPTH_TIME, &self.metrics_labels);
            self.inner.count_dlq_depth().await?
        };
        common_metrics::gauge(DLQ_DEPTH, &self.metrics_labels, dlq_depth as f64);

        common_metrics::inc(RUN_ENDS, &self.metrics_labels, 1);
        info!("Janitor loop complete");
        Ok(CleanupResult {
            completed: completed_count,
            failed: failed_count,
            poisoned,
            stalled,
        })
    }
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
