//! Async chunk stages: [`ChunkStep`], using **native async-fn-in-trait** — no
//! `async_trait`, no boxed futures.
//!
//! Sync steps fuse into one inlined pass over the chunk; async appears only at
//! explicit chunk-stage boundaries (a batched Redis lookup, a Kafka produce-ack). A
//! [`ChunkStep`] receives the whole chunk of survivors at once and returns one verdict
//! per input, *in order* — the same-length invariant is what keeps verdicts positional
//! across stages.
//!
//! [`run_pipeline`] demonstrates the execution model the harness uses per batch:
//! sync segment → await chunk stage → sync segment.

use crate::framework::result::StepResult;
use crate::framework::step::Step;
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};

/// A runtime-agnostic "yield once" await point — the std-only stand-in for
/// `tokio::task::yield_now`, so the library never depends on a specific runtime.
/// A demo async step awaits this to prove there is a real suspension point at the
/// chunk boundary.
pub async fn yield_now() {
    /// Resolves `Pending` exactly once, then `Ready`.
    struct YieldOnce(bool);
    impl Future for YieldOnce {
        type Output = ();
        fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
            if self.0 {
                Poll::Ready(())
            } else {
                self.0 = true;
                cx.waker().wake_by_ref();
                Poll::Pending
            }
        }
    }
    YieldOnce(false).await
}

/// An asynchronous, chunk-scoped step. `apply_chunk` gets every survivor of the
/// preceding sync segment and must return exactly one verdict per input.
///
/// The `async fn` desugars to an anonymous future with no boxing — the library needs
/// no async runtime; only *executing* a chunk step does (tokio in tests). See the
/// crate-level `async_fn_in_trait` allow.
pub trait ChunkStep<In, Fx> {
    /// The event state produced on `Continue`.
    type Out;
    /// The redirect targets this step can emit.
    type Outputs: crate::framework::result::Outputs;

    /// Process the whole chunk. The returned vector MUST be the same length as
    /// `events`, with verdict `i` corresponding to input `i`.
    async fn apply_chunk(
        &self,
        events: Vec<In>,
        fx: &mut Fx,
    ) -> Vec<StepResult<Self::Out, Self::Outputs>>;

    /// Stable step name.
    fn name(&self) -> &'static str;
}

/// Run one chunk stage, enforcing the same-length invariant.
pub async fn run_chunk_stage<In, Fx, C>(
    step: &C,
    events: Vec<In>,
    fx: &mut Fx,
) -> Vec<StepResult<C::Out, C::Outputs>>
where
    C: ChunkStep<In, Fx>,
{
    let n = events.len();
    let out = step.apply_chunk(events, fx).await;
    assert_eq!(
        out.len(),
        n,
        "chunk step `{}` broke the same-length invariant",
        step.name()
    );
    out
}

