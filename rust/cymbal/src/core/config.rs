use aws_config::{BehaviorVersion, Region};
use envconfig::Envconfig;
use tracing::{info, warn};

/// Configuration for the shared symbol-resolution stack. Both run modes parse
/// this slice; processing mode nests it on [`crate::modes::processing::ProcessingConfig`], and
/// resolution mode reads it alongside its own service config. Keeping it in
/// `core` means the resolver (and a future `cymbal-core` crate) never needs the
/// processing-only knobs (Kafka, Redis, rules, remote-resolution client).
#[derive(Envconfig, Clone)]
pub struct ResolverConfig {
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    // Rust services connect directly to postgres, not via pgbouncer, so we keep this low
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

    // Used by cymbal and cymbal-resolution through the shared symbol resolver config.
    // Resolved frame results are relatively stable, while unresolved results can become
    // resolvable after a user uploads missing symbols, so keep them shorter.
    #[envconfig(default = "1800")]
    pub frame_resolved_ttl_seconds: u64,

    #[envconfig(default = "300")]
    pub frame_unresolved_ttl_seconds: u64,

    // Maximum number of lines of pre and post context to get per frame
    #[envconfig(default = "15")]
    pub context_line_count: usize,

    // Global maximum number of concurrent symbol resolution operations.
    // This limiter is shared across frame and exception symbol resolution paths.
    #[envconfig(default = "64")]
    pub symbol_resolution_concurrency: usize,

    // Shared secret authenticating the cymbal <-> cymbal-resolution gRPC seam.
    #[envconfig(default = "")]
    pub internal_api_secret: String,

    // Comma-separated previous secrets still accepted for verification during zero-downtime rotation.
    #[envconfig(default = "")]
    pub internal_api_secret_fallbacks: String,
}

impl ResolverConfig {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Self::init_from_env()
    }
}

pub async fn get_aws_config(config: &ResolverConfig) -> aws_sdk_s3::Config {
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
