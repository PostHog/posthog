use std::future::Future;

use crate::error::UnhandledError;

pub type TeamId = i32;

pub trait OperatorContext: Send {}

impl OperatorContext for () {}

pub trait Operator<Context: OperatorContext = ()> {
    type Input;
    type Output;

    fn validate(_: &Self::Input) -> Result<(), String> {
        Ok(())
    }

    fn execute(
        &self,
        input: Self::Input,
        ctx: &Context,
    ) -> impl Future<Output = Result<Self::Output, UnhandledError>> + Send;
}
