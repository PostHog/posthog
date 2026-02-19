use std::future::Future;

use crate::types::batch::Batch;

/// Stages are the building blocks of a pipeline.
/// Each stage takes a batch of items as input and produces a batch of items as output.
/// They control how operators are executed and how errors are handled.
pub trait Stage {
    type Input;
    type Output;
    type Error;

    fn name(&self) -> &'static str;

    fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> impl Future<Output = Result<Batch<Self::Output>, Self::Error>>;
}

#[allow(type_alias_bounds)]
pub type StageResult<T: Stage> = Result<Batch<T::Output>, T::Error>;
