use std::collections::HashMap;

use common_metrics::inc;
use common_types::ProjectId;
use sqlx::FromRow;

use crate::{
    api::errors::FlagError,
    metrics::{consts::FLAG_EVALUATION_ERROR_COUNTER, utils::parse_exception_for_prometheus_label},
};

use super::flag_matching::PostgresReader;

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
#[derive(Clone)]
pub struct GroupTypeMappingCache {
    project_id: ProjectId,
    failed_to_fetch_flags: bool,
    group_types_to_indexes: HashMap<String, GroupTypeIndex>,
    group_indexes_to_types: HashMap<GroupTypeIndex, String>,
    reader: PostgresReader,
}

impl GroupTypeMappingCache {
    pub fn new(project_id: ProjectId, reader: PostgresReader) -> Self {
        GroupTypeMappingCache {
            project_id,
            failed_to_fetch_flags: false,
            group_types_to_indexes: HashMap::new(),
            group_indexes_to_types: HashMap::new(),
            reader,
        }
    }

    pub fn get_group_types_to_indexes(&self) -> &HashMap<String, GroupTypeIndex> {
        &self.group_types_to_indexes
    }

    pub async fn group_type_to_group_type_index_map(
        &mut self,
    ) -> Result<HashMap<String, GroupTypeIndex>, FlagError> {
        if self.failed_to_fetch_flags {
            return Err(FlagError::DatabaseUnavailable);
        }

        if !self.group_types_to_indexes.is_empty() {
            return Ok(self.group_types_to_indexes.clone());
        }

        let mapping = match self
            .fetch_group_type_mapping(self.reader.clone(), self.project_id)
            .await
        {
            Ok(mapping) if !mapping.is_empty() => mapping,
            Ok(_) => {
                self.failed_to_fetch_flags = true;
                let reason = "no_group_type_mappings";
                inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), reason.to_string())],
                    1,
                );
                return Err(FlagError::NoGroupTypeMappings);
            }
            Err(e) => {
                self.failed_to_fetch_flags = true;
                let reason = parse_exception_for_prometheus_label(&e);
                inc(
                    FLAG_EVALUATION_ERROR_COUNTER,
                    &[("reason".to_string(), reason.to_string())],
                    1,
                );
                return Err(e);
            }
        };
        self.group_types_to_indexes.clone_from(&mapping);

        Ok(mapping)
    }

    pub async fn group_type_index_to_group_type_map(
        &mut self,
    ) -> Result<HashMap<GroupTypeIndex, String>, FlagError> {
        if !self.group_indexes_to_types.is_empty() {
            return Ok(self.group_indexes_to_types.clone());
        }

        let types_to_indexes = self.group_type_to_group_type_index_map().await?;
        let result: HashMap<GroupTypeIndex, String> =
            types_to_indexes.into_iter().map(|(k, v)| (v, k)).collect();

        if !result.is_empty() {
            self.group_indexes_to_types.clone_from(&result);
            Ok(result)
        } else {
            let reason = "no_group_type_mappings";
            inc(
                FLAG_EVALUATION_ERROR_COUNTER,
                &[("reason".to_string(), reason.to_string())],
                1,
            );
            Err(FlagError::NoGroupTypeMappings)
        }
    }

    async fn fetch_group_type_mapping(
        &mut self,
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

        let mapping: HashMap<String, GroupTypeIndex> = rows
            .into_iter()
            .map(|row| (row.group_type, row.group_type_index))
            .collect();

        if mapping.is_empty() {
            let reason = "no_group_type_mappings";
            inc(
                FLAG_EVALUATION_ERROR_COUNTER,
                &[("reason".to_string(), reason.to_string())],
                1,
            );
            Err(FlagError::NoGroupTypeMappings)
        } else {
            Ok(mapping)
        }
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
