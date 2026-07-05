//! Checkpoint metadata: the per-attempt file registry, plus S3-key construction.
//!
//! `topic`/`partition` are pinned to the fixed store identity (`STORE_TOPIC`/`STORE_PARTITION`); the
//! offset scalars are written as 0 and never read, since offset positions live in a separate manifest.

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tracing::debug;

use super::{STORE_PARTITION, STORE_TOPIC};
use crate::store::STORE_SCHEMA_VERSION;

/// Deterministic 8-hex-char prefix for spreading S3 object keys across internal partitions.
/// Applied ONLY to checkpoint object file paths, NEVER to metadata.json paths.
pub fn hash_prefix_for_partition(topic: &str, partition: i32) -> String {
    let input = format!("{topic}/{partition}");
    let hash = Sha256::digest(input.as_bytes());
    format!(
        "{:02x}{:02x}{:02x}{:02x}",
        hash[0], hash[1], hash[2], hash[3]
    )
}

/// The single, process-wide S3 hash prefix, derived from the fixed store identity. One DB holds all
/// partitions, so there is exactly one stable prefix. Computed once and cached.
pub fn store_hash_prefix() -> &'static str {
    static PREFIX: OnceLock<String> = OnceLock::new();
    PREFIX.get_or_init(|| hash_prefix_for_partition(STORE_TOPIC, STORE_PARTITION))
}

/// Build the store path `<base_path>/<topic>/<partition>`. Slashes in the topic are replaced with
/// `_` to guarantee a two-level directory structure.
fn format_store_path(base_path: &Path, topic: &str, partition: i32) -> PathBuf {
    base_path
        .join(topic.replace('/', "_"))
        .join(partition.to_string())
}

/// Filename of the checkpoint metadata JSON file. Used in remote checkpoint attempt directories (S3)
/// and in local store directories (see `write_to_dir` / `load_from_dir`).
pub const METADATA_FILENAME: &str = "metadata.json";
/// Hour-scoped prefix format used to filter the S3 listing window.
pub const DATE_PLUS_HOURS_ONLY_FORMAT: &str = "%Y-%m-%d-%H";
/// Checkpoint ID format: human-readable S3 path element derived from `attempt_timestamp`.
pub const TIMESTAMP_FORMAT: &str = "%Y-%m-%dT%H-%M-%SZ";

/// Metadata about a checkpoint. Can be written to and loaded from a local store directory via
/// `write_to_dir` / `load_from_dir` (e.g. after import or for round-trip tests).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointMetadata {
    /// Checkpoint ID (RFC3339-ish timestamp, e.g., "2025-10-14T16-00-05Z")
    pub id: String,
    /// Topic name (fixed to `STORE_TOPIC`).
    pub topic: String,
    /// Partition number (fixed to `STORE_PARTITION`).
    pub partition: i32,
    /// Timestamp of this checkpoint's attempt
    pub attempt_timestamp: DateTime<Utc>,
    /// RocksDB sequence number at checkpoint time
    pub sequence: u64,
    /// Unused: written as 0 and never read (offsets live in a separate manifest).
    pub consumer_offset: i64,
    /// Unused: written as 0 and never read.
    pub producer_offset: i64,
    /// When this metadata was last written (creation or local write). Serde default when
    /// deserializing metadata.json that lacks this field (backward compat).
    #[serde(default = "Utc::now")]
    pub updated_at: DateTime<Utc>,
    /// The store schema version ([`STORE_SCHEMA_VERSION`]) the checkpointed DB was written under.
    /// Stamped at construction. A restore skips a checkpoint whose `store_schema` does not match this
    /// binary's `STORE_SCHEMA_VERSION` before downloading it, so an incompatible on-disk layout is
    /// never imported. `#[serde(default)]` makes pre-versioning metadata.json decode to `0`, which
    /// never matches a real version and is therefore skipped — the intended "old checkpoints are
    /// unusable" behavior. The store's open-time CF-set/version guard remains the backstop.
    #[serde(default)]
    pub store_schema: u32,
    /// Registry of file metadata for all remotely-stored files required to reconstitute a local
    /// RocksDB store across all relevant checkpoint attempts.
    pub files: Vec<CheckpointFile>,
}

