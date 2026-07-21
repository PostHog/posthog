//! `ApplyQuota` — billing-quota check (fallible; must be `fail_open()`-wrapped).

use crate::events::capabilities::{HasEventName, HasToken};
use crate::framework::result::{NoOutputs, StepResult};
use crate::framework::step::FallibleStep;

/// An unexpected error from the quota limiter (e.g. Redis unavailable).
#[derive(Debug)]
pub struct QuotaError;

/// Billing-quota check. Fallible: it returns `Err` when its backing store is
/// unavailable, so it must be `fail_open()`-wrapped before joining the (infallible)
/// capture chain. On the happy path it drops over-quota events.
///
/// Open by default: generic over any `In: HasToken + HasEventName`, output equals
/// input (a pure filter).
pub struct ApplyQuota {
    /// A token whose lookup simulates an infra failure (returns `Err`).
    pub failing_token: &'static str,
}

impl<In, Fx> FallibleStep<In, Fx> for ApplyQuota
where
    In: HasToken + HasEventName,
{
    type Out = In;
    type Outputs = NoOutputs;
    type Error = QuotaError;

    fn apply(&self, event: In, _fx: &mut Fx) -> Result<StepResult<In, NoOutputs>, QuotaError> {
        if event.token() == self.failing_token {
            return Err(QuotaError); // limiter unavailable
        }
        if event.event_name() == "quota_blocked" {
            return Ok(StepResult::Drop {
                reason: "quota_limited",
            });
        }
        Ok(StepResult::Continue(event))
    }

    fn name(&self) -> &'static str {
        "apply_quota"
    }
}
