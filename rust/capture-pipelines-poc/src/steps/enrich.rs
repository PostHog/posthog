//! `Enrich` — attaches a resolved geo country to an event.

use crate::events::wrappers::WithGeo;
use crate::framework::result::{NoOutputs, StepResult};
use crate::framework::step::Step;

/// Adds a resolved geo country to any event, wrapping it in
/// [`WithGeo`](crate::events::wrappers::WithGeo).
///
/// Open by default on input (`In` is unconstrained — it reads nothing). Its *output*
/// is the concrete [`WithGeo`] wrapper, which is the legitimate "this step creates a
/// new capability layer" case: enrichment's whole job is to add data, and it does so
/// without touching any other step. Inserting `Enrich` ahead of a chain leaves every
/// downstream step's signature unchanged — the open-extension property (see the
/// `open_extension_*` regression test).
pub struct Enrich {
    /// The geo country to stamp (a fixed lookup result, for the demo).
    pub geo: &'static str,
}

impl<In, Fx> Step<In, Fx> for Enrich {
    type Out = WithGeo<In>;
    type Outputs = NoOutputs;

    fn apply(&self, event: In, _fx: &mut Fx) -> StepResult<WithGeo<In>, NoOutputs> {
        StepResult::Continue(WithGeo::new(event, self.geo))
    }

    fn name(&self) -> &'static str {
        "enrich"
    }
}
