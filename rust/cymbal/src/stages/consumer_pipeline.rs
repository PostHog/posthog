use std::{collections::HashMap, sync::Arc};

use common_types::ClickHouseEvent;
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    metric_consts::CONSUMER_EXCEPTION_PIPELINE,
    stages::pipeline::{ExceptionEventHandledError, ExceptionEventPipeline},
    types::{
        batch::Batch,
        event::{AnyEvent, PropertiesContainer},
        exception_properties::ExceptionProperties,
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
    type Input = ClickHouseEvent;
    type Output = Result<ClickHouseEvent, ExceptionEventHandledError>;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        CONSUMER_EXCEPTION_PIPELINE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        let clickhouse_events_by_id = Arc::new(Mutex::new(HashMap::new()));
        batch
            // Resolve stack traces
            .apply_func(clickhouse_to_props, clickhouse_events_by_id.clone())
            .await?
            .apply_stage(ExceptionEventPipeline::new(self.app_context.clone()))
            .await?
            .apply_func(handle_results, clickhouse_events_by_id.clone())
            .await
    }
}

async fn clickhouse_to_props(
    evt: ClickHouseEvent,
    map: Arc<Mutex<HashMap<Uuid, ClickHouseEvent>>>,
) -> Result<Result<ExceptionProperties, ExceptionEventHandledError>, UnhandledError> {
    let event_uuid = evt.uuid;
    map.lock().await.insert(evt.uuid, evt.clone());
    match AnyEvent::try_from(evt) {
        Ok(evt) => match ExceptionProperties::try_from(evt) {
            Ok(props) => Ok(Ok(props)),
            Err(err) => Ok(Err(ExceptionEventHandledError::new(event_uuid, err))),
        },
        Err(err) => Ok(Err(ExceptionEventHandledError::new(event_uuid, err))),
    }
}

async fn handle_results(
    item: Result<ExceptionProperties, ExceptionEventHandledError>,
    map: Arc<Mutex<HashMap<Uuid, ClickHouseEvent>>>,
) -> Result<Result<ClickHouseEvent, ExceptionEventHandledError>, UnhandledError> {
    let new_item = match item {
        Ok(props) => {
            let mut mutex_guard = map.lock().await;
            let mut original_evt = mutex_guard
                .remove(&props.uuid)
                .ok_or(UnhandledError::Other("Missing event".into()))?;
            original_evt.set_properties(props)?;
            Ok(original_evt)
        }
        Err(err) => match err.error {
            // we keep suppressed errors to drop events later in the pipeline
            EventError::Suppressed(_) => Err(err),
            // we attach error to original event and continue
            evt_err => {
                let mut mutex_guard = map.lock().await;
                let mut original_evt = mutex_guard
                    .remove(&err.uuid)
                    .ok_or(UnhandledError::Other("Missing event".into()))?;
                original_evt.attach_error(evt_err.to_string())?;
                Ok(original_evt)
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
