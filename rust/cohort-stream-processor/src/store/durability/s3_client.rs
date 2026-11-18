//! Shared S3 client setup for the checkpoint uploader and downloader.
//!
//! This module provides a unified way to create S3 clients with proper credential resolution for
//! both production (IRSA) and local dev (MinIO/SeaweedFS).

use anyhow::{Context, Result};
use futures::StreamExt;
use object_store::aws::{AmazonS3, AmazonS3Builder};
use object_store::limit::LimitStore;
use object_store::path::Path as ObjectPath;
use object_store::{BackoffConfig, ClientOptions, ObjectStore};
use std::future::Future;
use std::sync::Arc;
use std::time::Duration;
use tokio_util::sync::CancellationToken;
use tracing::{debug, info, warn};

use super::config::DurabilityConfig;

/// Short timeout for bucket validation so misconfiguration fails fast.
const VALIDATION_TIMEOUT: Duration = Duration::from_secs(10);

/// object_store never retries an error of kind `Unknown`, such as a TLS EOF on a proxied
/// connection, so a whole file is tried again instead.
const FILE_ATTEMPTS: u32 = 3;
const FILE_RETRY_WAIT: Duration = Duration::from_secs(1);

/// Runs `attempt` up to `FILE_ATTEMPTS` times, and stops once `cancel` fires.
pub(super) async fn retry_file<T, Fut>(
    key: &str,
    cancel: &CancellationToken,
    mut attempt: impl FnMut() -> Fut,
) -> Result<T>
where
    Fut: Future<Output = Result<T>>,
{
    let mut result = attempt().await;
    for retry in 1..FILE_ATTEMPTS {
        let Err(e) = &result else { break };
        if cancel.is_cancelled() {
            break;
        }
        let wait = FILE_RETRY_WAIT * retry;
        warn!(
            key,
            retry,
            wait_secs = wait.as_secs(),
            error = %format!("{e:#}"),
            "checkpoint file failed; trying it again",
        );
        if cancel
            .run_until_cancelled(tokio::time::sleep(wait))
            .await
            .is_none()
        {
            break;
        }
        result = attempt().await;
    }
    result
}

/// Build an S3 client wrapped in a `LimitStore` for bounded concurrency, and check that it can list
/// `lineage_dir`.
///
/// Credential priority: explicit config (local dev) → IRSA (`AWS_WEB_IDENTITY_TOKEN_FILE` +
/// `AWS_ROLE_ARN`) → default AWS credential chain.
pub async fn create_s3_client(
    config: &DurabilityConfig,
    max_concurrent_requests: usize,
    lineage_dir: &str,
) -> Result<Arc<LimitStore<AmazonS3>>> {
    let mut builder = AmazonS3Builder::from_env()
        .with_bucket_name(&config.s3_bucket)
        .with_client_options(ClientOptions::new().with_timeout(config.s3_attempt_timeout))
        .with_retry(object_store::RetryConfig {
            // From 1 s instead of object_store's 100 ms, so ten fast failures spread over tens of
            // seconds and outlast a broken connection. Each wait is a random draw between 1 s and
            // twice the last wait, capped at 15 s, so the total stays below about 105 s. Slow
            // attempts reach `retry_timeout` first.
            backoff: BackoffConfig {
                init_backoff: Duration::from_secs(1),
                max_backoff: Duration::from_secs(15),
                base: 2.0,
            },
            max_retries: config.s3_max_retries,
            retry_timeout: config.s3_operation_timeout,
        });

    if let Some(ref region) = config.aws_region {
        builder = builder.with_region(region);
    }

    if let Some(ref endpoint) = config.s3_endpoint {
        builder = builder.with_endpoint(endpoint);
        if endpoint.starts_with("http://") {
            builder = builder.with_allow_http(true);
        }
    }

    // Explicit credentials override the env-based chain (for local dev without IAM).
    if let (Some(ref access_key), Some(ref secret_key)) =
        (&config.s3_access_key_id, &config.s3_secret_access_key)
    {
        info!("Using explicit S3 credentials from config");
        builder = builder
            .with_access_key_id(access_key)
            .with_secret_access_key(secret_key);
    } else if std::env::var("AWS_WEB_IDENTITY_TOKEN_FILE").is_ok()
        && std::env::var("AWS_ROLE_ARN").is_ok()
    {
        info!("Using IRSA credentials (AWS_WEB_IDENTITY_TOKEN_FILE + AWS_ROLE_ARN)");
    } else {
        debug!("Using default AWS credential chain");
    }

    if config.s3_force_path_style {
        builder = builder.with_virtual_hosted_style_request(false);
    }

    let base_store = builder.build().with_context(|| {
        format!(
            "Failed to create S3 client for bucket '{}' in region '{}'",
            config.s3_bucket,
            config.aws_region.as_deref().unwrap_or("default")
        )
    })?;

    let store = Arc::new(LimitStore::new(base_store, max_concurrent_requests));

    validate_bucket_access(&store, &config.s3_bucket, &config.aws_region, lineage_dir).await?;

    Ok(store)
}

/// Lists the lineage's own prefix rather than the bucket root, so the role needs `ListBucket` only
/// on what the pod reads.
async fn validate_bucket_access(
    store: &LimitStore<AmazonS3>,
    bucket: &str,
    region: &Option<String>,
    lineage_dir: &str,
) -> Result<()> {
    info!(bucket = %bucket, prefix = %lineage_dir, "Validating S3 bucket access...");

    let prefix = ObjectPath::from(lineage_dir);
    let mut stream = store.list(Some(&prefix));

    match tokio::time::timeout(VALIDATION_TIMEOUT, stream.next()).await {
        Ok(Some(Err(e))) => Err(anyhow::anyhow!(e)).with_context(|| {
            format!(
                "S3 bucket validation failed for '{}' in region '{}' - check bucket exists, credentials, and network",
                bucket,
                region.as_deref().unwrap_or("default")
            )
        }),
        Err(_) => Err(anyhow::anyhow!(
            "S3 bucket validation timed out after {:?} for bucket '{}' - check network connectivity and credentials",
            VALIDATION_TIMEOUT,
            bucket
        )),
        Ok(Some(Ok(_))) | Ok(None) => {
            info!(bucket = %bucket, "S3 bucket validated successfully");
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validation_timeout_is_reasonable() {
        assert!(VALIDATION_TIMEOUT >= Duration::from_secs(5));
        assert!(VALIDATION_TIMEOUT <= Duration::from_secs(30));
    }
}
