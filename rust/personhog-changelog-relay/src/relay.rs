use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka::kafka_producer::KafkaContext;
use futures::future::join_all;
use lifecycle::Handle;
use metrics::{counter, gauge, histogram, Gauge};
use personhog_coordination::follow::ChangelogSubscription;
use rdkafka::error::KafkaError;
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::util::Timeout;
use tracing::warn;

use crate::consumer::{ChangelogConsumer, Record};
use crate::transcode::person_row;

const RETRY_BACKOFF_START: Duration = Duration::from_millis(100);
const RETRY_BACKOFF_MAX: Duration = Duration::from_secs(5);

pub struct Relay {
    consumer: Arc<ChangelogConsumer>,
    producer: FutureProducer<KafkaContext>,
    output_topic: String,
    dlq_topic: String,
    batch_size: usize,
    batch_timeout: Duration,
    /// How far `clickhouse_person` trails the leaders, in seconds.
    lag: Gauge,
}

impl Relay {
    pub fn new(
        consumer: Arc<ChangelogConsumer>,
        producer: FutureProducer<KafkaContext>,
        output_topic: String,
        dlq_topic: String,
        batch_size: usize,
        batch_timeout: Duration,
    ) -> Self {
        Self {
            consumer,
            producer,
            output_topic,
            dlq_topic,
            batch_size: batch_size.max(1),
            batch_timeout,
            lag: gauge!("personhog_changelog_relay_lag_seconds"),
        }
    }

    fn set_lag_since(&self, timestamp_ms: i64) {
        let now = chrono::Utc::now().timestamp_millis();
        self.lag.set((now - timestamp_ms).max(0) as f64 / 1000.0);
    }

    pub async fn run(&self, handle: &Handle) {
        let mut last_relayed_ms = None;
        while !handle.is_shutting_down() {
            let Some((batch, consumer_failed)) = self.collect(handle).await else {
                return;
            };
            handle.report_healthy();
            gauge!("personhog_changelog_relay_draining").set(if self.consumer.is_draining() {
                1.0
            } else {
                0.0
            });
            histogram!("personhog_changelog_relay_batch_records").record(batch.len() as f64);
            if batch.is_empty() {
                // An empty batch is caught up only if the consumer could read;
                // otherwise the lag is at most the age of the last record relayed.
                match (consumer_failed, last_relayed_ms) {
                    (false, _) => self.lag.set(0.0),
                    (true, Some(relayed)) => self.set_lag_since(relayed),
                    (true, None) => {}
                }
                continue;
            }
            let started = Instant::now();
            if !self.relay_batch(&batch, handle).await {
                return;
            }
            histogram!("personhog_changelog_relay_batch_duration_ms")
                .record(started.elapsed().as_secs_f64() * 1000.0);
            if let Some(oldest) = batch.iter().filter_map(|r| r.timestamp_ms).min() {
                self.set_lag_since(oldest);
            }
            last_relayed_ms = batch.iter().filter_map(|r| r.timestamp_ms).max();
        }
    }

    /// Up to a batch of records, or what arrived within the batch timeout, and
    /// whether a read failed meanwhile. `None` when the consumer is fatally broken.
    async fn collect(&self, handle: &Handle) -> Option<(Vec<Record>, bool)> {
        let deadline = tokio::time::Instant::now() + self.batch_timeout;
        let mut batch = Vec::new();
        let mut failed = false;
        while batch.len() < self.batch_size {
            let received = tokio::select! {
                _ = handle.shutdown_recv() => return Some((Vec::new(), false)),
                received = tokio::time::timeout_at(deadline, self.consumer.recv()) => received,
            };
            match received {
                Err(_) => break,
                Ok(Ok(record)) => batch.push(record),
                Ok(Err(e)) => {
                    if let Some((code, reason)) = self.consumer.fatal_error() {
                        handle.signal_failure(format!(
                            "Kafka consumer entered a fatal state ({code:?}): {reason}"
                        ));
                        return None;
                    }
                    counter!("personhog_changelog_relay_consumer_errors_total").increment(1);
                    warn!(error = %e, "Kafka recv error");
                    failed = true;
                }
            }
        }
        Some((batch, failed))
    }

