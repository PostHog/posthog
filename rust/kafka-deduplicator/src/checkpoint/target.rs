use std::path::{Path, PathBuf};
use std::time::SystemTime;

use crate::kafka::types::Partition;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

// The prefix appended to all topic name path elements, local and remote
pub const CHECKPOINT_TOPIC_PREFIX: &str = "topic_";

// The prefix appended to all partition number path elements, local and remote
pub const CHECKPOINT_PARTITION_PREFIX: &str = "part_";

// The subdirectory path element containing all metadata files associated
// with a given topic and partition, local and remote. Each metadata file
//name embeds the timestamp of the associated checkpoint attempt
pub const CHECKPOINT_METADATA_SUBDIR: &str = "metadata";

// The base prefix for all checkpoint-related remote storage paths
pub const CHECKPOINT_REMOTE_PATH_NAMESPACE: &str = "checkpoints";

/// Encapsulates local/remote coordinates for a single checkpoint attempt
/// for a given source topic and partition, and convience methods for
/// constructing various local and remote paths for checkpoint import/export.
///
/// For convenience, the timestamp is optional depending on the kind of paths
/// the caller wishes to construct. Targets stored in CheckpointMetadata files
/// hydrated from JSON are expected to contain an attempt timestamp.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct CheckpointTarget {
    /// The source store's topic and partition for this checkpoint attempt
    pub partition: Partition,
    /// This checkpoint attempt's timestamp in UNIX microseconds
    pub attempt_timestamp: Option<DateTime<Utc>>,

    /// The local base directory for all local checkpoints. Not serialized for export. Usage:
    /// 1. During local checkpoint attempt creation and export (applied at checkpoint creation time)
    /// 2. During checkpoint attempt import to local temp location (applied as remote metadata is hydrated)
    ///
    /// NOTE: the final import step from temp dir to RocksDB store directory
    ///       will not match the path structure used by CheckpointTarget and
    ///       will be sourced from other store-facing modules
    #[serde(skip)]
    local_base_dir: PathBuf,
}

// Constructors and methods for CheckpointTarget
impl CheckpointTarget {
    pub fn new(
        partition: Partition,
        attempt_timestamp: Option<SystemTime>,
        local_checkpoint_base_dir: &Path,
    ) -> Self {
        let local_base_dir = local_checkpoint_base_dir.to_path_buf();
        let attempt_timestamp = attempt_timestamp.map(|ts| ts.into());

        Self {
            partition,
            attempt_timestamp,
            local_base_dir,
        }
    }

    /// Construct a CheckpointTarget from a well-formed local checkpoint path of the shape:
    /// <local_checkpoint_base_path>/topic_<topic_name>/part_<partition_number>/<0-padded_unix_micros_timestamp>
    /// Primarily a helper for the checkpoint cleaner process
    pub fn from_local_attempt_path(local_path: &Path) -> Result<Self> {
        let ts_elem: &str = local_path
            .file_name()
            .ok_or(anyhow::anyhow!(
                "Missing expected timestamp dir element in path: {local_path:?}"
            ))?
            .to_str()
            .ok_or(anyhow::anyhow!(
                "Failed to stringify timestamp dir element in path: {local_path:?}"
            ))?;
        let attempt_timestamp: DateTime<Utc> = Self::timestamp_from_dirname(ts_elem)
            .context(format!("Extracting timestamp dir from: {local_path:?}"))?;

        let local_partition_path = local_path.parent().ok_or(anyhow::anyhow!(
            "Expected parent partition elem in path: {local_path:?}"
        ))?;

        let partition_number: i32 = local_partition_path
            .file_name()
            .ok_or(anyhow::anyhow!(
                "Missing expected partition element in path: {local_path:?}"
            ))?
            .to_str()
            .ok_or(anyhow::anyhow!(
                "Failed to stringify partition element in path: {local_path:?}"
            ))?
            .strip_prefix(CHECKPOINT_PARTITION_PREFIX)
            .ok_or(anyhow::anyhow!(
                "Missing expected partition element in path: {local_path:?}"
            ))?
            .parse::<i32>()
            .map_err(|e| anyhow::anyhow!("Failed to parse partition element as i32: {e}"))?;

        let local_topic_path = local_partition_path.parent().ok_or(anyhow::anyhow!(
            "Expected parent topic elem in path: {local_path:?}"
        ))?;

        let topic_name: &str = local_topic_path
            .file_name()
            .ok_or(anyhow::anyhow!(
                "Missing expected topic element in path: {local_path:?}"
            ))?
            .to_str()
            .ok_or(anyhow::anyhow!(
                "Failed to stringify topic element in path: {local_path:?}"
            ))?
            .strip_prefix(CHECKPOINT_TOPIC_PREFIX)
            .ok_or(anyhow::anyhow!(
                "Missing expected topic element in path: {local_path:?}"
            ))?;

        let local_base_dir = local_topic_path
            .parent()
            .ok_or(anyhow::anyhow!(
                "Expected parent base dir elem in path: {local_path:?}"
            ))?
            .to_path_buf();

        Ok(Self {
            partition: Partition::new(topic_name.to_string(), partition_number),
            attempt_timestamp: Some(attempt_timestamp),
            local_base_dir,
        })
    }

