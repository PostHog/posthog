use crate::{api::errors::FlagError, team::team_models::Team};
use common_database::Client as DatabaseClient;
use serde_json::Value;
use std::sync::Arc;

#[derive(sqlx::FromRow)]
struct SuppressionRuleRow {
    filters: Value,
}

/// Get suppression rules for error tracking from the database
/// Equivalent to Django's get_suppression_rules function
pub async fn get_suppression_rules(
    client: Arc<dyn DatabaseClient + Send + Sync>,
    team: &Team,
) -> Result<Vec<Value>, FlagError> {
    let mut conn = client.get_connection().await?;

    let query = "SELECT filters FROM posthog_errortrackingsuppressionrule WHERE team_id = $1";

    let rows = sqlx::query_as::<_, SuppressionRuleRow>(query)
        .bind(team.id)
        .fetch_all(&mut *conn)
        .await
        .map_err(|e| {
            tracing::error!(
                "Failed to fetch suppression rules for team {}: {}",
                team.id,
                e
            );
            FlagError::DatabaseUnavailable
        })?;

    Ok(rows.into_iter().map(|row| row.filters).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::{
        insert_new_team_in_pg, insert_suppression_rule_in_pg, setup_pg_reader_client,
    };
    use serde_json::json;

    #[tokio::test]
    async fn test_get_suppression_rules_empty() {
        let client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        let result = get_suppression_rules(client, &team).await.unwrap();

        assert!(result.is_empty());
    }

    #[tokio::test]
    async fn test_get_suppression_rules_with_data() {
        let client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        let filter1 = json!({"errorType": "TypeError", "message": "Cannot read property"});
        let filter2 = json!({"stackTrace": {"contains": "node_modules"}});

        insert_suppression_rule_in_pg(client.clone(), team.id, filter1.clone())
            .await
            .unwrap();
        insert_suppression_rule_in_pg(client.clone(), team.id, filter2.clone())
            .await
            .unwrap();

        let result = get_suppression_rules(client, &team).await.unwrap();

        assert_eq!(result.len(), 2);
        assert!(result.contains(&filter1));
        assert!(result.contains(&filter2));
    }

    #[tokio::test]
    async fn test_get_suppression_rules_filters_by_team() {
        let client = setup_pg_reader_client(None).await;
        let team1 = insert_new_team_in_pg(client.clone(), None).await.unwrap();
        let team2 = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        let filter1 = json!({"errorType": "TypeError"});
        let filter2 = json!({"errorType": "ReferenceError"});

        insert_suppression_rule_in_pg(client.clone(), team1.id, filter1.clone())
            .await
            .unwrap();
        insert_suppression_rule_in_pg(client.clone(), team2.id, filter2.clone())
            .await
            .unwrap();

        let result = get_suppression_rules(client, &team1).await.unwrap();

        assert_eq!(result.len(), 1);
        assert_eq!(result[0], filter1);
    }
}
