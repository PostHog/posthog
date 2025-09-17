use std::collections::HashMap;

use common_types::PersonMode;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    app_context::AppContext,
    error::{PipelineFailure, PipelineResult},
};

// Simple helper "view" into the props object, for this stage
#[derive(Debug, Clone, Serialize, Deserialize)]
struct GroupsProps {
    #[serde(rename = "$groups", skip_serializing_if = "Option::is_none")]
    groups: Option<HashMap<String, String>>,

    #[serde(flatten)]
    other: HashMap<String, Value>,
}

pub async fn map_group_types(
    mut events: Vec<PipelineResult>,
    context: &AppContext,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    let mut mappings = HashMap::new();
    for (i, event) in events.iter().enumerate() {
        let Ok(event) = event else {
            continue;
        };

        if mappings.contains_key(&event.team_id) {
            continue;
        }

        let group_type_mappings = context
            .team_manager
            .get_group_types(&context.pool, event.team_id)
            .await
            .map_err(|e| (i, e))?;

        if group_type_mappings.is_empty() {
            continue;
        }

        mappings.insert(event.team_id, group_type_mappings);
    }

    for event in events.iter_mut() {
        let Ok(event) = event else {
            continue;
        };

        let Some(mappings) = mappings.get(&event.team_id) else {
            continue; // We skip teams with no mapping
        };

        if !matches!(event.person_mode, PersonMode::Full) {
            continue; // We don't do group processing on personless events (force-upgrade or propertyless)
        }

        let Some(props) = &event.properties else {
            continue;
        };

        let Ok(groups_props) = serde_json::from_str::<GroupsProps>(props) else {
            // This either means we couldn't parse the groups object (if, say, it's an invalid shape with e.g. an object as a key)
            // Either way, we simply skip group identification here.
            continue;
        };

        let Some(groups) = &groups_props.groups else {
            continue;
        };

        let mut indexed_groups = HashMap::new();

        for mapping in mappings {
            let Some(id) = groups.get(&mapping.group_type) else {
                continue;
            };
            indexed_groups.insert(
                format!("$group_{}", mapping.group_type_index),
                Value::String(id.clone()),
            );
        }

        let mut final_props = groups_props;
        final_props.other.extend(indexed_groups);
        event.properties = Some(
            serde_json::to_string(&final_props)
                .expect("Failed to serialize properties we successfully deserialized"),
        );
    }

    Ok(events)
}
