use std::collections::HashSet;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use futures::stream::FuturesUnordered;
use futures::StreamExt;
use metrics::{counter, histogram};
use tracing::Level;
use uuid::Uuid;

use crate::config::CaptureMode;
use crate::v1::context::Context;
use crate::v1::sinks::event::Event;
use crate::v1::sinks::sink::Sink;
use crate::v1::sinks::types::{BatchSummary, Outcome, SinkResult};
use crate::v1::sinks::{Config, SinkName};

use super::producer::ProduceRecord;
use super::types::{KafkaResult, KafkaSinkError};
use super::KafkaProducerTrait;

/// Shared label values for metrics emitted within a single `publish_batch` call.
/// All fields are `&'static str` (zero-cost) or `SharedString` (Arc-based, so
/// `.clone()` is a refcount bump rather than a heap allocation).
struct MetricLabels {
    sink: &'static str,
    mode: &'static str,
    path: metrics::SharedString,
    attempt: metrics::SharedString,
}

pub struct KafkaSink<P: KafkaProducerTrait> {
    name: SinkName,
    producer: Arc<P>,
    config: Config,
    capture_mode: CaptureMode,
    handle: lifecycle::Handle,
}

impl<P: KafkaProducerTrait> KafkaSink<P> {
    pub fn new(
        name: SinkName,
        producer: Arc<P>,
        config: Config,
        capture_mode: CaptureMode,
        handle: lifecycle::Handle,
    ) -> Self {
        Self {
            name,
            producer,
            config,
            capture_mode,
            handle,
        }
    }
}

/// Reject every publishable event in `events` as `SinkUnavailable`,
/// incrementing a single counter for the batch.
fn reject_publishable(
    events: &[&(dyn Event + Send + Sync)],
    labels: &MetricLabels,
) -> Vec<Box<dyn SinkResult>> {
    let enqueued_at = Utc::now();
    let publishable: Vec<_> = events.iter().filter(|e| e.should_publish()).collect();
    counter!(
        "capture_v1_kafka_publish_total",
        "mode" => labels.mode,
        "cluster" => labels.sink,
        "outcome" => Outcome::RetriableError.as_tag(),
        "path" => labels.path.clone(),
        "attempt" => labels.attempt.clone(),
    )
    .increment(publishable.len() as u64);
    publishable
        .into_iter()
        .map(|e| -> Box<dyn SinkResult> {
            Box::new(KafkaResult::err(
                e.uuid(),
                KafkaSinkError::SinkUnavailable,
                enqueued_at,
            ))
        })
        .collect()
}

type AckFuture = Pin<
    Box<
        dyn Future<
                Output = (
                    Uuid,
                    DateTime<Utc>,
                    Result<(), super::producer::ProduceError>,
                ),
            > + Send,
    >,
>;