    // Applied by CheckpointImporter to set the local base directory on targets hydrated
    // with remote CheckpointMetadata objects, prior to resolving local and remote import
    // paths for downloading the associated checkpoint attempt files
    pub fn with_local_base_dir(&mut self, local_base_dir: &Path) {
        self.local_base_dir = local_base_dir.to_path_buf();
    }

    /// Construct the remote base path for all checkpoint attempts and metadata files
    /// related to this topic and partition. This includes path elements representing
    /// the namespace in the remote bucket, the source topic and source partition
    pub fn remote_base_path(&self) -> String {
        format!(
            "{}/{}/{}",
            CHECKPOINT_REMOTE_PATH_NAMESPACE,
            Self::topic_path_elem(&self.partition),
            Self::partition_path_elem(&self.partition),
        )
    }

    /// Remote storage checkpoint path representing a single checkpoint attempt.
    /// Path elements include namespace, topic, partition, and 0-padded UNIX micros
    /// timestamp directory matching the corresponding metadata file timestamp.
    /// The RocksDB checkpoint files for this attempt will be stored in this directory.
    ///
    /// NOTE! This method will return an error if the attempt timestamp is not set
    pub fn remote_attempt_path(&self) -> Result<String> {
        if self.attempt_timestamp.is_none() {
            return Err(anyhow::anyhow!(
                "remote_attempt_path: attempt timestamp is required"
            ));
        }

        let ts_dirname = Self::format_timestamp_dir(self.attempt_timestamp.unwrap());
        Ok(format!("{}/{}", self.remote_base_path(), ts_dirname))
    }

    /// Construct the remote base path for all metadata files related to this topic and partition.
    /// Path elements include namespace, topic, partition, and metadata label
    pub fn remote_metadata_path(&self) -> String {
        format!("{}/{}", self.remote_base_path(), CHECKPOINT_METADATA_SUBDIR,)
    }

    /// Construct the full remote path to the metadata file associated with this checkpoint attempt.
    /// Path elements include namespace, topic, partition, and metadata label. Filename embeds the
    /// 0-padded UNIX micros timestamp of the corresponding checkpoint attempt.
    ///
    /// NOTE! This method will return an error if the attempt timestamp is not set
    pub fn remote_metadata_file(&self) -> Result<String> {
        if self.attempt_timestamp.is_none() {
            return Err(anyhow::anyhow!(
                "remote_metadata_file: attempt timestamp is required"
            ));
        }
        let filename = Self::format_metadata_filename(self.attempt_timestamp.unwrap());

        Ok(format!("{}/{}", self.remote_metadata_path(), filename))
    }

