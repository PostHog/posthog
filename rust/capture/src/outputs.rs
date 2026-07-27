//! The outputs layer: the produce surface a pipeline publishes through.
//!
//! An [`Output`] owns one or more targets and the **policy** that picks
//! between them per batch. All multi-target behavior lives here and only
//! here — a sink is always a single backend; anything that picks between
//! sinks is an output policy:
//!
//! - single — one backend.
//! - failover — health-gated primary/secondary (Kafka → S3 today): skip the
//!   primary while its advisory handle reports unhealthy, and re-publish the
//!   batch to the secondary on a retriable failure.
//! - split — token-routed primary/secondary (the AI → secondary cluster
//!   migration): each event publishes through exactly one target.
//!
//! Targets are outputs themselves, so policies compose the way the old sink
//! composites did (e.g. split over a failover pair). Leaves drive the full
//! dance internally — lane resolution, serialization, and topic assembly via
//! the backend's prep path, then the mechanism publish — so no caller ever
//! sees a two-phase protocol.
//!
//! This is capture's version of the Node.js `IngestionOutputs` model: steps
//! publish to an output; producer selection, topic resolution, and
//! multi-target routing are the output's business, configured at boot.
//!
//! [`OutputTable`] is the handle the router state holds: the
//! `(pipeline, lane)` → output mapping. Every address resolves to the one
//! deployment-wide output today (per-lane topics still resolve inside the
//! prep path via the `OutputRegistry`); the table is where per-address
//! wiring lands when the first config needs it.

use std::sync::Arc;

use async_trait::async_trait;
use metrics::{counter, gauge, histogram};
use tracing::instrument;
use tracing::log::error;

use crate::api::CaptureError;
use crate::config::AiRouting;
use crate::sinks::sink::{fold_results, Prepare};
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

/// A produce destination: a single backend, or a policy composing two of them.
/// The representation is private — construction happens at boot in `setup`,
/// and nothing outside this crate builds or inspects one.
pub struct Output {
    repr: Repr,
}

enum Repr {
    Single {
        sink: Arc<dyn Prepare>,
    },
    /// Health-gated failover, Kafka primary / S3 secondary today. Publishes
    /// to the primary and re-publishes the batch to the secondary on a
    /// retriable failure; skips the primary entirely while the advisory
    /// lifecycle handle reports it unhealthy. Fatal errors are the event's
    /// fault and never fail over.
    Failover {
        primary: Box<Output>,
        secondary: Box<Output>,
        advisory_handle: Option<lifecycle::Handle>,
    },
    /// Token-routed split, primary cluster / secondary cluster (e.g.
    /// WarpStream) today. Routing is decided per event before any prep, so
    /// each partition resolves topics and serializes through its own target.
    Split {
        primary: Box<Output>,
        secondary: Box<Output>,
        routing: AiRouting,
    },
}

impl Output {
    pub fn single(sink: Arc<dyn Prepare>) -> Self {
        Output {
            repr: Repr::Single { sink },
        }
    }

    pub fn failover(
        primary: Output,
        secondary: Output,
        advisory_handle: lifecycle::Handle,
    ) -> Self {
        gauge!("capture_primary_sink_health").set(1.0);
        Output {
            repr: Repr::Failover {
                primary: Box::new(primary),
                secondary: Box::new(secondary),
                advisory_handle: Some(advisory_handle),
            },
        }
    }

    /// Failover without an advisory handle: reactive only (used in tests).
    #[cfg(test)]
    pub(crate) fn failover_reactive(primary: Output, secondary: Output) -> Self {
        Output {
            repr: Repr::Failover {
                primary: Box::new(primary),
                secondary: Box::new(secondary),
                advisory_handle: None,
            },
        }
    }

    pub fn split(primary: Output, secondary: Output, routing: AiRouting) -> Self {
        Output {
            repr: Repr::Split {
                primary: Box::new(primary),
                secondary: Box::new(secondary),
                routing,
            },
        }
    }

