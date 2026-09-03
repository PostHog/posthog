use std::time::Duration;

use async_trait::async_trait;
use moka::future::Cache;
use sqlx::PgPool;
use thiserror::Error;
use uuid::Uuid;

#[derive(Debug, Error)]
pub enum ResolveError {
    #[error("team ID is outside the supported range")]
    InvalidTeamId,
    #[error("team has no organization")]
    Missing,
    #[error("database lookup failed: {0}")]
    Database(#[from] sqlx::Error),
}

#[async_trait]
pub trait OrganizationResolver: Send + Sync {
    async fn resolve(&self, team_id: i64) -> Result<Uuid, ResolveError>;
}

pub struct PostgresOrganizationResolver {
    cache: Cache<i64, Option<Uuid>>,
    database: PgPool,
}

impl PostgresOrganizationResolver {
    pub fn new(database: PgPool) -> Self {
        Self {
            cache: Cache::builder()
                .time_to_live(Duration::from_secs(5 * 60))
                .build(),
            database,
        }
    }
}

#[async_trait]
impl OrganizationResolver for PostgresOrganizationResolver {
    async fn resolve(&self, team_id: i64) -> Result<Uuid, ResolveError> {
        if team_id <= 0 {
            return Err(ResolveError::InvalidTeamId);
        }
        if let Some(organization_id) = self.cache.get(&team_id).await {
            metrics::counter!("usage_ingestion_organization_resolver_cache_lookups_total", "result" => "hit")
                .increment(1);
            return organization_id.ok_or(ResolveError::Missing);
        }
        metrics::counter!("usage_ingestion_organization_resolver_cache_lookups_total", "result" => "miss")
            .increment(1);

        // A short TTL bounds stale attribution after a project moves organizations while avoiding
        // a PostgreSQL lookup for every invalid or repeated record.
        let organization_id = sqlx::query_scalar::<_, Uuid>(
            "SELECT organization_id FROM posthog_team WHERE id = $1 AND organization_id IS NOT NULL",
        )
        .bind(team_id)
        .fetch_optional(&self.database)
        .await?;
        self.cache.insert(team_id, organization_id).await;
        organization_id.ok_or(ResolveError::Missing)
    }
}
