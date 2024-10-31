use std::collections::HashSet;
use std::sync::Arc;
use tracing::instrument;

use crate::cohort_models::{Cohort, CohortId, CohortProperty, InnerCohortProperty};
use crate::{api::FlagError, database::Client as DatabaseClient, flag_definitions::PropertyFilter};

impl Cohort {
    /// Returns a cohort from postgres given a cohort_id and team_id
    #[instrument(skip_all)]
    pub async fn from_pg(
        client: Arc<dyn DatabaseClient + Send + Sync>,
        cohort_id: i32,
        team_id: i32,
    ) -> Result<Cohort, FlagError> {
        let mut conn = client.get_connection().await.map_err(|e| {
            tracing::error!("Failed to get database connection: {}", e);
            // TODO should I model my errors more generally?  Like, yes, everything behind this API is technically a FlagError,
            // but I'm not sure if accessing Cohort definitions should be a FlagError (vs idk, a CohortError?  A more general API error?)
            FlagError::DatabaseUnavailable
        })?;

        let query = "SELECT id, name, description, team_id, deleted, filters, query, version, pending_version, count, is_calculating, is_static, errors_calculating, groups, created_by_id FROM posthog_cohort WHERE id = $1 AND team_id = $2";
        let cohort = sqlx::query_as::<_, Cohort>(query)
            .bind(cohort_id)
            .bind(team_id)
            .fetch_optional(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!("Failed to fetch cohort from database: {}", e);
                FlagError::Internal(format!("Database query error: {}", e))
            })?;

        cohort.ok_or_else(|| {
            FlagError::CohortNotFound(format!(
                "Cohort with id {} not found for team {}",
                cohort_id, team_id
            ))
        })
    }

    /// Returns all cohorts for a given team
    #[instrument(skip_all)]
    pub async fn list_from_pg(
        client: Arc<dyn DatabaseClient + Send + Sync>,
        team_id: i32,
    ) -> Result<Vec<Cohort>, FlagError> {
        let mut conn = client.get_connection().await.map_err(|e| {
            tracing::error!("Failed to get database connection: {}", e);
            FlagError::DatabaseUnavailable
        })?;

        let query = "SELECT id, name, description, team_id, deleted, filters, query, version, pending_version, count, is_calculating, is_static, errors_calculating, groups, created_by_id FROM posthog_cohort WHERE team_id = $1";
        let cohorts = sqlx::query_as::<_, Cohort>(query)
            .bind(team_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!("Failed to fetch cohorts from database: {}", e);
                FlagError::Internal(format!("Database query error: {}", e))
            })?;

        Ok(cohorts)
    }

    /// Parses the filters JSON into a CohortProperty structure
    // TODO: this doesn't handle the deprecated "groups" field, see
    // https://github.com/PostHog/posthog/blob/feat/dynamic-cohorts-rust/posthog/models/cohort/cohort.py#L114-L169
    // I'll handle that in a separate PR.
    pub fn parse_filters(&self) -> Result<Vec<PropertyFilter>, FlagError> {
        let cohort_property: CohortProperty = serde_json::from_value(self.filters.clone())
            .map_err(|e| {
                tracing::error!("Failed to parse filters for cohort {}: {}", self.id, e);
                FlagError::CohortFiltersParsingError
            })?;
        Ok(cohort_property
            .properties
            .to_property_filters()
            .into_iter()
            .filter(|f| !(f.key == "id" && f.prop_type == "cohort"))
            .collect())
    }

    /// Extracts dependent CohortIds from the cohort's filters
    pub fn extract_dependencies(&self) -> Result<HashSet<CohortId>, FlagError> {
        let cohort_property: CohortProperty = serde_json::from_value(self.filters.clone())
            .map_err(|e| {
                tracing::error!("Failed to parse filters for cohort {}: {}", self.id, e);
                FlagError::CohortFiltersParsingError
            })?;

        let mut dependencies = HashSet::new();
        Self::traverse_filters(&cohort_property.properties, &mut dependencies)?;
        Ok(dependencies)
    }

    /// Recursively traverses the filter tree to find cohort dependencies
    ///
    /// Example filter tree structure:
    /// ```json
    /// {
    ///   "properties": {
    ///     "type": "OR",
    ///     "values": [
    ///       {
    ///         "type": "OR",
    ///         "values": [
    ///           {
    ///             "key": "id",
    ///             "value": 123,
    ///             "type": "cohort",
    ///             "operator": "exact"
    ///           },
    ///           {
    ///             "key": "email",
    ///             "value": "@posthog.com",
    ///             "type": "person",
    ///             "operator": "icontains"
    ///           }
    ///         ]
    ///       }
    ///     ]
    ///   }
    /// }
    /// ```
    fn traverse_filters(
        inner: &InnerCohortProperty,
        dependencies: &mut HashSet<CohortId>,
    ) -> Result<(), FlagError> {
        for cohort_values in &inner.values {
            for filter in &cohort_values.values {
                if filter.is_cohort() {
                    // Assuming the value is a single integer CohortId
                    if let Some(cohort_id) = filter.value.as_i64() {
                        dependencies.insert(cohort_id as CohortId);
                    } else {
                        return Err(FlagError::CohortFiltersParsingError);
                    }
                }
                // NB: we don't support nested cohort properties, so we don't need to traverse further
            }
        }
        Ok(())
    }
}

