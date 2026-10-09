//! Checkpoint metadata: the per-attempt file registry, plus S3-key construction.

use std::path::Path;

use chrono::{DateTime, NaiveDateTime, Utc};
use serde::{Deserialize, Serialize};
use tracing::debug;

use super::lineage::{CheckpointLineage, PodOrdinal};
use crate::store::STORE_SCHEMA_VERSION;

/// Filename of the checkpoint metadata JSON file, in a remote attempt directory and in a local one.
pub const METADATA_FILENAME: &str = "metadata.json";
/// Checkpoint ID format: the S3 attempt directory name, derived from `attempt_timestamp`. It
/// carries milliseconds, so two checkpoints in one second get two attempt paths.
pub const TIMESTAMP_FORMAT: &str = "%Y-%m-%dT%H-%M-%S-%3fZ";
/// Current metadata shape. Decode refuses any other, so a restore can tell a checkpoint written by
/// an older build from a corrupt one.
pub const METADATA_VERSION: u32 = 2;

#[derive(Debug, thiserror::Error)]
pub enum MetadataError {
    /// Metadata written before `version` existed decodes as format 0.
    #[error("checkpoint metadata format {found}; this build reads {METADATA_VERSION}")]
    UnsupportedFormat { found: u32 },
    #[error(transparent)]
    Decode(#[from] serde_json::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

/// Metadata about a checkpoint: what a restore must download, and what the next incremental upload
/// may reuse.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CheckpointMetadata {
    /// Always [`METADATA_VERSION`] once decoded.
    pub version: u32,
    /// Checkpoint ID, e.g. `2025-10-14T16-00-05-123Z`.
    pub id: String,
    /// The lineage this checkpoint belongs to.
    pub ordinal: PodOrdinal,
    pub attempt_timestamp: DateTime<Utc>,
    /// The [`STORE_SCHEMA_VERSION`] the checkpointed DB was written under. A restore checks it
    /// before downloading anything.
    pub store_schema: u32,
    /// Every remote file needed to reconstitute the store, across this and earlier attempts.
    pub files: Vec<CheckpointFile>,
}

impl CheckpointMetadata {
    pub fn new(ordinal: PodOrdinal, attempt_timestamp: DateTime<Utc>) -> Self {
        Self {
            version: METADATA_VERSION,
            id: Self::generate_id(attempt_timestamp),
            ordinal,
            attempt_timestamp,
            store_schema: STORE_SCHEMA_VERSION,
            files: Vec::new(),
        }
    }

    pub fn generate_id(attempt_timestamp: DateTime<Utc>) -> String {
        attempt_timestamp.format(TIMESTAMP_FORMAT).to_string()
    }

    /// The attempt instant a checkpoint id names, or `None` for a name that is not an id.
    pub fn parse_id(id: &str) -> Option<DateTime<Utc>> {
        NaiveDateTime::parse_from_str(id, TIMESTAMP_FORMAT)
            .ok()
            .map(|naive| naive.and_utc())
    }

    pub fn from_json_bytes(json: &[u8]) -> Result<Self, MetadataError> {
        #[derive(Deserialize)]
        struct FormatProbe {
            #[serde(default)]
            version: u32,
        }
        let FormatProbe { version } = serde_json::from_slice(json)?;
        if version != METADATA_VERSION {
            return Err(MetadataError::UnsupportedFormat { found: version });
        }
        Ok(serde_json::from_slice(json)?)
    }

    pub fn load(path: &Path) -> Result<Self, MetadataError> {
        Self::from_json_bytes(&std::fs::read(path)?)
    }

    /// Write atomically (tmp file + rename) so a reader never sees a torn file.
    pub fn save(&self, path: &Path) -> Result<(), MetadataError> {
        let tmp_path = path.with_extension("json.tmp");
        if let Err(e) = std::fs::write(&tmp_path, self.to_json()?) {
            drop(std::fs::remove_file(&tmp_path));
            return Err(e.into());
        }
        std::fs::rename(&tmp_path, path)?;
        debug!(path = %path.display(), "saved checkpoint metadata");
        Ok(())
    }

    pub fn track_file(&mut self, remote_filepath: String, checksum: String) {
        self.files
            .push(CheckpointFile::new(remote_filepath, checksum));
    }

    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string_pretty(self)
    }
}

