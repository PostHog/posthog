//! Policy surfaces: outputs implementations that pick between other outputs.
//!
//! A policy holds `Arc<dyn Outputs>` children, so it composes freely — a
//! split over a failover pair, a failover of two clusters, a table of
//! per-pipeline surfaces. Policies operate on events *before* any prep, so
//! each child resolves topics and serializes for itself (two clusters of a
//! pair can run different payload contracts during a migration).

use std::sync::Arc;

use async_trait::async_trait;
use metrics::{counter, gauge};
use tracing::log::error;

use crate::config::AiRouting;
use crate::failover::{AttemptOutcome, BreakerState, FailoverController, Route as FailoverRoute};
use crate::outputs::Outputs;
use crate::sinks::{Outcome, SinkResult};
use crate::v0_request::ProcessedEvent;

/// Health-gated failover, kafka primary / S3 secondary today. Publishes to
/// the primary and re-publishes the batch to the secondary on a retriable
/// failure; skips the primary entirely while the advisory lifecycle handle
/// reports it unhealthy. Fatal errors are the event's fault and never fail
/// over. With a controller, the circuit breaker drives autonomous
/// switchover and recovery probing on top of the reactive guarantee.
pub struct FailoverOutputs {
    primary: Arc<dyn Outputs>,
    secondary: Arc<dyn Outputs>,
    advisory_handle: Option<lifecycle::Handle>,
    /// Breaker-driven autonomous mode (dark-launched): `None` runs the
    /// reactive advisory mode.
    controller: Option<Arc<FailoverController>>,
}

impl FailoverOutputs {
    pub fn new(
        primary: Arc<dyn Outputs>,
        secondary: Arc<dyn Outputs>,
        advisory_handle: lifecycle::Handle,
    ) -> Self {
        gauge!("capture_primary_sink_health").set(1.0);
        Self {
            primary,
            secondary,
            advisory_handle: Some(advisory_handle),
            controller: None,
        }
    }

    /// Breaker-driven failover (dark-launched behind `CAPTURE_FAILOVER_ENABLED`):
    /// the same primary/secondary pair, with autonomous switchover and recovery
    /// probing driven by the controller's circuit breaker.
    pub fn with_breaker(
        primary: Arc<dyn Outputs>,
        secondary: Arc<dyn Outputs>,
        advisory_handle: lifecycle::Handle,
        controller: Arc<FailoverController>,
    ) -> Self {
        gauge!("capture_primary_sink_health").set(1.0);
        Self {
            primary,
            secondary,
            advisory_handle: Some(advisory_handle),
            controller: Some(controller),
        }
    }

    /// Failover without an advisory handle: reactive only (used in tests).
    #[cfg(test)]
    pub(crate) fn reactive(primary: Arc<dyn Outputs>, secondary: Arc<dyn Outputs>) -> Self {
        Self {
            primary,
            secondary,
            advisory_handle: None,
            controller: None,
        }
    }

    /// Breaker-driven failover without an advisory handle (used in tests to
    /// drive the breaker with a manual clock and scripted control plane).
    #[cfg(test)]
    pub(crate) fn breaker_for_tests(
        primary: Arc<dyn Outputs>,
        secondary: Arc<dyn Outputs>,
        controller: Arc<FailoverController>,
    ) -> Self {
        Self {
            primary,
            secondary,
            advisory_handle: None,
            controller: Some(controller),
        }
    }
}

#[async_trait]
impl Outputs for FailoverOutputs {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Vec<SinkResult> {
        let advisory_healthy = self
            .advisory_handle
            .as_ref()
            .map(|h| h.is_healthy())
            .unwrap_or(true);

        let Some(controller) = &self.controller else {
            // Reactive advisory mode: skip the primary while unhealthy,
            // fail the batch over on a retriable error, never on fatal.
            gauge!("capture_primary_sink_health").set(if advisory_healthy { 1.0 } else { 0.0 });

            if !advisory_healthy {
                counter!("capture_fallback_sink_failovers_total").increment(1);
                return self.secondary.publish(events).await;
            }

            let results = self.primary.publish(events.clone()).await;
            return match classify(&results) {
                AttemptOutcome::Retriable => {
                    error!("Primary sink failed, falling back");
                    counter!("capture_fallback_sink_failovers_total").increment(1);
                    self.secondary.publish(events).await
                }
                _ => results,
            };
        };

        // Breaker mode: the controller decides the route per batch —
        // autonomous open/half-open/closed switchover on top of the
        // reactive guarantee below.
        let healthy = advisory_healthy && controller.primary_available();
        let (route, state, error_ratio) = controller.poll(healthy);

