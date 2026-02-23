use std::sync::Arc;

use crate::{
    app_context::AppContext,
    error::{PipelineFailure, PipelineResult},
    stages::consumer_pipeline::ConsumerEventPipeline,
    types::batch::Batch,
};

pub async fn do_exception_handling(
    events: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    let pipeline = ConsumerEventPipeline::new(context);
    let input_batch = Batch::from(events);
    let output_batch_events = input_batch.apply_stage(pipeline).await?;
    Ok(output_batch_events.into())
}
