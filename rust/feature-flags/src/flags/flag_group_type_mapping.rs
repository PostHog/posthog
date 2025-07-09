use std::collections::HashMap;

use common_database::PostgresReader;
use common_metrics::inc;
use common_types::ProjectId;
use sqlx::FromRow;
use tracing::error;

use crate::{api::errors::FlagError, metrics::consts::FLAG_EVALUATION_ERROR_COUNTER};

pub type GroupTypeIndex = i32;

#[derive(Debug, FromRow)]
pub struct GroupTypeMapping {
    pub group_type: String,
    pub group_type_index: GroupTypeIndex,
}

/// This struct is a cache for group type mappings, which are stored in a DB.  We use these mappings
/// to look up group names based on the group aggregation indices stored on flag filters, which lets us
/// perform group property matching.  We cache them per request so that we can perform multiple flag evaluations
/// without needing to fetch the mappings from the DB each time.
/// Typically, the mappings look like this:
///
/// let group_types = vec![
///     ("project", 0),
///     ("organization", 1),
///     ("instance", 2),
///     ("customer", 3),
///     ("team", 4),  ];
///
/// But for backwards compatibility, we also support whatever mappings may lie in the table.
/// These mappings are ingested via the plugin server.
#[derive(Clone, Debug)]
pub struct GroupTypeMappingCache {
    project_id: ProjectId,
    group_types_to_indexes: HashMap<String, GroupTypeIndex>,
    group_indexes_to_types: HashMap<GroupTypeIndex, String>,
}

impl GroupTypeMappingCache {
    pub fn new(project_id: ProjectId) -> Self {
        GroupTypeMappingCache {
            project_id,
            group_types_to_indexes: HashMap::new(),
            group_indexes_to_types: HashMap::new(),
        }
    }

    pub async fn init(&mut self, reader: PostgresReader) -> Result<(), FlagError> {
        let mapping = self
            .fetch_group_type_mapping(reader, self.project_id)
            .await?;

        if mapping.is_empty() {
            let reason = "no_group_type_mappings";
            error!(
                "No group type mappings found for project {}",
                self.project_id
            );
            inc(
                FLAG_EVALUATION_ERROR_COUNTER,
                &[("reason".to_string(), reason.to_string())],
                1,
            );
            return Err(FlagError::NoGroupTypeMappings);
        }

        self.group_types_to_indexes = mapping.clone();
        self.group_indexes_to_types = mapping.into_iter().map(|(k, v)| (v, k)).collect();
        Ok(())
    }

    pub fn get_group_types_to_indexes(
        &self,
    ) -> Result<&HashMap<String, GroupTypeIndex>, FlagError> {
        if self.group_types_to_indexes.is_empty() {
            return Err(FlagError::NoGroupTypeMappings);
        }
        Ok(&self.group_types_to_indexes)
    }

    pub fn get_group_type_index_to_type_map(
        &self,
    ) -> Result<&HashMap<GroupTypeIndex, String>, FlagError> {
        if self.group_indexes_to_types.is_empty() {
            return Err(FlagError::NoGroupTypeMappings);
        }
        Ok(&self.group_indexes_to_types)
    }

    async fn fetch_group_type_mapping(
        &self,
        reader: PostgresReader,
        project_id: ProjectId,
    ) -> Result<HashMap<String, GroupTypeIndex>, FlagError> {
        let mut conn = reader.as_ref().get_connection().await?;

        let query = r#"
            SELECT group_type, group_type_index 
            FROM posthog_grouptypemapping 
            WHERE project_id = $1
        "#;

        let rows = sqlx::query_as::<_, GroupTypeMapping>(query)
            .bind(project_id)
            .fetch_all(&mut *conn)
            .await?;

        Ok(rows
            .into_iter()
            .map(|row| (row.group_type, row.group_type_index))
            .collect())
    }

    #[cfg(test)]
    pub fn set_test_mappings(
        &mut self,
        types_to_indexes: HashMap<String, GroupTypeIndex>,
        indexes_to_types: HashMap<GroupTypeIndex, String>,
    ) {
        self.group_types_to_indexes = types_to_indexes;
        self.group_indexes_to_types = indexes_to_types;
    }
}