impl<P: KafkaProducerTrait + 'static> KafkaSink<P> {
    /// Phase 1: serialize and enqueue events to the producer sequentially,
    /// preserving per-partition ordering. Returns early results for
    /// serialization / send failures and collects ack futures for events
    /// that were successfully enqueued.
    #[allow(clippy::too_many_arguments)]
    async fn enqueue_events(
        &self,
        ctx: &Context,
        events: &[&(dyn Event + Send + Sync)],
        labels: &MetricLabels,
        enqueued_at: DateTime<Utc>,
        results: &mut Vec<Box<dyn SinkResult>>,
        pending: &mut FuturesUnordered<AckFuture>,
        enqueued_keys: &mut Vec<Uuid>,
    ) {
        let mut payload_buf = String::with_capacity(4096);
        let mut key_buf = String::with_capacity(128);

        for event in events {
            if !event.should_publish() {
                continue;
            }

            let uuid = event.uuid();

            let topic = match self.config.kafka.topic_for(event.destination()) {
                Some(t) => t,
                None => continue,
            };

            payload_buf.clear();
            if let Err(e) = event.serialize_into(ctx, &mut payload_buf) {
                crate::ctx_log!(
                    Level::ERROR,
                    ctx,
                    sink = labels.sink,
                    event_uuid = %uuid,
                    error = %e,
                    "event serialization failed, dropping event"
                );
                counter!(
                    "capture_v1_kafka_publish_total",
                    "mode" => labels.mode,
                    "cluster" => labels.sink,
                    "outcome" => Outcome::FatalError.as_tag(),
                    "path" => labels.path.clone(),
                    "attempt" => labels.attempt.clone(),
                )
                .increment(1);
                results.push(Box::new(KafkaResult::err(
                    uuid,
                    KafkaSinkError::SerializationFailed(format!("{e:#}")),
                    enqueued_at,
                )));
                continue;
            }

            let headers: rdkafka::message::OwnedHeaders = event.headers(ctx).into();

            key_buf.clear();
            let key = event.partition_key(ctx, &mut key_buf);

            let mut record = ProduceRecord {
                topic,
                key,
                payload: &payload_buf,
                headers,
            };

            let enqueue_retry_max = self.config.kafka.enqueue_retry_max;
            let enqueue_poll = Duration::from_millis(self.config.kafka.enqueue_poll_ms as u64);
            let mut hit_queue_full = false;

            for enqueue_attempt in 0..=enqueue_retry_max {
                if enqueue_attempt > 0 {
                    tokio::time::sleep(enqueue_poll).await;
                }

                match self.producer.send(record) {
                    Ok(ack_future) => {
                        if hit_queue_full {
                            counter!(
                                "capture_v1_kafka_queue_full_retries_total",
                                "mode" => labels.mode,
                                "cluster" => labels.sink,
                                "result" => "recovered",
                            )
                            .increment(1);
                        }
                        enqueued_keys.push(uuid);
                        pending.push(Box::pin(async move {
                            let result = ack_future.await;
                            (uuid, Utc::now(), result)
                        }));
                        break;
                    }
                    Err((e, returned_record))
                        if e.is_queue_full() && enqueue_attempt < enqueue_retry_max =>
                    {
                        hit_queue_full = true;
                        record = returned_record;
                        continue;
                    }
                    Err((e, _)) => {
                        if hit_queue_full || e.is_queue_full() {
                            counter!(
                                "capture_v1_kafka_queue_full_retries_total",
                                "mode" => labels.mode,
                                "cluster" => labels.sink,
                                "result" => "exhausted",
                            )
                            .increment(1);
                        }
                        let sink_err = KafkaSinkError::Produce(e);
                        let outcome = sink_err.outcome();
                        counter!(
                            "capture_v1_kafka_publish_total",
                            "mode" => labels.mode,
                            "cluster" => labels.sink,
                            "outcome" => outcome.as_tag(),
                            "path" => labels.path.clone(),
                            "attempt" => labels.attempt.clone(),
                        )
                        .increment(1);
                        results.push(Box::new(KafkaResult::err(uuid, sink_err, enqueued_at)));
                        break;
                    }
                }
            }
        }
    }

    /// Phase 2: drain ack futures with a per-sink deadline. Dropping remaining
    /// futures on timeout is safe — the underlying DeliveryFuture is a
    /// oneshot::Receiver; dropping it just means rdkafka's delivery callback
    /// send() returns Err (silently ignored). The message still completes in
    /// librdkafka (or times out via message.timeout.ms).
    async fn drain_acks(
        &self,
        labels: &MetricLabels,
        enqueued_at: DateTime<Utc>,
        results: &mut Vec<Box<dyn SinkResult>>,
        pending: &mut FuturesUnordered<AckFuture>,
    ) -> HashSet<Uuid> {
        let deadline = tokio::time::Instant::now() + self.config.produce_timeout;
        let mut resolved_keys: HashSet<Uuid> = HashSet::new();

        loop {
            match tokio::time::timeout_at(deadline, pending.next()).await {
                Ok(Some((uuid, completed_at, ack))) => {
                    resolved_keys.insert(uuid);
                    match ack {
                        Ok(()) => {
                            counter!(
                                "capture_v1_kafka_publish_total",
                                "mode" => labels.mode,
                                "cluster" => labels.sink,
                                "outcome" => Outcome::Success.as_tag(),
                                "path" => labels.path.clone(),
                                "attempt" => labels.attempt.clone(),
                            )
                            .increment(1);
                            let elapsed = completed_at.signed_duration_since(enqueued_at);
                            if let Ok(secs) = elapsed.to_std() {
                                histogram!(
                                    "capture_v1_kafka_ack_duration_seconds",
                                    "mode" => labels.mode,
                                    "cluster" => labels.sink,
                                    "outcome" => Outcome::Success.as_tag(),
                                    "path" => labels.path.clone(),
                                    "attempt" => labels.attempt.clone(),
                                )
                                .record(secs.as_secs_f64());
                            }
                            results.push(Box::new(
                                KafkaResult::ok(uuid, enqueued_at).with_completed_at(completed_at),
                            ));
                        }
                        Err(e) => {
                            let sink_err = KafkaSinkError::Produce(e);
                            let outcome = sink_err.outcome();
                            counter!(
                                "capture_v1_kafka_publish_total",
                                "mode" => labels.mode,
                                "cluster" => labels.sink,
                                "outcome" => outcome.as_tag(),
                                "path" => labels.path.clone(),
                                "attempt" => labels.attempt.clone(),
                            )
                            .increment(1);
                            results.push(Box::new(
                                KafkaResult::err(uuid, sink_err, enqueued_at)
                                    .with_completed_at(completed_at),
                            ));
                        }
                    }
                }
                Ok(None) => break,
                Err(_) => break,
            }
        }
        resolved_keys
    }

    /// Phase 3: identify enqueued events whose acks were not resolved before
    /// the deadline and emit timeout results.
    fn collect_timeouts(
        labels: &MetricLabels,
        enqueued_at: DateTime<Utc>,
        enqueued_keys: Vec<Uuid>,
        resolved_keys: &HashSet<Uuid>,
        results: &mut Vec<Box<dyn SinkResult>>,
    ) {
        let timed_out_keys: Vec<_> = enqueued_keys
            .into_iter()
            .filter(|k| !resolved_keys.contains(k))
            .collect();
        if timed_out_keys.is_empty() {
            return;
        }
        counter!(
            "capture_v1_kafka_publish_total",
            "mode" => labels.mode,
            "cluster" => labels.sink,
            "outcome" => Outcome::Timeout.as_tag(),
            "path" => labels.path.clone(),
            "attempt" => labels.attempt.clone(),
        )
        .increment(timed_out_keys.len() as u64);
        let gave_up_at = Utc::now();
        for uuid in timed_out_keys {
            results.push(Box::new(
                KafkaResult::err(uuid, KafkaSinkError::Timeout, enqueued_at)
                    .with_completed_at(gave_up_at),
            ));
        }
    }
}

