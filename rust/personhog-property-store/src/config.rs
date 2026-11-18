use std::collections::HashMap;
use std::str::FromStr;
use std::time::Duration;

use envconfig::Envconfig;
use slatedb::config::CompressionCodec;

use crate::PropertyStoreError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Compression {
    None,
    Lz4,
    Zstd,
}

impl Compression {
    pub fn codec(self) -> Option<CompressionCodec> {
        match self {
            Compression::None => None,
            Compression::Lz4 => Some(CompressionCodec::Lz4),
            Compression::Zstd => Some(CompressionCodec::Zstd),
        }
    }
}

impl FromStr for Compression {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "none" => Ok(Compression::None),
            "lz4" => Ok(Compression::Lz4),
            "zstd" => Ok(Compression::Zstd),
            other => Err(format!(
                "unknown compression {other:?}; use none, lz4 or zstd"
            )),
        }
    }
}

/// No `Debug`: it holds S3 credentials.
#[derive(Envconfig, Clone)]
pub struct PropertyStoreConfig {
    /// Required: no default, so a pod cannot write to its own disk by omission.
    #[envconfig(from = "PROPERTY_STORE_URL")]
    pub url: Option<String>,

    #[envconfig(from = "PROPERTY_STORE_S3_ENDPOINT")]
    pub s3_endpoint: Option<String>,

    #[envconfig(from = "PROPERTY_STORE_S3_ACCESS_KEY_ID")]
    pub s3_access_key_id: Option<String>,

    #[envconfig(from = "PROPERTY_STORE_S3_SECRET_ACCESS_KEY")]
    pub s3_secret_access_key: Option<String>,

    #[envconfig(from = "PROPERTY_STORE_S3_REGION")]
    pub s3_region: Option<String>,

    #[envconfig(from = "PROPERTY_STORE_PREFIX", default = "tmp/personhog-properties")]
    pub prefix: String,

    /// Must be a multiple of every changelog partition count.
    #[envconfig(from = "PROPERTY_STORE_SHARDS", default = "64")]
    pub shards: u32,

    #[envconfig(from = "PROPERTY_STORE_L0_SST_BYTES", default = "4194304")]
    pub l0_sst_bytes: usize,

    #[envconfig(from = "PROPERTY_STORE_MAX_UNFLUSHED_BYTES", default = "8388608")]
    pub max_unflushed_bytes: usize,

    #[envconfig(from = "PROPERTY_STORE_MIN_FILTER_KEYS", default = "1")]
    pub min_filter_keys: u32,

    #[envconfig(from = "PROPERTY_STORE_FILTER_BITS_PER_KEY", default = "10")]
    pub filter_bits_per_key: u32,

    /// Bounds the write-ahead log a reopen or reader replays. 0 disables.
    #[envconfig(from = "PROPERTY_STORE_MEMTABLE_FLUSH_SECS", default = "60")]
    pub memtable_flush_secs: u64,

    /// Bounds how long deleted properties survive. 0 disables.
    #[envconfig(from = "PROPERTY_STORE_FULL_COMPACTION_SECS", default = "86400")]
    pub full_compaction_secs: u64,

    #[envconfig(from = "PROPERTY_STORE_MAX_FULL_COMPACTIONS", default = "4")]
    pub max_full_compactions: usize,

    #[envconfig(from = "PROPERTY_STORE_COMPRESSION", default = "zstd")]
    pub compression: Compression,

    /// Off by default: the leader's person cache already holds what this would.
    #[envconfig(from = "PROPERTY_STORE_BLOCK_CACHE_BYTES", default = "0")]
    pub block_cache_bytes: u64,

    #[envconfig(from = "PROPERTY_STORE_META_CACHE_BYTES", default = "67108864")]
    pub meta_cache_bytes: u64,

    /// How often a reader looks for new data; also how far it can lag.
    #[envconfig(from = "PROPERTY_STORE_READER_POLL_MS", default = "5000")]
    pub reader_poll_ms: u64,

    /// Readers see a write only once a memtable flush puts it in an SST, so they lag by up to
    /// `PROPERTY_STORE_MEMTABLE_FLUSH_SECS` but never fetch WAL files.
    #[envconfig(from = "PROPERTY_STORE_READER_SKIP_WAL", default = "false")]
    pub reader_skip_wal: bool,

