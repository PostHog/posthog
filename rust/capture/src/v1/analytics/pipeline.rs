//! Capture-profile adapter over the `common-pipelines` framework.
//!
//! This module rebuilds capture v1's analytics policy phase as composable
//! framework [`Step`](common_pipelines::Step)s while preserving v1's wire
//! behavior exactly. It is the "capture profile" of the framework described in
//! `rust-ingestion-pipelines-design.md` §3.9.
//!
//! ## Verdict mapping (the adapter contract)
//!
//! The framework's per-event vocabulary is `Continue | Drop | Dlq | Redirect`.
//! Capture maps onto it as follows, and the mapping is the whole reason this is
//! an *adapter* rather than a straight reuse:
//!
//! - **Capture never removes an event from the batch.** v1 keeps every event in
//!   the response slice and expresses rejection as per-event *state*
//!   ([`EventResult::Drop`] + a `details` tag), so later steps skip it by
//!   inspecting `result`. The framework's terminal `Drop`/`Dlq`/`Redirect`
//!   verdicts *remove* the event from the survivor set — which is wrong for
//!   capture. Therefore capture steps only ever return
//!   [`StepResult::Continue`](common_pipelines::StepResult::Continue), carrying
//!   the (mutated) event forward. A framework `Drop` decision is realized as a
//!   `Continue` whose event has been stamped `EventResult::Drop` — "framework
//!   Drop ⇒ v1 per-event Drop result, NOT removal".
//! - **Redirects are destination stamping, not produces.** A restriction that
//!   force-overflows or DLQs an event stamps [`Destination`] on the event; the
//!   sink layer (unchanged) turns that into the actual topic. Capture never
//!   emits a framework `Redirect` (which would produce to a registry output),
//!   so the pipeline's redirect-target type is
//!   [`NoOutputs`](common_pipelines::NoOutputs) — the compiler proves capture
//!   never redirects at the framework level.
//!
//! Because every capture verdict is `Continue`, [`run_in_place`] preserves the
//! batch length and order: survivors == inputs, each carrying its stamped state.
//!
//! ## Effects
//!
//! [`CaptureFx`] is the pipeline's composed effects struct. Capture registers no
//! sink plugins (no ingestion warnings — that plugin is consumer-profile only),
//! so it is empty. It exists to satisfy the framework's `Fx` type parameter and
//! to be the natural home for future capture-scoped effects.

use common_pipelines::{NoOutputs, Pipeline, StepError};

use super::types::{Batch, WrappedEvent};
use crate::v1::Error;

/// The capture profile's composed effects struct. Empty: capture registers no
/// sink plugins. Threaded through every step as `&mut CaptureFx`.
#[derive(Debug, Default)]
pub struct CaptureFx;

/// Capture never redirects at the framework level (redirects are [`Destination`]
/// stamping, handled by the sink layer), so its redirect-target type is
/// uninhabited.
///
/// [`Destination`]: crate::v1::sinks::Destination
pub type CaptureOutputs = NoOutputs;

/// A built capture policy pipeline: consumes and yields [`WrappedEvent`]s,
/// threading [`CaptureFx`], never redirecting.
pub type CapturePipeline = Pipeline<WrappedEvent, WrappedEvent, CaptureFx, CaptureOutputs>;

/// A built capture *request* pipeline: consumes the decoded request [`Batch`]
/// as a single item and yields `Out` (the request phase ends by expanding the
/// batch into per-event state). Request steps either `Continue` or reject the
/// whole request via [`StepError::Reject`] — they never drop the request item.
pub type CaptureRequestPipeline<Out> = Pipeline<Batch, Out, CaptureFx, CaptureOutputs>;

/// Run a capture request pipeline over the decoded request.
///
/// The chunk holds exactly one item (the request). A step rejecting via
/// [`StepError::reject`] surfaces here as the typed capture [`Error`], which
/// `process_batch` returns as the request's HTTP error — exactly the semantics
/// the extracted validation/quota functions had via `?`.
pub async fn run_request<Out: Send + 'static>(
    pipeline: &CaptureRequestPipeline<Out>,
    batch: Batch,
) -> Result<Out, Error> {
    let mut fx = CaptureFx;
    let outcome = pipeline
        .run_chunk(vec![batch], &mut fx)
        .await
        .map_err(reject_to_error)?;

    let mut survivors = outcome.into_survivors();
    debug_assert_eq!(
        survivors.len(),
        1,
        "request steps continue or reject; they never drop the request item"
    );
    survivors
        .pop()
        .ok_or_else(|| Error::InternalError("request pipeline yielded no output".into()))
}

