pub mod config;
pub mod encoding;
mod engine;
pub mod reader;
pub mod writer;

pub use config::{Compression, PropertyStoreConfig};
pub use encoding::StoredProperties;
pub use reader::PropertyReader;
pub use writer::{PartitionKey, PropertyRecord, PropertyWriter, PutError};

pub use slatedb::{bytes, object_store};

use std::sync::Arc;

use object_store::ObjectStore;

#[derive(Debug, thiserror::Error)]
pub enum PropertyStoreError {
    #[error("slatedb: {0}")]
    Slate(#[from] slatedb::Error),
    #[error("stored value for team {team_id} person {person_id} is malformed: {reason}")]
    Malformed {
        team_id: i64,
        person_id: i64,
        reason: String,
    },
    #[error("invalid configuration: {0}")]
    Config(String),
    #[error("{0}")]
    ShardLayout(String),
    #[error("property store read timed out")]
    Timeout,
    #[error("property store shard {shard} unavailable: {reason}")]
    ShardUnavailable { shard: u32, reason: String },
}

/// SlateDB reports object-store requests in seconds, which the default millisecond ladder cannot resolve.
pub const OBJECT_STORE_REQUEST_DURATION: &str = "slatedb_object_store_request_duration_seconds";
pub const OBJECT_STORE_REQUEST_BUCKETS_SECONDS: &[f64] = &[
    0.002, 0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
];

pub const READ_LATENCY_BUCKETS_MS: &[f64] = &[
    1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 75.0, 100.0, 125.0, 150.0, 200.0, 250.0,
    300.0, 400.0, 500.0, 750.0, 1000.0, 2000.0, 5000.0,
];

/// A shard count that is a multiple of the partition count maps every shard to one partition.
pub fn shard_for(team_id: i64, person_id: i64, shards: u32) -> u32 {
    personhog_common::partitioning::person_hash(team_id, person_id) % shards
}

fn shard_path(prefix: &str, shard: u32) -> String {
    format!("{prefix}/shard-{shard:05}")
}

pub fn object_store(
    config: &PropertyStoreConfig,
) -> Result<Arc<dyn ObjectStore>, PropertyStoreError> {
    let url = config.url()?;
    if !url.starts_with("s3://") {
        return Ok(slatedb::Db::resolve_object_store(url)?);
    }
    let mut builder = object_store::aws::AmazonS3Builder::from_env().with_url(url);
    if let Some(endpoint) = &config.s3_endpoint {
        builder = builder
            .with_endpoint(endpoint)
            .with_allow_http(endpoint.starts_with("http://"));
    }
    if let Some(key) = &config.s3_access_key_id {
        builder = builder.with_access_key_id(key);
    }
    if let Some(secret) = &config.s3_secret_access_key {
        builder = builder.with_secret_access_key(secret);
    }
    if let Some(region) = &config.s3_region {
        builder = builder.with_region(region);
    }
    let store = builder
        .build()
        .map_err(|e| PropertyStoreError::Config(format!("s3 object store: {e}")))?;
    Ok(Arc::new(store))
}
