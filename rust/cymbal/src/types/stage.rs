use std::future::Future;

use crate::{error::UnhandledError, types::batch::Batch};

// Stages are shared context between operators with the lifetime of the batch
// They also control how operators are executed and how errors are handled.
pub trait Stage {
    type Item: Send;

    fn pre_process<B: Batch<Self::Item>>(
        &self,
        batch: B,
    ) -> impl Future<Output = Result<B, UnhandledError>> {
        async move { Ok(batch) }
    }

    fn process(
        &self,
        batch: impl Batch<Self::Item>,
    ) -> impl Future<Output = Result<impl Batch<Self::Item>, UnhandledError>> {
        async move { Ok(batch) }
    }

    fn post_process<B: Batch<Self::Item>>(
        &self,
        batch: B,
    ) -> impl Future<Output = Result<B, UnhandledError>> {
        async move { Ok(batch) }
    }
}