/// Map the framework's error channel back to capture's typed [`Error`].
///
/// `Reject` carries the capture error a gate step raised; anything else is a
/// programming bug (capture steps are otherwise infallible), mapped to a 500
/// rather than a panic on the request path.
fn reject_to_error(err: StepError) -> Error {
    match err.try_into_reject::<Error>() {
        Ok(capture_err) => capture_err,
        Err(other) => Error::InternalError(other.to_string()),
    }
}

/// Run a capture pipeline over `events` in place, preserving order and length.
///
/// Capture steps always `Continue` (see the module docs), so every input is a
/// survivor and the output slice is the input slice with stamped state. The
/// events are moved through the framework executor and moved back.
///
/// A step may reject the whole request via [`StepError::reject`] (e.g. the
/// quota step's billing 402); that surfaces as the typed capture [`Error`]. On
/// rejection `events` is left empty — the request is aborted, matching the old
/// `?`-return behavior where the batch never reached the sink. Any other error
/// is a programming bug (capture steps are otherwise infallible), mapped to a
/// 500 rather than a panic. Capture must never silently lose an event.
pub async fn run_in_place(
    pipeline: &CapturePipeline,
    events: &mut Vec<WrappedEvent>,
) -> Result<(), Error> {
    let input_len = events.len();
    let owned = std::mem::take(events);
    let mut fx = CaptureFx;

    let outcome = pipeline
        .run_chunk(owned, &mut fx)
        .await
        .map_err(reject_to_error)?;

    debug_assert_eq!(
        outcome.survivor_count(),
        input_len,
        "capture pipeline dropped an event: capture must stamp state, never remove"
    );

    *events = outcome.into_survivors();
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::v1::analytics::types::EventResult;
    use crate::v1::sinks::Destination;
    use crate::v1::test_utils::{find_by_did, wrapped_event};
    use common_pipelines::{Step, StepError, StepResult};

    /// A toy step demonstrating the adapter contract: a "drop decision" is
    /// realized by stamping `EventResult::Drop` and returning `Continue`, so the
    /// event stays in the batch. Drops the event whose distinct_id matches.
    struct DropByDistinctId(&'static str);

    impl Step<WrappedEvent, CaptureFx> for DropByDistinctId {
        type Out = WrappedEvent;
        type Outputs = CaptureOutputs;

        fn apply(
            &self,
            mut event: WrappedEvent,
            _fx: &mut CaptureFx,
        ) -> Result<StepResult<WrappedEvent, CaptureOutputs>, StepError> {
            if event.event.distinct_id == self.0 {
                event.result = EventResult::Drop;
                event.destination = Destination::Drop;
                event.details = Some("toy_drop");
            }
            Ok(StepResult::Continue(event))
        }

        fn name(&self) -> &'static str {
            "drop_by_distinct_id"
        }
    }

    #[tokio::test]
    async fn run_in_place_stamps_drop_and_keeps_event_in_batch() {
        let pipeline = CapturePipeline::builder()
            .step(DropByDistinctId("user-2"))
            .build();

        let mut events = vec![
            wrapped_event("$pageview", "user-1"),
            wrapped_event("$identify", "user-2"),
            wrapped_event("$click", "user-3"),
        ];

        run_in_place(&pipeline, &mut events).await.unwrap();

        // Length and order preserved — the "dropped" event is NOT removed.
        assert_eq!(events.len(), 3);
        assert_eq!(events[0].event.distinct_id, "user-1");
        assert_eq!(events[1].event.distinct_id, "user-2");
        assert_eq!(events[2].event.distinct_id, "user-3");

        // The drop decision is expressed as stamped per-event state.
        let dropped = find_by_did(&events, "user-2");
        assert_eq!(dropped.result, EventResult::Drop);
        assert_eq!(dropped.destination, Destination::Drop);
        assert_eq!(dropped.details, Some("toy_drop"));

        // Others untouched.
        assert_eq!(find_by_did(&events, "user-1").result, EventResult::Ok);
        assert_eq!(find_by_did(&events, "user-3").result, EventResult::Ok);
    }

    #[tokio::test]
    async fn run_in_place_on_empty_batch_is_noop() {
        let pipeline = CapturePipeline::builder()
            .step(DropByDistinctId("user-2"))
            .build();
        let mut events: Vec<WrappedEvent> = vec![];
        run_in_place(&pipeline, &mut events).await.unwrap();
        assert!(events.is_empty());
    }
}
