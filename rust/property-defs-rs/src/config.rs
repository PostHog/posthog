use std::{num::ParseIntError, str::FromStr};

use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    // this maps to the original, shared CLOUD PG DB instance in production for
    // both the property-defs-rs and new property-defs-rs-v2 deployments
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    #[envconfig(default = "10")]
    pub max_concurrent_transactions: usize,

    #[envconfig(default = "1000")]
    pub update_batch_size: usize,

    // We issue updates in batches of update_batch_size, or when we haven't
    // received a new update in this many seconds
    #[envconfig(default = "300")]
    pub max_issue_period: u64,

    // Propdefs spawns N workers to pull events from kafka,
    // marshal, and convert to updates. The number of
    // concurrent update batches sent to postgres is controlled
    // by max_concurrent_transactions
    #[envconfig(default = "4")]
    pub worker_loop_count: usize,

    // We maintain an internal cache, to avoid sending the same UPSERT multiple times. This is it's size.
    #[envconfig(default = "1000000")]
    pub cache_capacity: usize,

    // We impose a slow-start, where each batch update operation is delayed by
    // this many milliseconds, multiplied by the % of the cache currently unused. The idea
    // is that we want to drip-feed updates to the DB during warmup, since
    // cache fill rate is highest when it's most empty, and cache fill rate
    // is exactly equivalent to the rate at which we can issue updates to the DB.
    // The maths here is:
    //     max(writes/s) = max_concurrent_transactions * update_batch_size / transaction_seconds
    // By artificially inflating transaction_time, we put a cap on writes/s. This cap is
    // then loosened as the cache fills, until we're operating in "normal" mode and
    // only presenting "true" DB backpressure (in the form of write time) to the main loop.
    #[envconfig(default = "1000")]
    pub cache_warming_delay_ms: u32,

    // This is the slow-start cutoff. Once the cache is this full, we
    // don't delay the batch updates any more. 50% is fine for testing,
    // in production you want to be using closer to 80-90%
    #[envconfig(default = "0.5")]
    pub cache_warming_cutoff: f64,

    // Each worker maintains a small local batch of updates, which it
    // flushes to the main thread (updating/filtering by the
    // cross-thread cache while it does). This is that batch size.
    #[envconfig(default = "10000")]
    pub compaction_batch_size: usize,

    // Workers send updates back to the main thread over a channel,
    // which has a depth of this many slots. If the main thread slows,
    // which usually means if postgres is slow, the workers will block
    // after filling this channel.
    #[envconfig(default = "1000")]
    pub channel_slots_per_worker: usize,

    // If an event has some ridiculous number of updates, we skip it
    #[envconfig(default = "10000")]
    pub update_count_skip_threshold: usize,

    // Do everything except actually write to the DB
    #[envconfig(default = "true")]
    pub skip_writes: bool,

    // Do everything except actually read or write from the DB
    #[envconfig(default = "true")]
    pub skip_reads: bool,

    // We maintain a small cache for mapping from group names to group type indexes.
    // You have very few reasons to ever change this... group type index resolution
    // is done as a final step before writing an update, and is low-cost even without
    // caching, compared to the rest of the process.
    #[envconfig(default = "100000")]
    pub group_type_cache_size: usize,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,

    // The set of teams to opt-in or opt-out of property definitions processing (depending on the setting below)
    #[envconfig(default = "")]
    pub filtered_teams: TeamList,

    // Whether the team list above is used to filter teams OUT of processing (opt-out) or IN to processing (opt-in).
    // Defaults to opt-in for now, skipping all updates for teams not in the list. TODO - change this to opt-out
    // once rollout is complete.
    #[envconfig(default = "opt_in")]
    pub filter_mode: TeamFilterMode,

    // this enables codepaths used by the new mirror deployment
    // property-defs-rs-v2 in ArgoCD. The main thing we're gating
    // at first is use of the DB client for the new isolated Postgres
    // on all write paths."
    #[envconfig(default = "false")]
    pub enable_mirror: bool,

    // TEMP: used to gate the new process_batch_v2 write path code in
    // the current property-defs-rs deployments *and* new mirror
    #[envconfig(default = "false")]
    pub enable_v2: bool,

    #[envconfig(default = "100")]
    pub v2_ingest_batch_size: usize,

    // *ONLY* for use in the new property-defs-rs-v2 mirror deploy, and (for now)
    // behind `enable_mirror` flag during the refactor/transition. Maps to the new
    // PROPDEFS isolated PG DB instances in production.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_propdefs_url: String,
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
            _ => Err(format!("Invalid team filter mode: {}", s)),
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
        let consumer_group = match std::env::var("ENABLE_V2") {
            Ok(enabled_v2) => {
                if enabled_v2.to_lowercase() == "true" {
                    "property-defs-rs-v2"
                } else {
                    "property_defs_rs"
                }
            }
            _ => "property-defs-rs",
        };
        ConsumerConfig::set_defaults(consumer_group, "clickhouse_events_json", true);
        Config::init_from_env()
    }
}
