//! The demo's async stage processors, the batch key function, and result handling.
//!
//! There is **no pipeline composition here** — the stages are wired into the pipeline
//! by the builder in [`build_analytics_pipeline`](super::build_analytics_pipeline). This
//! module only defines the per-item async work (mirroring capture's per-key overflow and
//! a per-item enrichment) and the thin result handler that turns final verdicts into
//! produces + outcomes.
//!
//! Both processors carry a shared probe (`Arc`) so tests can observe real, bounded
//! concurrency deterministically — their `yield_now` points stand in for async I/O
//! latency, no sleeping.

use super::outputs::AnalyticsOutputs;
use crate::events::capabilities::{HasDistinctId, HasEventName, HasToken};
use crate::events::parsed::ParsedEvent;
use crate::events::wrappers::{Restricted, Validated};
use crate::framework::chunk::yield_now;
use crate::framework::concurrency::AsyncProcessor;
use crate::framework::outputs::{OutputRegistry, Produce};
use crate::framework::result::{NoOutputs, StepResult};
use std::sync::atomic::{AtomicUsize, Ordering::SeqCst};
use std::sync::{Arc, Mutex};

/// The event state flowing through the async phase (post-restrictions).
pub type Survivor = Restricted<Validated<ParsedEvent>>;

/// The batch group key: `token:distinct_id`, mirroring capture's overflow keying.
pub fn group_key(event: &Survivor) -> String {
    format!("{}:{}", event.token(), event.distinct_id().unwrap_or("-"))
}

/// The demo's per-event outcome, positional (verdict `i` ↔ input `i`).
#[derive(Debug, PartialEq)]
pub enum Verdict {
    /// Survived the whole pipeline.
    Continue,
    /// Dropped, with the static reason.
    Drop(&'static str),
    /// Redirected to a typed output.
    Redirect(AnalyticsOutputs),
}

/// Shared observation state for a concurrent stage.
#[derive(Default)]
pub struct Probe {
    in_flight: AtomicUsize,
    max_in_flight: AtomicUsize,
    order: Mutex<Vec<(String, String)>>,
}

impl Probe {
    /// The peak number of concurrent in-flight items.
    pub fn max_in_flight(&self) -> usize {
        self.max_in_flight.load(SeqCst)
    }
    /// The event names processed for `key`, in processing order.
    pub fn order_for(&self, key: &str) -> Vec<String> {
        self.order
            .lock()
            .unwrap()
            .iter()
            .filter(|(k, _)| k == key)
            .map(|(_, name)| name.clone())
            .collect()
    }
    fn enter(&self, key: String, tag: String) {
        let now = self.in_flight.fetch_add(1, SeqCst) + 1;
        self.max_in_flight.fetch_max(now, SeqCst);
        self.order.lock().unwrap().push((key, tag));
    }
    fn leave(&self) {
        self.in_flight.fetch_sub(1, SeqCst);
    }
}

/// Grouped per-key policy (overflow / skip-person): groups concurrent, items in-order.
#[derive(Default)]
pub struct OverflowCheck {
    probe: Arc<Probe>,
}

impl OverflowCheck {
    /// A fresh stage processor.
    pub fn new() -> Self {
        Self::default()
    }
    /// A shared handle to its probe (clone before moving the processor into the builder).
    pub fn probe(&self) -> Arc<Probe> {
        self.probe.clone()
    }
}

impl AsyncProcessor for OverflowCheck {
    type In = Survivor;
    type Out = Survivor;
    type Outputs = NoOutputs;

    async fn process(&self, event: Survivor) -> StepResult<Survivor, NoOutputs> {
        self.probe
            .enter(group_key(&event), event.event_name().to_string());
        yield_now().await; // stand-in for a batched per-key async check
        yield_now().await;
        self.probe.leave();
        StepResult::Continue(event) // real capture would stamp overflow / skip_person
    }

    fn name(&self) -> &'static str {
        "overflow_check"
    }
}

/// A per-item-independent async enrichment (e.g. a geo lookup) — order-independent, so
/// it runs via `concurrently`.
#[derive(Default)]
pub struct GeoAnnotate {
    probe: Arc<Probe>,
}

impl GeoAnnotate {
    /// A fresh stage processor.
    pub fn new() -> Self {
        Self::default()
    }
    /// A shared handle to its probe.
    pub fn probe(&self) -> Arc<Probe> {
        self.probe.clone()
    }
}

impl AsyncProcessor for GeoAnnotate {
    type In = Survivor;
    type Out = Survivor;
    type Outputs = NoOutputs;

    async fn process(&self, event: Survivor) -> StepResult<Survivor, NoOutputs> {
        self.probe
            .enter(group_key(&event), event.event_name().to_string());
        yield_now().await; // stand-in for an independent per-item lookup
        yield_now().await;
        self.probe.leave();
        StepResult::Continue(event)
    }

    fn name(&self) -> &'static str {
        "geo_annotate"
    }
}

/// Result handling only (no composition): turn the pipeline's final positional verdicts
/// into produces + [`Verdict`]s. Redirects produce the original payload to the resolved
/// topic; everything else maps straight through.
pub fn handle_results<T, P: Produce>(
    verdicts: Vec<StepResult<T, AnalyticsOutputs>>,
    raw: &[Vec<u8>],
    registry: &OutputRegistry<AnalyticsOutputs, P>,
) -> Vec<Verdict> {
    verdicts
        .into_iter()
        .enumerate()
        .map(|(i, verdict)| match verdict {
            StepResult::Continue(_) => Verdict::Continue,
            StepResult::Drop { reason } | StepResult::Dlq { reason } => Verdict::Drop(reason),
            StepResult::Redirect { output, .. } => {
                let _ = registry.emit(output, raw[i].clone());
                Verdict::Redirect(output)
            }
        })
        .collect()
}