    /// Delivers every record, then commits past them. Returns false when
    /// shutdown interrupted a delivery, leaving the batch uncommitted.
    pub async fn relay_batch(&self, batch: &[Record], handle: &Handle) -> bool {
        let delivered = join_all(batch.iter().map(|record| self.deliver(record, handle))).await;
        if !delivered.into_iter().all(|ok| ok) {
            return false;
        }
        let mut highest: HashMap<(String, i32), i64> = HashMap::new();
        for record in batch {
            let offset = highest
                .entry((record.topic.clone(), record.partition))
                .or_insert(record.offset);
            *offset = (*offset).max(record.offset);
        }
        if let Err(e) = self.consumer.commit(&highest) {
            counter!("personhog_changelog_relay_commit_errors_total").increment(1);
            warn!(error = %e, "offset commit failed; the next batch commits past it");
        }
        true
    }

    async fn deliver(&self, record: &Record, handle: &Handle) -> bool {
        let (reason, error) = match person_row(record.payload.as_deref()) {
            Ok(row) => match self
                .send(
                    &self.output_topic,
                    &row,
                    None,
                    record.timestamp_ms,
                    handle,
                    false,
                )
                .await
            {
                Sent::Delivered => {
                    counter!("personhog_changelog_relay_records_total", "outcome" => "relayed")
                        .increment(1);
                    return true;
                }
                Sent::Shutdown => return false,
                Sent::Rejected(e) => ("rejected", format!("the output rejected the row: {e}")),
            },
            Err(poison) => (poison.reason(), poison.to_string()),
        };
        warn!(
            topic = %record.topic,
            partition = record.partition,
            offset = record.offset,
            reason,
            error = %error,
            "unrelayable changelog record; sending it to the DLQ"
        );
        let headers = dlq_headers(record, reason, &error);
        let payload = record.payload.as_deref().unwrap_or_default();
        // The record already fit on the changelog, so the DLQ retries even a rejection.
        match self
            .send(
                &self.dlq_topic,
                payload,
                Some(headers),
                record.timestamp_ms,
                handle,
                true,
            )
            .await
        {
            Sent::Delivered => {
                counter!(
                    "personhog_changelog_relay_records_total",
                    "outcome" => "dlq",
                    "reason" => reason
                )
                .increment(1);
                true
            }
            Sent::Rejected(_) | Sent::Shutdown => false,
        }
    }

    /// Retries until the broker acks, so an outage holds the relay's offsets
    /// where they are. A rejection no retry can fix returns unless
    /// `retry_rejections` is set.
    async fn send(
        &self,
        topic: &str,
        payload: &[u8],
        headers: Option<OwnedHeaders>,
        timestamp_ms: Option<i64>,
        handle: &Handle,
        retry_rejections: bool,
    ) -> Sent {
        let mut backoff = RETRY_BACKOFF_START;
        loop {
            let mut record = FutureRecord::<(), [u8]>::to(topic).payload(payload);
            if let Some(headers) = &headers {
                record = record.headers(headers.clone());
            }
            match self.producer.send(record, Timeout::Never).await {
                Ok(_) => return Sent::Delivered,
                Err((e, _)) if !retry_rejections && is_rejection(&e) => return Sent::Rejected(e),
                Err((e, _)) => {
                    counter!("personhog_changelog_relay_produce_retries_total", "topic" => topic.to_string())
                        .increment(1);
                    warn!(topic, error = %e, "produce failed; retrying");
                }
            }
            // A broker outage is not a stuck process, but the lag shows it.
            handle.report_healthy();
            if let Some(timestamp_ms) = timestamp_ms {
                self.set_lag_since(timestamp_ms);
            }
            tokio::select! {
                _ = handle.shutdown_recv() => return Sent::Shutdown,
                _ = tokio::time::sleep(backoff) => {}
            }
            backoff = (backoff * 2).min(RETRY_BACKOFF_MAX);
        }
    }
}

enum Sent {
    Delivered,
    Rejected(KafkaError),
    Shutdown,
}

/// Errors about the record itself, which no retry can fix.
fn is_rejection(e: &KafkaError) -> bool {
    matches!(
        e,
        KafkaError::MessageProduction(
            RDKafkaErrorCode::MessageSizeTooLarge
                | RDKafkaErrorCode::MessageBatchTooLarge
                | RDKafkaErrorCode::InvalidRecord
        )
    )
}

fn dlq_headers(record: &Record, reason: &str, error: &str) -> OwnedHeaders {
    let partition = record.partition.to_string();
    let offset = record.offset.to_string();
    OwnedHeaders::new()
        .insert(Header {
            key: "source_topic",
            value: Some(record.topic.as_str()),
        })
        .insert(Header {
            key: "source_partition",
            value: Some(partition.as_str()),
        })
        .insert(Header {
            key: "source_offset",
            value: Some(offset.as_str()),
        })
        .insert(Header {
            key: "reason",
            value: Some(reason),
        })
        .insert(Header {
            key: "error",
            value: Some(error),
        })
}
