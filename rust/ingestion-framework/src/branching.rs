use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;

use crate::context::{OkResultWithContext, ResultWithContext};
use crate::pipeline::{DynPipeline, Pipeline};
use crate::results::{NonOk, Outcome};

pub type BranchDecisionFn<T> = Arc<dyn Fn(&T) -> String + Send + Sync>;

pub struct BranchingPipeline<I, M, O, C> {
    decision: BranchDecisionFn<M>,
    branches: HashMap<String, DynPipeline<M, O, C>>,
    previous: DynPipeline<I, M, C>,
}

impl<I, M, O, C> BranchingPipeline<I, M, O, C> {
    pub fn new(
        decision: BranchDecisionFn<M>,
        branches: HashMap<String, DynPipeline<M, O, C>>,
        previous: DynPipeline<I, M, C>,
    ) -> Self {
        Self {
            decision,
            branches,
            previous,
        }
    }
}

#[async_trait]
impl<I, M, O, C> Pipeline<I, O, C> for BranchingPipeline<I, M, O, C>
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
        let ok = match previous.into_ok() {
            Ok(ok) => ok,
            Err((non_ok, context)) => {
                return Ok(ResultWithContext::<M, C>::non_ok(non_ok, context))
            }
        };

        let branch_name = (self.decision)(&ok.value);
        match self.branches.get(&branch_name) {
            Some(branch) => branch.process(ok).await,
            None => Ok(ResultWithContext {
                result: Outcome::NonOk(NonOk::Dlq {
                    reason: format!("Unknown branch: {branch_name}"),
                    error: Some(Arc::new(anyhow::anyhow!(
                        "Branch '{branch_name}' not found in branching pipeline"
                    ))),
                }),
                context: ok.context,
            }),
        }
    }
}
