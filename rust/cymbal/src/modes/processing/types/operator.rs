use std::future::Future;

pub use crate::core::ids::TeamId;
use crate::error::{contain_failure, EventError, UnhandledError};

/// An Operator is a stateless function that can be applied in parallel to items in a batch.
pub trait Operator {
    type Context: Clone + Send;
    type Input: Send;
    type Output: Send;
    type Error: Send;

    fn name(&self) -> &'static str;
    fn execute(
        &self,
        input: Self::Input,
        ctx: Self::Context,
    ) -> impl Future<Output = Result<Self::Output, Self::Error>> + Send;
}

/// A Value Operator is a specific type of Operator that can be applied to a batch of results.
/// Handled errors will wrap the output and allow the processing of the batch to continue
/// Unhandled errors stop the processing of the whole batch, unless the item's own data caused them
pub trait ValueOperator {
    type Context: Clone + Send;
    type Item: Send;
    type HandledError: Send;
    type UnhandledError: Send;

    fn name(&self) -> &'static str;
    fn execute_value(
        &self,
        input: Self::Item,
        ctx: Self::Context,
    ) -> impl Future<Output = Result<Result<Self::Item, Self::HandledError>, Self::UnhandledError>> + Send;
}

impl<T, C, I> Operator for T
where
    I: Send,
    C: Clone + Send,
    T: ValueOperator<
            Context = C,
            Item = I,
            HandledError = EventError,
            UnhandledError = UnhandledError,
        > + Sync,
{
    type Context = T::Context;
    type Input = Result<T::Item, T::HandledError>;
    type Output = Result<T::Item, T::HandledError>;
    type Error = T::UnhandledError;

    fn name(&self) -> &'static str {
        self.name()
    }

    async fn execute(
        &self,
        item: Self::Input,
        ctx: Self::Context,
    ) -> Result<Self::Output, Self::Error> {
        match item {
            Err(e) => Ok(Err(e)),
            Ok(value) => Ok(
                contain_failure(self.name(), self.execute_value(value, ctx).await)?
                    .and_then(|handled| handled),
            ),
        }
    }
}

#[allow(type_alias_bounds)]
pub type OperatorResult<T: ValueOperator> =
    Result<Result<T::Item, T::HandledError>, T::UnhandledError>;
