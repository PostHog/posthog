use std::{collections::HashMap, sync::Arc};

use common_types::ClickHouseEvent;
use uuid::Uuid;

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
    let mut result = events.clone();

    let id_to_indices: HashMap<Uuid, usize> =
        events
            .iter()
            .enumerate()
            .fold(HashMap::new(), |mut acc, (index, item)| {
                if let Ok(event) = item {
                    acc.insert(event.uuid, index);
                }
                acc
            });

    // We filter out events that errored in previous stages
    let input_batch_events: Batch<ClickHouseEvent> = Batch::from(
        events
            .into_iter()
            .enumerate()
            .filter_map(|(index, item)| match item {
                Ok(event) => Some(event),
                Err(err) => {
                    result[index] = Err(err);
                    None
                }
            })
            .collect::<Vec<_>>(),
    );

    let output_batch_events = pipeline.process(input_batch_events).await?;

    // Remap events
    for event in output_batch_events.into_iter() {
        match event {
            Ok(evt) => {
                let index = id_to_indices.get(&evt.uuid).expect("Event UUID not found");
                result[*index] = Ok(evt);
            }
            Err(err) => {
                let index = id_to_indices.get(&err.uuid).expect("Error UUID not found");
                result[*index] = Err(err.error);
            }
        }
    }

    Ok(result)
}