    #[envconfig(from = "PROPERTY_STORE_READ_TIMEOUT_MS", default = "1000")]
    pub read_timeout_ms: u64,

    /// Bounds opening a partition's shards, which replays the WAL since the last memtable flush.
    #[envconfig(from = "PROPERTY_STORE_OPEN_TIMEOUT_MS", default = "10000")]
    pub open_timeout_ms: u64,

    #[envconfig(from = "PROPERTY_STORE_READER_MEMTABLE_BYTES", default = "8388608")]
    pub reader_memtable_bytes: u64,

    #[envconfig(from = "PROPERTY_STORE_READER_IDLE_SECS", default = "300")]
    pub reader_idle_secs: u64,

    #[envconfig(from = "PROPERTY_STORE_MAX_FRESH_READS", default = "8")]
    pub max_fresh_reads: usize,

    #[envconfig(from = "PROPERTY_STORE_EXPRESS_BUCKETS", default = "")]
    pub express_buckets: String,

    #[envconfig(from = "PROPERTY_STORE_EXPRESS_READ_BUCKET", default = "")]
    pub express_read_bucket: String,

    /// Bounds how long an upload waits on one copy; a slow copy is dropped, not retried.
    #[envconfig(from = "PROPERTY_STORE_EXPRESS_COPY_TIMEOUT_MS", default = "5000")]
    pub express_copy_timeout_ms: u64,

    #[envconfig(from = "PROPERTY_STORE_EXPRESS_READ_TIMEOUT_MS", default = "100")]
    pub express_read_timeout_ms: u64,
}

impl PropertyStoreConfig {
    pub fn local(prefix: &str, shards: u32) -> Self {
        let mut env = HashMap::new();
        env.insert("PROPERTY_STORE_PREFIX".to_string(), prefix.to_string());
        env.insert("PROPERTY_STORE_SHARDS".to_string(), shards.to_string());
        Self::init_from_hashmap(&env).expect("defaults parse")
    }

    pub fn url(&self) -> Result<&str, PropertyStoreError> {
        self.url
            .as_deref()
            .filter(|url| !url.is_empty())
            .ok_or_else(|| PropertyStoreError::Config("PROPERTY_STORE_URL is required".to_string()))
    }

    pub fn location(&self) -> Result<String, PropertyStoreError> {
        Ok(format!(
            "{}/{}",
            self.url()?.trim_end_matches('/'),
            self.prefix.trim_matches('/')
        ))
    }

    pub fn reader_poll_interval(&self) -> Duration {
        Duration::from_millis(self.reader_poll_ms.max(1))
    }

    pub fn read_timeout(&self) -> Duration {
        Duration::from_millis(self.read_timeout_ms.max(1))
    }

    pub fn open_timeout(&self) -> Duration {
        Duration::from_millis(self.open_timeout_ms.max(1))
    }

    pub fn express_bucket_list(&self) -> Vec<&str> {
        self.express_buckets
            .split(',')
            .map(str::trim)
            .filter(|bucket| !bucket.is_empty())
            .collect()
    }

    pub fn express_copy_timeout(&self) -> Duration {
        Duration::from_millis(self.express_copy_timeout_ms.max(1))
    }

    pub fn express_read_timeout(&self) -> Duration {
        Duration::from_millis(self.express_read_timeout_ms.max(1))
    }

    pub fn reader_idle(&self) -> Duration {
        Duration::from_secs(self.reader_idle_secs.max(1))
    }

    fn optional_secs(secs: u64) -> Option<Duration> {
        (secs > 0).then(|| Duration::from_secs(secs))
    }

    pub fn memtable_flush_interval(&self) -> Option<Duration> {
        Self::optional_secs(self.memtable_flush_secs)
    }

    pub fn full_compaction_interval(&self) -> Option<Duration> {
        Self::optional_secs(self.full_compaction_secs)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_store_has_no_location_until_its_url_is_set() {
        let mut config = PropertyStoreConfig::local("/props/", 1);
        assert!(config.location().is_err());
        config.url = Some("s3://bucket/".to_string());
        assert_eq!(config.location().unwrap(), "s3://bucket/props");
    }
}
