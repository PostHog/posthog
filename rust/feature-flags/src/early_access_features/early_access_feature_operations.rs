use crate::api::errors::FlagError;
use crate::early_access_features::early_access_feature_models::EarlyAccessFeature;
use common_database::PostgresReader;

impl EarlyAccessFeature {
    // Returns all early access features for a given team
    pub async fn list_from_pg(
        client: PostgresReader,
        project_id: i64,
    ) -> Result<Vec<EarlyAccessFeature>, FlagError> {
        let mut conn = client.get_connection().await.map_err(|e| {
            tracing::error!(
                "Failed to get database connection for project {}: {}",
                project_id,
                e
            );
            FlagError::DatabaseUnavailable
        })?;

        let query = r#"
            SELECT f.id,
                  f.team_id,
                  f.feature_flag_id,
                  f.name,
                  f.description,
                  f.stage,
                  f.documentation_url
              FROM posthog_earlyaccessfeature AS f
              JOIN posthog_team AS t ON (f.team_id = t.id)
            WHERE t.project_id = $1
            AND f.feature_flag_id IS NOT NULL
        "#;
        let early_access_features = sqlx::query_as::<_, EarlyAccessFeature>(query)
            .bind(project_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to fetch early access features from database for project {}: {}",
                    project_id,
                    e
                );
                FlagError::Internal(format!("Database query error: {e}"))
            })?;
        Ok(early_access_features)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::TestContext;

    #[tokio::test]
    async fn test_list_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");
        context
            .insert_early_access_feature(team.id, None, "flag1".to_string())
            .await
            .expect("Failed to insert early_access_feature1");
        context
            .insert_early_access_feature(team.id, Some("alpha".to_string()), "flag2".to_string())
            .await
            .expect("Failed to insert early_access_feature2");

        let early_access_features =
            EarlyAccessFeature::list_from_pg(context.non_persons_reader, team.project_id)
                .await
                .expect("Failed to list early_access_features");

        assert_eq!(early_access_features.len(), 2);
    }
}
