use std::sync::Arc;

use crate::{
    app_context::AppContext,
    error::{PipelineFailure, PipelineResult},
    stages::consumer_pipeline::ConsumerEventPipeline,
    types::{batch::Batch, stage::Stage},
};

pub async fn do_exception_handling(
    events: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    let pipeline = ConsumerEventPipeline::new(context);
    let input_batch = Batch::from(events);
    let output_batch_events = pipeline.process(input_batch).await?;
    Ok(output_batch_events.into())
}
