//! The composed demo analytics pipeline: its effects struct, output vocabulary, and
//! the full builder + runner wiring.
//!
//! The sync segment is `ParsedEvent` → [`Validate`] → [`ApplyQuota`]`.fail_open()` →
//! [`Branching`] (heatmap split), spelled out as [`AnalyticsPipeline`] — the visible
//! proof it is one flat, monomorphized struct. The async phase (run by
//! [`run_analytics_batch`](runner::run_analytics_batch)) then composes
//! [`concurrently_per_group`](crate::concurrently_per_group) (keyed on
//! `token:distinct_id`, mirroring the Node joined pipeline's post-team block) and
//! [`concurrently`](crate::concurrently) (a per-item-independent enrichment).

pub mod accumulate;
pub mod outputs;
pub mod runner;

pub use outputs::{analytics_topic_for, AnalyticsOutputs};
pub use runner::{run_analytics_batch, GeoAnnotate, OverflowCheck, Verdict};

use crate::compose_fx;
use crate::events::capabilities::HasEventName;
use crate::events::parsed::ParsedEvent;
use crate::events::wrappers::{Restricted, Validated};
use crate::framework::chain::{builder, Chain, Identity, Pipeline};
use crate::framework::concurrency::Branching;
use crate::framework::fail_open::{FailOpen, FallibleStepExt};
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
type RouteFn = fn(
    Route,
    Validated<ParsedEvent>,
    &mut AnalyticsFx,
) -> StepResult<Restricted<Validated<ParsedEvent>>, AnalyticsOutputs>;

/// The demo's branching step: classify by event name, route to one of two sub-chains
/// that both produce `Restricted<Validated<ParsedEvent>>`.
pub type BranchStep = Branching<Route, ClassifyFn, RouteFn>;

fn classify_branch(event: &Validated<ParsedEvent>) -> Route {
    // `$$`-prefixed events (e.g. `$$heatmap`) are the heatmap-like split.
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
) -> StepResult<Restricted<Validated<ParsedEvent>>, AnalyticsOutputs> {
    match route {
        // Standard events go through the real restriction policy (may redirect).
        Route::Standard => ApplyRestrictions {
            dlq_token: DLQ_TOKEN,
            overflow_token: OVERFLOW_TOKEN,
        }
        .apply(event, fx),
        // Heatmaps skip restrictions entirely and are stamped skip-person.
        Route::Heatmap => StepResult::Continue(Restricted::new(event, true, Some("heatmap"))),
    }
}

/// The fully monomorphized sync segment. The nested `Chain<Chain<…>>` type — with the
/// `FailOpen` and `Branching` combinators visible — is the static-dispatch proof: no
/// `Box`, no vtable, one flat struct. (The complexity lint is silenced because the
/// verbosity is the point.)
#[allow(clippy::type_complexity)]
pub type AnalyticsPipeline = Pipeline<
    Chain<Chain<Chain<Identity<ParsedEvent>, Validate>, FailOpen<ApplyQuota>>, BranchStep>,
>;

/// Build the analytics sync pipeline. `fail_open` is generic and the builder's `.step`
/// is unconstrained, so those types are named here; the return-type alias then pins the
/// whole composed shape.
pub fn build_analytics_pipeline() -> AnalyticsPipeline {
    builder::<ParsedEvent>()
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
        .build()
}
