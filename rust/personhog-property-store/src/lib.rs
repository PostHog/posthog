pub mod config;
pub mod encoding;
mod engine;
pub mod express;
pub mod reader;
pub mod repair;
pub mod writer;

pub use config::{Compression, PropertyStoreConfig};
pub use encoding::{StoredProperties, STUB_VERSION};
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

impl PropertyStoreError {
    /// `data` needs someone to look at the stored bytes; `unavailable` passes once the store does.
    pub fn class(&self) -> &'static str {
        match self {
            PropertyStoreError::Malformed { .. } => "data",
            PropertyStoreError::Slate(e) if e.kind() == slatedb::ErrorKind::Data => "data",
            _ => "unavailable",
        }
    }
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
    // SlateDB's resolver refuses a path in the URL, so a local directory is opened here.
    if let Some(path) = url
        .strip_prefix("file://")
        .filter(|p| !p.trim_matches('/').is_empty())
    {
        let local = std::fs::create_dir_all(path)
            .map_err(|e| e.to_string())
            .and_then(|()| {
                object_store::local::LocalFileSystem::new_with_prefix(path)
                    .map_err(|e| e.to_string())
            })
            .map_err(|e| {
                PropertyStoreError::Config(format!("local object store at {path}: {e}"))
            })?;
        return Ok(Arc::new(local));
    }
    let Some(bucket_and_path) = url.strip_prefix("s3://") else {
        return Ok(slatedb::Db::resolve_object_store(url)?);
    };
    if bucket_and_path.trim_end_matches('/').contains('/') {
        return Err(PropertyStoreError::Config(format!(
            "PROPERTY_STORE_URL {url} has a path; S3 ignores it, use PROPERTY_STORE_PREFIX"
        )));
    }
    build_s3(s3_builder(config).with_url(url))
}

pub fn writer_object_store(
    config: &PropertyStoreConfig,
) -> Result<Arc<dyn ObjectStore>, PropertyStoreError> {
    let primary = object_store(config)?;
    let copies = express_buckets(config)?;
    if copies.is_empty() {
        return Ok(primary);
    }
    Ok(Arc::new(express::TeeStore::new(
        primary,
        copies,
        config.express_copy_timeout(),
    )))
}

pub fn express_buckets(
    config: &PropertyStoreConfig,
) -> Result<Vec<express::Bucket>, PropertyStoreError> {
    config
        .express_bucket_list()
        .into_iter()
        .map(|bucket| Ok(express::Bucket::new(bucket, bucket_store(config, bucket)?)))
        .collect()
}

pub fn reader_object_store(
    config: &PropertyStoreConfig,
) -> Result<Arc<dyn ObjectStore>, PropertyStoreError> {
    let primary = object_store(config)?;
    let own = config.express_read_bucket.trim();
    if own.is_empty() {
        return Ok(primary);
    }
    let order = std::iter::once(own).chain(
        config
            .express_bucket_list()
            .into_iter()
            .filter(|bucket| *bucket != own),
    );
    let buckets = order
        .map(|bucket| Ok(express::Bucket::new(bucket, bucket_store(config, bucket)?)))
        .collect::<Result<Vec<_>, PropertyStoreError>>()?;
    Ok(Arc::new(express::ReadThroughStore::new(
        primary,
        buckets,
        config.express_read_timeout(),
    )))
}

/// A directory bucket name ends in `--x-s3` (AWS naming rule), so any other name is a plain
/// bucket on the configured endpoint, which is how the local stack stands one in.
fn bucket_store(
    config: &PropertyStoreConfig,
    bucket: &str,
) -> Result<Arc<dyn ObjectStore>, PropertyStoreError> {
    let builder = if bucket.ends_with("--x-s3") {
        let mut builder = object_store::aws::AmazonS3Builder::from_env().with_s3_express(true);
        if let Some(region) = &config.s3_region {
            builder = builder.with_region(region);
        }
        builder
    } else {
        s3_builder(config)
    };
    build_s3(builder.with_bucket_name(bucket))
}

fn s3_builder(config: &PropertyStoreConfig) -> object_store::aws::AmazonS3Builder {
    let mut builder = object_store::aws::AmazonS3Builder::from_env();
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
    builder
}

fn build_s3(
    builder: object_store::aws::AmazonS3Builder,
) -> Result<Arc<dyn ObjectStore>, PropertyStoreError> {
    let store = builder
        .build()
        .map_err(|e| PropertyStoreError::Config(format!("s3 object store: {e}")))?;
    Ok(Arc::new(store))
}

#[cfg(test)]
mod tests {
    use object_store::ObjectStoreExt;

    use super::*;

    #[tokio::test]
    async fn a_file_url_with_a_path_opens_that_directory() {
        let dir = tempfile::tempdir().unwrap();
        let mut config = PropertyStoreConfig::local("props", 1);
        config.url = Some(format!("file://{}", dir.path().join("store").display()));

        let store = object_store(&config).unwrap();
        store
            .put(
                &object_store::path::Path::from("marker"),
                object_store::PutPayload::from_static(b"1"),
            )
            .await
            .unwrap();

        assert!(dir.path().join("store/marker").exists());
    }

    #[test]
    fn an_s3_url_with_a_path_is_refused() {
        let mut config = PropertyStoreConfig::local("props", 1);
        config.url = Some("s3://bucket/path".to_string());

        assert!(matches!(
            object_store(&config),
            Err(PropertyStoreError::Config(_))
        ));
    }
}
