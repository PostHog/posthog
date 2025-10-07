use std::{
    path::{Path, PathBuf},
    sync::atomic::{AtomicUsize, Ordering},
};

use aws_config::{BehaviorVersion, Region};
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use common_types::error_tracking::EmbeddingModelList;
use envconfig::Envconfig;
use tracing::{info, warn};

// TODO - I'm just too lazy to pipe this all the way through the resolve call stack
pub static FRAME_CONTEXT_LINES: AtomicUsize = AtomicUsize::new(15);

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3305")]
    pub port: u16,

    pub posthog_api_key: Option<String>,

    #[envconfig(default = "https://us.i.posthog.com/capture")]
    pub posthog_endpoint: String,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "cdp_internal_events")]
    pub internal_events_topic: String,

    #[envconfig(default = "clickhouse_events_json")]
    pub events_topic: String,

    #[envconfig(default = "clickhouse_error_tracking_issue_fingerprint")]
    pub issue_overrides_topic: String,

    #[envconfig(default = "clickhouse_ingestion_warnings")]
    pub ingestion_warnings_topic: String,

    #[envconfig(default = "error_tracking_new_fingerprints")]
    pub new_fingerprints_topic: String,

    pub embedding_enabled_team_id: Option<i32>,

    #[envconfig(default = "text-embedding-3-large")]
    pub embedding_models: EmbeddingModelList,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    // Rust service connect directly to postgres, not via pgbouncer, so we keep this low
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    // cymbal makes HTTP get requests to auto-resolve sourcemaps - and follows redirects. To protect against SSRF, we only allow requests to public URLs by default
    #[envconfig(default = "false")]
    pub allow_internal_ips: bool,

    #[envconfig(default = "30")]
    pub sourcemap_timeout_seconds: u64,

    #[envconfig(default = "5")]
    pub sourcemap_connect_timeout_seconds: u64,

    #[envconfig(default = "100000000")] // 100MB - in prod, we should use closer to 1-10GB
    pub symbol_store_cache_max_bytes: usize,

    #[envconfig(default = "http://127.0.0.1:19000")] // minio
    pub object_storage_endpoint: String,

    #[envconfig(default = "symbol_sets")]
    pub object_storage_bucket: String,

    #[envconfig(default = "us-east-1")]
    pub object_storage_region: String,

    #[envconfig(default = "object_storage_root_user")]
    pub object_storage_access_key_id: String,

    #[envconfig(default = "object_storage_root_password")]
    pub object_storage_secret_access_key: String,

    #[envconfig(default = "false")] // Enable for MinIO compatibility
    pub object_storage_force_path_style: bool,

    #[envconfig(default = "symbolsets")]
    pub ss_prefix: String,

    #[envconfig(default = "100000")]
    pub frame_cache_size: u64,

    #[envconfig(default = "600")]
    pub frame_cache_ttl_seconds: u64,

    // When we resolve a frame, we put it in PG, so other instances of cymbal can
    // use it, or so we can re-use it after a restart. This is the TTL for that,
    // after this many minutes we'll discard saved resolution results and re-resolve
    // TODO - 10 minutes is too short for production use, it's only twice as long as
    // our in-memory caching. We should do at least an hour once we release
    #[envconfig(default = "10")]
    pub frame_result_ttl_minutes: u32,

    // Maximum number of lines of pre and post context to get per frame
    #[envconfig(default = "15")]
    pub context_line_count: usize,

    #[envconfig(default = "1000")]
    pub max_events_per_batch: usize,

    #[envconfig(default = "10")]
    pub max_event_batch_wait_seconds: u64,

    #[envconfig(default = "300")]
    pub team_cache_ttl_secs: u64,

    #[envconfig(default = "10000")]
    pub max_team_cache_size: u64,

    #[envconfig(default = "300")]
    pub assignment_rule_cache_ttl_secs: u64,

    #[envconfig(default = "100000")]
    // The maximum number of bytecode operations we'll store in the cache, across all rules, across all teams
    pub max_assignment_rule_cache_size: u64,

    #[envconfig(default = "300")]
    pub grouping_rule_cache_ttl_secs: u64,

    #[envconfig(default = "100000")]
    // The maximum number of bytecode operations we'll store in the cache, across all rules, across all teams
    pub max_grouping_rule_cache_size: u64,

    #[envconfig(from = "MAXMIND_DB_PATH")]
    pub maxmind_db_path: PathBuf,

    #[envconfig(default = "redis://localhost:6379/")]
    pub redis_url: String,

    #[envconfig(default = "")]
    pub filtered_teams: String, // Comma seperated list of teams to either filter in (process) or filter out (ignore)

    #[envconfig(default = "out")]
    pub filter_mode: String, // in/out - in means drop all teams not in the list, out means drop all teams in the list

    #[envconfig(default = "false")]
    pub auto_assignment_enabled: bool, // Comma seperated list of users to either filter in (process) or filter out (ignore)
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Our consumer is used in a transaction, so we disable offset commits.
        ConsumerConfig::set_defaults("error-tracking-rs", "exceptions_ingestion", false);

        if std::env::var("MAXMIND_DB_PATH").is_err() {
            std::env::set_var(
                "MAXMIND_DB_PATH",
                default_maxmind_db_path().to_string_lossy().to_string(),
            );
        }

        let res = Self::init_from_env()?;
        init_global_state(&res);
        Ok(res)
    }
}

pub fn init_global_state(config: &Config) {
    FRAME_CONTEXT_LINES.store(config.context_line_count, Ordering::Relaxed);
}

fn default_maxmind_db_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("share")
        .join("GeoLite2-City.mmdb")
}

pub async fn get_aws_config(config: &Config) -> aws_sdk_s3::Config {
    // If we have a role ARN and token file, which are added to the container due to the SA annotation we use in prod
    if std::env::var("AWS_ROLE_ARN").is_ok() && std::env::var("AWS_WEB_IDENTITY_TOKEN_FILE").is_ok()
    {
        info!("AWS role and token file detected, config loaded from environment variables");
        // Use default aws config loading behaviour, which should pick up the role-based credentials. We
        // assume region and endpoint will be properly set due to SA annotation. Behaviour version will
        // be latest due to config crate feature flag
        aws_sdk_s3::config::Builder::from(&aws_config::load_from_env().await)
            .force_path_style(config.object_storage_force_path_style)
            .build()
    } else {
        warn!("Falling back to building config from explicit environment variables");
        // Fall back to building our config from the explicit environment variables we use in local dev
        let env_credentials = aws_sdk_s3::config::Credentials::new(
            &config.object_storage_access_key_id,
            &config.object_storage_secret_access_key,
            None,
            None,
            "environment",
        );
        aws_sdk_s3::config::Builder::new()
            .region(Region::new(config.object_storage_region.clone()))
            .endpoint_url(&config.object_storage_endpoint)
            .credentials_provider(env_credentials)
            .behavior_version(BehaviorVersion::latest())
            .force_path_style(config.object_storage_force_path_style)
            .build()
    }
}