    /// This is the local base dir for all checkpoint activity associated with this topic and partition.
    /// Subdirs include:
    /// - One timestamp-based subdir per checkpoint attempt
    /// - One metadata subdir that will store all per-attempt metadata files
    ///
    /// Subdirs/files created under this base are intended for export to remote storage,
    /// and are subject to periodic automated cleanup by CheckpointManager
    pub fn local_base_path(&self) -> PathBuf {
        self.local_base_dir
            .join(Self::topic_path_elem(&self.partition))
            .join(Self::partition_path_elem(&self.partition))
    }

    /// Local path (including base dir, topic, partition, and 0-padded UNIX micros timestamp)
    /// where file resulting from this checkpoint attempt will be stored prior to export.
    ///
    /// NOTE! This method will return an error if the attempt timestamp is not set
    pub fn local_attempt_path(&self) -> Result<PathBuf> {
        if self.attempt_timestamp.is_none() {
            return Err(anyhow::anyhow!(
                "local_attempt_path: attempt timestamp is required"
            ));
        }

        Ok(self
            .local_base_path()
            .join(Self::format_timestamp_dir(self.attempt_timestamp.unwrap())))
    }

    /// Local path to the metadata files associated with this checkpoint topic and partition
    pub fn local_metadata_path(&self) -> PathBuf {
        self.local_base_path().join(CHECKPOINT_METADATA_SUBDIR)
    }

    /// Full path to the local metadata file associated with this checkpoint attempt.
    /// NOTE! This method will return an error if the attempt timestamp is not set
    pub fn local_metadata_file(&self) -> Result<PathBuf> {
        if self.attempt_timestamp.is_none() {
            return Err(anyhow::anyhow!(
                "local_metadata_file: attempt timestamp is required"
            ));
        }
        let filename = Self::format_metadata_filename(self.attempt_timestamp.unwrap());

        Ok(self.local_metadata_path().join(filename))
    }

    /// The local path as log/stat tag. Includes attempt timestamp dir if present
    pub fn local_path_tag(&self) -> String {
        if self.attempt_timestamp.is_none() {
            return self.local_base_path().to_string_lossy().to_string();
        }

        self.local_attempt_path()
            .unwrap()
            .to_string_lossy()
            .to_string()
    }
}

// Utility functions for use in CheckpointTarget methods, test suites, and external modules
impl CheckpointTarget {
    /// Utility to convert a stringified, 0-padded microsecond timestamp into a DateTime<Utc>
    /// for use as a sortable directory name or filename element; public for test convenience
    pub fn timestamp_from_dirname(dirname: &str) -> Result<DateTime<Utc>> {
        let ts_elem: i64 = dirname
            .trim_start_matches('0')
            .parse::<i64>()
            .map_err(|e| {
                anyhow::anyhow!("Failed to parse timestamp dir element {dirname} as i64: {e}")
            })?;
        let attempt_timestamp: DateTime<Utc> = DateTime::from_timestamp_micros(ts_elem).ok_or(
            anyhow::anyhow!("Failed to convert UNIX micros timestamp to DateTime<Utc>: {ts_elem}"),
        )?;

        Ok(attempt_timestamp)
    }

    /// Utility to convert a DateTime<Utc> into a stringified, 0-padded microsecond timestamp
    /// for use as a sortable directory name or filename element; public for test convenience
    pub fn format_timestamp_dir(st: DateTime<Utc>) -> String {
        format!("{:020}", st.timestamp_micros())
    }

    /// Utility to convert a DateTime<Utc> into a sortable
    /// metadata filename associated with a checkpoint attempt;
    /// public for convenience in checkpoint cleanup and tests
    pub fn format_metadata_filename(st: DateTime<Utc>) -> String {
        format!("metadata-{}.json", Self::format_timestamp_dir(st))
    }