        // Half-open admits a single probe at a time: while one batch is
        // testing the primary, others fall back rather than flood a
        // still-flaky primary. A `Primary` route here becomes `Fallback`
        // if we can't win the permit.
        let mut probing = false;
        let effective = if route == FailoverRoute::Primary {
            if state == BreakerState::HalfOpen {
                if controller.try_acquire_probe() {
                    probing = true;
                    FailoverRoute::Primary
                } else {
                    FailoverRoute::Fallback
                }
            } else {
                FailoverRoute::Primary
            }
        } else {
            FailoverRoute::Fallback
        };

        // The gauge tracks the *effective* routing decision (breaker +
        // health), not health alone: `capture_primary_sink_health == 0`
        // iff this batch is served by the secondary, preserving the
        // reactive mode's invariant.
        gauge!("capture_primary_sink_health").set(if effective == FailoverRoute::Primary {
            1.0
        } else {
            0.0
        });

        if effective == FailoverRoute::Fallback {
            counter!("capture_fallback_sink_failovers_total").increment(1);
            controller.report_routed_to_fallback(state, error_ratio);
            return self.secondary.publish(events).await;
        }

        // Primary route (closed, or the single admitted half-open
        // probe): attempt, then record. The mechanism reports
        // batch-uniform results, so the batch classification *is* the
        // attempt outcome.
        let results = self.primary.publish(events.clone()).await;
        let outcome = classify(&results);
        if probing {
            controller.release_probe();
        }
        controller.record(outcome, state);

        // Preserve the reactive guarantee: a retriable primary failure
        // still fails this batch over to the secondary immediately, on
        // top of the breaker tripping for subsequent batches. A fatal
        // outcome is returned as-is (no failover), matching v0.
        if matches!(outcome, AttemptOutcome::Retriable) {
            error!("Primary sink failed retriably, failing batch over to fallback");
            counter!("capture_fallback_sink_failovers_total").increment(1);
            return self.secondary.publish(events).await;
        }
        results
    }

    /// Flush the primary only (matching the former `FallbackSink`).
    fn flush(&self) -> Result<(), anyhow::Error> {
        self.primary.flush()
    }
}

/// Classify a batch of per-event results the way the folded v0 response
/// did: the first failure wins (Retriable only for `RetryableSinkError`),
/// success otherwise. Failover routing is a batch-level decision, so it
/// keys off this batch classification.
fn classify(results: &[SinkResult]) -> AttemptOutcome {
    for result in results {
        match result.outcome() {
            Outcome::Success => continue,
            Outcome::Retriable => return AttemptOutcome::Retriable,
            Outcome::Fatal => return AttemptOutcome::Fatal,
        }
    }
    AttemptOutcome::Success
}

/// Token-routed split, primary cluster / secondary cluster (e.g. WarpStream)
/// today. Routing is decided per event before any prep, so each partition
/// resolves topics and serializes through its own child surface.
pub struct SplitOutputs {
    primary: Arc<dyn Outputs>,
    secondary: Arc<dyn Outputs>,
    routing: AiRouting,
}

impl SplitOutputs {
    pub fn new(primary: Arc<dyn Outputs>, secondary: Arc<dyn Outputs>, routing: AiRouting) -> Self {
        Self {
            primary,
            secondary,
            routing,
        }
    }
}

#[async_trait]
impl Outputs for SplitOutputs {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Vec<SinkResult> {
        // Partition by destination, preserving per-destination order.
        // The common case (every event routes the same way — e.g. a
        // single-token batch in full-secondary mode) leaves one Vec
        // empty and forwards the other whole.
        let mut to_primary: Vec<ProcessedEvent> = Vec::new();
        let mut to_secondary: Vec<ProcessedEvent> = Vec::new();
        for event in events {
            if self.routing.routes_to_secondary(&event.event.token) {
                to_secondary.push(event);
            } else {
                to_primary.push(event);
            }
        }

        counter!("capture_split_sink_selected", "cluster" => "primary")
            .increment(to_primary.len() as u64);
        counter!("capture_split_sink_selected", "cluster" => "secondary")
            .increment(to_secondary.len() as u64);

        // A batch is built from a single request, so every event carries the
        // same request-level token and one partition is always empty today;
        // the both-non-empty arm is defensive against a future multi-token
        // batch path, not a hot path.
        match (to_primary.is_empty(), to_secondary.is_empty()) {
            (false, true) => self.primary.publish(to_primary).await,
            (true, false) => self.secondary.publish(to_secondary).await,
            (false, false) => {
                // Cross-destination ordering is irrelevant (separate
                // clusters); publish concurrently. Per-event results mean
                // each partition reports its own outcomes — the caller's
                // fold (or per-event response) decides what a partial
                // failure means.
                let (mut p, s) = tokio::join!(
                    self.primary.publish(to_primary),
                    self.secondary.publish(to_secondary),
                );
                p.extend(s);
                p
            }
            (true, true) => Vec::new(),
        }
    }

    /// Split flushes both clusters.
    fn flush(&self) -> Result<(), anyhow::Error> {
        self.primary.flush()?;
        self.secondary.flush()?;
        Ok(())
    }
}
