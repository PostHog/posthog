//! The demo batch runner: sync segment → grouped async policy → concurrent async
//! enrichment, composing the combinators into the pipeline itself (not a side demo).
//!
//! This mirrors the Node joined pipeline: after the synchronous per-event policy, the
//! post-team phase is a `concurrentlyPerGroup(token:distinctId)` block. Here the grouped
//! stage ([`OverflowCheck`]) runs per `token:distinct_id` with groups concurrent and
//! in-group order preserved; the following per-item-independent enrichment
//! ([`GeoAnnotate`]) runs via [`concurrently`].
//!
//! The two async stages carry in-flight counters so tests can prove real, bounded
//! concurrency deterministically (their `yield_now` points stand in for async I/O
//! latency — no sleeping).

use super::outputs::AnalyticsOutputs;
use super::AnalyticsFx;
use super::AnalyticsPipeline;
use crate::events::capabilities::{HasDistinctId, HasEventName, HasToken};
use crate::events::parsed::ParsedEvent;
use crate::events::wrappers::{Restricted, Validated};
use crate::framework::chunk::yield_now;
use crate::framework::concurrency::{concurrently, concurrently_per_group, AsyncProcessor};
use crate::framework::outputs::{OutputRegistry, Produce};
use crate::framework::result::{NoOutputs, StepResult};
use std::sync::atomic::{AtomicUsize, Ordering::SeqCst};
use std::sync::Mutex;

/// The event state flowing through the async phase (post-restrictions).
type Survivor = Restricted<Validated<ParsedEvent>>;

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

/// Groups run concurrently keyed on `token:distinct_id`; within a group, items are
/// processed strictly in order (this is the stateful per-key policy — overflow /
/// skip-person — that must not reorder a key's events). Records max in-flight and the
/// per-key processing order for tests.
#[derive(Default)]
pub struct OverflowCheck {
    in_flight: AtomicUsize,
    max_in_flight: AtomicUsize,
    order: Mutex<Vec<(String, String)>>,
}

impl OverflowCheck {
    /// A fresh probe.
    pub fn new() -> Self {
        Self::default()
    }
    /// The peak number of groups processed concurrently.
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
}

fn group_key<E: HasToken + HasDistinctId>(event: &E) -> String {
    format!("{}:{}", event.token(), event.distinct_id().unwrap_or("-"))
}

impl AsyncProcessor<Survivor> for OverflowCheck {
    type Out = Survivor;
    type Outputs = NoOutputs;

    async fn process(&self, event: Survivor) -> StepResult<Survivor, NoOutputs> {
        let now = self.in_flight.fetch_add(1, SeqCst) + 1;
        self.max_in_flight.fetch_max(now, SeqCst);
        self.order
            .lock()
            .unwrap()
            .push((group_key(&event), event.event_name().to_string()));
        yield_now().await; // stand-in for a batched per-key async check
        yield_now().await;
        self.in_flight.fetch_sub(1, SeqCst);
        StepResult::Continue(event) // real capture would stamp overflow / skip_person
    }

    fn name(&self) -> &'static str {
        "overflow_check"
    }
}

/// A genuinely per-item-independent async enrichment (e.g. a geo lookup): order does
/// not matter, so it runs via `concurrently` for max throughput. Records max in-flight.
#[derive(Default)]
pub struct GeoAnnotate {
    in_flight: AtomicUsize,
    max_in_flight: AtomicUsize,
}

impl GeoAnnotate {
    /// A fresh probe.
    pub fn new() -> Self {
        Self::default()
    }
    /// The peak number of items enriched concurrently.
    pub fn max_in_flight(&self) -> usize {
        self.max_in_flight.load(SeqCst)
    }
}

impl AsyncProcessor<Survivor> for GeoAnnotate {
    type Out = Survivor;
    type Outputs = NoOutputs;

    async fn process(&self, event: Survivor) -> StepResult<Survivor, NoOutputs> {
        let now = self.in_flight.fetch_add(1, SeqCst) + 1;
        self.max_in_flight.fetch_max(now, SeqCst);
        yield_now().await; // stand-in for an independent per-item lookup
        yield_now().await;
        self.in_flight.fetch_sub(1, SeqCst);
        StepResult::Continue(event)
    }

    fn name(&self) -> &'static str {
        "geo_annotate"
    }
}

/// Run one batch end to end: sync segment (with the heatmap branch) → grouped async
/// policy (`concurrently_per_group` on `token:distinct_id`) → per-item concurrent
/// enrichment (`concurrently`). Redirects are produced to `registry` with the raw
/// payload; the returned verdicts are positional.
// A demo harness legitimately threads its collaborators (pipeline, both async stages,
// effects, registry, raw payloads); the real consumer loop would own these as fields.
#[allow(clippy::too_many_arguments)]
pub async fn run_analytics_batch<P: Produce>(
    pipeline: &AnalyticsPipeline,
    overflow: &OverflowCheck,
    geo: &GeoAnnotate,
    fx: &mut AnalyticsFx,
    registry: &OutputRegistry<AnalyticsOutputs, P>,
    raw: &[Vec<u8>],
    batch: Vec<ParsedEvent>,
    max_concurrency: usize,
) -> Vec<Verdict> {
    let total = batch.len();
    let mut verdicts: Vec<Option<Verdict>> = (0..total).map(|_| None).collect();

    // --- Sync segment (Validate -> Quota.fail_open -> Branching) ---
    let mut survivors: Vec<Survivor> = Vec::new();
    let mut survivor_idx: Vec<usize> = Vec::new();
    for (i, verdict) in pipeline.run_chunk(batch, fx).into_iter().enumerate() {
        match verdict {
            StepResult::Continue(event) => {
                survivor_idx.push(i);
                survivors.push(event);
            }
            StepResult::Drop { reason } | StepResult::Dlq { reason } => {
                verdicts[i] = Some(Verdict::Drop(reason));
            }
            StepResult::Redirect { output, .. } => {
                let _ = registry.emit(output, raw[i].clone());
                verdicts[i] = Some(Verdict::Redirect(output));
            }
        }
    }

    // --- Grouped async policy: groups concurrent, in-order within each key ---
    let grouped = concurrently_per_group(max_concurrency, group_key, overflow, survivors).await;

    let mut stage2: Vec<Survivor> = Vec::new();
    let mut stage2_idx: Vec<usize> = Vec::new();
    for (j, verdict) in grouped.into_iter().enumerate() {
        let idx = survivor_idx[j];
        match verdict {
            StepResult::Continue(event) => {
                stage2_idx.push(idx);
                stage2.push(event);
            }
            StepResult::Drop { reason } | StepResult::Dlq { reason } => {
                verdicts[idx] = Some(Verdict::Drop(reason));
            }
            // `OverflowCheck` declares `NoOutputs`, so a redirect is unconstructible.
            StepResult::Redirect { output, .. } => match output {},
        }
    }

    // --- Per-item-independent concurrent enrichment ---
    let enriched = concurrently(max_concurrency, geo, stage2).await;
    for (k, verdict) in enriched.into_iter().enumerate() {
        let idx = stage2_idx[k];
        verdicts[idx] = Some(match verdict {
            StepResult::Continue(_) => Verdict::Continue,
            StepResult::Drop { reason } | StepResult::Dlq { reason } => Verdict::Drop(reason),
            StepResult::Redirect { output, .. } => match output {},
        });
    }

    verdicts
        .into_iter()
        .map(|v| v.expect("every position resolved"))
        .collect()
}
