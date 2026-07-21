//! Split sink: routes each AI capture event to either the primary or a
//! secondary sink based on the configured `AiSinkMode` (and token allowlist).
//!
//! Composes two `Event` sinks behind the `Event` trait — the same pattern as
//! `FallbackSink` — but selects a destination per event instead of failing
//! over. Used to migrate AI ingestion to a secondary cluster (e.g. WarpStream)
//! gradually: allowlist a few tokens, then cut everything over. The routing
//! policy lives in `AiSinkMode::routes_to_secondary`; this sink only dispatches.

use std::sync::Arc;

use async_trait::async_trait;
use metrics::counter;

use crate::api::CaptureError;
use crate::config::AiRouting;
use crate::sinks::sink::{PreparedRecord, Sink, SinkResult};
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

/// Routes events between a primary and secondary sink per the `AiRouting` policy.
pub struct SplitKafkaSink {
    primary: Arc<dyn Event + Send + Sync>,
    secondary: Arc<dyn Event + Send + Sync>,
    routing: AiRouting,
}

impl SplitKafkaSink {
    pub fn new(
        primary: Arc<dyn Event + Send + Sync>,
        secondary: Arc<dyn Event + Send + Sync>,
        routing: AiRouting,
    ) -> Self {
        Self {
            primary,
            secondary,
            routing,
        }
    }

    fn routes_to_secondary(&self, event: &ProcessedEvent) -> bool {
        self.routing.routes_to_secondary(&event.event.token)
    }

    /// Sink-path variant: route by the token header carried on a prepared
    /// record. `to_headers()` always stamps the token, so this recovers the
    /// same routing decision `routes_to_secondary` makes on a `ProcessedEvent`.
    fn record_routes_to_secondary(&self, record: &PreparedRecord) -> bool {
        record
            .record
            .headers
            .token
            .as_deref()
            .map(|token| self.routing.routes_to_secondary(token))
            .unwrap_or(false)
    }
}

#[async_trait]
impl Event for SplitKafkaSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        if self.routes_to_secondary(&event) {
            counter!("capture_split_sink_selected", "cluster" => "secondary").increment(1);
            self.secondary.send(event).await
        } else {
            counter!("capture_split_sink_selected", "cluster" => "primary").increment(1);
            self.primary.send(event).await
        }
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        // Partition by destination, preserving per-destination order. The common
        // case (every event routes the same way — e.g. a single-token batch in
        // full-secondary mode) leaves one Vec empty and forwards the other whole.
        let mut primary: Vec<ProcessedEvent> = Vec::new();
        let mut secondary: Vec<ProcessedEvent> = Vec::new();
        for event in events {
            if self.routes_to_secondary(&event) {
                secondary.push(event);
            } else {
                primary.push(event);
            }
        }

        counter!("capture_split_sink_selected", "cluster" => "primary")
            .increment(primary.len() as u64);
        counter!("capture_split_sink_selected", "cluster" => "secondary")
            .increment(secondary.len() as u64);

        // A batch is built from a single request, so every event carries the
        // same request-level token (see `events::analytics` / `otel`). Routing is
        // token-based, so today one of these partitions is always empty and the
        // whole batch goes to a single cluster — the both-non-empty arm below is
        // defensive against a future multi-token batch path, not a hot path.
        match (primary.is_empty(), secondary.is_empty()) {
            (false, true) => self.primary.send_batch(primary).await,
            (true, false) => self.secondary.send_batch(secondary).await,
            (false, false) => {
                // Cross-destination ordering is irrelevant (separate clusters);
                // send concurrently and fail if either fails. Caveat for the day
                // this arm goes live: failing the whole batch makes the caller
                // retry both partitions, duplicating events the healthy cluster
                // already accepted. Avoiding that needs partial-batch retry, which
                // the `Event` contract (one Result per batch) can't express.
                let (p, s) = tokio::join!(
                    self.primary.send_batch(primary),
                    self.secondary.send_batch(secondary),
                );
                p.and(s)
            }
            (true, true) => Ok(()),
        }
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        // Disambiguate: `dyn Event` now carries both `Event::flush` and its
        // `Sink::flush` supertrait method.
        Sink::flush(&*self.primary)?;
        Sink::flush(&*self.secondary)?;
        Ok(())
    }
}

/// Sink-path split: mirrors the [`Event`] impl above so a call site that
/// publishes through the unified [`Sink`] (the analytics pipeline) keeps the
/// same per-token routing. The two clusters use different topics, so each
/// partition must be serialized by its own inner sink in `prepare`;
/// `publish_batch` then routes each prepared record back to the same cluster by
/// its token header. Inner sinks are already `Sink`-backed.
#[async_trait]
impl Sink for SplitKafkaSink {
    async fn prepare(
        &self,
        events: Vec<ProcessedEvent>,
    ) -> Result<Vec<PreparedRecord>, CaptureError> {
        let mut primary_events: Vec<ProcessedEvent> = Vec::new();
        let mut secondary_events: Vec<ProcessedEvent> = Vec::new();
        for event in events {
            if self.routes_to_secondary(&event) {
                secondary_events.push(event);
            } else {
                primary_events.push(event);
            }
        }

        // Prep is fail-fast (a single error aborts the whole batch), so prepare
        // the primary partition first and only touch the secondary if it clears.
        let mut prepared: Vec<PreparedRecord> = Vec::new();
        if !primary_events.is_empty() {
            prepared.extend(self.primary.prepare(primary_events).await?);
        }
        if !secondary_events.is_empty() {
            prepared.extend(self.secondary.prepare(secondary_events).await?);
        }
        Ok(prepared)
    }

