use std::{collections::HashMap, sync::Arc};

use common_types::{format::format_ch_datetime, Person, PersonMode};

use crate::{
    app_context::AppContext,
    error::{PipelineFailure, PipelineResult},
    WithIndices,
};

pub async fn add_person_properties(
    events: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    let mut lookup_handles: HashMap<String, WithIndices<_>> = HashMap::new();
    for (index, event) in events.iter().enumerate() {
        let Ok(event) = event else {
            continue;
        };

        // We simply do not do force upgrading for exception events... and I think that's fine. New product, new rules, etc
        if !matches!(event.person_mode, PersonMode::Full) {
            continue;
        }

        let distinct_id = &event.distinct_id;

        if lookup_handles.contains_key(distinct_id) {
            lookup_handles
                .get_mut(distinct_id)
                .unwrap()
                .indices
                .push(index);
            continue;
        }

        let m_context = context.clone();
        let m_distinct_id = distinct_id.clone();
        let team_id = event.team_id;
        let fut = async move {
            let res = Person::from_distinct_id(&m_context.persons_pool, team_id, &m_distinct_id)
                .await
                .map_err(|e| {
                    tracing::error!("Failed to fetch person {}, {:?}", m_distinct_id, e);
                    e
                });

            match res {
                Ok(p) => Ok(p),
                Err(sqlx::Error::ColumnDecode { .. }) => {
                    // If we failed to decode the person properties, we just put an empty property set on
                    // the event, so e.g. counting exceptions by person still works
                    Person::from_distinct_id_no_props(
                        &m_context.persons_pool,
                        team_id,
                        &m_distinct_id,
                    )
                    .await
                }
                Err(e) => Err(e),
            }
        };

        let handle = tokio::spawn(fut);

        let val = WithIndices {
            indices: vec![index],
            inner: handle,
        };

        lookup_handles.insert(distinct_id.clone(), val);
    }

    let mut persons_lut = HashMap::new();
    for (distinct_id, val) in lookup_handles {
        let handle = val.inner;
        let person = handle
            .await
            .expect("Task completes")
            .map_err(|e| (val.indices[0], e.into()))?;

        persons_lut.insert(distinct_id, person);
    }

    let mut events = events;

    for (i, event) in events.iter_mut().enumerate() {
        let Ok(event) = event else {
            continue;
        };

        if !matches!(event.person_mode, PersonMode::Full) {
            continue;
        }

        let person = persons_lut
            .get(&event.distinct_id)
            .expect("All person lookups were done");

        let Some(person) = person else {
            continue;
        };

        event.person_created_at = Some(format_ch_datetime(person.created_at));
        event.person_id = Some(person.uuid.to_string());
        event.person_properties =
            Some(serde_json::to_string(&person.properties).map_err(|e| (i, e.into()))?);
    }

    Ok(events)
}
