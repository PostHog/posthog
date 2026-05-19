//! Shared S3 client setup for checkpoint uploader and downloader.
//!
//! This module provides a unified way to create S3 clients with proper
//! credential resolution for both production (IRSA) and local dev (MinIO).

use anyhow::{Context, Result};
use futures::StreamExt;
use object_store::aws::{AmazonS3, AmazonS3Builder};
use object_store::limit::LimitStore;
use object_store::path::Path as ObjectPath;
use object_store::{ClientOptions, ObjectStore};
use std::sync::Arc;
use std::time::Duration;
use tracing::{debug, info};

use super::config::CheckpointConfig;

/// Timeout for bucket validation during client initialization.
/// Keep this short to fail fast on misconfiguration rather than hanging.
const VALIDATION_TIMEOUT: Duration = Duration::from_secs(10);

/// Create an S3 client with proper credential resolution.
///
/// Credential priority:
/// 1. Explicit credentials from config (for local dev/CI with MinIO)
/// 2. IRSA via AWS_WEB_IDENTITY_TOKEN_FILE + AWS_ROLE_ARN (for EKS production)
/// 3. Default credential chain (IMDS, env vars, config files)
///
/// The client is wrapped in a `LimitStore` to bound concurrent requests.
pub async fn create_s3_client(
    config: &CheckpointConfig,
    max_concurrent_requests: usize,
) -> Result<Arc<LimitStore<AmazonS3>>> {
    // Start with from_env() to pick up AWS_* vars including IRSA credentials
    // (AWS_WEB_IDENTITY_TOKEN_FILE, AWS_ROLE_ARN, AWS_REGION, etc.)
    let mut builder = AmazonS3Builder::from_env()
        .with_bucket_name(&config.s3_bucket)
        .with_client_options(ClientOptions::new().with_timeout(config.s3_attempt_timeout))
        .with_retry(object_store::RetryConfig {
            max_retries: config.s3_max_retries,
            retry_timeout: config.s3_operation_timeout,
            ..Default::default()
        });

    // Set region if provided (overrides env)
    if let Some(ref region) = config.aws_region {
        builder = builder.with_region(region);
    }

    // Set custom endpoint for MinIO/local dev
    if let Some(ref endpoint) = config.s3_endpoint {
        builder = builder.with_endpoint(endpoint);
        if endpoint.starts_with("http://") {
            builder = builder.with_allow_http(true);
        }
    }

    // Explicit credentials override env (for local dev without IAM)
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

    // Force path-style URLs if needed (required for MinIO)
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

    // Validate bucket access with SHORT timeout - fail fast if misconfigured
    validate_bucket_access(&store, &config.s3_bucket, &config.aws_region).await?;

    Ok(store)
}

/// Validate bucket access with a short timeout to fail fast on misconfiguration.
///
/// This prevents the service from hanging for minutes when S3 is unreachable
/// or credentials are invalid, allowing K8s health checks to fail quickly
/// with a meaningful error message.
async fn validate_bucket_access(
    store: &LimitStore<AmazonS3>,
    bucket: &str,
    region: &Option<String>,
) -> Result<()> {
    info!(bucket = %bucket, "Validating S3 bucket access...");

    let prefix = ObjectPath::from("");
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
    fn test_validation_timeout_is_reasonable() {
        // Ensure the validation timeout is short enough to fail fast
        // but long enough for a healthy S3 to respond
        assert!(VALIDATION_TIMEOUT >= Duration::from_secs(5));
        assert!(VALIDATION_TIMEOUT <= Duration::from_secs(30));
    }
}
