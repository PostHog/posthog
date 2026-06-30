//! Shared hypercache-write plumbing for the out-of-process flags-cache binaries
//! (`warm-flags-cache` and `flags-cache-builder`).
//!
//! These constants and helpers are deliberately in one place: if the namespace,
//! object name, or expiry sorted-set key drifted between the two writers, one
//! binary would write cache entries the request path can't read — a silent
//! prod bug. Sharing the definitions makes that impossible.

use crate::flags::flag_models::HypercacheFlagsWrapper;
use common_hypercache::writer::HyperCacheWriter;
use common_hypercache::{HyperCacheConfig, HyperCacheError, KeyType};
use common_types::TeamId;

/// Redis sorted-set key used by Python's `FLAGS_CACHE_EXPIRY_SORTED_SET`. Keeping
/// these in lockstep lets the existing refresh/verification workflows pick up
/// entries these binaries write.
pub const FLAGS_CACHE_EXPIRY_SORTED_SET: &str = "flags_cache_expiry";

/// HyperCache namespace and object-name used by Python's flags warmer. Must match
/// the feature-flags service's reader so entries written here are discoverable at
/// request time.
pub const HYPERCACHE_NAMESPACE: &str = "feature_flags";
pub const HYPERCACHE_OBJECT_NAME: &str = "flags.json";

/// Build the hypercache config the flags binaries use, wiring the expiry
/// sorted-set key and (optionally) a custom S3 endpoint for local dev / MinIO.
pub fn make_cache_config(
    region: &str,
    bucket: &str,
    s3_endpoint: Option<&str>,
) -> HyperCacheConfig {
    let mut config = HyperCacheConfig::new(
        HYPERCACHE_NAMESPACE.to_string(),
        HYPERCACHE_OBJECT_NAME.to_string(),
        region.to_string(),
        bucket.to_string(),
    );
    if let Some(endpoint) = s3_endpoint.filter(|e| !e.is_empty()) {
        config.s3_endpoint = Some(endpoint.to_string());
    }
    config.expiry_sorted_set_key = Some(FLAGS_CACHE_EXPIRY_SORTED_SET.to_string());
    config
}

/// Outcome of a successful persist, for callers that want to log it.
pub struct PersistOutcome {
    pub etag: String,
    pub size_bytes: usize,
}

/// Persist a freshly built flags cache for `team_id` with the given TTL.
///
/// Uses `set_with_etag` (not `set`): `set()` unconditionally DELs the `:etag` key
/// via `delete_etag`, and `FlagDefinitionsCache` keys on `(team_id, etag)`, so a
/// missing etag forces the in-memory cache bypass on every `/flags` request.
///
/// On success, returns the etag and serialized size so callers can log what was
/// written. On failure, returns the typed `HyperCacheError` so callers can
/// attribute it to the Redis vs S3 vs serialization tier (the flags-cache-builder
/// uses this to label its build-failure metric and DLQ headers for triage).
pub async fn persist_flags_cache(
    writer: &HyperCacheWriter,
    team_id: TeamId,
    cache: &HypercacheFlagsWrapper,
    ttl_seconds: u64,
) -> Result<PersistOutcome, HyperCacheError> {
    let key = KeyType::int(team_id);
    let json = serde_json::to_string(cache)?;
    let size_bytes = json.len();
    let etag = writer.set_with_etag(&key, &json, ttl_seconds).await?;
    Ok(PersistOutcome { etag, size_bytes })
}

/// Assemble the hypercache writer the flags binaries use: an S3 client plus the
/// shared cache config, wired to the dedicated flags Redis. Both binaries go
/// through this one constructor so the two writers can't drift. Empty
/// `s3_endpoint` is treated as "no override" by the helpers below.
#[cfg(any(feature = "warm-flags-cache", feature = "flags-cache-builder"))]
pub async fn build_writer(
    redis_client: std::sync::Arc<dyn common_redis::Client + Send + Sync>,
    region: &str,
    bucket: &str,
    s3_endpoint: Option<&str>,
) -> HyperCacheWriter {
    let s3_client = create_s3_client(region, s3_endpoint).await;
    let config = make_cache_config(region, bucket, s3_endpoint);
    HyperCacheWriter::new(redis_client, s3_client, config)
}

/// Construct an S3 client for the flags binaries. Gated to the binary features so
/// the AWS SDK stays out of the request-path server build.
#[cfg(any(feature = "warm-flags-cache", feature = "flags-cache-builder"))]
pub async fn create_s3_client(
    region: &str,
    s3_endpoint: Option<&str>,
) -> std::sync::Arc<dyn common_s3::S3Client + Send + Sync> {
    use std::sync::Arc;

    let endpoint = s3_endpoint.filter(|e| !e.is_empty());

    let mut aws_config_builder = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .region(aws_config::Region::new(region.to_string()));
    if let Some(endpoint) = endpoint {
        aws_config_builder = aws_config_builder.endpoint_url(endpoint);
    }
    let aws_config = aws_config_builder.load().await;

    let mut s3_config_builder = aws_sdk_s3::config::Builder::from(&aws_config);
    if endpoint.is_some() {
        // Path-style addressing for MinIO / SeaweedFS, which don't do
        // virtual-host bucket subdomains.
        s3_config_builder = s3_config_builder.force_path_style(true);
    }

    let aws_s3_client = aws_sdk_s3::Client::from_conf(s3_config_builder.build());
    Arc::new(common_s3::S3Impl::new(aws_s3_client))
}
