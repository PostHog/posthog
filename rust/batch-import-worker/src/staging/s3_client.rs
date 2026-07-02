use std::sync::Arc;

use anyhow::{Context, Result};
use object_store::aws::AmazonS3Builder;
use object_store::limit::LimitStore;
use object_store::ObjectStore;

use crate::config::Config;

/// Bound concurrent requests to the temp bucket so a single job can't stampede S3.
const MAX_CONCURRENT_REQUESTS: usize = 16;

/// Build the `object_store` client for the temp bucket from config.
///
/// Credentials come from the standard AWS chain (`from_env`): IRSA in production
/// (`AWS_WEB_IDENTITY_TOKEN_FILE` + `AWS_ROLE_ARN`), or `AWS_ACCESS_KEY_ID` /
/// `AWS_SECRET_ACCESS_KEY` locally. A custom endpoint (local dev / SeaweedFS) switches
/// to path-style addressing and allows plain HTTP. The store is wrapped in a
/// `LimitStore` to cap concurrent requests.
pub async fn create_temp_bucket_store(config: &Config) -> Result<Arc<dyn ObjectStore>> {
    let mut builder = AmazonS3Builder::from_env().with_bucket_name(&config.temp_bucket_name);

    if let Some(region) = config.temp_bucket_region() {
        builder = builder.with_region(region);
    }

    if let Some(endpoint) = config.temp_bucket_endpoint() {
        builder = builder.with_endpoint(endpoint);
        if endpoint.starts_with("http://") {
            builder = builder.with_allow_http(true);
        }
        // S3-compatible dev stores (SeaweedFS, MinIO) require path-style addressing.
        builder = builder.with_virtual_hosted_style_request(false);
    }

    let store = builder.build().with_context(|| {
        format!(
            "Failed to build temp-bucket S3 client for bucket '{}'",
            config.temp_bucket_name
        )
    })?;

    Ok(Arc::new(LimitStore::new(store, MAX_CONCURRENT_REQUESTS)))
}
