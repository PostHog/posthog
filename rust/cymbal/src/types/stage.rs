use std::future::Future;

use crate::{error::UnhandledError, types::batch::Batch};

// Stages are shared context between operators with the lifetime of the batch
// They also control how operators are executed and how errors are handled.
pub trait Stage {
    type Item;

    fn process(
        self,
        batch: Batch<Self::Item>,
    ) -> impl Future<Output = Result<Batch<Self::Item>, UnhandledError>>;
}
