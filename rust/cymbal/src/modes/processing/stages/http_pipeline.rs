use std::sync::Arc;

use common_ingestion_response::codes;

use crate::{
    app_context::AppContext,
    error::{contain_failure, EventError, UnhandledError},
    metric_consts::{HTTP_EXCEPTION_PIPELINE, POST_PROCESSING_STAGE},
    stages::pipeline::{create_pre_post_processing, ExceptionEventPipeline, HandledError},
    types::{
        batch::Batch,
        event::{AnyEvent, ProcessOutcome, PropertiesContainer},
        exception_event::{ExceptionEvent, Finalized},
        stage::{Stage, StageResult},
    },
};

pub struct HttpEventPipeline {
    app_context: Arc<AppContext>,
    isolate_event_failures: bool,
}

impl HttpEventPipeline {
    pub fn new(app_context: Arc<AppContext>, isolate_event_failures: bool) -> Self {
        Self {
            app_context,
            isolate_event_failures,
        }
    }
}

impl Stage for HttpEventPipeline {
    type Input = AnyEvent;
    type Output = ProcessOutcome;

    fn name(&self) -> &'static str {
        HTTP_EXCEPTION_PIPELINE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        // Counted before any processing starts, so the count covers every event of a hot team.
        if let Some(slots) = &self.app_context.team_db_slots {
            slots.record_hot_arrivals(batch.inner_ref().iter().map(|event| event.team_id));
        }
        let (preprocess, postprocess) =
            create_pre_post_processing(batch.len(), Box::new(handle_result));
        // Sanitize first: pre-processing keeps this copy and returns it unchanged on failure.
        let drop_team_ids = self.app_context.drop_code_variables_team_ids.clone();
        let batch = batch.map(
            |mut event, ()| {
                event.drop_adaptive_ingestion_properties();
                if drop_team_ids.contains(&event.team_id) {
                    event.drop_code_variables();
                } else {
                    event.mask_code_variables();
                }
                event
            },
            &mut (),
        );
        batch
            .apply_stage(preprocess)
            .await?
            .apply_stage(ExceptionEventPipeline::new(
                self.app_context.clone(),
                self.isolate_event_failures,
            ))
            .await?
            .apply_stage(postprocess)
            .await
    }
}

fn handle_result(
    mut original: AnyEvent,
    processed: Result<ExceptionEvent<Finalized>, HandledError>,
) -> Result<ProcessOutcome, UnhandledError> {
    let attached = match processed {
        Ok(props) => original.set_properties(props.into_clickhouse_properties()),
        Err(EventError::Suppressed(_)) => return Ok(ProcessOutcome::Dropped("suppressed")),
        Err(EventError::SuppressedByRule(_)) => {
            return Ok(ProcessOutcome::Dropped("suppressed_by_rule"))
        }
        Err(EventError::RateLimitedPerIssue(_)) => {
            return Ok(ProcessOutcome::Dropped("rate_limited_per_issue"))
        }
        Err(EventError::RateLimitedProject(_)) => {
            return Ok(ProcessOutcome::Dropped("rate_limited_project"))
        }
        Err(EventError::ProcessingFailed {
            code,
            message,
            retriable,
        }) => return Ok(ProcessOutcome::unprocessed(code, message, retriable)),
        Err(err) => original.attach_error(err.to_string()),
    };
    Ok(match contain_failure(POST_PROCESSING_STAGE, attached)? {
        Ok(()) => ProcessOutcome::Ok(original),
        Err(EventError::ProcessingFailed {
            code,
            message,
            retriable,
        }) => ProcessOutcome::unprocessed(code, message, retriable),
        Err(err) => ProcessOutcome::Failed {
            code: codes::INVALID_INPUT,
            message: err.to_string(),
        },
    })
}
