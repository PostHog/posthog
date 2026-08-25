use std::{num::ParseIntError, str::FromStr};

use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    // this maps to the original, shared CLOUD PG DB instance in production.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    // Backstop only; the writer guard is what detects a failover. Kept because the guard's
    // `before_acquire` hook never sees a freshly opened connection, so recycling still bounds a
    // connection the guard cannot reach. Overrides sqlx's 30 minute default. Jitter puts the
    // effective lifetime in `base..=base + base/5`, so 300 here means 300-360s.
    #[envconfig(default = "300")]
    pub pg_max_lifetime_secs: u64,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    #[envconfig(default = "1000")]
    pub update_batch_size: usize,

    // Ceiling on how long the consumer will wait for a batch to reach update_batch_size before
    // issuing it short. Measured from the start of the fill, not from the last update received,
    // so a batch that trickles in one update at a time still breaks out after this many seconds.
    #[envconfig(default = "300")]
    pub max_issue_period: u64,

    // Propdefs spawns N workers to pull events from kafka, marshal, and convert to updates.
    // Write concurrency is not bounded by any semaphore: process_batch spawns a task per chunk,
    // so max_pg_connections is the only thing applying backpressure to Postgres.
    #[envconfig(default = "4")]
    pub worker_loop_count: usize,

    // Per-data-type cache capacities (event definitions, event properties, property definitions).
    // Each internal cache avoids sending the same UPSERT multiple times.
    #[envconfig(default = "1000000")]
    pub eventdefs_cache_capacity: usize,
    #[envconfig(default = "1000000")]
    pub eventprops_cache_capacity: usize,
    #[envconfig(default = "1000000")]
    pub propdefs_cache_capacity: usize,

    // Each worker maintains a small local batch of updates, which it
    // flushes to the main thread (updating/filtering by the
    // cross-thread cache while it does). This is that batch size.
    #[envconfig(default = "10000")]
    pub compaction_batch_size: usize,

    // How long a producer's compaction batch may sit before it is flushed regardless of size.
    // Bounds how stale the tail of a partition's updates can get once its traffic stops.
    #[envconfig(default = "10")]
    pub producer_drain_interval_secs: u64,

    // Multiplier on update_batch_size for the depth of the single channel workers send updates
    // back to the main thread over, so the real depth is update_batch_size * this. The channel is
    // shared across all workers and its size does not vary with worker_loop_count, despite the
    // name. If the main thread slows, which usually means postgres is slow, workers block once
    // the channel fills.
    #[envconfig(default = "1000")]
    pub channel_slots_per_worker: usize,

    // If an event has some ridiculous number of updates, we skip it
    #[envconfig(default = "10000")]
    pub update_count_skip_threshold: usize,

    // Period an event definition's last_seen_at is floored to for dedup purposes, which bounds
    // how often we re-issue its write: once per (team, name) per period, per pod. The stored
    // value is generated fresh at write time, so a coarser period only means a staler
    // last_seen_at in the DB. Its only consumers are staleness filters, so read them before
    // raising this: `?exclude_stale=true` compares against 30 days, but the event-screenshots
    // Temporal workflow shortlists event types on a 3 hour window. Must be in
    // 1..=MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS: flooring is what bounds this table's write volume,
    // so startup fails rather than run without it.
    #[envconfig(from = "EVENTDEF_LAST_SEEN_FLOOR_SECS", default = "3600")]
    pub eventdef_last_seen_floor_secs: i64,

    // Skip group-type resolution, which is the only read this service performs. Writes are
    // unaffected: process_batch runs regardless of this setting.
    #[envconfig(default = "true")]
    pub skip_reads: bool,

    // Cache mapping group names to group type indexes. Resolution runs once per consumer batch,
    // before the batch is written, and is a gRPC round trip to personhog with retries and
    // backoff, so caching matters more than the size of this value usually does.
    #[envconfig(default = "100000")]
    pub group_type_cache_size: usize,

    // Negative cache for group-type resolution misses (personhog returned no mapping).
    // A new group type's $groupidentify can arrive here before its GroupTypeMapping is
    // visible to personhog's eventual read, so a miss is often a transient race, not
    // terminal misuse. We cache the miss for this TTL so we neither hammer personhog for
    // repeated unresolvable keys nor block a legitimate new group for longer than the TTL:
    // once the entry expires the next $groupidentify re-attempts resolution. Kept short on
    // purpose (the mapping is committed to PG primary before we consume the event, so only
    // replica lag remains).
    #[envconfig(default = "30")]
    pub group_type_negative_ttl_secs: u64,
    #[envconfig(default = "100000")]
    pub group_type_negative_cache_size: usize,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,

    // The set of teams to opt-in or opt-out of property definitions processing (depending on the setting below)
    #[envconfig(default = "")]
    pub filtered_teams: TeamList,

    // Whether the team list above is used to filter teams OUT of processing (opt-out) or IN to processing (opt-in).
    #[envconfig(default = "opt_out")]
    pub filter_mode: TeamFilterMode,

    #[envconfig(default = "100")]
    pub write_batch_size: usize,

    #[envconfig(default = "")]
    pub personhog_addr: String,

    #[envconfig(default = "5000")]
    pub personhog_timeout_ms: u64,

    #[envconfig(default = "5000")]
    pub personhog_connect_timeout_ms: u64,

    #[envconfig(default = "2")]
    pub personhog_max_retries: u32,

    #[envconfig(default = "50")]
    pub personhog_initial_backoff_ms: u64,

    #[envconfig(default = "1000")]
    pub personhog_max_backoff_ms: u64,
}