    fn topic_path_elem(partition: &Partition) -> String {
        format!("{}{}", CHECKPOINT_TOPIC_PREFIX, partition.topic())
    }

    fn partition_path_elem(partition: &Partition) -> String {
        format!(
            "{}{}",
            CHECKPOINT_PARTITION_PREFIX,
            partition.partition_number()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_checkpoint_target() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let attempt_timestamp = SystemTime::now();
        let attempt_dt_utc: DateTime<Utc> = attempt_timestamp.into();
        let local_base_dir = Path::new("/tmp/checkpoint");
        let target = CheckpointTarget::new(partition, Some(attempt_timestamp), local_base_dir);

        assert_eq!(target.partition.topic(), "test-topic");
        assert_eq!(target.partition.partition_number(), 33);
        assert!(target.attempt_timestamp.is_some());
        assert_eq!(target.attempt_timestamp.unwrap(), attempt_dt_utc);
        assert_eq!(target.local_base_dir, Path::new("/tmp/checkpoint"));
    }

    #[test]
    fn test_checkpoint_target_from_local_attempt_path() {
        let local_path = Path::new("/tmp/checkpoint/topic_test-topic/part_33/00000123451234567890");
        let target = CheckpointTarget::from_local_attempt_path(local_path).unwrap();
        assert_eq!(target.partition.topic(), "test-topic");
        assert_eq!(target.partition.partition_number(), 33);
        assert_eq!(
            target.attempt_timestamp,
            Some(DateTime::from_timestamp_micros(123451234567890).unwrap())
        );
        assert_eq!(target.local_base_dir, Path::new("/tmp/checkpoint"));
    }

    #[test]
    fn test_checkpoint_target_with_local_base_dir() {
        let partition = Partition::new("test-topic".to_string(), 33);

        let attempt_timestamp = SystemTime::now();
        let ts_dir = CheckpointTarget::format_timestamp_dir(attempt_timestamp.into());
        let meta_file = CheckpointTarget::format_metadata_filename(attempt_timestamp.into());

        let local_base_dir = Path::new("/tmp/checkpoint");
        let mut target = CheckpointTarget::new(partition, Some(attempt_timestamp), local_base_dir);
        assert_eq!(
            target.local_base_path(),
            Path::new("/tmp/checkpoint/topic_test-topic/part_33")
        );
        assert_eq!(
            target.local_attempt_path().unwrap(),
            Path::new(&format!(
                "/tmp/checkpoint/topic_test-topic/part_33/{ts_dir}"
            ))
        );
        assert_eq!(
            target.local_metadata_path(),
            Path::new("/tmp/checkpoint/topic_test-topic/part_33/metadata")
        );
        assert_eq!(
            target.local_metadata_file().unwrap(),
            Path::new(&format!(
                "/tmp/checkpoint/topic_test-topic/part_33/metadata/{meta_file}"
            ))
        );
        assert_eq!(target.local_base_dir, Path::new("/tmp/checkpoint"));

        target.with_local_base_dir(Path::new("/tmp/checkpoint2"));
        assert_eq!(target.local_base_dir, Path::new("/tmp/checkpoint2"));
        assert_eq!(
            target.local_base_path(),
            Path::new("/tmp/checkpoint2/topic_test-topic/part_33")
        );
        assert_eq!(
            target.local_attempt_path().unwrap(),
            Path::new(&format!(
                "/tmp/checkpoint2/topic_test-topic/part_33/{ts_dir}"
            ))
        );
        assert_eq!(
            target.local_metadata_path(),
            Path::new("/tmp/checkpoint2/topic_test-topic/part_33/metadata")
        );
        assert_eq!(
            target.local_metadata_file().unwrap(),
            Path::new(&format!(
                "/tmp/checkpoint2/topic_test-topic/part_33/metadata/{meta_file}"
            ))
        );
    }

    #[test]
    fn test_checkpoint_target_remote_base_path() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let attempt_timestamp = SystemTime::now();
        let local_base_dir = Path::new("/tmp/checkpoint");

        let target =
            CheckpointTarget::new(partition.clone(), Some(attempt_timestamp), local_base_dir);
        assert_eq!(
            target.remote_base_path(),
            "checkpoints/topic_test-topic/part_33"
        );

        // this path generation does not depend on a particular attempt
        let target = CheckpointTarget::new(partition, None, local_base_dir);
        assert_eq!(
            target.remote_base_path(),
            "checkpoints/topic_test-topic/part_33"
        );
    }

