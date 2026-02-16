use std::marker::PhantomData;

use crate::{
    error::{EventError, UnhandledError},
    metric_consts::DROP_SUPPRESSED_STAGE,
    stages::pipeline::ExceptionEventHandledError,
    types::{batch::Batch, stage::Stage},
};

pub struct DropSuppressedStage<T> {
    _d: PhantomData<T>,
}

impl<T> DropSuppressedStage<T> {
    pub fn new() -> Self {
        Self { _d: PhantomData }
    }
}

impl<T> Stage for DropSuppressedStage<T> {
    type Input = Result<T, ExceptionEventHandledError>;
    type Output = Result<T, ExceptionEventHandledError>;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        DROP_SUPPRESSED_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> Result<Batch<Self::Output>, Self::Error> {
        let output: Vec<Result<T, ExceptionEventHandledError>> = batch
            .into_iter()
            .filter_map(|evt| match evt {
                Err(ExceptionEventHandledError { uuid, error }) => match error {
                    EventError::Suppressed(_) => None,
                    err => Some(Err(ExceptionEventHandledError { uuid, error: err })),
                },
                Ok(evt) => Some(Ok(evt)),
            })
            .collect::<Vec<Result<T, ExceptionEventHandledError>>>();
        Ok(Batch::from(output))
    }
}
