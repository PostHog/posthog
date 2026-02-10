use moka::future::Cache;
use sqlx::PgPool;
use std::sync::Arc;
use std::time::Duration;
use tracing::{debug, warn};

pub struct TeamResolver {
    pool: PgPool,
    cache: Cache<String, Option<i32>>,
}

impl TeamResolver {
    pub fn new(pool: PgPool, cache_ttl_secs: u64) -> Self {
        let cache = Cache::builder()
            .max_capacity(10_000)
            .time_to_live(Duration::from_secs(cache_ttl_secs))
            .build();
        Self { pool, cache }
    }

    pub async fn resolve(&self, token: &str) -> Option<i32> {
        let token_owned = token.to_string();
        let pool = self.pool.clone();
        match self
            .cache
            .try_get_with(token_owned.clone(), async {
                Self::lookup(&pool, &token_owned).await
            })
            .await
        {
            Ok(team_id) => team_id,
            Err(e) => {
                warn!("team_id lookup failed: {e}");
                None
            }
        }
    }

    async fn lookup(pool: &PgPool, token: &str) -> Result<Option<i32>, Arc<sqlx::Error>> {
        let row: Option<(i32,)> =
            sqlx::query_as("SELECT id FROM posthog_team WHERE api_token = $1")
                .bind(token)
                .fetch_optional(pool)
                .await
                .map_err(Arc::new)?;
        let prefix_len = 8.min(token.len());
        debug!(
            token_prefix = &token[..prefix_len],
            team_id = ?row,
            "resolved token"
        );
        Ok(row.map(|(id,)| id))
    }
}
