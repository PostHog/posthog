//! [`AsyncProcessor`]: a per-item async transform the concurrency combinators drive.

use crate::framework::result::{Outputs, StepResult};

/// A per-item asynchronous processor — the unit of work the concurrency combinators run
/// over a chunk, and the payload of an async pipeline stage.
///
/// It takes an item by value and returns a verdict. Unlike [`Step`](crate::framework::step::Step)
/// it has **no `&mut Fx`**: running many of these concurrently would make a shared
/// `&mut Fx` unsound, and the framework collects effects at chunk boundaries rather than
/// per concurrent item. `&self` config is fine (shared across items by reference).
///
/// `In` is an associated type (not a type parameter) so the pipeline builder can name a
/// stage's output type when it opens the next sync segment.
pub trait AsyncProcessor {
    /// The item this processor consumes.
    type In;
    /// The event state produced on `Continue`.
    type Out;
    /// The redirect targets this processor can emit.
    type Outputs: Outputs;

    /// Process one item.
    async fn process(&self, item: Self::In) -> StepResult<Self::Out, Self::Outputs>;

    /// Stable name.
    fn name(&self) -> &'static str;
}
