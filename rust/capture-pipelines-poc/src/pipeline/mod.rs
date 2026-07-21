//! The composed demo analytics pipeline: its effects struct, its output vocabulary,
//! and the builder wiring.
//!
//! `ParsedEvent` → [`Validate`] → [`ApplyQuota`]`.fail_open()` → [`ApplyRestrictions`],
//! with the async [`BatchAnnotate`](crate::steps::annotate::BatchAnnotate) chunk stage
//! run after the sync segment by the integration test. The composed sync-segment type
//! is spelled out as [`AnalyticsPipeline`] — the visible proof that the whole thing is
//! one flat, monomorphized struct (no boxes, no `dyn`).

pub mod accumulate;
pub mod outputs;

pub use outputs::{analytics_topic_for, AnalyticsOutputs};

use crate::compose_fx;
use crate::events::parsed::ParsedEvent;
use crate::events::wrappers::Validated;
use crate::framework::chain::{builder, Chain, Identity, Pipeline};
use crate::framework::fail_open::{FailOpen, FallibleStepExt};
use crate::framework::fx::WarningSink;
use crate::steps::quota::ApplyQuota;
use crate::steps::restrictions::ApplyRestrictions;
use crate::steps::validate::Validate;

// The demo effects struct: just the ingestion-warnings sink for now. Adding a second
// concern later is one more field here — no framework change.
compose_fx!(AnalyticsFx {
    warnings: WarningSink,
});

/// The fully monomorphized sync segment of the analytics pipeline. The nested
/// `Chain<Chain<…>>` type — with the `FailOpen` wrapper visible — is the static-
/// dispatch proof: no `Box`, no vtable, one flat struct. (The complexity lint is
/// silenced because the verbosity is the point.)
#[allow(clippy::type_complexity)]
pub type AnalyticsPipeline = Pipeline<
    Chain<Chain<Chain<Identity<ParsedEvent>, Validate>, FailOpen<ApplyQuota>>, ApplyRestrictions>,
>;

/// Build the analytics sync pipeline with the given demo config.
///
/// `fail_open` is generic over its input/effects types, and the builder's `.step` is
/// intentionally unconstrained, so those types are named here; the return-type alias
/// then pins the whole composed shape.
pub fn build_analytics_pipeline(
    failing_token: &'static str,
    dlq_token: &'static str,
    overflow_token: &'static str,
) -> AnalyticsPipeline {
    builder::<ParsedEvent>()
        .step(Validate)
        .step(
            FallibleStepExt::<Validated<ParsedEvent>, AnalyticsFx>::fail_open(ApplyQuota {
                failing_token,
            }),
        )
        .step(ApplyRestrictions {
            dlq_token,
            overflow_token,
        })
        .build()
}
