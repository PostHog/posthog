use crate::config::Config;
use health::{HealthHandle, HealthRegistry};

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use sqlx::PgPool;

pub struct Context {
    pub config: Config,
    pub pool: PgPool,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
}

#[derive(Clone, Debug, Serialize, Deserialize, FromRow, PartialEq, Eq, Hash)]
pub struct FilterRow {
    // the team this filter represents
    pub team_id: i64,
    // the raw bytes (from Postgres BYTEA cols) of the serialized bloom filters
    pub fwd_bloom: Option<Vec<u8>>,
    pub rev_bloom: Option<Vec<u8>>,
    // number of property definitions recorded in the filters
    pub property_count: i32,
    // is this team prohibited from defining any more properties?
    pub blocked: bool,
    // timestamps for the filter update cron to use to know which teams
    // need the filter to be crawled and updated with new records
    pub last_updated_at: DateTime<Utc>,
}