    /// Publish a batch of processed events through this output, collapsing
    /// per-event results to today's whole-request response (first failure
    /// wins). Policies operate on events, before any prep, so each target
    /// resolves topics and serializes for itself.
    pub async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        match &self.repr {
            Repr::Single { sink } => {
                let prepared = sink.prepare_batch(events).await?;
                fold_results(sink.publish(prepared).await)
            }
            Repr::Failover {
                primary,
                secondary,
                advisory_handle,
            } => {
                let healthy = advisory_handle
                    .as_ref()
                    .map(|h| h.is_healthy())
                    .unwrap_or(true);
                gauge!("capture_primary_sink_health").set(if healthy { 1.0 } else { 0.0 });

                if !healthy {
                    counter!("capture_fallback_sink_failovers_total").increment(1);
                    return Box::pin(secondary.publish(events)).await;
                }

                match Box::pin(primary.publish(events.clone())).await {
                    Ok(()) => Ok(()),
                    Err(CaptureError::RetryableSinkError) => {
                        error!("Primary sink failed, falling back");
                        counter!("capture_fallback_sink_failovers_total").increment(1);
                        Box::pin(secondary.publish(events)).await
                    }
                    Err(e) => Err(e),
                }
            }
            Repr::Split {
                primary,
                secondary,
                routing,
            } => {
                // Partition by destination, preserving per-destination order.
                // The common case (every event routes the same way — e.g. a
                // single-token batch in full-secondary mode) leaves one Vec
                // empty and forwards the other whole.
                let mut to_primary: Vec<ProcessedEvent> = Vec::new();
                let mut to_secondary: Vec<ProcessedEvent> = Vec::new();
                for event in events {
                    if routing.routes_to_secondary(&event.event.token) {
                        to_secondary.push(event);
                    } else {
                        to_primary.push(event);
                    }
                }

                counter!("capture_split_sink_selected", "cluster" => "primary")
                    .increment(to_primary.len() as u64);
                counter!("capture_split_sink_selected", "cluster" => "secondary")
                    .increment(to_secondary.len() as u64);

                // A batch is built from a single request, so every event
                // carries the same request-level token and one partition is
                // always empty today; the both-non-empty arm is defensive
                // against a future multi-token batch path, not a hot path.
                match (to_primary.is_empty(), to_secondary.is_empty()) {
                    (false, true) => Box::pin(primary.publish(to_primary)).await,
                    (true, false) => Box::pin(secondary.publish(to_secondary)).await,
                    (false, false) => {
                        // Cross-destination ordering is irrelevant (separate
                        // clusters); publish concurrently and fail if either
                        // fails. Caveat for the day this arm goes live: failing
                        // the whole batch makes the caller retry both
                        // partitions, duplicating events the healthy cluster
                        // already accepted; avoiding that needs partial-batch
                        // retry, which the whole-request contract can't express.
                        let (p, s) = tokio::join!(
                            Box::pin(primary.publish(to_primary)),
                            Box::pin(secondary.publish(to_secondary)),
                        );
                        p.and(s)
                    }
                    (true, true) => Ok(()),
                }
            }
        }
    }

    /// Flush before shutdown. Failover flushes the primary only (matching the
    /// former `FallbackSink`); split flushes both clusters.
    pub fn flush(&self) -> Result<(), anyhow::Error> {
        match &self.repr {
            Repr::Single { sink } => sink.flush(),
            Repr::Failover { primary, .. } => primary.flush(),
            Repr::Split {
                primary, secondary, ..
            } => {
                primary.flush()?;
                secondary.flush()?;
                Ok(())
            }
        }
    }
}

/// The `(pipeline, lane)` → output mapping the router state holds. Every
/// address resolves to the one deployment-wide output today; per-lane topics
/// resolve inside the prep path via the `OutputRegistry`, whose boot-time
/// completeness check guarantees the addresses this deployment can produce
/// to are wired.
pub struct OutputTable {
    default: Output,
}

impl OutputTable {
    pub fn new(default: Output) -> Self {
        Self { default }
    }

    /// Publish a batch through the output its address resolves to.
    pub async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.default.publish(events).await
    }

    pub fn flush(&self) -> Result<(), anyhow::Error> {
        self.default.flush()
    }
}

