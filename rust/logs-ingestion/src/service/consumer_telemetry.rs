//! The metrics of Node's Kafka consumer (`common/kafka/consumer/metrics.ts` and `consumer-v1.ts`), with Node's names, labels, buckets and units, so one query reads both consumers.

use std::sync::Arc;
use std::time::Duration;

use ingestion_framework::KafkaMessage;
use metrics::{counter, gauge, histogram};
use metrics_exporter_prometheus::{BuildError, Matcher, PrometheusBuilder};

/// The buckets of `serve_metrics::setup_metrics_recorder`, which every other histogram of this service keeps.
const DEFAULT_BUCKETS: &[f64] = &[
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 50.0, 100.0, 250.0,
];

/// prom-client's default buckets, which Node uses for a histogram that names none.
const PROM_CLIENT_BUCKETS: &[f64] = &[
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
];

/// Node's buckets for each histogram, because a query that sums both consumers by `le` needs one set of bounds. The exporter adds `+Inf`.
const NODE_BUCKETS: &[(&str, &[f64])] = &[
    ("consumed_batch_duration_ms", PROM_CLIENT_BUCKETS),
    ("consumed_batch_background_duration_ms", PROM_CLIENT_BUCKETS),
    (
        "consumed_batch_backpressure_duration_ms",
        PROM_CLIENT_BUCKETS,
    ),
    (
        "consumer_batch_size",
        &[
            0.0, 50.0, 100.0, 250.0, 500.0, 750.0, 1_000.0, 1_500.0, 2_000.0, 3_000.0,
        ],
    ),
    (
        "consumer_batch_size_kb",
        &[
            0.0, 128.0, 512.0, 1_024.0, 5_120.0, 10_240.0, 20_480.0, 51_200.0, 102_400.0, 204_800.0,
        ],
    ),
    (
        "kafka_consume_interval_ms",
        &[
            0.0, 20.0, 100.0, 200.0, 500.0, 1_000.0, 2_500.0, 5_000.0, 10_000.0, 20_000.0,
            30_000.0, 60_000.0,
        ],
    ),
    (
        "kafka_consumer_drain_duration_ms",
        &[
            10.0, 50.0, 100.0, 500.0, 1_000.0, 5_000.0, 10_000.0, 30_000.0, 60_000.0, 120_000.0,
        ],
    ),
];

pub fn prometheus_builder() -> Result<PrometheusBuilder, BuildError> {
    let mut builder = PrometheusBuilder::new().set_buckets(DEFAULT_BUCKETS)?;
    for (name, buckets) in NODE_BUCKETS {
        builder = builder.set_buckets_for_metric(Matcher::Full((*name).to_string()), buckets)?;
    }
    Ok(builder)
}

#[derive(Debug, Clone, Default)]
pub struct ConsumerTelemetry {
    topic: Arc<str>,
    group_id: Arc<str>,
    pod: Arc<str>,
}

impl ConsumerTelemetry {
    pub fn new(topic: &str, group_id: &str, pod: &str) -> Self {
        Self {
            topic: Arc::from(topic),
            group_id: Arc::from(group_id),
            pod: Arc::from(pod),
        }
    }

    pub fn consume_interval(&self, since_last_poll: Duration) {
        histogram!("kafka_consume_interval_ms", "topic" => self.topic.clone(), "groupId" => self.group_id.clone())
            .record(millis(since_last_poll));
    }

    /// Node measures every poll, so an idle consumer reports a utilization of 0 and not its last busy value.
    pub fn poll(&self, messages: &[KafkaMessage], max_messages: usize) {
        let bytes: usize = messages
            .iter()
            .map(|m| m.value.as_ref().map_or(0, |value| value.len()))
            .sum();
        counter!("kafka_consumer_polls_total", "topic" => self.topic.clone(), "groupId" => self.group_id.clone())
            .increment(1);
        histogram!("consumer_batch_size").record(messages.len() as f64);
        histogram!("consumer_batch_size_kb").record(bytes as f64 / 1024.0);
        gauge!("consumer_batch_utilization", "groupId" => self.group_id.clone())
            .set(messages.len() as f64 / max_messages as f64);
    }

    pub fn batch_processed(&self, elapsed: Duration) {
        histogram!("consumed_batch_duration_ms", "topic" => self.topic.clone(), "groupId" => self.group_id.clone())
            .record(millis(elapsed));
    }

    // Node times the next three with prom-client's `startTimer`, which records seconds under these `_ms` names.
    // The port records seconds too, because a dashboard reads one series from both consumers.

    pub fn background_task_settled(&self, elapsed: Duration) {
        histogram!("consumed_batch_background_duration_ms", "topic" => self.topic.clone(), "groupId" => self.group_id.clone())
            .record(elapsed.as_secs_f64());
    }

    pub fn backpressure_released(&self, elapsed: Duration) {
        histogram!("consumed_batch_backpressure_duration_ms", "topic" => self.topic.clone(), "groupId" => self.group_id.clone())
            .record(elapsed.as_secs_f64());
    }

    pub fn shutdown_drained(&self, elapsed: Duration) {
        histogram!("kafka_consumer_drain_duration_ms", "topic" => self.topic.clone(), "groupId" => self.group_id.clone(), "cause" => "shutdown")
            .record(elapsed.as_secs_f64());
    }

    pub fn stale_store_offsets_skipped(&self, partitions: u64) {
        counter!("kafka_consumer_stale_store_offsets_skipped_total", "topic" => self.topic.clone(), "groupId" => self.group_id.clone())
            .increment(partitions);
    }

    pub fn partition_assigned(&self, topic: &str, partition: i32, assigned: bool) {
        let topic: Arc<str> = Arc::from(topic);
        let partition: Arc<str> = Arc::from(partition.to_string());
        gauge!(
            "kafka_consumer_assignment",
            "topic_name" => topic,
            "partition_id" => partition,
            "pod" => self.pod.clone(),
            "group_id" => self.group_id.clone()
        )
        .set(if assigned { 1.0 } else { 0.0 });
    }
}

fn millis(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1000.0
}

/// The exposition text of the metrics that `run` records, as a scrape of this service returns it.
#[cfg(test)]
pub fn render_metrics_of(run: impl FnOnce()) -> String {
    let recorder = prometheus_builder().unwrap().build_recorder();
    let handle = recorder.handle();
    metrics::with_local_recorder(&recorder, run);
    handle.render()
}

/// The `le` bounds of a histogram, in the order of the exposition text.
#[cfg(test)]
pub fn bucket_bounds<'a>(rendered: &'a str, histogram: &str) -> Vec<&'a str> {
    let prefix = format!("{histogram}_bucket{{");
    rendered
        .lines()
        .filter(|line| line.starts_with(&prefix))
        .filter_map(|line| line.split("le=\"").nth(1)?.split('"').next())
        .collect()
}

#[cfg(test)]
pub fn assert_metric_lines(rendered: &str, expected: &[&str]) {
    let lines: Vec<&str> = rendered.lines().collect();
    for line in expected {
        assert!(lines.contains(line), "no line `{line}` in:\n{rendered}");
    }
}
