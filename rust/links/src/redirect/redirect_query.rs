use std::sync::Arc;

use common_database::Client as DatabaseClient;
use tracing::instrument;

use super::redirect_service::RedirectError;

pub type PostgresReader = Arc<dyn DatabaseClient + Send + Sync>;

#[instrument(name = "fetch_redirect_url", skip(db_reader_client))]
pub async fn fetch_redirect_url(
    db_reader_client: PostgresReader,
    short_link_domain: &str,
    short_code: &str,
) -> Result<String, RedirectError> {
    let mut conn = db_reader_client.get_connection().await.map_err(|e| {
        tracing::error!("Failed to get database connection: {}", e);
        RedirectError::DatabaseUnavailable
    })?;
    // TODO: Validate query
    let query = sqlx::query!(
        r#"
        SELECT redirect_url
        FROM posthog_link
        WHERE short_code = $1 AND short_link_domain = $2
        "#,
        short_code,
        short_link_domain
    )
    .fetch_optional(&mut *conn)
    .await?;
    match query {
        Some(row) => Ok(row.redirect_url),
        _ => Err(RedirectError::LinkNotFound),
    }
}

#[cfg(test)]
mod tests {
    use crate::utils::test_utils::{
        insert_new_link_in_pg, insert_new_team_in_pg, random_string, setup_pg_client,
    };

    use super::*;

    use anyhow::Result;

    #[tokio::test]
    async fn test_should_fetch_redirect_url_from_database() -> Result<()> {
        let db_client = setup_pg_client(None).await;
        let short_link_domain = "phog.gg";
        let short_code = &random_string("", 6);
        let redirect_url = "https://example.com";

        let team = insert_new_team_in_pg(db_client.clone(), None).await?;
        let row = insert_new_link_in_pg(
            db_client.clone(),
            short_link_domain,
            short_code,
            redirect_url,
            team.id,
        )
        .await?;

        println!("Inserted link with ID: {:?}", row);

        let result = fetch_redirect_url(db_client, short_link_domain, short_code).await;

        assert_eq!(result.unwrap(), redirect_url);
        Ok(())
    }
}
