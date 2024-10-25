use serde::{Deserialize, Serialize};

pub const TEAM_TOKEN_CACHE_PREFIX: &str = "posthog:1:team_token:";

#[derive(Clone, Debug, Deserialize, Serialize, sqlx::FromRow)]
pub struct Team {
    pub id: i32,
    pub name: String,
    pub api_token: String,
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
