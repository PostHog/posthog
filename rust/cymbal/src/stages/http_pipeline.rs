use std::{collections::HashMap, sync::Arc};

use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    metric_consts::HTTP_EXCEPTION_PIPELINE,
    stages::pipeline::{ExceptionEventHandledError, ExceptionEventPipeline},
    types::{
        batch::Batch,
        event::{AnyEvent, PropertiesContainer},
        exception_properties::ExceptionProperties,
        stage::Stage,
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
    type Output = AnyEvent;
    type Error = UnhandledError;

    fn name(&self) -> &'static str {
        HTTP_EXCEPTION_PIPELINE
    }

    async fn process(
        self,
        batch: Batch<Self::Input>,
    ) -> Result<Batch<Self::Output>, UnhandledError> {
        let mut events_by_id: HashMap<_, _> = HashMap::new();
        batch
            .map(any_to_props, &mut events_by_id)
            .apply_stage(ExceptionEventPipeline::new(self.app_context.clone()))
            .await?
            .try_filter_map(handle_res, &mut events_by_id)
    }
}

fn any_to_props(
    evt: AnyEvent,
    map: &mut HashMap<Uuid, AnyEvent>,
) -> Result<ExceptionProperties, ExceptionEventHandledError> {
    let item_uuid = evt.uuid;
    map.insert(item_uuid, evt.clone());
    ExceptionProperties::try_from(evt)
        .map_err(|err| ExceptionEventHandledError::new(item_uuid, err))
}

fn handle_res(
    res: Result<ExceptionProperties, ExceptionEventHandledError>,
    events_by_id: &mut HashMap<Uuid, AnyEvent>,
) -> Result<Option<AnyEvent>, UnhandledError> {
    let item: Option<AnyEvent> = match res {
        Err(ExceptionEventHandledError { uuid, error }) => match error {
            EventError::Suppressed(_) => None,
            err => {
                let mut original_evt = events_by_id
                    .remove(&uuid)
                    .ok_or(UnhandledError::Other("missing event".into()))?;
                original_evt.attach_error(err.to_string())?;
                Some(original_evt)
            }
        },
        Ok(props) => {
            let mut original_evt = events_by_id
                .remove(&props.uuid)
                .ok_or(UnhandledError::Other("missing event".into()))?;
            original_evt.set_properties(props)?;
            Some(original_evt)
        }
    };
    Ok(item)
}