    async fn publish_batch(&self, prepared: Vec<PreparedRecord>) -> Vec<SinkResult> {
        let mut primary: Vec<PreparedRecord> = Vec::new();
        let mut secondary: Vec<PreparedRecord> = Vec::new();
        for record in prepared {
            if self.record_routes_to_secondary(&record) {
                secondary.push(record);
            } else {
                primary.push(record);
            }
        }

        counter!("capture_split_sink_selected", "cluster" => "primary")
            .increment(primary.len() as u64);
        counter!("capture_split_sink_selected", "cluster" => "secondary")
            .increment(secondary.len() as u64);

        // A batch is built from a single request and routing is token-based, so
        // today one partition is always empty and the whole batch goes to one
        // cluster; the both-non-empty arm is defensive against a future
        // multi-token batch path, matching the `Event` impl above.
        match (primary.is_empty(), secondary.is_empty()) {
            (false, true) => self.primary.publish_batch(primary).await,
            (true, false) => self.secondary.publish_batch(secondary).await,
            (false, false) => {
                let (mut p, s) = tokio::join!(
                    self.primary.publish_batch(primary),
                    self.secondary.publish_batch(secondary),
                );
                p.extend(s);
                p
            }
            (true, true) => Vec::new(),
        }
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        // Disambiguate: `dyn Event` now carries both `Event::flush` and its
        // `Sink::flush` supertrait method.
        Sink::flush(&*self.primary)?;
        Sink::flush(&*self.secondary)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sinks::test_sink::MockSink;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;

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
                event: "$ai_generation".to_string(),
                timestamp,
                is_cookieless_mode: false,
                historical_migration: false,
            },
            metadata: ProcessedEventMetadata {
                data_type: DataType::AnalyticsMain,
                session_id: None,
                computed_timestamp: None,
                event_name: "$ai_generation".to_string(),
                force_overflow: false,
                skip_person_processing: false,
                redirect_to_dlq: false,
                redirect_to_topic: None,
                skip_heatmap_processing: false,
                overflow_reason: None,
            },
        }
    }

    fn split_sink(allowed: &[&str]) -> (SplitKafkaSink, MockSink, MockSink) {
        let primary = MockSink::new();
        let secondary = MockSink::new();
        let allowlist = allowed.iter().map(|s| s.to_string()).collect();
        let sink = SplitKafkaSink::new(
            Arc::new(primary.clone()),
            Arc::new(secondary.clone()),
            AiRouting::SecondaryAllowlist(allowlist),
        );
        (sink, primary, secondary)
    }

    fn tokens(sink: &MockSink) -> Vec<String> {
        sink.get_events()
            .iter()
            .map(|e| e.event.token.clone())
            .collect()
    }

    #[tokio::test]
    async fn routes_single_event_by_allowlist() {
        let (sink, primary, secondary) = split_sink(&["secondary_tok"]);

        sink.send(event_with_token("secondary_tok")).await.unwrap();
        sink.send(event_with_token("other")).await.unwrap();

        assert_eq!(tokens(&secondary), vec!["secondary_tok"]);
        assert_eq!(tokens(&primary), vec!["other"]);
    }

    #[tokio::test]
    async fn batch_partitions_across_sinks_preserving_order() {
        let (sink, primary, secondary) = split_sink(&["sec_1", "sec_2"]);

        sink.send_batch(vec![
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

    /// The `Sink` path (used by the analytics pipeline after Step 6) must split
    /// by the same per-token policy as the `Event` path: each event is prepared
    /// by its destination's inner sink and published back to that same cluster.
    #[tokio::test]
    async fn sink_path_partitions_across_sinks_by_token() {
        let (sink, primary, secondary) = split_sink(&["sec_1", "sec_2"]);

        let prepared = Sink::prepare(
            &sink,
            vec![
                event_with_token("sec_1"),
                event_with_token("pri_1"),
                event_with_token("sec_2"),
                event_with_token("pri_2"),
            ],
        )
        .await
        .unwrap();
        let results = sink.publish_batch(prepared).await;

        // Every prepared record acks, and each partition was serialized by its
        // own inner sink (MockSink captures in `prepare`).
        assert_eq!(results.len(), 4);
        assert!(results.iter().all(|r| r.result.is_ok()));
        assert_eq!(tokens(&secondary), vec!["sec_1", "sec_2"]);
        assert_eq!(tokens(&primary), vec!["pri_1", "pri_2"]);
    }
}
