//! `Validate` — shape validation/normalization.

use crate::events::capabilities::{HasEventName, HasTeamId, HasToken};
use crate::events::wrappers::Validated;
use crate::framework::fx::WarningEffects;
use crate::framework::result::{NoOutputs, StepResult};
use crate::framework::step::Step;

/// Shape validation/normalization. Drops empty event names; warns (but continues) on
/// suspiciously long tokens. Infallible — no I/O — so it needs no `fail_open()`.
///
/// Open by default: generic over any input `In` that carries the fields it reads
/// (`HasEventName + HasToken + HasTeamId`) and over any `Fx` that can emit warnings.
/// An upstream step that enriches the event — adding a wrapper — does not change this
/// signature, so `Validate` (and every downstream step) keeps compiling unchanged. See
/// the `open_extension_*` regression test.
pub struct Validate;

impl<In, Fx> Step<In, Fx> for Validate
where
    In: HasEventName + HasToken + HasTeamId,
    Fx: WarningEffects,
{
    type Out = Validated<In>;
    type Outputs = NoOutputs;

    fn apply(&self, event: In, fx: &mut Fx) -> StepResult<Validated<In>, NoOutputs> {
        if event.event_name().is_empty() {
            return StepResult::Drop {
                reason: "invalid_event_name",
            };
        }
        let token_len = event.token().len();
        if token_len > 40 {
            fx.warn(
                event.team_id(),
                "long_token",
                format!("token length {token_len}"),
            );
        }
        StepResult::Continue(Validated::new(event))
    }

    fn name(&self) -> &'static str {
        "validate"
    }
}
