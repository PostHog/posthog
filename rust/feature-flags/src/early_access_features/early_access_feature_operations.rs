use common_database::PostgresReader;
use crate::early_access_features::early_access_feature_models::EarlyAccessFeature;
use crate::{
    api::errors::FlagError,
};

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
