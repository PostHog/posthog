use std::sync::Arc;

use common_database::Client as DatabaseClient;
use tracing::instrument;

use super::redirect_service::RedirectError;

pub type PostgresReader = Arc<dyn DatabaseClient + Send + Sync>;

#[instrument(name = "fetch_redirect_url", skip(db_reader_client))]
pub async fn fetch_redirect_url(
    db_reader_client: PostgresReader,
    origin_domain: &str,
    origin_key: &str,
) -> Result<String, RedirectError> {
    let mut conn = db_reader_client.get_connection().await.map_err(|e| {
        tracing::error!("Failed to get database connection: {}", e);
        RedirectError::DatabaseUnavailable
    })?;
    // TODO: Validate query
    let query = sqlx::query!(
        r#"
        SELECT destination
        FROM posthog_shortlink
        WHERE origin_key = $1 AND origin_domain = $2
        "#,
        origin_key,
        origin_domain
    )
    .fetch_optional(&mut *conn)
    .await?;
    match query {
        Some(row) => Ok(row.destination),
        _ => Err(RedirectError::LinkNotFound),
    }
}

#[cfg(test)]
mod tests {
    use crate::utils::test_utils::{insert_new_link_in_pg, insert_new_team_in_pg, setup_pg_client};

    use super::*;

    use anyhow::Result;

    #[tokio::test]
    async fn test_should_fetch_destination_from_database() -> Result<()> {
        let db_client = setup_pg_client(None).await;
        let origin_domain = "phog.gg";
        let origin_key = "test_key";
        let destination = "https://example.com";
        let team_id = 1;

        insert_new_team_in_pg(db_client.clone(), Some(team_id)).await?;
        let row = insert_new_link_in_pg(
            db_client.clone(),
            origin_domain,
            origin_key,
            destination,
            team_id,
        )
        .await?;

        println!("Inserted link with ID: {:?}", row);

        let result = fetch_redirect_url(db_client, origin_domain, origin_key).await;

        assert_eq!(result.unwrap(), destination);
        Ok(())
    }
}
