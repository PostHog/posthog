//! Port of `pipeline.interface.ts` (`Pipeline`), `start-pipeline.ts` and `step-pipeline.ts`.

use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;

use crate::context::{OkResultWithContext, ResultWithContext};
use crate::metrics::{record_budget_checkpoint, record_step_duration, BudgetCheckpoint};
use crate::results::{NonOk, Outcome};
use crate::steps::ProcessingStep;

/// A single-item processor. An `Err` is the Node `throw`: it crashes the batch.
#[async_trait]
pub trait Pipeline<I, O, C>: Send + Sync {
    async fn process(
        &self,
        input: OkResultWithContext<I, C>,
    ) -> anyhow::Result<ResultWithContext<O, C>>;
}

pub type DynPipeline<I, O, C> = Arc<dyn Pipeline<I, O, C>>;

pub struct StartPipeline;

#[async_trait]
impl<T: Send + 'static, C: Send + 'static> Pipeline<T, T, C> for StartPipeline {
    async fn process(
        &self,
        input: OkResultWithContext<T, C>,
    ) -> anyhow::Result<ResultWithContext<T, C>> {
        Ok(input.into_result())
    }
}

pub struct StepPipeline<I, M, O, C> {
    step: ProcessingStep<M, O>,
    previous: DynPipeline<I, M, C>,
}

impl<I, M, O, C> StepPipeline<I, M, O, C> {
    pub fn new(step: ProcessingStep<M, O>, previous: DynPipeline<I, M, C>) -> Self {
        Self { step, previous }
    }
}

#[async_trait]
impl<I, M, O, C> Pipeline<I, O, C> for StepPipeline<I, M, O, C>
where
    I: Send + 'static,
    M: Send + 'static,
    O: Send + 'static,
    C: Send + 'static,
{
    async fn process(
        &self,
        input: OkResultWithContext<I, C>,
    ) -> anyhow::Result<ResultWithContext<O, C>> {
        let previous = self.previous.process(input).await?;
        let (value, mut context) = match previous.into_ok() {
            Ok(ok) => (ok.value, ok.context),
            Err((non_ok, context)) => {
                return Ok(ResultWithContext::<M, C>::non_ok(non_ok, context))
            }
        };

        let step_name = self.step.name();
        // lastStep keeps the step that spent the time; the reason names the step that never started.
        if context.budget.as_ref().is_some_and(|b| b.exhausted()) {
            record_budget_checkpoint(BudgetCheckpoint::Step, step_name.clone());
            return Ok(ResultWithContext {
                result: Outcome::NonOk(NonOk::Timeout {
                    reason: format!("budget exceeded before {step_name}"),
                }),
                context,
            });
        }

        let started = Instant::now();
        let result = match self.step.call(value).await {
            Ok(result) => {
                record_step_duration(
                    step_name.clone(),
                    "element",
                    result.result_type().as_label(),
                    started.elapsed().as_secs_f64(),
                );
                result
            }
            Err(error) => {
                record_step_duration(
                    step_name.clone(),
                    "element",
                    "exception",
                    started.elapsed().as_secs_f64(),
                );
                tracing::error!(
                    step = %step_name,
                    error = %error,
                    debug_context = ?context.debug_context,
                    "Step threw"
                );
                return Err(error);
            }
        };

        let outcome = context.absorb_step(step_name, result);
        Ok(ResultWithContext {
            result: outcome,
            context,
        })
    }
}
