use std::collections::HashSet;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use futures::stream::FuturesUnordered;
use futures::StreamExt;
use metrics::{counter, histogram};
use tracing::Level;
use uuid::Uuid;

use crate::config::CaptureMode;
use crate::v1::context::RequestContext;
use crate::v1::sinks::sink::Sink;
use crate::v1::sinks::types::{BatchSummary, Destination, Outcome, PreparedEvent, SinkResult};
use crate::v1::sinks::{Config, SinkName};

use super::constants::*;
use super::producer::ProduceRecord;
use super::types::{KafkaResult, KafkaSinkError};
use super::KafkaProducerTrait;

/// Returns true when the partition key should be nulled — i.e. when person
/// processing is force-disabled for Main/Overflow destinations, spreading
/// load across partitions instead of hotspotting on a single key.
fn should_null_partition_key(
    force_disable_person_processing: bool,
    destination: &Destination,
) -> bool {
    force_disable_person_processing
        && matches!(
            destination,
            Destination::AnalyticsMain | Destination::Overflow
        )
}

/// Shared label values for metrics emitted within a single `publish_batch` call.
struct MetricLabels {
    sink: &'static str,
    mode: &'static str,
    path: &'static str,
    attempt: &'static str,
}

/// Map the client-controlled attempt number to a bounded static label value.
/// Attempts 0-5 map to themselves; 6 or more bucket into "6+" as a
/// cardinality defense (the label reads literally: "6 or more").
fn attempt_tag(attempt: u32) -> &'static str {
    match attempt {
        0 => "0",
        1 => "1",
        2 => "2",
        3 => "3",
        4 => "4",
        5 => "5",
        _ => "6+",
    }
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