impl CheckpointMetadata {
    pub fn new(
        topic: String,
        partition: i32,
        attempt_timestamp: DateTime<Utc>,
        sequence: u64,
        consumer_offset: i64,
        producer_offset: i64,
    ) -> Self {
        Self {
            id: CheckpointMetadata::generate_id(attempt_timestamp),
            topic,
            partition,
            attempt_timestamp,
            sequence,
            consumer_offset,
            producer_offset,
            updated_at: attempt_timestamp,
            // Every constructed metadata describes a NEW checkpoint of this binary's store, so it is
            // stamped with the current schema version. Older on-disk metadata.json decodes `0` via the
            // serde default and is skipped on restore.
            store_schema: STORE_SCHEMA_VERSION,
            files: Vec::new(),
        }
    }

    pub fn generate_id(attempt_timestamp: DateTime<Utc>) -> String {
        attempt_timestamp.format(TIMESTAMP_FORMAT).to_string()
    }

    pub fn from_json_bytes(json: &[u8]) -> Result<Self> {
        let metadata: Self =
            serde_json::from_slice(json).context("In CheckpointMetadata::from_json")?;
        Ok(metadata)
    }

    pub async fn load_from_dir(dir: &Path) -> Result<Self> {
        let path = dir.join(METADATA_FILENAME);
        let json = tokio::fs::read_to_string(&path)
            .await
            .with_context(|| format!("Failed to read metadata from: {path:?}"))?;
        let metadata: Self = serde_json::from_str(&json)
            .with_context(|| format!("Failed to parse metadata from: {path:?}"))?;
        Ok(metadata)
    }

    /// Write metadata.json atomically (tmp file + rename) to prevent torn reads.
    pub async fn write_to_dir(&mut self, dir: &Path) -> Result<()> {
        self.updated_at = Utc::now();
        let json = self.to_json().context("In write_to_dir")?;
        let path = dir.join(METADATA_FILENAME);
        let tmp_path = dir.join(".metadata.json.tmp");
        if let Err(e) = tokio::fs::write(&tmp_path, json).await {
            drop(tokio::fs::remove_file(&tmp_path).await);
            return Err(e)
                .with_context(|| format!("Failed to write temp metadata to: {tmp_path:?}"));
        }
        tokio::fs::rename(&tmp_path, &path)
            .await
            .with_context(|| format!("Failed to rename temp metadata to: {path:?}"))?;
        debug!("Saved checkpoint metadata to {:?}", path);
        Ok(())
    }

    pub fn track_file(&mut self, remote_filepath: String, checksum: String) {
        self.files
            .push(CheckpointFile::new(remote_filepath, checksum));
    }

    /// Returns `<topic>/<partition>/<checkpoint_id>`, excluding bucket namespace and local base path.
    pub fn get_attempt_path(&self) -> String {
        format!("{}/{}/{}", self.topic, self.partition, self.id)
    }

    pub fn get_store_path(&self, local_store_base_path: &Path) -> PathBuf {
        format_store_path(local_store_base_path, &self.topic, self.partition)
    }

    pub fn get_metadata_filepath(&self) -> String {
        format!("{}/{}", self.get_attempt_path(), METADATA_FILENAME)
    }

    pub fn to_json(&self) -> Result<String> {
        serde_json::to_string_pretty(self).context("Failed to serialize checkpoint metadata")
    }
}

#[derive(Debug, Clone)]
pub struct CheckpointInfo {
    pub metadata: CheckpointMetadata,
    /// App-level S3 bucket namespace for all checkpoint attempts.
    pub s3_key_prefix: String,
    /// When `Some`, object file keys include this prefix; metadata.json keys never do.
    pub hash_prefix: Option<String>,
}