/// A checkpoint's metadata and where its attempt lives in S3.
#[derive(Debug, Clone)]
pub struct CheckpointInfo {
    pub metadata: CheckpointMetadata,
    /// App-level S3 bucket namespace for all checkpoint attempts.
    pub s3_key_prefix: String,
}

impl CheckpointInfo {
    pub fn new(metadata: CheckpointMetadata, s3_key_prefix: String) -> Self {
        Self {
            metadata,
            s3_key_prefix,
        }
    }

    /// `<lineage remote dir><checkpoint id>`.
    pub fn get_remote_attempt_path(&self) -> String {
        format!(
            "{}{}",
            CheckpointLineage::new(self.metadata.ordinal).remote_dir(&self.s3_key_prefix),
            self.metadata.id,
        )
    }

    pub fn get_metadata_key(&self) -> String {
        self.get_file_key(METADATA_FILENAME)
    }

    /// Remote key for a file this attempt uploads. Files reused from earlier attempts keep the key
    /// they were uploaded under.
    pub fn get_file_key(&self, filename: &str) -> String {
        format!("{}/{filename}", self.get_remote_attempt_path())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointFile {
    /// Fully-qualified remote path from the original upload:
    /// `<hash>/<namespace>/cohort_stream_state/<ordinal>/<id>/<filename>`. The importer GETs this
    /// path.
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
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn metadata(ordinal: PodOrdinal) -> CheckpointMetadata {
        let attempt = Utc.with_ymd_and_hms(2026, 10, 9, 16, 0, 5).unwrap()
            + chrono::Duration::milliseconds(123);
        CheckpointMetadata::new(ordinal, attempt)
    }

    #[test]
    fn metadata_round_trips_through_a_file() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join(METADATA_FILENAME);
        let mut original = metadata(PodOrdinal::STANDALONE);
        original.track_file("a/000001.sst".to_string(), String::new());

        original.save(&path).unwrap();
        assert_eq!(CheckpointMetadata::load(&path).unwrap(), original);
    }

    #[test]
    fn metadata_from_another_format_is_refused_as_a_format_not_as_corruption() {
        let older = serde_json::json!({
            "id": "2026-10-09T16-00-05Z",
            "topic": "cohort_stream_state",
            "partition": 0,
            "attempt_timestamp": "2026-10-09T16:00:05Z",
            "sequence": 1,
            "consumer_offset": 0,
            "producer_offset": 0,
            "store_schema": STORE_SCHEMA_VERSION,
            "files": [],
        });
        assert!(matches!(
            CheckpointMetadata::from_json_bytes(older.to_string().as_bytes()),
            Err(MetadataError::UnsupportedFormat { found: 0 }),
        ));
        assert!(matches!(
            CheckpointMetadata::from_json_bytes(b"{\"version\": 2, \"id\": 5}"),
            Err(MetadataError::Decode(_)),
        ));
    }

    #[test]
    fn ids_carry_milliseconds_and_parse_back_to_the_attempt_instant() {
        let metadata = metadata(PodOrdinal::STANDALONE);
        assert_eq!(metadata.id, "2026-10-09T16-00-05-123Z");
        assert_eq!(
            CheckpointMetadata::parse_id(&metadata.id),
            Some(metadata.attempt_timestamp),
        );
        assert_eq!(CheckpointMetadata::parse_id("2026-10-09T16-00-05Z"), None);
        assert_eq!(CheckpointMetadata::parse_id("not-an-id"), None);
    }

    #[test]
    fn remote_keys_live_under_the_lineage_of_the_metadata_ordinal() {
        let zero = CheckpointInfo::new(metadata(PodOrdinal::STANDALONE), "checkpoints".to_string());
        assert_eq!(
            zero.get_metadata_key(),
            "819f7b67/checkpoints/cohort_stream_state/0/2026-10-09T16-00-05-123Z/metadata.json",
        );
        assert_eq!(
            zero.get_file_key("000001.sst"),
            "819f7b67/checkpoints/cohort_stream_state/0/2026-10-09T16-00-05-123Z/000001.sst",
        );

        let three = CheckpointInfo::new(
            metadata(PodOrdinal::from_pod_name("p-3").unwrap()),
            "checkpoints".to_string(),
        );
        assert!(three
            .get_file_key("000001.sst")
            .ends_with("/checkpoints/cohort_stream_state/3/2026-10-09T16-00-05-123Z/000001.sst"));
        assert_ne!(three.get_file_key("x")[..8], zero.get_file_key("x")[..8]);
    }
}
