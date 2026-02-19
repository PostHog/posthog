use std::sync::{Arc, Mutex};

use crate::{
    error::{EventError, UnhandledError},
    metric_consts::POST_PROCESSING_STAGE,
    stages::{pipeline::ExceptionEventPipelineItem, pre_processing::PreProcessingContext},
    types::{batch::Batch, stage::Stage},
};

pub type PostProcessingHandler<I, O> =
    Box<dyn Fn(I, ExceptionEventPipelineItem) -> Result<O, UnhandledError> + Send>;

pub struct PostProcessingStage<T, O> {
    ctx: Arc<Mutex<PreProcessingContext<T>>>,
    handler: PostProcessingHandler<T, O>,
}

impl<T: Clone, O> PostProcessingStage<T, O> {
    pub fn new(
        ctx: Arc<Mutex<PreProcessingContext<T>>>,
        handler: PostProcessingHandler<T, O>,
    ) -> Self {
        Self { ctx, handler }
    }
}
pub struct PostProcessingError<T> {
    pub original: T,
    pub error: EventError,
}

impl<T: Clone, O> Stage for PostProcessingStage<T, O> {
    type Input = ExceptionEventPipelineItem;
    type Output = O;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        POST_PROCESSING_STAGE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        let mut ctx = self.ctx.lock().expect("failed to lock ctx");
        Ok(Batch::from(
            batch
                .into_iter()
                .enumerate()
                .map(|(index, item)| {
                    let original_item = ctx
                        .take(index)
                        .ok_or(UnhandledError::Other("Missing event".into()))?;
                    (self.handler)(original_item, item)
                })
                .collect::<Result<Vec<_>, UnhandledError>>()?,
        ))
    }
}
