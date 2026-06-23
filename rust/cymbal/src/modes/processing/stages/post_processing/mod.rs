use std::sync::Arc;

use tokio::sync::Mutex;

use crate::{
    error::UnhandledError,
    metric_consts::POST_PROCESSING_STAGE,
    stages::{pipeline::LinkedItem, pre_processing::PreProcessingContext},
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
    },
};

pub type PostProcessingHandler<I, O> =
    Box<dyn Fn(I, LinkedItem) -> Result<O, UnhandledError> + Send>;

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

impl<T: Clone, O> Stage for PostProcessingStage<T, O> {
    type Input = LinkedItem;
    type Output = O;

    fn name(&self) -> &'static str {
        POST_PROCESSING_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let mut ctx = self.ctx.lock().await;
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
