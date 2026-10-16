use std::time::Duration;

use common_database::PoolConfig;
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

use crate::config::{IdentityTables, IdentityTablesConfig};
use crate::publish::DrainConfig;

#[derive(Envconfig, Clone)]
pub struct PublisherConfig {
    /// The persons primary identity writes to; the outbox lives there.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub primary_database_url: String,

    #[envconfig(nested = true)]
    pub tables: IdentityTablesConfig,

    /// One pool: a replica holds one claim transaction at a time plus the
    /// gauge query, so a small pool is a ceiling, not a target.
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    #[envconfig(default = "10")]
    pub acquire_timeout_secs: u64,

    /// Bounds any one statement of the claim transaction, so a stuck
    /// resolution cannot hold the claimed rows past the produce timeout
    /// by much.
    #[envconfig(default = "5000")]
    pub statement_timeout_ms: u64,

    #[envconfig(default = "300")]
    pub idle_timeout_secs: u64,

    #[envconfig(default = "9109")]
    pub metrics_port: u16,

    /// Idle poll between passes; a pass that claims a full batch loops
    /// again at once.
    #[envconfig(default = "200")]
    pub lifecycle_publish_interval_ms: u64,

    #[envconfig(default = "1000")]
    pub lifecycle_publish_batch_size: i64,

    /// Distinct id rows one pass produces at most, across every row it
    /// claimed. A large merge or delete drains across several passes, each
    /// advancing its pointer's cursor, so no transaction stays open across
    /// more produces than the produce timeout can carry.
    #[envconfig(default = "10000")]
    pub lifecycle_publish_max_rows_per_pass: i64,

    /// How long one claim waits for Kafka acks before it rolls back and
    /// retries. Keep it well under the database's
    /// idle_in_transaction_session_timeout.
    #[envconfig(default = "5000")]
    pub lifecycle_publish_produce_timeout_ms: u64,

    /// Lag above which the gauge refresh logs a warning. The page itself
    /// lives in Grafana on the lag gauge.
    #[envconfig(default = "300")]
    pub lifecycle_publish_lag_alert_secs: u64,

    /// No default on purpose. The table set defaults to the validation
    /// tables, whose versions come from a different sequence than the real
    /// tables and would win in ClickHouse, so a deployment must say which
    /// topic it feeds: `clickhouse_person_distinct_id` only behind the real
    /// tables, a capture topic behind the validation set.
    pub person_distinct_id_topic: String,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,
}

impl PublisherConfig {
    pub fn tables(&self) -> IdentityTables {
        self.tables.tables()
    }

    pub fn pool_config(&self) -> PoolConfig {
        PoolConfig {
            min_connections: 0,
            max_connections: self.max_pg_connections,
            acquire_timeout: Duration::from_secs(self.acquire_timeout_secs),
            idle_timeout: (self.idle_timeout_secs != 0)
                .then(|| Duration::from_secs(self.idle_timeout_secs)),
            test_before_acquire: false,
            statement_timeout_ms: (self.statement_timeout_ms != 0)
                .then_some(self.statement_timeout_ms),
            pool_name: Some("publisher".to_string()),
        }
    }

    pub fn drain_config(&self) -> DrainConfig {
        DrainConfig {
            batch_size: self.lifecycle_publish_batch_size,
            max_rows_per_pass: self.lifecycle_publish_max_rows_per_pass,
            interval: Duration::from_millis(self.lifecycle_publish_interval_ms),
            lag_alert: Duration::from_secs(self.lifecycle_publish_lag_alert_secs),
        }
    }

    pub fn produce_timeout(&self) -> Duration {
        Duration::from_millis(self.lifecycle_publish_produce_timeout_ms)
    }

    /// How long a pass usually takes at most: one produce wait plus one
    /// slow statement. The publisher component's graceful shutdown covers
    /// it so an in-flight claim normally commits or rolls back cleanly. It
    /// is not a hard bound: a pass with many pointers runs two statements
    /// per pointer, and a pass torn down past the window only rolls back,
    /// because nothing commits before the acks.
    pub fn pass_deadline(&self) -> Duration {
        self.produce_timeout() + Duration::from_millis(self.statement_timeout_ms)
    }
}
