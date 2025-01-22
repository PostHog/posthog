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
    // TODO: the following fields are used for the `/decide` response,
    // but they're not used for flags and they don't live in redis.
    // At some point I'll need to differentiate between teams in Redis and teams
    // with additional fields in Postgres, since the Postgres team is a superset of the fields
    // we use for flags, anyway.
    // pub surveys_opt_in: bool,
    // pub heatmaps_opt_in: bool,
    // pub capture_performance_opt_in: bool,
    // pub autocapture_web_vitals_opt_in: bool,
    // pub autocapture_opt_out: bool,
    // pub autocapture_exceptions_opt_in: bool,
}
