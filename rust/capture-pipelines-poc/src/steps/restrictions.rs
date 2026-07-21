//! `ApplyRestrictions` — redirects configured tokens to DLQ or overflow.

use crate::events::capabilities::{HasDistinctId, HasEventName, HasToken};
use crate::events::wrappers::Restricted;
use crate::framework::result::StepResult;
use crate::framework::step::Step;
use crate::pipeline::outputs::AnalyticsOutputs;

/// Event restrictions: redirects configured tokens to the DLQ or overflow output.
/// This is the one demo step with a non-empty `Outputs` set, so it drives the
/// [`OutputRegistry`](crate::framework::outputs::OutputRegistry) completeness check.
///
/// Open by default on input (`In: HasToken + HasDistinctId + HasEventName`). Its
/// `Outputs` is the analytics pipeline's output vocabulary — the redirect targets are
/// domain data, not an input constraint.
pub struct ApplyRestrictions {
    /// Token forced to the DLQ.
    pub dlq_token: &'static str,
    /// Token forced to overflow.
    pub overflow_token: &'static str,
}

impl<In, Fx> Step<In, Fx> for ApplyRestrictions
where
    In: HasToken + HasDistinctId + HasEventName,
{
    type Out = Restricted<In>;
    type Outputs = AnalyticsOutputs;

    fn apply(&self, event: In, _fx: &mut Fx) -> StepResult<Restricted<In>, AnalyticsOutputs> {
        let target = {
            let token = event.token();
            if token == self.dlq_token {
                Some(AnalyticsOutputs::Dlq)
            } else if token == self.overflow_token {
                Some(AnalyticsOutputs::Overflow)
            } else {
                None
            }
        };
        match target {
            Some(AnalyticsOutputs::Dlq) => StepResult::Redirect {
                output: AnalyticsOutputs::Dlq,
                preserve_key: false,
            },
            Some(AnalyticsOutputs::Overflow) => StepResult::Redirect {
                output: AnalyticsOutputs::Overflow,
                // hot key stays on its partition
                preserve_key: true,
            },
            None => StepResult::Continue(Restricted::new(event, false, None)),
        }
    }

    fn name(&self) -> &'static str {
        "apply_restrictions"
    }
}
