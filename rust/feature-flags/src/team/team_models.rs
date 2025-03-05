use serde::{Deserialize, Serialize};

// TRICKY: This cache data is coming from django-redis. If it ever goes out of sync, we'll bork.
// TODO: Add integration tests across repos to ensure this doesn't happen.
pub const TEAM_TOKEN_CACHE_PREFIX: &str = "posthog:1:team_token:";

#[derive(Clone, Debug, Deserialize, Serialize, sqlx::FromRow)]
pub struct Team {
    pub id: i32,
    pub name: String,
    pub api_token: String,
    /// Project ID. This field is not present in Redis cache before Dec 2025, but this is not a problem at all,
    /// because we know all Teams created before Dec 2025 have `project_id` = `id`. To handle this case gracefully,
    /// we use 0 as a fallback value in deserialization here, and handle this in `Team::from_redis`.
    /// Thanks to this default-base approach, we avoid invalidating the whole cache needlessly.
    #[serde(default)]
    pub project_id: i64,
}