/// Execute the canonical shape: a sync segment, then an async chunk stage, then a
/// second sync segment. Non-`Continue` verdicts from the first sync segment are
/// recorded at their position and do not enter the chunk stage; survivors flow through
/// and their post-stage verdicts are merged back positionally, so order is preserved
/// end to end.
///
/// The chunk stage passes events through unchanged here, keeping the demo focused on
/// ordering.
pub async fn run_pipeline<In, Fx, S1, C, S2>(
    sync_head: &S1,
    chunk: &C,
    sync_tail: &S2,
    events: Vec<In>,
    fx: &mut Fx,
) -> Vec<StepResult<S2::Out, S2::Outputs>>
where
    S1: Step<In, Fx>,
    C: ChunkStep<S1::Out, Fx, Out = S1::Out, Outputs = S1::Outputs>,
    S2: Step<C::Out, Fx, Outputs = S1::Outputs>,
{
    // First sync segment: keep survivors (with their original index) apart from the
    // terminal verdicts.
    let mut terminal: Vec<Option<StepResult<S2::Out, S2::Outputs>>> = Vec::new();
    let mut survivors = Vec::new();
    let mut survivor_index = Vec::new();

    for event in events {
        match sync_head.apply(event, fx) {
            StepResult::Continue(mid) => {
                terminal.push(None);
                survivor_index.push(terminal.len() - 1);
                survivors.push(mid);
            }
            StepResult::Drop { reason } => terminal.push(Some(StepResult::Drop { reason })),
            StepResult::Dlq { reason } => terminal.push(Some(StepResult::Dlq { reason })),
            StepResult::Redirect {
                output,
                preserve_key,
            } => terminal.push(Some(StepResult::Redirect {
                output,
                preserve_key,
            })),
        }
    }

    // Async chunk stage over the survivors only.
    let staged = run_chunk_stage(chunk, survivors, fx).await;

    // Second sync segment, merged back into the terminal slots by original position.
    for (result, slot) in staged.into_iter().zip(survivor_index) {
        let verdict = match result {
            StepResult::Continue(mid) => sync_tail.apply(mid, fx),
            StepResult::Drop { reason } => StepResult::Drop { reason },
            StepResult::Dlq { reason } => StepResult::Dlq { reason },
            StepResult::Redirect {
                output,
                preserve_key,
            } => StepResult::Redirect {
                output,
                preserve_key,
            },
        };
        terminal[slot] = Some(verdict);
    }

    terminal.into_iter().map(|v| v.unwrap()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::framework::result::NoOutputs;

    // A demo async chunk step: pretend to do a batched lookup, yielding to the runtime
    // mid-flight, then annotate each event by doubling it.
    struct BatchAnnotate;

    impl<Fx> ChunkStep<u32, Fx> for BatchAnnotate {
        type Out = u32;
        type Outputs = NoOutputs;

        async fn apply_chunk(
            &self,
            events: Vec<u32>,
            _fx: &mut Fx,
        ) -> Vec<StepResult<u32, NoOutputs>> {
            yield_now().await; // an await point at the chunk boundary
            events
                .into_iter()
                .map(|e| StepResult::Continue(e * 2))
                .collect()
        }

        fn name(&self) -> &'static str {
            "batch_annotate"
        }
    }

    // A sync step that drops odd numbers, to exercise the survivor split.
    struct DropOdd;
    impl<Fx> Step<u32, Fx> for DropOdd {
        type Out = u32;
        type Outputs = NoOutputs;
        fn apply(&self, event: u32, _fx: &mut Fx) -> StepResult<u32, NoOutputs> {
            if event % 2 == 1 {
                StepResult::Drop { reason: "odd" }
            } else {
                StepResult::Continue(event)
            }
        }
        fn name(&self) -> &'static str {
            "drop_odd"
        }
    }

    struct AddTen;
    impl<Fx> Step<u32, Fx> for AddTen {
        type Out = u32;
        type Outputs = NoOutputs;
        fn apply(&self, event: u32, _fx: &mut Fx) -> StepResult<u32, NoOutputs> {
            StepResult::Continue(event + 10)
        }
        fn name(&self) -> &'static str {
            "add_ten"
        }
    }

    #[tokio::test]
    async fn sync_chunk_sync_preserves_order_and_verdicts() {
        let mut fx = ();
        // 1 dropped, 2 -> annotate(4) -> +10 = 14, 3 dropped, 4 -> annotate(8) -> +10 = 18
        let out = run_pipeline(&DropOdd, &BatchAnnotate, &AddTen, vec![1, 2, 3, 4], &mut fx).await;

        assert_eq!(out.len(), 4);
        assert!(matches!(out[0], StepResult::Drop { reason: "odd" }));
        assert!(matches!(out[1], StepResult::Continue(14)));
        assert!(matches!(out[2], StepResult::Drop { reason: "odd" }));
        assert!(matches!(out[3], StepResult::Continue(18)));
    }
}
