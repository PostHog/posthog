use std::future::Future;

pub type TeamId = i32;

pub trait Operator {
    type Context: Clone + Send;
    type Item: Send;
    type Error: Send;

    fn execute(
        &self,
        input: Self::Item,
        ctx: Self::Context,
    ) -> impl Future<Output = Result<Self::Item, Self::Error>> + Send;
}

pub trait ValueOperator {
    type Context: Clone + Send;
    type Item: Send;
    type HandledError: Send;
    type UnhandledError: Send;

    fn execute_value(
        &self,
        input: Self::Item,
        ctx: Self::Context,
    ) -> impl Future<Output = Result<Result<Self::Item, Self::HandledError>, Self::UnhandledError>> + Send;
}

impl<T, C, I, HE, UE> Operator for T
where
    I: Send,
    UE: Send,
    HE: Send,
    C: Clone + Send,
    T: ValueOperator<Context = C, Item = I, HandledError = HE, UnhandledError = UE> + Sync,
{
    type Context = T::Context;
    type Item = Result<T::Item, T::HandledError>;
    type Error = T::UnhandledError;

    async fn execute(
        &self,
        item: Self::Item,
        ctx: Self::Context,
    ) -> Result<Self::Item, Self::Error> {
        match item {
            Err(e) => Ok(Err(e)),
            Ok(value) => self.execute_value(value, ctx).await,
        }
    }
}

#[allow(type_alias_bounds)]
pub type OperatorResult<T: ValueOperator> =
    Result<Result<T::Item, T::HandledError>, T::UnhandledError>;
