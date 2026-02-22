use std::sync::Arc;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    metric_consts::HTTP_EXCEPTION_PIPELINE,
    stages::pipeline::{create_pre_post_processing, ExceptionEventPipeline, HandledError},
    types::{
        batch::Batch,
        event::{AnyEvent, PropertiesContainer},
        exception_properties::ExceptionProperties,
        stage::{Stage, StageResult},
    },
};

pub struct HttpEventPipeline {
    app_context: Arc<AppContext>,
}

impl HttpEventPipeline {
    pub fn new(app_context: Arc<AppContext>) -> Self {
        Self { app_context }
    }
}

impl Stage for HttpEventPipeline {
    type Input = AnyEvent;
    type Output = Option<AnyEvent>;

    fn name(&self) -> &'static str {
        HTTP_EXCEPTION_PIPELINE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let (preprocess, postprocess) =
            create_pre_post_processing(batch.len(), Box::new(handle_result));
        batch
            .apply_stage(preprocess)
            .await?
            .apply_stage(ExceptionEventPipeline::new(self.app_context.clone()))
            .await?
            .apply_stage(postprocess)
            .await
    }
}

fn handle_result(
    mut original: AnyEvent,
    processed: Result<ExceptionProperties, HandledError>,
) -> Result<Option<AnyEvent>, UnhandledError> {
    let item: Option<AnyEvent> = match processed {
        Ok(props) => {
            original.set_properties(props)?;
            Some(original)
        }
        Err(err) => match err {
            EventError::Suppressed(_) => None,
            err => {
                original.attach_error(err.to_string())?;
                Some(original)
            }
        },
    };
    Ok(item)
}
