//! `BatchAnnotate` — the demo async chunk stage.

use crate::framework::chunk::{yield_now, ChunkStep};
use crate::framework::result::{NoOutputs, StepResult};

/// A demo async chunk step standing in for a batched lookup (e.g. a batched Redis
/// round-trip). It suspends once at the chunk boundary via
/// [`yield_now`](crate::framework::chunk::yield_now), then returns one `Continue` per
/// input, unchanged — the point demonstrated is ordering and the same-length
/// invariant, not the lookup itself.
///
/// Open by default: generic over any input `In`; it reads nothing and passes events
/// through.
pub struct BatchAnnotate;

impl<In, Fx> ChunkStep<In, Fx> for BatchAnnotate {
    type Out = In;
    type Outputs = NoOutputs;

    async fn apply_chunk(&self, events: Vec<In>, _fx: &mut Fx) -> Vec<StepResult<In, NoOutputs>> {
        yield_now().await; // a real suspension point at the chunk boundary
        events.into_iter().map(StepResult::Continue).collect()
    }

    fn name(&self) -> &'static str {
        "batch_annotate"
    }
}