#[derive(Clone)]
pub struct TeamList {
    pub teams: Vec<i32>,
}

impl FromStr for TeamList {
    type Err = ParseIntError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let mut teams = Vec::new();
        for team in s.trim().split(',') {
            if team.is_empty() {
                continue;
            }
            teams.push(team.parse()?);
        }
        Ok(TeamList { teams })
    }
}

#[derive(Clone)]
pub enum TeamFilterMode {
    OptIn,
    OptOut,
}

impl FromStr for TeamFilterMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().trim() {
            "opt_in" => Ok(TeamFilterMode::OptIn),
            "opt_out" => Ok(TeamFilterMode::OptOut),
            "opt-in" => Ok(TeamFilterMode::OptIn),
            "opt-out" => Ok(TeamFilterMode::OptOut),
            "optin" => Ok(TeamFilterMode::OptIn),
            "optout" => Ok(TeamFilterMode::OptOut),
            _ => Err(format!("Invalid team filter mode: {s}")),
        }
    }
}

impl TeamFilterMode {
    pub fn should_process(&self, list: &[i32], team_id: i32) -> bool {
        match self {
            TeamFilterMode::OptIn => list.contains(&team_id),
            TeamFilterMode::OptOut => !list.contains(&team_id),
        }
    }
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Production overrides KAFKA_CONSUMER_TOPIC to team_event_partitioned_events_json, which
        // a WarpStream Bento pipeline repartitions out of clickhouse_events_json. This default is
        // only what a local run gets.
        ConsumerConfig::set_defaults("property-defs-rs", "clickhouse_events_json", true);
        Config::init_from_env()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_opt_out_with_empty_list_processes_all_teams() {
        let mode = TeamFilterMode::OptOut;
        let list: Vec<i32> = vec![];

        assert!(mode.should_process(&list, 1));
        assert!(mode.should_process(&list, 999));
        assert!(mode.should_process(&list, 12345));
    }

    #[test]
    fn test_opt_in_with_empty_list_processes_no_teams() {
        let mode = TeamFilterMode::OptIn;
        let list: Vec<i32> = vec![];

        assert!(!mode.should_process(&list, 1));
        assert!(!mode.should_process(&list, 999));
    }

    #[test]
    fn test_opt_out_excludes_listed_teams() {
        let mode = TeamFilterMode::OptOut;
        let list = vec![1, 2, 3];

        assert!(!mode.should_process(&list, 1));
        assert!(!mode.should_process(&list, 2));
        assert!(mode.should_process(&list, 4));
        assert!(mode.should_process(&list, 999));
    }

    #[test]
    fn test_opt_in_includes_only_listed_teams() {
        let mode = TeamFilterMode::OptIn;
        let list = vec![1, 2, 3];

        assert!(mode.should_process(&list, 1));
        assert!(mode.should_process(&list, 2));
        assert!(!mode.should_process(&list, 4));
        assert!(!mode.should_process(&list, 999));
    }

    #[test]
    fn test_filter_mode_parsing() {
        assert!(matches!(
            TeamFilterMode::from_str("opt_out"),
            Ok(TeamFilterMode::OptOut)
        ));
        assert!(matches!(
            TeamFilterMode::from_str("opt-out"),
            Ok(TeamFilterMode::OptOut)
        ));
        assert!(matches!(
            TeamFilterMode::from_str("optout"),
            Ok(TeamFilterMode::OptOut)
        ));
        assert!(matches!(
            TeamFilterMode::from_str("OPT_OUT"),
            Ok(TeamFilterMode::OptOut)
        ));
        assert!(matches!(
            TeamFilterMode::from_str("opt_in"),
            Ok(TeamFilterMode::OptIn)
        ));
        assert!(TeamFilterMode::from_str("invalid").is_err());
    }

    #[test]
    fn test_team_list_parsing() {
        let list: TeamList = "1,2,3".parse().unwrap();
        assert_eq!(list.teams, vec![1, 2, 3]);

        let empty: TeamList = "".parse().unwrap();
        assert!(empty.teams.is_empty());

        let single: TeamList = "42".parse().unwrap();
        assert_eq!(single.teams, vec![42]);
    }
}