    #[test]
    fn test_checkpoint_target_remote_attempt_path() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let attempt_timestamp = SystemTime::now();
        let ts_dir = CheckpointTarget::format_timestamp_dir(attempt_timestamp.into());

        let target = CheckpointTarget::new(
            partition,
            Some(attempt_timestamp),
            Path::new("/tmp/checkpoint"),
        );

        assert!(target.remote_attempt_path().is_ok());
        assert_eq!(
            &target.remote_attempt_path().unwrap(),
            &format!("checkpoints/topic_test-topic/part_33/{ts_dir}")
        );
    }

    #[test]
    fn test_checkpoint_target_remote_metadata_path() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let attempt_timestamp = SystemTime::now();
        let local_base_dir = Path::new("/tmp/checkpoint");

        let target =
            CheckpointTarget::new(partition.clone(), Some(attempt_timestamp), local_base_dir);

        assert_eq!(
            target.remote_metadata_path(),
            "checkpoints/topic_test-topic/part_33/metadata"
        );

        // this path generation does not depend on a particular attempt
        let target = CheckpointTarget::new(partition, None, local_base_dir);

        assert_eq!(
            target.remote_metadata_path(),
            "checkpoints/topic_test-topic/part_33/metadata"
        );
    }

    #[test]
    fn test_checkpoint_target_remote_metadata_file() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let attempt_timestamp = SystemTime::now();
        let meta_file = CheckpointTarget::format_metadata_filename(attempt_timestamp.into());
        let target = CheckpointTarget::new(
            partition,
            Some(attempt_timestamp),
            Path::new("/tmp/checkpoint"),
        );
        assert!(target.remote_metadata_file().is_ok());
        assert_eq!(
            &target.remote_metadata_file().unwrap(),
            &format!("checkpoints/topic_test-topic/part_33/metadata/{meta_file}")
        );
    }

    #[test]
    fn test_checkpoint_target_local_base_path() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let attempt_timestamp = SystemTime::now();
        let local_base_dir = Path::new("/tmp/checkpoint");

        let target =
            CheckpointTarget::new(partition.clone(), Some(attempt_timestamp), local_base_dir);

        assert_eq!(
            target.local_base_path(),
            Path::new("/tmp/checkpoint/topic_test-topic/part_33")
        );

        // this path generation does not depend on a particular attempt
        let target = CheckpointTarget::new(partition, None, local_base_dir);

        assert_eq!(
            target.local_base_path(),
            Path::new("/tmp/checkpoint/topic_test-topic/part_33")
        );
    }

    #[test]
    fn test_checkpoint_target_local_attempt_path() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let local_base_dir = Path::new("/tmp/checkpoint");
        let attempt_timestamp = SystemTime::now();
        let ts_dir = CheckpointTarget::format_timestamp_dir(attempt_timestamp.into());

        let target = CheckpointTarget::new(partition, Some(attempt_timestamp), local_base_dir);

        assert_eq!(
            target.local_attempt_path().unwrap(),
            Path::new(&format!(
                "/tmp/checkpoint/topic_test-topic/part_33/{ts_dir}"
            ))
        );
    }

    #[test]
    fn test_checkpoint_target_local_metadata_path() {
        let target = CheckpointTarget::new(
            Partition::new("test-topic".to_string(), 33),
            Some(SystemTime::now()),
            Path::new("/tmp/checkpoint"),
        );

        assert_eq!(
            target.local_metadata_path(),
            Path::new("/tmp/checkpoint/topic_test-topic/part_33/metadata")
        );
    }

    #[test]
    fn test_checkpoint_target_local_metadata_file() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let attempt_timestamp = SystemTime::now();
        let meta_file = CheckpointTarget::format_metadata_filename(attempt_timestamp.into());
        let local_base_dir = Path::new("/tmp/checkpoint");

        let target = CheckpointTarget::new(partition, Some(attempt_timestamp), local_base_dir);

        assert_eq!(
            target.local_metadata_file().unwrap(),
            Path::new(&format!(
                "/tmp/checkpoint/topic_test-topic/part_33/metadata/{meta_file}"
            ))
        );
    }

    #[test]
    fn test_checkpoint_target_local_path_tag() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let local_base_dir = Path::new("/tmp/checkpoint");
        let target = CheckpointTarget::new(partition, None, local_base_dir);
        assert_eq!(
            &target.local_path_tag(),
            "/tmp/checkpoint/topic_test-topic/part_33"
        );
    }

    #[test]
    fn test_checkpoint_target_local_path_tag_with_attempt_timestamp() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let attempt_timestamp = SystemTime::now();
        let ts_dir = CheckpointTarget::format_timestamp_dir(attempt_timestamp.into());
        let target = CheckpointTarget::new(
            partition,
            Some(attempt_timestamp),
            Path::new("/tmp/checkpoint"),
        );
        assert_eq!(
            target.local_path_tag(),
            format!("/tmp/checkpoint/topic_test-topic/part_33/{ts_dir}")
        );
    }

    #[test]
    fn test_checkpoint_target_timestamp_from_dirname() {
        let dirname = "00000123451234567890";
        let timestamp = CheckpointTarget::timestamp_from_dirname(dirname).unwrap();
        assert_eq!(
            timestamp,
            DateTime::from_timestamp_micros(123451234567890).unwrap()
        );
    }

    #[test]
    fn test_checkpoint_target_format_timestamp_dir() {
        let timestamp = SystemTime::now();
        let timestamp_dt_utc: DateTime<Utc> = timestamp.into();
        let ts_dir = CheckpointTarget::format_timestamp_dir(timestamp.into());
        assert_eq!(
            ts_dir,
            format!("{:020}", timestamp_dt_utc.timestamp_micros())
        );
    }

    #[test]
    fn test_checkpoint_target_format_metadata_filename() {
        let timestamp = SystemTime::now();
        let timestamp_dt_utc: DateTime<Utc> = timestamp.into();
        let meta_file = CheckpointTarget::format_metadata_filename(timestamp.into());
        assert_eq!(
            meta_file,
            format!(
                "metadata-{}.json",
                &format!("{:020}", timestamp_dt_utc.timestamp_micros())
            )
        );
    }

    #[test]
    fn test_checkpoint_target_local_attempt_path_no_timestamp_fails() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let target = CheckpointTarget::new(partition, None, Path::new("/tmp/checkpoint"));
        assert!(target.local_attempt_path().is_err());
    }

    #[test]
    fn test_checkpoint_target_local_metadata_file_no_timestamp_fails() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let target = CheckpointTarget::new(partition, None, Path::new("/tmp/checkpoint"));
        assert!(target.local_metadata_file().is_err());
    }

    #[test]
    fn test_checkpoint_target_remote_attempt_path_no_timestamp_fails() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let target = CheckpointTarget::new(partition, None, Path::new("/tmp/checkpoint"));
        assert!(target.remote_attempt_path().is_err());
    }

    #[test]
    fn test_checkpoint_target_remote_metadata_file_no_timestamp_fails() {
        let partition = Partition::new("test-topic".to_string(), 33);
        let target = CheckpointTarget::new(partition, None, Path::new("/tmp/checkpoint"));
        assert!(target.remote_metadata_file().is_err());
    }
}