impl InnerCohortProperty {
    /// Flattens the nested cohort property structure into a list of property filters.
    ///
    /// The cohort property structure in Postgres looks like:
    /// ```json
    /// {
    ///   "type": "OR",
    ///   "values": [
    ///     {
    ///       "type": "OR",
    ///       "values": [
    ///         {
    ///           "key": "email",
    ///           "value": "@posthog.com",
    ///           "type": "person",
    ///           "operator": "icontains"
    ///         },
    ///         {
    ///           "key": "age",
    ///           "value": 25,
    ///           "type": "person",
    ///           "operator": "gt"
    ///         }
    ///       ]
    ///     }
    ///   ]
    /// }
    /// ```
    pub fn to_property_filters(&self) -> Vec<PropertyFilter> {
        self.values
            .iter()
            .flat_map(|value| &value.values)
            .cloned()
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        cohort_models::{CohortPropertyType, CohortValues},
        test_utils::{
            insert_cohort_for_team_in_pg, insert_new_team_in_pg, setup_pg_reader_client,
            setup_pg_writer_client,
        },
    };
    use serde_json::json;

    #[tokio::test]
    async fn test_cohort_from_pg() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team");

        let cohort = insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            None,
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$initial_browser_version", "type": "person", "value": ["125"], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert cohort");

        let fetched_cohort = Cohort::from_pg(postgres_reader, cohort.id, team.id)
            .await
            .expect("Failed to fetch cohort");

        assert_eq!(fetched_cohort.id, cohort.id);
        assert_eq!(fetched_cohort.name, "Test Cohort");
        assert_eq!(fetched_cohort.team_id, team.id);
    }

    #[tokio::test]
    async fn test_list_from_pg() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team");

        // Insert multiple cohorts for the team
        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Cohort 1".to_string()),
            json!({"properties": {"type": "AND", "values": [{"type": "property", "values": [{"key": "age", "type": "person", "value": [30], "negation": false, "operator": "gt"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert cohort1");

        insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Cohort 2".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "property", "values": [{"key": "country", "type": "person", "value": ["USA"], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert cohort2");

        let cohorts = Cohort::list_from_pg(postgres_reader, team.id)
            .await
            .expect("Failed to list cohorts");

        assert_eq!(cohorts.len(), 2);
        let names: HashSet<String> = cohorts.into_iter().map(|c| c.name).collect();
        assert!(names.contains("Cohort 1"));
        assert!(names.contains("Cohort 2"));
    }

    #[test]
    fn test_cohort_parse_filters() {
        let cohort = Cohort {
            id: 1,
            name: "Test Cohort".to_string(),
            description: None,
            team_id: 1,
            deleted: false,
            filters: json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$initial_browser_version", "type": "person", "value": ["125"], "negation": false, "operator": "exact"}]}]}}),
            query: None,
            version: None,
            pending_version: None,
            count: None,
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups: json!({}),
            created_by_id: None,
        };

        let result = cohort.parse_filters().unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].key, "$initial_browser_version");
        assert_eq!(result[0].value, json!(["125"]));
        assert_eq!(result[0].prop_type, "person");
    }

    #[test]
    fn test_cohort_property_to_property_filters() {
        let cohort_property = InnerCohortProperty {
            prop_type: CohortPropertyType::AND,
            values: vec![CohortValues {
                prop_type: "property".to_string(),
                values: vec![
                    PropertyFilter {
                        key: "email".to_string(),
                        value: json!("test@example.com"),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    },
                    PropertyFilter {
                        key: "age".to_string(),
                        value: json!(25),
                        operator: None,
                        prop_type: "person".to_string(),
                        group_type_index: None,
                        negation: None,
                    },
                ],
            }],
        };

        let result = cohort_property.to_property_filters();
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].key, "email");
        assert_eq!(result[0].value, json!("test@example.com"));
        assert_eq!(result[1].key, "age");
        assert_eq!(result[1].value, json!(25));
    }

    #[tokio::test]
    async fn test_extract_dependencies() {
        let postgres_reader = setup_pg_reader_client(None).await;
        let postgres_writer = setup_pg_writer_client(None).await;

        let team = insert_new_team_in_pg(postgres_reader.clone(), None)
            .await
            .expect("Failed to insert team");

        // Insert a single cohort that is dependent on another cohort
        let dependent_cohort = insert_cohort_for_team_in_pg(
            postgres_writer.clone(),
            team.id,
            Some("Dependent Cohort".to_string()),
            json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "$browser", "type": "person", "value": ["Safari"], "negation": false, "operator": "exact"}]}]}}),
            false,
        )
        .await
        .expect("Failed to insert dependent_cohort");

        // Insert main cohort with a single dependency
        let main_cohort = insert_cohort_for_team_in_pg(
                postgres_writer.clone(),
                team.id,
                Some("Main Cohort".to_string()),
                json!({"properties": {"type": "OR", "values": [{"type": "OR", "values": [{"key": "id", "type": "cohort", "value": dependent_cohort.id, "negation": false}]}]}}),
                false,
            )
            .await
            .expect("Failed to insert main_cohort");

        let fetched_main_cohort = Cohort::from_pg(postgres_reader.clone(), main_cohort.id, team.id)
            .await
            .expect("Failed to fetch main cohort");

        println!("fetched_main_cohort: {:?}", fetched_main_cohort);

        let dependencies = fetched_main_cohort.extract_dependencies().unwrap();
        let expected_dependencies: HashSet<CohortId> =
            [dependent_cohort.id].iter().cloned().collect();

        assert_eq!(dependencies, expected_dependencies);
    }
}
