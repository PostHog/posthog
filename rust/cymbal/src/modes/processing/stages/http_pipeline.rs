use std::sync::Arc;

use common_ingestion_response::codes;

use crate::{
    app_context::AppContext,
    error::{EventError, EventFailure, UnhandledError},
    metric_consts::HTTP_EXCEPTION_PIPELINE,
    stages::pipeline::{create_pre_post_processing, ExceptionEventPipeline, HandledError},
    types::{
        batch::Batch,
        event::{AnyEvent, PropertiesContainer},
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

#[derive(Debug)]
pub enum ProcessedEvent {
    Event(AnyEvent),
    Dropped(&'static str),
    Failed(EventFailure),
}

impl Stage for HttpEventPipeline {
    type Input = AnyEvent;
    type Output = ProcessedEvent;

    fn name(&self) -> &'static str {
        HTTP_EXCEPTION_PIPELINE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
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
) -> Result<ProcessedEvent, UnhandledError> {
    let err = match processed {
        Ok(props) => {
            original.set_properties(props.into_clickhouse_properties())?;
            return Ok(ProcessedEvent::Event(original));
        }
        Err(err) => err,
    };
    let item = match err {
        EventError::Suppressed(_) => ProcessedEvent::Dropped("suppressed"),
        EventError::SuppressedByRule(_) => ProcessedEvent::Dropped("suppressed_by_rule"),
        EventError::RateLimitedPerIssue(_) => ProcessedEvent::Dropped("rate_limited_per_issue"),
        EventError::RateLimitedProject(_) => ProcessedEvent::Dropped("rate_limited_project"),
        EventError::Failed(_, failure) => ProcessedEvent::Failed(failure),
        err => match original.attach_error(err.to_string()) {
            Ok(()) => ProcessedEvent::Event(original),
            // `properties` that are not an object cannot carry `$cymbal_errors`.
            Err(attach_err) => ProcessedEvent::Failed(EventFailure::fail(
                codes::INVALID_INPUT,
                format!("{err}; cannot attach the error: {attach_err}"),
            )),
        },
    };
    Ok(item)
}
