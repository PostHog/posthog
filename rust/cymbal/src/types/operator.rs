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
