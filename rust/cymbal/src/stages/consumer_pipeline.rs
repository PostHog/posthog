use common_types::ClickHouseEvent;
use std::sync::Arc;

use crate::{
    app_context::AppContext,
    error::{EventError, PipelineResult, UnhandledError},
    metric_consts::CONSUMER_EXCEPTION_PIPELINE,
    stages::pipeline::{create_pre_post_processing, ExceptionEventPipeline},
    types::{
        batch::Batch, event::PropertiesContainer, exception_properties::ExceptionProperties,
        stage::Stage,
    },
};

pub struct ConsumerEventPipeline {
    app_context: Arc<AppContext>,
}

impl ConsumerEventPipeline {
    pub fn new(ctx: Arc<AppContext>) -> Self {
        ConsumerEventPipeline { app_context: ctx }
    }
}

impl Stage for ConsumerEventPipeline {
    type Input = PipelineResult;
    type Output = PipelineResult;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        CONSUMER_EXCEPTION_PIPELINE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        let (preprocess, postprocess) =
            create_pre_post_processing(batch.len(), Box::new(handle_result));
        batch
            // preprocess by converting items
            .apply_stage(preprocess)
            .await?
            .apply_stage(ExceptionEventPipeline::new(self.app_context.clone()))
            .await?
            // postprocess by attaching properties or error to clickhouse events
            .apply_stage(postprocess)
            .await
    }
}

fn handle_result(
    input: PipelineResult,
    output: Result<ExceptionProperties, EventError>,
) -> Result<PipelineResult, UnhandledError> {
    let Ok(mut clickhouse_event) = input else {
        let input_error = input.expect_err("input should be an event error");
        let output_error = output.expect_err("output should be an event error");
        // errors should be the same as we just forward it
        assert_eq!(
            input_error, output_error,
            "error mismatch: input_error: {input_error}, output_error: {output_error}"
        );
        return Ok(Err(input_error));
    };
    let new_item = match output {
        Ok(props) => {
            clickhouse_event.set_properties(props)?;
            Ok(clickhouse_event)
        }
        Err(err) => match err {
            // we keep suppressed errors to drop events later in the pipeline
            EventError::Suppressed(_) => Err(err),
            // we attach error to original event and continue
            evt_err => {
                clickhouse_event
                    .attach_error(evt_err.to_string())
                    .expect("failed to attach error");
                Ok(clickhouse_event)
            }
        },
    };
    Ok(new_item)
}

impl PropertiesContainer for ClickHouseEvent {
    fn set_properties(&mut self, new_props: ExceptionProperties) -> Result<(), UnhandledError> {
        self.properties = Some(serde_json::to_string(&new_props)?);
        Ok(())
    }

    fn attach_error(&mut self, error: String) -> Result<(), UnhandledError> {
        let mut props = self.take_raw_properties()?;
        let mut errors = match props.remove("$cymbal_errors") {
            Some(serde_json::Value::Array(errors)) => errors,
            _ => Vec::new(),
        };

        errors.push(serde_json::Value::String(error));
        props.insert(
            "$cymbal_errors".to_string(),
            serde_json::Value::Array(errors),
        );
        self.set_raw_properties(props)?;
        Ok(())
    }
}