#[async_trait]
impl<P: KafkaProducerTrait + 'static> Sink for KafkaSink<P> {
    fn name(&self) -> SinkName {
        self.name
    }

    async fn publish_batch(
        &self,
        ctx: &Context,
        events: &[&(dyn Event + Send + Sync)],
    ) -> Vec<Box<dyn SinkResult>> {
        let labels = MetricLabels {
            sink: self.name.as_str(),
            mode: self.capture_mode.as_tag(),
            path: ctx.path.clone().into(),
            attempt: ctx.attempt.to_string().into(),
        };

        if !self.producer.is_ready() {
            crate::ctx_log!(
                Level::ERROR,
                ctx,
                sink = labels.sink,
                mode = labels.mode,
                "producer not ready — rejecting batch"
            );
            return reject_publishable(events, &labels);
        }

        let enqueued_at = Utc::now();
        let mut results: Vec<Box<dyn SinkResult>> = Vec::new();
        let mut pending: FuturesUnordered<AckFuture> = FuturesUnordered::new();
        let mut enqueued_keys: Vec<Uuid> = Vec::new();

        self.enqueue_events(
            ctx,
            events,
            &labels,
            enqueued_at,
            &mut results,
            &mut pending,
            &mut enqueued_keys,
        )
        .await;

        let resolved_keys = self
            .drain_acks(&labels, enqueued_at, &mut results, &mut pending)
            .await;

        Self::collect_timeouts(
            &labels,
            enqueued_at,
            enqueued_keys,
            &resolved_keys,
            &mut results,
        );

        let summary = BatchSummary::from_results(&results);
        if summary.all_ok() {
            crate::ctx_log!(Level::DEBUG, ctx,
                sink = labels.sink,
                mode = labels.mode,
                %summary,
                "batch published");
        } else if summary.succeeded == 0 {
            crate::ctx_log!(Level::ERROR, ctx,
                sink = labels.sink,
                mode = labels.mode,
                %summary,
                errors = ?summary.errors,
                "batch fully failed");
        } else {
            crate::ctx_log!(Level::WARN, ctx,
                sink = labels.sink,
                mode = labels.mode,
                %summary,
                errors = ?summary.errors,
                "batch partially failed");
        }
        for (tag, count) in &summary.errors {
            counter!(
                "capture_v1_kafka_produce_errors_total",
                "cluster" => labels.sink,
                "mode" => labels.mode,
                "error" => *tag
            )
            .increment(*count as u64);
        }

        if summary.succeeded > 0 {
            self.handle.report_healthy();
        }
        results
    }

    async fn flush(&self) -> anyhow::Result<()> {
        let timeout = self.config.produce_timeout;
        let producer = self.producer.clone();
        let name_str = self.name.as_str();
        tokio::task::spawn_blocking(move || {
            producer
                .flush(timeout)
                .map_err(|e| anyhow::anyhow!("{name_str}: flush error: {e:#}"))
        })
        .await
        .map_err(|e| anyhow::anyhow!("flush task panicked: {e:#}"))?
    }
}
