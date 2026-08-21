use std::sync::Arc;

use async_trait::async_trait;
use common_hypercache::{HyperCacheReader, KeyType};
use serde::Deserialize;
use sqlx::PgPool;
use thiserror::Error;
use tracing::warn;
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

#[derive(Deserialize)]
struct TeamOrganizationMapping {
    organization_id: Uuid,
}

pub struct HyperCacheOrganizationResolver {
    cache: Arc<HyperCacheReader>,
    database: PgPool,
}

impl HyperCacheOrganizationResolver {
    pub fn new(cache: Arc<HyperCacheReader>, database: PgPool) -> Self {
        Self { cache, database }
    }
}

#[async_trait]
impl OrganizationResolver for HyperCacheOrganizationResolver {
    async fn resolve(&self, team_id: i64) -> Result<Uuid, ResolveError> {
        let cache_team_id = i32::try_from(team_id).map_err(|_| ResolveError::InvalidTeamId)?;
        match self.cache.get(&KeyType::int(cache_team_id)).await {
            Ok(value) => match serde_json::from_value::<TeamOrganizationMapping>(value) {
                Ok(mapping) => return Ok(mapping.organization_id),
                Err(error) => {
                    warn!(team_id, %error, "Invalid team organization HyperCache payload; falling back to PostgreSQL")
                }
            },
            Err(error) => {
                warn!(team_id, %error, "Team organization HyperCache miss; falling back to PostgreSQL")
            }
        }

        sqlx::query_scalar::<_, Uuid>(
            "SELECT organization_id FROM posthog_team WHERE id = $1 AND organization_id IS NOT NULL",
        )
        .bind(team_id)
        .fetch_optional(&self.database)
        .await?
        .ok_or(ResolveError::Missing)
    }
}
