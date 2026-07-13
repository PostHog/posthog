use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use object_store::aws::AmazonS3Builder;
use object_store::limit::LimitStore;
use object_store::{ClientOptions, ObjectStore};
use tracing::{debug, info};

use crate::config::Config;

/// Build the `object_store` client for the temp bucket from config, following the
/// kafka-deduplicator checkpoint client pattern (the repo standard for S3 access).
///
/// Credential priority:
/// 1. Explicit credentials from config (local dev / CI against SeaweedFS)
/// 2. IRSA via `AWS_WEB_IDENTITY_TOKEN_FILE` + `AWS_ROLE_ARN` (EKS production)
/// 3. Default AWS credential chain (env vars, config files, IMDS)
///
/// Timeouts and retries are config-driven: the attempt timeout must fit a full
/// CHUNK_SIZE (~100 MB) ranged GET, and client-level retries are kept small because
/// job-level backoff retries on top. The store is wrapped in a `LimitStore` to cap
/// concurrent requests per job client.
///
/// Deliberately NOT validated eagerly here: the client is built per job, and a
/// `Job::new` failure pauses the job without transient-error classification — an
/// eager bucket probe would turn an S3 blip into a paused customer job. The first
/// HEAD/PUT of part 1 validates seconds later on a path with proper classification
/// (blip -> backoff, misconfig -> clear pause).
pub async fn create_temp_bucket_store(config: &Config) -> Result<Arc<dyn ObjectStore>> {
    let mut builder = AmazonS3Builder::from_env()
        .with_bucket_name(&config.temp_bucket_name)
        .with_client_options(
            ClientOptions::new()
                .with_timeout(Duration::from_secs(config.temp_bucket_attempt_timeout_secs)),
        )
        .with_retry(object_store::RetryConfig {
            max_retries: config.temp_bucket_max_retries,
            retry_timeout: Duration::from_secs(config.temp_bucket_operation_timeout_secs),
            ..Default::default()
        });

    if let Some(region) = config.temp_bucket_region() {
        builder = builder.with_region(region);
    }

    // Custom endpoint for local dev / CI (SeaweedFS).
    if let Some(endpoint) = config.temp_bucket_endpoint() {
        builder = builder.with_endpoint(endpoint);
        if endpoint.starts_with("http://") {
            builder = builder.with_allow_http(true);
        }
    }

    // Explicit credentials override env (local dev / CI without IAM).
    if let Some((access_key, secret_key)) = config.temp_bucket_credentials() {
        info!("Temp bucket: using explicit S3 credentials from config");
        builder = builder
            .with_access_key_id(access_key)
            .with_secret_access_key(secret_key);
    } else if std::env::var("AWS_WEB_IDENTITY_TOKEN_FILE").is_ok()
        && std::env::var("AWS_ROLE_ARN").is_ok()
    {
        info!("Temp bucket: using IRSA credentials (AWS_WEB_IDENTITY_TOKEN_FILE + AWS_ROLE_ARN)");
    } else {
        debug!("Temp bucket: using default AWS credential chain");
    }

    // Path-style object URLs (required by S3-compatible dev stores like SeaweedFS).
    if config.temp_bucket_force_path_style {
        builder = builder.with_virtual_hosted_style_request(false);
    }

    let store = builder.build().with_context(|| {
        format!(
            "Failed to build temp-bucket S3 client for bucket '{}'",
            config.temp_bucket_name
        )
    })?;

    Ok(Arc::new(LimitStore::new(
        store,
        config.temp_bucket_max_concurrent_requests,
    )))
}
