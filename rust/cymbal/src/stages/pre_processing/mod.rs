use std::sync::{Arc, Mutex};

use crate::{
    error::{EventError, UnhandledError},
    metric_consts::PRE_PROCESSING_STAGE,
    stages::pipeline::ExceptionEventPipelineItem,
    types::{batch::Batch, exception_properties::ExceptionProperties, stage::Stage},
};

pub struct PreProcessingContext<T> {
    pub capacity: usize,
    pub items: Vec<Option<T>>,
}

impl<T> PreProcessingContext<T> {
    pub fn new(capacity: usize) -> Arc<Mutex<Self>> {
        Arc::new(Mutex::new(Self {
            capacity,
            items: Vec::with_capacity(capacity),
        }))
    }

    pub fn take(&mut self, index: usize) -> Option<T> {
        self.items[index].take()
    }
}

pub struct PreProcessingStage<T: TryInto<ExceptionProperties, Error = EventError> + Clone> {
    ctx: Arc<Mutex<PreProcessingContext<T>>>,
}

impl<T: TryInto<ExceptionProperties, Error = EventError> + Clone> PreProcessingStage<T> {
    pub fn new(ctx: Arc<Mutex<PreProcessingContext<T>>>) -> Self {
        Self { ctx }
    }
}

impl<T: TryInto<ExceptionProperties, Error = EventError> + Clone> Stage for PreProcessingStage<T> {
    type Input = T;
    type Output = ExceptionEventPipelineItem;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        PRE_PROCESSING_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> Result<Batch<Self::Output>, Self::Error> {
        let mut ctx = self.ctx.lock().expect("failed to lock ctx");
        Ok(batch
            .into_iter()
            .map(|item| {
                ctx.items.push(Some(item.clone()));
                item.try_into()
            })
            .collect::<Vec<Self::Output>>()
            .into())
    }
}
