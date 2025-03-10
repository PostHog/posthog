use crate::{
    app_context::AppContext,
    error::{PipelineFailure, PipelineResult},
};

// TODO - error tracking is free right now, so billing limits don't really exist? Idk
pub async fn apply_billing_limits(
    buffer: Vec<PipelineResult>,
    _context: &AppContext,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    Ok(buffer)
}