impl CheckpointInfo {
    pub fn new(
        metadata: CheckpointMetadata,
        s3_key_prefix: String,
        hash_prefix: Option<String>,
    ) -> Self {
        Self {
            metadata,
            s3_key_prefix,
            hash_prefix,
        }
    }

    pub fn get_metadata_key(&self) -> String {
        match &self.hash_prefix {
            Some(h) => format!(
                "{}/{}/{}",
                h,
                self.s3_key_prefix,
                self.metadata.get_metadata_filepath()
            ),
            None => format!(
                "{}/{}",
                self.s3_key_prefix,
                self.metadata.get_metadata_filepath()
            ),
        }
    }

    /// Fully-qualified remote path for a file in this attempt (`relative_file_path` is filename only).
    /// Files from prior attempts already carry their full remote path and should not go through this.
    pub fn get_file_key(&self, relative_file_path: &str) -> String {
        match &self.hash_prefix {
            Some(h) => format!(
                "{}/{}/{}/{}",
                h,
                self.s3_key_prefix,
                self.metadata.get_attempt_path(),
                relative_file_path
            ),
            None => format!("{}/{}", self.get_remote_attempt_path(), relative_file_path),
        }
    }

    pub fn get_remote_attempt_path(&self) -> String {
        match &self.hash_prefix {
            Some(h) => format!(
                "{}/{}/{}",
                h,
                self.s3_key_prefix,
                self.metadata.get_attempt_path(),
            ),
            None => format!(
                "{}/{}",
                self.s3_key_prefix,
                self.metadata.get_attempt_path(),
            ),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointFile {
    /// Fully-qualified remote path from the original upload. Object files:
    /// `<hash>/<namespace>/<topic>/<partition>/<id>/<filename>`. The importer GETs using this path.
    pub remote_filepath: String,

    /// SHA256 of the file contents. Planning compares it against a same-named file from the previous
    /// attempt to decide reuse vs re-upload. Computed for mutable (non-SST) files only; SST files are
    /// immutable, so their checksum is left empty.
    pub checksum: String,
}

impl CheckpointFile {
    pub fn new(remote_filepath: String, checksum: String) -> Self {
        Self {
            remote_filepath,
            checksum,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[tokio::test]
    async fn checkpoint_metadata_creation() {
        let attempt_timestamp = Utc::now();
        let metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            attempt_timestamp,
            1234567890,
            0,
            0,
        );

        assert_eq!(
            metadata.id,
            CheckpointMetadata::generate_id(attempt_timestamp)
        );
        assert_eq!(metadata.topic, STORE_TOPIC);
        assert_eq!(metadata.partition, STORE_PARTITION);
        assert_eq!(metadata.sequence, 1234567890);
        assert_eq!(metadata.files.len(), 0);
    }

    #[tokio::test]
    async fn write_to_dir_creates_metadata_json_file() {
        let dir = TempDir::new().unwrap();
        let mut metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            Utc::now(),
            1,
            0,
            0,
        );
        metadata.write_to_dir(dir.path()).await.unwrap();
        let path = dir.path().join(METADATA_FILENAME);
        assert!(
            path.exists(),
            "write_to_dir should create {METADATA_FILENAME} in dir",
        );
    }

    #[tokio::test]
    async fn load_from_dir_fails_when_metadata_missing() {
        let dir = TempDir::new().unwrap();
        let result = CheckpointMetadata::load_from_dir(dir.path()).await;
        assert!(result.is_err(), "load_from_dir on empty dir should fail");
    }

    #[tokio::test]
    async fn write_to_dir_and_load_from_dir_round_trip() {
        let dir = TempDir::new().unwrap();
        let bucket_namespace = "checkpoints";
        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);

        let mut metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            attempt_timestamp,
            9876543210,
            0,
            0,
        );
        metadata.track_file(
            format!(
                "{}/{}/000001.sst",
                bucket_namespace,
                metadata.get_attempt_path()
            ),
            "checksum1".to_string(),
        );

        metadata.write_to_dir(dir.path()).await.unwrap();

        let loaded = CheckpointMetadata::load_from_dir(dir.path()).await.unwrap();

        assert_eq!(loaded.id, metadata.id);
        assert_eq!(loaded.topic, metadata.topic);
        assert_eq!(loaded.partition, metadata.partition);
        assert_eq!(loaded.attempt_timestamp, metadata.attempt_timestamp);
        assert_eq!(loaded.sequence, metadata.sequence);
        assert_eq!(loaded.files.len(), 1);
        let expected_remote_file_path = format!(
            "{bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}/000001.sst"
        );
        assert_eq!(loaded.files[0].remote_filepath, expected_remote_file_path);
        assert_eq!(loaded.files[0].checksum, "checksum1");

        assert!(
            (loaded.updated_at - Utc::now()).num_seconds().abs() < 2,
            "updated_at should be approximately now after write_to_dir, got {:?}",
            loaded.updated_at
        );
    }

    #[test]
    fn updated_at_set_on_creation() {
        let attempt_timestamp = Utc::now();
        let metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            attempt_timestamp,
            1,
            0,
            0,
        );
        assert_eq!(metadata.updated_at, attempt_timestamp);
    }

