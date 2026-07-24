//! The composed demo analytics pipeline: one fluent construction, one spelled-out type.
//!
//! [`build_analytics_pipeline`] composes the whole thing — sync steps, the heatmap
//! [`Branching`] split, and **both async stages** — in a single builder chain:
//!
//! ```text
//! Validate → ApplyQuota.fail_open() → Branching        (sync segment)
//!   → grouped_stage(token:distinct_id, OverflowCheck)  (async: groups concurrent, in-order)
//!   → stage(GeoAnnotate)                               (async: per-item concurrent)
//! ```
//!
//! [`build_analytics_pipeline`] returns the composed [`Built`] pipeline behind an
//! opaque `impl BatchPipeline`: every sync chain *and* async stage is still fused into
//! one flat, monomorphized struct (no boxes) — the opaque return just spares callers the
//! spelled-out `Then<Then<…>>` shape, so the builder chain itself is the only pipeline
//! description. Running a batch is `pipeline.run_batch(..)`;
//! [`handle_results`](runner::handle_results) then turns the positional verdicts into
//! produces + outcomes — the only logic outside the composition, and it does no wiring.

pub mod accumulate;
pub mod outputs;
pub mod runner;

pub use outputs::{analytics_topic_for, AnalyticsOutputs};
pub use runner::{group_key, handle_results, GeoAnnotate, OverflowCheck, Survivor, Verdict};

use crate::compose_fx;
use crate::events::capabilities::HasEventName;
use crate::events::parsed::ParsedEvent;
use crate::events::wrappers::{Restricted, Validated};
use crate::framework::batch::{compose, BatchPipeline, Built};
use crate::framework::concurrency::Branching;
use crate::framework::fail_open::FallibleStepExt;
use crate::framework::fx::WarningSink;
use crate::framework::result::StepResult;
use crate::framework::step::Step;
use crate::steps::quota::ApplyQuota;
use crate::steps::restrictions::ApplyRestrictions;
use crate::steps::validate::Validate;

// The demo effects struct: just the ingestion-warnings sink for now. Adding a second
// concern later is one more field here — no framework change.
compose_fx!(AnalyticsFx {
    warnings: WarningSink,
});

/// Demo config (fixture tokens), fixed so the builder can name the composed type.
pub const FAILING_TOKEN: &str = "redis_down";
/// Token forced to the DLQ by restrictions.
pub const DLQ_TOKEN: &str = "dlq_tok";
/// Token forced to overflow by restrictions.
pub const OVERFLOW_TOKEN: &str = "overflow_tok";
/// Concurrency ceiling for the async stages (high enough to run every group/item at once).
pub const MAX_CONCURRENCY: usize = 16;

/// Which sub-chain an event takes. Adding a variant here turns [`route_branch`]'s
/// `match` into a non-exhaustive-match compile error until it is handled — the
/// exhaustiveness guarantee that replaces Node's `Exclude<TRemaining, B>` builder trick.
#[derive(Clone, Copy)]
pub enum Route {
    /// The normal policy path (applies restrictions).
    Standard,
    /// Heatmap-like `$$`-prefixed events: skip restrictions, mirroring capture's split.
    Heatmap,
}

type ClassifyFn = fn(&Validated<ParsedEvent>) -> Route;
type RouteFn =
    fn(Route, Validated<ParsedEvent>, &mut AnalyticsFx) -> StepResult<Survivor, AnalyticsOutputs>;
type GroupKeyFn = fn(&Survivor) -> String;

/// The demo's branching step: classify by event name, route to one of two sub-chains
/// that both produce `Restricted<Validated<ParsedEvent>>`.
pub type BranchStep = Branching<Route, ClassifyFn, RouteFn>;

fn classify_branch(event: &Validated<ParsedEvent>) -> Route {
    if event.event_name().starts_with("$$") {
        Route::Heatmap
    } else {
        Route::Standard
    }
}

fn route_branch(
    route: Route,
    event: Validated<ParsedEvent>,
    fx: &mut AnalyticsFx,
) -> StepResult<Survivor, AnalyticsOutputs> {
    match route {
        Route::Standard => ApplyRestrictions {
            dlq_token: DLQ_TOKEN,
            overflow_token: OVERFLOW_TOKEN,
        }
        .apply(event, fx),
        Route::Heatmap => StepResult::Continue(Restricted::new(event, true, Some("heatmap"))),
    }
}

/// Compose the analytics pipeline as nested scopes, so the code shape mirrors the
/// execution shape (the Node builder's `sequentially` / `concurrentlyPerGroup` /
/// `concurrently` callbacks):
///
/// - one `sequentially` scope fuses the sync steps (validate → quota → branch),
/// - `grouped` runs groups concurrently with items **in order within a group**
///   (the `in_order` body makes that per-group ordering explicit — the flat
///   `.grouped_stage()` hid it),
/// - `concurrently` runs the geo processor per item.
///
/// The return type is the composed [`Built`] pipeline behind `impl BatchPipeline`:
/// every sync chain and async stage is still fused into one flat, monomorphized
/// struct (no `Box`, no `dyn` — the boxless proof is the ZST
/// `composed_pipeline_with_async_stage_is_a_flat_struct` test in
/// [`framework::batch`](crate::framework::batch)). The two async stage processors are
/// passed in so a caller (a test) can hold a shared probe handle before they move
/// into the composition.
pub fn build_analytics_pipeline(
    overflow: OverflowCheck,
    geo: GeoAnnotate,
) -> Built<impl BatchPipeline<ParsedEvent, AnalyticsFx, Out = Survivor, Outputs = AnalyticsOutputs>>
{
    compose::<ParsedEvent, AnalyticsOutputs>()
        .sequentially(|events| {
            events
                .step(Validate)
                .step(
                    FallibleStepExt::<Validated<ParsedEvent>, AnalyticsFx>::fail_open(ApplyQuota {
                        failing_token: FAILING_TOKEN,
                    }),
                )
                .step(Branching::new(
                    classify_branch as ClassifyFn,
                    route_branch as RouteFn,
                ))
        })
        .grouped(MAX_CONCURRENCY, group_key as GroupKeyFn, |group| {
            group.in_order(overflow)
        })
        .concurrently(MAX_CONCURRENCY, |item| item.run(geo))
        .build()
}
