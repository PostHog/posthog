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
    mut events: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    let pipeline = ConsumerEventPipeline::new(context);
    let cloned_events = events.clone();

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
        cloned_events
            .into_iter()
            .filter_map(|item| item.ok())
            .collect::<Vec<_>>(),
    );

    let output_batch_events = pipeline.process(input_batch_events).await?;

    // Remap events
    for event in output_batch_events.into_iter() {
        match event {
            Ok(evt) => {
                let index = id_to_indices.get(&evt.uuid).unwrap();
                events[*index] = Ok(evt);
            }
            Err(err) => {
                let index = id_to_indices.get(&err.uuid).unwrap();
                events[*index] = Err(err.error);
            }
        }
    }

    Ok(events)
}