    #[test]
    fn updated_at_serde_default() {
        let json = r#"{
            "id": "2025-06-15T12-00-00Z",
            "topic": "cohort_stream_state",
            "partition": 0,
            "attempt_timestamp": "2025-06-15T12:00:00Z",
            "sequence": 1,
            "consumer_offset": 0,
            "producer_offset": 0,
            "files": []
        }"#;
        let metadata: CheckpointMetadata =
            serde_json::from_str(json).expect("deserialize without updated_at should succeed");
        assert_eq!(metadata.topic, "cohort_stream_state");
        assert_eq!(metadata.partition, 0);
        assert!(metadata.updated_at.timestamp() > 0);
        // The pre-versioning metadata.json above has no `store_schema`, so it decodes to `0` — a value
        // that never matches a real `STORE_SCHEMA_VERSION`, so restore skips such old-era checkpoints.
        assert_eq!(
            metadata.store_schema, 0,
            "metadata without store_schema defaults to 0 (old-era, skipped on restore)",
        );
    }

    #[test]
    fn store_schema_is_stamped_on_new_and_round_trips() {
        let mut metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            Utc::now(),
            1,
            0,
            0,
        );
        assert_eq!(
            metadata.store_schema, STORE_SCHEMA_VERSION,
            "a newly-constructed checkpoint is stamped with the current store schema",
        );
        // The field must survive a JSON round-trip so it is present in the persisted metadata.json.
        let decoded = CheckpointMetadata::from_json_bytes(metadata.to_json().unwrap().as_bytes())
            .expect("round-trip");
        assert_eq!(decoded.store_schema, STORE_SCHEMA_VERSION);

        // A hand-forged older-era value survives decode unchanged (so the restore skip can read it).
        metadata.store_schema = STORE_SCHEMA_VERSION - 1;
        let older = CheckpointMetadata::from_json_bytes(metadata.to_json().unwrap().as_bytes())
            .expect("round-trip");
        assert_eq!(older.store_schema, STORE_SCHEMA_VERSION - 1);
    }

    #[test]
    fn get_attempt_path_formats_topic_partition_id() {
        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);

        let metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            attempt_timestamp,
            1234567890,
            0,
            0,
        );

        let prefix = metadata.get_attempt_path();
        let expected_attempt_path = format!("{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}");
        assert_eq!(prefix, expected_attempt_path);
    }

    #[test]
    fn checkpoint_info_keys_without_hash_prefix() {
        let attempt_timestamp = Utc::now();
        let bucket_namespace = "checkpoints";
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            attempt_timestamp,
            1234567890,
            0,
            0,
        );

        let info = CheckpointInfo::new(metadata, bucket_namespace.to_string(), None);

        assert_eq!(
            info.get_metadata_key(),
            format!(
                "{bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}/{METADATA_FILENAME}"
            )
        );

        let local_file_relative_path = "000001.sst";
        assert_eq!(
            info.get_file_key(local_file_relative_path),
            format!(
                "{bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}/000001.sst"
            )
        );
    }

    #[test]
    fn hash_prefix_deterministic() {
        let h1 = hash_prefix_for_partition("events", 0);
        let h2 = hash_prefix_for_partition("events", 0);
        assert_eq!(h1, h2);
    }

    #[test]
    fn hash_prefix_different_partitions() {
        let h0 = hash_prefix_for_partition("events", 0);
        let h1 = hash_prefix_for_partition("events", 1);
        let h2 = hash_prefix_for_partition("other-topic", 0);
        assert_ne!(h0, h1);
        assert_ne!(h0, h2);
        assert_ne!(h1, h2);
    }

    #[test]
    fn hash_prefix_format() {
        let h = hash_prefix_for_partition("t", 0);
        assert_eq!(h.len(), 8);
        assert!(h.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn store_hash_prefix_is_the_single_db_identity_hash() {
        assert_eq!(
            store_hash_prefix(),
            hash_prefix_for_partition(STORE_TOPIC, STORE_PARTITION)
        );
    }

    #[test]
    fn checkpoint_info_with_hash_prefix() {
        let attempt_timestamp = Utc::now();
        let bucket_namespace = "checkpoints";
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            attempt_timestamp,
            1234567890,
            0,
            0,
        );
        let hash = store_hash_prefix().to_string();
        let info = CheckpointInfo::new(metadata, bucket_namespace.to_string(), Some(hash.clone()));

        let meta_key = info.get_metadata_key();
        assert!(meta_key.contains(&hash));
        assert_eq!(
            meta_key,
            format!(
                "{hash}/{bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}/{METADATA_FILENAME}"
            )
        );

        let file_key = info.get_file_key("000001.sst");
        assert!(file_key.contains(&hash));
        assert_eq!(
            file_key,
            format!(
                "{hash}/{bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}/000001.sst"
            )
        );
    }

    #[test]
    fn metadata_filepath_format() {
        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            attempt_timestamp,
            1234567890,
            0,
            0,
        );

        let expected_metadata_filepath =
            format!("{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}/{METADATA_FILENAME}");
        assert_eq!(metadata.get_metadata_filepath(), expected_metadata_filepath);
    }

    #[test]
    fn generate_id_format() {
        let attempt_timestamp = Utc::now();
        let id = CheckpointMetadata::generate_id(attempt_timestamp);
        let expected_id = attempt_timestamp.format(TIMESTAMP_FORMAT).to_string();

        assert!(id.contains('T'));
        assert!(id.ends_with('Z'));
        assert!(id.len() > 15);
        assert_eq!(id, expected_id);
    }

    #[test]
    fn get_store_path_nests_topic_and_partition() {
        let metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            Utc::now(),
            1234567890,
            0,
            0,
        );

        let base_path = Path::new("/data/stores");
        let store_path = metadata.get_store_path(base_path);
        assert_eq!(
            store_path,
            PathBuf::from(format!("/data/stores/{STORE_TOPIC}/{STORE_PARTITION}"))
        );
    }

    #[test]
    fn get_store_path_replaces_slashes_in_topic() {
        let metadata = CheckpointMetadata::new(
            "org/team/events".to_string(),
            0,
            Utc::now(),
            1234567890,
            0,
            0,
        );

        let base_path = Path::new("/data/stores");
        let store_path = metadata.get_store_path(base_path);
        assert_eq!(store_path, PathBuf::from("/data/stores/org_team_events/0"));
    }
}
