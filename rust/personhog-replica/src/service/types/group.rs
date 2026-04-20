use personhog_proto::personhog::types::v1::{Group, GroupTypeMapping};

use crate::storage;

impl From<storage::Group> for Group {
    fn from(group: storage::Group) -> Self {
        Group {
            id: group.id,
            team_id: group.team_id,
            group_type_index: group.group_type_index,
            group_key: group.group_key,
            group_properties: serde_json::to_vec(&group.group_properties).unwrap_or_default(),
            created_at: group.created_at.timestamp_millis(),
            properties_last_updated_at: group
                .properties_last_updated_at
                .map(|v| serde_json::to_vec(&v).unwrap_or_default())
                .unwrap_or_default(),
            properties_last_operation: group
                .properties_last_operation
                .map(|v| serde_json::to_vec(&v).unwrap_or_default())
                .unwrap_or_default(),
            version: group.version,
        }
    }
}

impl From<storage::GroupTypeMapping> for GroupTypeMapping {
    fn from(mapping: storage::GroupTypeMapping) -> Self {
        GroupTypeMapping {
            id: mapping.id,
            team_id: mapping.team_id,
            project_id: mapping.project_id,
            group_type: mapping.group_type,
            group_type_index: mapping.group_type_index,
            name_singular: mapping.name_singular,
            name_plural: mapping.name_plural,
            default_columns: mapping
                .default_columns
                .map(|v| serde_json::to_vec(&v).unwrap_or_default()),
            detail_dashboard_id: mapping.detail_dashboard_id,
            created_at: mapping.created_at.map(|t| t.timestamp_millis()),
        }
    }
}