/// Transitional facade: the v0 `Event` surface served by the outputs layer,
/// so call sites migrate to `OutputTable::publish` one commit at a time. The
/// batch-size histogram is recorded here — where the old sink impls recorded
/// it — and moves to the call sites as they migrate.
#[async_trait]
impl Event for OutputTable {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        histogram!("capture_event_batch_size").record(1.0);
        self.publish(vec![event]).await
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        histogram!("capture_event_batch_size").record(events.len() as f64);
        self.publish(events).await
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        OutputTable::flush(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sinks::test_sink::{FailSink, MockSink};
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::time::Duration;

    fn event_with_token(token: &str) -> ProcessedEvent {
        let timestamp = chrono::Utc::now();
        ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7_from_datetime(timestamp),
                distinct_id: "did".to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: "{}".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: token.to_string(),
                event: "test_event".to_string(),
                timestamp,
                is_cookieless_mode: false,
                historical_migration: false,
            },
            metadata: ProcessedEventMetadata {
                data_type: DataType::AnalyticsMain,
                session_id: None,
                computed_timestamp: None,
                event_name: "test_event".to_string(),
                force_overflow: false,
                skip_person_processing: false,
                redirect_to_dlq: false,
                redirect_to_topic: None,
                skip_heatmap_processing: false,
                overflow_reason: None,
            },
        }
    }

    fn tokens(sink: &MockSink) -> Vec<String> {
        sink.get_events()
            .iter()
            .map(|e| e.event.token.clone())
            .collect()
    }

    #[tokio::test]
    async fn failover_publishes_to_secondary_on_retriable_failure() {
        let secondary = MockSink::new();
        let output = Output::failover_reactive(
            Output::single(Arc::new(FailSink(CaptureError::RetryableSinkError))),
            Output::single(Arc::new(secondary.clone())),
        );

        output
            .publish(vec![event_with_token("tok")])
            .await
            .expect("failed to send event");
        output
            .publish(vec![event_with_token("tok"), event_with_token("tok")])
            .await
            .expect("failed to send batch");

        assert_eq!(secondary.get_events().len(), 3);
    }

    #[tokio::test]
    async fn failover_returns_error_when_both_fail() {
        let output = Output::failover_reactive(
            Output::single(Arc::new(FailSink(CaptureError::RetryableSinkError))),
            Output::single(Arc::new(FailSink(CaptureError::RetryableSinkError))),
        );

        assert!(matches!(
            output.publish(vec![event_with_token("tok")]).await,
            Err(CaptureError::RetryableSinkError)
        ));
        assert!(matches!(
            output
                .publish(vec![event_with_token("tok"), event_with_token("tok")])
                .await,
            Err(CaptureError::RetryableSinkError)
        ));
    }

    #[tokio::test]
    async fn failover_fatal_error_does_not_fail_over() {
        let secondary = MockSink::new();
        let output = Output::failover_reactive(
            Output::single(Arc::new(FailSink(CaptureError::NonRetryableSinkError))),
            Output::single(Arc::new(secondary.clone())),
        );

        assert!(matches!(
            output.publish(vec![event_with_token("tok")]).await,
            Err(CaptureError::NonRetryableSinkError)
        ));
        assert!(secondary.get_events().is_empty());
    }

    #[tokio::test]
    async fn advisory_handle_controls_primary_routing() {
        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_health_poll_interval(Duration::from_millis(50))
            .build();

        let kafka_handle = manager.register(
            "kafka-advisory",
            lifecycle::ComponentOptions::new()
                .with_liveness_deadline(Duration::from_millis(200))
                .is_advisory(true),
        );
        let _monitor = manager.monitor_background();

        let primary = MockSink::new();
        let secondary = MockSink::new();
        let output = Output::failover(
            Output::single(Arc::new(primary.clone())),
            Output::single(Arc::new(secondary.clone())),
            kafka_handle.clone(),
        );

        // Advisory handle starts healthy: publishes go to the primary.
        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        output.publish(vec![event_with_token("a")]).await.unwrap();
        assert_eq!(primary.get_events().len(), 1);
        assert!(secondary.get_events().is_empty());

        // Let the advisory deadline expire: publishes skip the primary.
        tokio::time::sleep(Duration::from_millis(400)).await;
        output.publish(vec![event_with_token("b")]).await.unwrap();
        assert_eq!(primary.get_events().len(), 1);
        assert_eq!(secondary.get_events().len(), 1);

        // Recovery: report healthy again and the primary serves once more.
        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        output.publish(vec![event_with_token("c")]).await.unwrap();
        assert_eq!(primary.get_events().len(), 2);
        assert_eq!(secondary.get_events().len(), 1);
    }

    #[tokio::test]
    async fn split_routes_single_event_by_allowlist() {
        let primary = MockSink::new();
        let secondary = MockSink::new();
        let output = Output::split(
            Output::single(Arc::new(primary.clone())),
            Output::single(Arc::new(secondary.clone())),
            AiRouting::SecondaryAllowlist(vec!["secondary_tok".to_string()].into_iter().collect()),
        );

        output
            .publish(vec![event_with_token("secondary_tok")])
            .await
            .unwrap();
        output
            .publish(vec![event_with_token("other")])
            .await
            .unwrap();

        assert_eq!(tokens(&secondary), vec!["secondary_tok"]);
        assert_eq!(tokens(&primary), vec!["other"]);
    }

    #[tokio::test]
    async fn split_batch_partitions_across_targets_preserving_order() {
        let primary = MockSink::new();
        let secondary = MockSink::new();
        let output = Output::split(
            Output::single(Arc::new(primary.clone())),
            Output::single(Arc::new(secondary.clone())),
            AiRouting::SecondaryAllowlist(
                vec!["sec_1".to_string(), "sec_2".to_string()]
                    .into_iter()
                    .collect(),
            ),
        );

        output
            .publish(vec![
                event_with_token("sec_1"),
                event_with_token("pri_1"),
                event_with_token("sec_2"),
                event_with_token("pri_2"),
            ])
            .await
            .unwrap();

        assert_eq!(tokens(&secondary), vec!["sec_1", "sec_2"]);
        assert_eq!(tokens(&primary), vec!["pri_1", "pri_2"]);
    }
}