/// Reject every event in `events` as `SinkUnavailable`, incrementing a single
/// counter per destination for the batch. Inputs are already serialized and
/// publishable (non-publishable events never reach a sink).
fn reject_all(events: &[PreparedEvent], labels: &MetricLabels) -> Vec<Box<dyn SinkResult>> {
    let enqueued_at = Utc::now();
    let mut by_dest: std::collections::HashMap<&'static str, u64> =
        std::collections::HashMap::new();
    for e in events {
        *by_dest.entry(e.destination.as_tag()).or_default() += 1;
    }
    for (dest_tag, count) in &by_dest {
        counter!(
            KAFKA_PUBLISH_TOTAL,
            "mode" => labels.mode,
            "cluster" => labels.sink,
            "outcome" => Outcome::RetriableError.as_tag(),
            "path" => labels.path,
            "attempt" => labels.attempt,
            "destination" => *dest_tag,
        )
        .increment(*count);
    }
    events
        .iter()
        .map(|e| -> Box<dyn SinkResult> {
            Box::new(KafkaResult::err(
                e.uuid,
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
                    &'static str,
                    DateTime<Utc>,
                    Duration,
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
    async fn enqueue_events(
        &self,
        events: &[PreparedEvent],
        labels: &MetricLabels,
        enqueued_at: DateTime<Utc>,
        results: &mut Vec<Box<dyn SinkResult>>,
        pending: &mut FuturesUnordered<AckFuture>,
        enqueued_keys: &mut Vec<(Uuid, &'static str, Instant)>,
    ) {
        for event in events {
            let uuid = event.uuid;
            let dest_tag = event.destination.as_tag();

            let topic = match self.config.kafka.topic_for(&event.destination) {
                Some(t) => t,
                None => continue,
            };

            let key = if should_null_partition_key(
                event
                    .headers
                    .force_disable_person_processing
                    .unwrap_or(false),
                &event.destination,
            ) {
                None
            } else {
                Some(event.partition_key.as_str())
            };

            let headers: rdkafka::message::OwnedHeaders = event.headers.clone().into();

            let record = ProduceRecord {
                topic,
                key,
                payload: event.payload.as_ref(),
                headers,
            };

            match self.producer.send(record) {
                Ok(ack_future) => {
                    let sent_at = Instant::now();
                    enqueued_keys.push((uuid, dest_tag, sent_at));
                    pending.push(Box::pin(async move {
                        let result = ack_future.await;
                        let ack_latency = sent_at.elapsed();
                        (uuid, dest_tag, Utc::now(), ack_latency, result)
                    }));
                }
                Err((e, _)) => {
                    let sink_err = KafkaSinkError::Produce(e);
                    let outcome = sink_err.outcome();
                    counter!(
                        KAFKA_PUBLISH_TOTAL,
                        "mode" => labels.mode,
                        "cluster" => labels.sink,
                        "outcome" => outcome.as_tag(),
                        "path" => labels.path,
                        "attempt" => labels.attempt,
                        "destination" => dest_tag,
                    )
                    .increment(1);
                    results.push(Box::new(KafkaResult::err(uuid, sink_err, enqueued_at)));
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
                Ok(Some((uuid, dest_tag, completed_at, ack_latency, ack))) => {
                    resolved_keys.insert(uuid);

                    let outcome_tag = match &ack {
                        Ok(()) => Outcome::Success.as_tag(),
                        Err(e) => {
                            if e.is_retriable() {
                                Outcome::RetriableError.as_tag()
                            } else {
                                Outcome::FatalError.as_tag()
                            }
                        }
                    };

                    counter!(
                        KAFKA_PUBLISH_TOTAL,
                        "mode" => labels.mode,
                        "cluster" => labels.sink,
                        "outcome" => outcome_tag,
                        "path" => labels.path,
                        "attempt" => labels.attempt,
                        "destination" => dest_tag,
                    )
                    .increment(1);

                    // Per-event broker-ack latency (send → ack), isolated from
                    // batch enqueue wall-time.
                    histogram!(
                        KAFKA_ACK_DURATION_SECONDS,
                        "mode" => labels.mode,
                        "cluster" => labels.sink,
                        "outcome" => outcome_tag,
                        "path" => labels.path,
                        "attempt" => labels.attempt,
                        "destination" => dest_tag,
                    )
                    .record(ack_latency.as_secs_f64());

                    match ack {
                        Ok(()) => results.push(Box::new(
                            KafkaResult::ok(uuid, enqueued_at).with_completed_at(completed_at),
                        )),
                        Err(e) => results.push(Box::new(
                            KafkaResult::err(uuid, KafkaSinkError::Produce(e), enqueued_at)
                                .with_completed_at(completed_at),
                        )),
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
        enqueued_keys: Vec<(Uuid, &'static str, Instant)>,
        resolved_keys: &HashSet<Uuid>,
        results: &mut Vec<Box<dyn SinkResult>>,
    ) {
        let timed_out: Vec<_> = enqueued_keys
            .into_iter()
            .filter(|(k, _, _)| !resolved_keys.contains(k))
            .collect();
        if timed_out.is_empty() {
            return;
        }
        let mut by_dest: std::collections::HashMap<&'static str, u64> =
            std::collections::HashMap::new();
        for (_, dest_tag, _) in &timed_out {
            *by_dest.entry(dest_tag).or_default() += 1;
        }
        for (dest_tag, count) in &by_dest {
            counter!(
                KAFKA_PUBLISH_TOTAL,
                "mode" => labels.mode,
                "cluster" => labels.sink,
                "outcome" => Outcome::Timeout.as_tag(),
                "path" => labels.path,
                "attempt" => labels.attempt,
                "destination" => *dest_tag,
            )
            .increment(*count);
        }
        let gave_up_at = Utc::now();
        for (uuid, dest_tag, sent_at) in timed_out {
            // Record timed-out acks so the latency tail (>= produce_timeout)
            // is visible rather than silently dropped.
            histogram!(
                KAFKA_ACK_DURATION_SECONDS,
                "mode" => labels.mode,
                "cluster" => labels.sink,
                "outcome" => Outcome::Timeout.as_tag(),
                "path" => labels.path,
                "attempt" => labels.attempt,
                "destination" => dest_tag,
            )
            .record(sent_at.elapsed().as_secs_f64());
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
        ctx: &RequestContext,
        events: &[PreparedEvent],
    ) -> Vec<Box<dyn SinkResult>> {
        let labels = MetricLabels {
            sink: self.name.as_str(),
            mode: self.capture_mode.as_tag(),
            path: ctx.path,
            attempt: attempt_tag(ctx.attempt),
        };

        if !self.producer.is_ready() {
            crate::ctx_log!(
                Level::ERROR,
                ctx,
                sink = labels.sink,
                mode = labels.mode,
                "producer not ready — rejecting batch"
            );
            return reject_all(events, &labels);
        }

        let enqueued_at = Utc::now();
        let mut results: Vec<Box<dyn SinkResult>> = Vec::new();
        let mut pending: FuturesUnordered<AckFuture> = FuturesUnordered::new();
        let mut enqueued_keys: Vec<(Uuid, &'static str, Instant)> = Vec::new();

        // Enqueue wall-time, isolated from per-event broker-ack latency.
        let enqueue_start = Instant::now();
        self.enqueue_events(
            events,
            &labels,
            enqueued_at,
            &mut results,
            &mut pending,
            &mut enqueued_keys,
        )
        .await;
        histogram!(
            KAFKA_ENQUEUE_DURATION_SECONDS,
            "mode" => labels.mode,
            "cluster" => labels.sink,
            "path" => labels.path,
            "attempt" => labels.attempt,
        )
        .record(enqueue_start.elapsed().as_secs_f64());

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
                KAFKA_PRODUCE_ERRORS_TOTAL,
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

#[cfg(test)]
mod should_null_partition_key_tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case::main_disabled(true, Destination::AnalyticsMain, true)]
    #[case::overflow_disabled(true, Destination::Overflow, true)]
    #[case::dlq_disabled(true, Destination::Dlq, false)]
    #[case::historical_disabled(true, Destination::AnalyticsHistorical, false)]
    #[case::custom_disabled(true, Destination::Custom("t".into()), false)]
    #[case::main_not_disabled(false, Destination::AnalyticsMain, false)]
    fn policy(#[case] force_disable: bool, #[case] dest: Destination, #[case] expected: bool) {
        assert_eq!(should_null_partition_key(force_disable, &dest), expected);
    }
}

#[cfg(test)]
mod attempt_tag_tests {
    use super::attempt_tag;

    #[test]
    fn maps_in_range_attempts_to_exact_values() {
        assert_eq!(attempt_tag(0), "0");
        assert_eq!(attempt_tag(1), "1");
        assert_eq!(attempt_tag(2), "2");
        assert_eq!(attempt_tag(3), "3");
        assert_eq!(attempt_tag(4), "4");
        assert_eq!(attempt_tag(5), "5");
    }

    #[test]
    fn caps_out_of_range_attempts() {
        assert_eq!(attempt_tag(6), "6+");
        assert_eq!(attempt_tag(100), "6+");
        assert_eq!(attempt_tag(u32::MAX), "6+");
    }
}
