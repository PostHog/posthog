use std::{collections::HashMap, sync::Arc};

use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    metric_consts::CONSUMER_EXCEPTION_PIPELINE,
    stages::{
        pipeline::{ExceptionEventHandledError, ExceptionEventPipeline},
        post_processing::{
            drop_suppressed::DropSuppressedStage, update_properties::UpdatePropertiesStage,
        },
    },
    types::{
        batch::Batch, event::AnyEvent, exception_properties::ExceptionProperties, stage::Stage,
    },
};

pub struct HttpEventPipeline {
    app_context: Arc<AppContext>,
}

impl Stage for HttpEventPipeline {
    type Input = AnyEvent;
    type Output = Result<AnyEvent, EventError>;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        CONSUMER_EXCEPTION_PIPELINE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        let event_pipeline = ExceptionEventPipeline::new(self.app_context.clone());
        let events_by_id: Arc<Mutex<HashMap<Uuid, AnyEvent>>> =
            Arc::new(Mutex::new(HashMap::new()));
        batch
            .apply_func(any_to_props, events_by_id.clone())
            .await?
            .apply_stage(event_pipeline)
            .await?
            .apply_stage(DropSuppressedStage::new())
            .await?
            .apply_stage(UpdatePropertiesStage::new(events_by_id.clone()))
            .await
    }
}

async fn any_to_props(
    evt: AnyEvent,
    map: Arc<Mutex<HashMap<Uuid, AnyEvent>>>,
) -> Result<Result<ExceptionProperties, ExceptionEventHandledError>, UnhandledError> {
    let item_uuid = evt.uuid.clone();
    map.lock().await.insert(item_uuid, evt.clone());
    Ok(ExceptionProperties::try_from(evt)
        .map_err(|err| ExceptionEventHandledError::new(item_uuid, err)))
}
