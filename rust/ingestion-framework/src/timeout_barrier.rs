//! Port of `timeout-barrier-pipeline.ts`.

use std::sync::Arc;

use async_trait::async_trait;

use crate::budget::BatchBudget;
use crate::context::{OkResultWithContext, ResultWithContext};
use crate::metrics::{record_budget_checkpoint, BudgetCheckpoint};
use crate::pipeline::{DynPipeline, Pipeline};
use crate::results::{NonOk, Outcome};

const TIMEOUT_BARRIER: &str = "timeoutBarrier";

/// The last budget checkpoint. An element that reaches it with time left continues with an
/// unlimited budget, so it always finishes. An exhausted element stops here.
pub struct TimeoutBarrierPipeline<I, O, C> {
    previous: DynPipeline<I, O, C>,
}

impl<I, O, C> TimeoutBarrierPipeline<I, O, C> {
    pub fn new(previous: DynPipeline<I, O, C>) -> Self {
        Self { previous }
    }
}

#[async_trait]
impl<I, O, C> Pipeline<I, O, C> for TimeoutBarrierPipeline<I, O, C>
where
    I: Send + 'static,
    O: Send + 'static,
    C: Send + 'static,
{
    async fn process(
        &self,
        input: OkResultWithContext<I, C>,
    ) -> anyhow::Result<ResultWithContext<O, C>> {
        let mut result = self.previous.process(input).await?;
        let Some(budget) = result.context.budget.as_ref() else {
            return Ok(result);
        };
        if !result.is_ok() {
            return Ok(result);
        }
        if budget.exhausted() {
            record_budget_checkpoint(BudgetCheckpoint::Step, Arc::from(TIMEOUT_BARRIER));
            return Ok(ResultWithContext {
                result: Outcome::NonOk(NonOk::Timeout {
                    reason: format!("budget exceeded before {TIMEOUT_BARRIER}"),
                }),
                context: result.context,
            });
        }
        if !budget.is_unlimited() {
            result.context.budget = Some(BatchBudget::unlimited());
        }
        Ok(result)
    }
}
