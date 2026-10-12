use std::sync::Arc;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
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
        // Drop or mask first: pre-processing keeps this copy and returns it unchanged on failure.
        let drop_team_ids = self.app_context.drop_code_variables_team_ids.clone();
        let batch = batch.map(
            |mut event, ()| {
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
            .apply_stage(ExceptionEventPipeline::new(self.app_context.clone()))
            .await?
            .apply_stage(postprocess)
            .await
    }
}

fn handle_result(
    mut original: AnyEvent,
    processed: Result<ExceptionEvent<Finalized>, HandledError>,
) -> Result<Option<AnyEvent>, UnhandledError> {
    let item: Option<AnyEvent> = match processed {
        Ok(props) => {
            original.set_properties(props.into_clickhouse_properties())?;
            Some(original)
        }
        Err(err) => match err {
            EventError::Suppressed(_)
            | EventError::SuppressedByRule(_)
            | EventError::RateLimitedPerIssue(_)
            | EventError::RateLimitedProject(_) => None,
            err => {
                original.attach_error(err.to_string())?;
                if let Some(reason) = err.dlq_reason() {
                    original.mark_for_dlq(reason)?;
                }
                Some(original)
            }
        },
    };
    Ok(item)
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use serde_json::json;
    use uuid::Uuid;

    use super::*;

    fn event(uuid: Uuid) -> AnyEvent {
        AnyEvent {
            uuid,
            event: "$exception".to_string(),
            team_id: 1,
            timestamp: String::new(),
            properties: json!({ "$exception_list": [] }),
            others: HashMap::new(),
        }
    }

    #[test]
    fn exception_too_large_is_marked_for_dlq() {
        let uuid = Uuid::from_u128(1);
        let out = handle_result(event(uuid), Err(EventError::ExceptionTooLarge(uuid, 5, 4)))
            .unwrap()
            .expect("event is returned so the caller can dead-letter it");

        assert_eq!(out.properties["$cymbal_dlq_reason"], "exception_too_large");
        assert!(out.properties["$cymbal_errors"].is_array());
    }

    #[test]
    fn other_handled_errors_are_not_marked_for_dlq() {
        let uuid = Uuid::from_u128(1);
        let out = handle_result(event(uuid), Err(EventError::EmptyExceptionList(uuid)))
            .unwrap()
            .expect("event is returned with the error attached");

        assert!(out.properties.get("$cymbal_dlq_reason").is_none());
        assert!(out.properties["$cymbal_errors"].is_array());
    }
}
