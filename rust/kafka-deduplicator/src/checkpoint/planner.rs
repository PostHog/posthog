use std::collections::HashMap;
use std::path::{Path, PathBuf};

use super::{CheckpointFile, CheckpointInfo, CheckpointMetadata};
use crate::kafka::types::Partition;
use crate::metrics_const::CHECKPOINT_PLAN_FILE_TRACKED_COUNTER;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use sha2::{Digest, Sha256};
use tracing::{debug, info};

/// Result of checkpoint planning
#[derive(Debug)]
pub struct CheckpointPlan {
    /// The new checkpoint metadata with files field populated
    pub info: CheckpointInfo,
    /// Files that need to be uploaded to S3 (filename, local_full_path)
    pub files_to_upload: Vec<LocalCheckpointFile>,
}

/// Create a checkpoint plan with new metadata and list of files to upload
#[allow(clippy::too_many_arguments)]
pub fn plan_checkpoint(
    local_checkpoint_attempt_dir: &Path,
    remote_bucket_namespace: String,
    partition: Partition,
    attempt_timestamp: DateTime<Utc>,
    sequence: u64,
    consumer_offset: i64,
    producer_offset: i64,
    previous_metadata: Option<&CheckpointMetadata>,
) -> Result<CheckpointPlan> {
    let metadata = CheckpointMetadata::new(
        partition.topic().to_string(),
        partition.partition_number(),
        attempt_timestamp,
        sequence,
        consumer_offset,
        producer_offset,
    );
    let mut info = CheckpointInfo::new(metadata, remote_bucket_namespace);
    let mut files_to_upload: Vec<LocalCheckpointFile> = Vec::new();

    // Collect all files in local checkpoint directory
    let local_files = collect_local_files(local_checkpoint_attempt_dir)?;
    info!(
        "Found {} files in local checkpoint directory",
        local_files.len()
    );

    // If no previous metadata, upload everything
    let Some(prev_meta) = previous_metadata else {
        info!("No previous checkpoint metadata - tracking all files for upload");
        for candidate in local_files {
            let remote_filepath = info.get_file_key(&candidate.filename);
            info.metadata
                .track_file(remote_filepath, candidate.checksum.clone());
            files_to_upload.push(candidate);
        }
        return Ok(CheckpointPlan {
            info,
            files_to_upload,
        });
    };

    // Build maps of filename -> file_path by type from previous checkpoint
    let mut prev_file_map: HashMap<String, CheckpointFile> = HashMap::new();
    for prev_cp_file in &prev_meta.files {
        let filename = prev_cp_file
            .remote_filepath
            .rsplit('/')
            .next()
            .unwrap_or(&prev_cp_file.remote_filepath)
            .to_string();
        prev_file_map.insert(filename, prev_cp_file.clone());
    }

    info!(
        "Built file map with {} files from previous checkpoint {}",
        prev_file_map.len(),
        prev_meta.id
    );

    // For each local file, check if it exists in previous metadata fileset
    // IMPORTANT: each type must be handled differently to maintain
    // a useable backup:
    // - .sst files: upload all new files, and skip uploading old ones (retain original paths)
    // - .log (WAL) files: upload only new files. drop old if missing from new checkpoint.
    //                     if same-named, keep newer or disambiguate w/checksum
    // - MANIFEST-* files: upload new files. drop old if missing from new checkpoint.
    //                     if same-named, keep newer or disambiguate w/checksum
    // - CURRENT    file:  upload the new file, drop the old one
    // - OPTIONS-*  files: upload new files. drop old if missing from new checkpoint.
    //                     if same-named, keep newer or disambiguate w/checksum
    for candidate in local_files {
        let filename = &candidate.filename;
        if let Some(prev_file) = prev_file_map.get(filename) {
            if retain_or_replace_duplicate(&candidate, prev_file) {
                debug!("Duplicate file {} - new file will be uploaded", filename);
                metrics::counter!(CHECKPOINT_PLAN_FILE_TRACKED_COUNTER, "file" => "replaced")
                    .increment(1);
                let remote_filepath = info.get_file_key(filename);
                info.metadata
                    .track_file(remote_filepath, candidate.checksum.clone());
                files_to_upload.push(candidate);
            } else {
                debug!(
                    "Duplicate file {} - retaining original, skipping upload",
                    filename
                );
                metrics::counter!(CHECKPOINT_PLAN_FILE_TRACKED_COUNTER, "file" => "retained")
                    .increment(1);
                info.metadata.track_file(
                    prev_file.remote_filepath.clone(),
                    prev_file.checksum.clone(),
                );
            }
        } else {
            // File is new - needs to be uploaded
            debug!("New file {} will be uploaded", filename);
            metrics::counter!(CHECKPOINT_PLAN_FILE_TRACKED_COUNTER, "file" => "added").increment(1);
            let remote_filepath = info.get_file_key(filename);
            info.metadata
                .track_file(remote_filepath, candidate.checksum.clone());
            files_to_upload.push(candidate);
        }
    }

    info!(
        "Checkpoint plan: {} new files, {} reused files",
        files_to_upload.len(),
        info.metadata.files.len() - files_to_upload.len(),
    );

    Ok(CheckpointPlan {
        info,
        files_to_upload,
    })
}

// if true, keep the new LocalCheckpointFile and add it to the metadata
// if false, drop the new file and add the old CandidateFile to the metadata
fn retain_or_replace_duplicate(
    candidate: &LocalCheckpointFile,
    prev_file: &CheckpointFile,
) -> bool {
    match &candidate.filename {
        // simple cases - CURRENT should always be latest; SST files should be retained
        f if f == "CURRENT" => true,
        f if f.ends_with(".sst") => false,

        // for other files that can be appended or mutated
        // w/o name change, use checksum to decide
        f if f.starts_with("OPTIONS-") || f.starts_with("MANIFEST-") || f.ends_with(".log") => {
            if candidate.checksum == prev_file.checksum {
                // retain old file, no change in content
                false
            } else {
                // same-named file content changed, upload new one
                true
            }
        }
        _ => true, // bias to keeping latest files for safety
    }
}

/// Collect all files in local checkpoint attempt directory of form:
/// <local_base_path>/<topic_name>/<partition_number>/<checkpoint_id>
fn collect_local_files(base_attempt_path: &Path) -> Result<Vec<LocalCheckpointFile>> {
    let mut files = Vec::new();
    let mut stack = vec![base_attempt_path.to_path_buf()];

    while let Some(current_path) = stack.pop() {
        let entries = std::fs::read_dir(&current_path)
            .with_context(|| format!("Failed to read directory: {current_path:?}"))?;

        for entry in entries {
            let entry = entry.context(format!(
                "Failed to read directory entry from {base_attempt_path:?}"
            ))?;
            let path = entry.path();

            if path.is_dir() {
                stack.push(path);
            } else {
                let candidate = build_candidate_file(&path).context("In build_candidate_file")?;
                files.push(candidate);
            }
        }
    }

    Ok(files)
}

fn build_candidate_file(file_path: &Path) -> Result<LocalCheckpointFile> {
    let local_file_path = file_path.to_path_buf();
    let filename = file_path
        .file_name()
        .context(format!("Failed to get filename for: {file_path:?}"))?
        .to_string_lossy()
        .to_string();

    let checksum = if filename.ends_with(".sst") {
        String::default()
    } else {
        load_and_hash_file(file_path).context("In load_and_hash_file")?
    };

    Ok(LocalCheckpointFile::new(
        filename,
        checksum,
        local_file_path,
    ))
}

fn load_and_hash_file(file_path: &Path) -> Result<String> {
    let mut file = std::fs::File::open(file_path)
        .with_context(|| format!("Failed to open file for hashing: {file_path:?}"))?;

    let mut hasher = Sha256::new();
    std::io::copy(&mut file, &mut hasher)
        .with_context(|| format!("Failed to read and hash file: {file_path:?}"))?;
    let hash = hasher.finalize();
    let checksum = format!("{hash:x}");

    Ok(checksum.to_string())
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalCheckpointFile {
    pub filename: String,
    pub checksum: String,
    pub local_path: PathBuf,
}

impl LocalCheckpointFile {
    pub fn new(filename: String, checksum: String, local_path: PathBuf) -> Self {
        Self {
            filename,
            checksum,
            local_path,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Duration;
    use tempfile::TempDir;

    #[test]
    fn test_plan_checkpoint_no_previous() {
        let temp_dir = TempDir::new().unwrap();
        let remote_bucket_namespace = "checkpoints";
        let topic = "test-topic";
        let partition_number = 0;
        let partition = Partition::new(topic.to_string(), partition_number);
        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let sequence = 1000;
        let consumer_offset = 0;
        let producer_offset = 100;
        let previous_metadata = None;
        let local_checkpoint_attempt_dir = temp_dir
            .path()
            .join(partition.topic())
            .join(partition.partition_number().to_string())
            .join(&checkpoint_id);

        // Create some test files
        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file1.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file2.sst"), b"data2").unwrap();

        let plan = plan_checkpoint(
            &local_checkpoint_attempt_dir,
            remote_bucket_namespace.to_string(),
            partition,
            attempt_timestamp,
            sequence,
            consumer_offset,
            producer_offset,
            previous_metadata,
        )
        .unwrap();

        let expected_sst1 =
            build_candidate_file(&local_checkpoint_attempt_dir.join("file1.sst")).unwrap();
        let expected_sst2 =
            build_candidate_file(&local_checkpoint_attempt_dir.join("file2.sst")).unwrap();

        // With no previous metadata, all files should be uploaded
        assert_eq!(plan.files_to_upload.len(), 2);
        let got_sst1 = plan
            .files_to_upload
            .iter()
            .find(|f| f.filename == "file1.sst")
            .unwrap();
        let got_sst2 = plan
            .files_to_upload
            .iter()
            .find(|f| f.filename == "file2.sst")
            .unwrap();
        assert_eq!(got_sst1, &expected_sst1);
        assert_eq!(got_sst2, &expected_sst2);

        // With no previous metadata, all files should be tracked in metadata
        assert_eq!(plan.info.metadata.files.len(), 2);
        let expected_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{checkpoint_id}");
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .all(|f| f.remote_filepath.starts_with(&expected_remote_path)));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|f| f.remote_filepath.ends_with("file1.sst")));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|f| f.remote_filepath.ends_with("file2.sst")));
    }

    #[test]
    fn test_plan_checkpoint_with_previous() {
        let temp_dir = TempDir::new().unwrap();
        let remote_bucket_namespace = "checkpoints";
        let topic = "test-topic";
        let partition_number = 0;
        let partition = Partition::new(topic.to_string(), partition_number);
        let prev_attempt_timestamp = Utc::now() - Duration::hours(1);
        let prev_checkpoint_id = CheckpointMetadata::generate_id(prev_attempt_timestamp);
        let prev_sequence = 1000;
        let prev_consumer_offset = 0;
        let prev_producer_offset = 100;

        // Create previous metadata with file1 and file2
        let mut prev_metadata = CheckpointMetadata::new(
            partition.topic().to_string(),
            partition.partition_number(),
            prev_attempt_timestamp,
            prev_sequence,
            prev_consumer_offset,
            prev_producer_offset,
        );

        let prev_local_attempt_dir = temp_dir
            .path()
            .join(partition.topic())
            .join(partition.partition_number().to_string())
            .join(&prev_checkpoint_id);

        std::fs::create_dir_all(&prev_local_attempt_dir).unwrap();
        std::fs::write(prev_local_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00002.sst"), b"data2").unwrap();

        let expected_prev_sst1 =
            build_candidate_file(&prev_local_attempt_dir.join("00001.sst")).unwrap();
        let expected_prev_sst2 =
            build_candidate_file(&prev_local_attempt_dir.join("00002.sst")).unwrap();

        let prev_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{prev_checkpoint_id}");

        let prev_sst1_remote_path = format!("{prev_remote_path}/00001.sst");
        prev_metadata.track_file(
            prev_sst1_remote_path.clone(),
            expected_prev_sst1.checksum.clone(),
        );

        let prev_sst2_remote_path = format!("{prev_remote_path}/00002.sst");
        prev_metadata.track_file(
            prev_sst2_remote_path.clone(),
            expected_prev_sst2.checksum.clone(),
        );

        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let sequence = 1001;
        let consumer_offset = 100;
        let producer_offset = 200;
        let local_checkpoint_attempt_dir = temp_dir
            .path()
            .join(topic)
            .join(partition.to_string())
            .join(&checkpoint_id);

        // Create test files we'd see in current checkpoint attempt
        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00002.sst"), b"data2").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00003.sst"), b"data3").unwrap();
        let expected_sst3 =
            build_candidate_file(&local_checkpoint_attempt_dir.join("00003.sst")).unwrap();

        let plan = plan_checkpoint(
            &local_checkpoint_attempt_dir,
            remote_bucket_namespace.to_string(),
            partition,
            attempt_timestamp,
            sequence,
            consumer_offset,
            producer_offset,
            Some(&prev_metadata),
        )
        .unwrap();

        // Only sst3 should be uploaded; sst1 and sst2 should be reused
        assert_eq!(plan.files_to_upload.len(), 1);
        let got_sst3 = plan
            .files_to_upload
            .iter()
            .find(|f| f.filename == "00003.sst")
            .unwrap();
        assert_eq!(got_sst3, &expected_sst3);

        assert_eq!(plan.info.metadata.files.len(), 3);
        let sst1_file_meta = plan
            .info
            .metadata
            .files
            .iter()
            .find(|f| f.remote_filepath == prev_sst1_remote_path)
            .unwrap();
        let sst2_file_meta = plan
            .info
            .metadata
            .files
            .iter()
            .find(|f| f.remote_filepath == prev_sst2_remote_path)
            .unwrap();

        // checksums should match across checkpoint file meta and local file refs for upload
        assert_eq!(&sst1_file_meta.checksum, &expected_prev_sst1.checksum);
        assert_eq!(&sst2_file_meta.checksum, &expected_prev_sst2.checksum);

        // Check that file3 is in metadata as a reference
        let current_attempt_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{checkpoint_id}");

        let sst1_remote_path = format!("{prev_remote_path}/00001.sst");
        let sst2_remote_path = format!("{prev_remote_path}/00002.sst");
        let sst3_remote_path = format!("{current_attempt_remote_path}/00003.sst");

        let sst1_file_meta = plan
            .info
            .metadata
            .files
            .iter()
            .find(|f| f.remote_filepath == sst1_remote_path)
            .unwrap();

        let sst2_file_meta = plan
            .info
            .metadata
            .files
            .iter()
            .find(|f| f.remote_filepath == sst2_remote_path)
            .unwrap();

        let sst3_file_meta = plan
            .info
            .metadata
            .files
            .iter()
            .find(|f| f.remote_filepath == sst3_remote_path)
            .unwrap();

        // checksums should match across checkpoint file meta and local file refs for upload
        assert_eq!(&sst1_file_meta.checksum, &expected_prev_sst1.checksum);
        assert_eq!(&sst2_file_meta.checksum, &expected_prev_sst2.checksum);
        assert_eq!(sst3_file_meta.checksum, expected_sst3.checksum);
    }

    #[test]
    fn test_plan_checkpoint_with_only_prev_files() {
        let temp_dir = TempDir::new().unwrap();
        let remote_bucket_namespace = "checkpoints";
        let topic = "test-topic";
        let partition_number = 0;
        let partition = Partition::new(topic.to_string(), partition_number);
        let prev_attempt_timestamp = Utc::now() - Duration::hours(1);
        let prev_checkpoint_id = CheckpointMetadata::generate_id(prev_attempt_timestamp);
        let prev_sequence = 1000;
        let prev_consumer_offset = 0;
        let prev_producer_offset = 100;

        // Create previous metadata with file1 and file2
        let mut prev_metadata = CheckpointMetadata::new(
            partition.topic().to_string(),
            partition.partition_number(),
            prev_attempt_timestamp,
            prev_sequence,
            prev_consumer_offset,
            prev_producer_offset,
        );

        let prev_local_attempt_dir = temp_dir
            .path()
            .join(topic)
            .join(partition.to_string())
            .join(&prev_checkpoint_id);

        // Create test files that won't be changed in the next checkpoint attempt
        std::fs::create_dir_all(&prev_local_attempt_dir).unwrap();
        std::fs::write(prev_local_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00002.sst"), b"data2").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00003.sst"), b"data3").unwrap();

        let expected_prev_sst1 =
            build_candidate_file(&prev_local_attempt_dir.join("00001.sst")).unwrap();
        let expected_prev_sst2 =
            build_candidate_file(&prev_local_attempt_dir.join("00002.sst")).unwrap();
        let expected_prev_sst3 =
            build_candidate_file(&prev_local_attempt_dir.join("00003.sst")).unwrap();

        let prev_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{prev_checkpoint_id}",);
        let prev_sst1_remote_path = format!("{prev_remote_path}/00001.sst");
        let prev_sst2_remote_path = format!("{prev_remote_path}/00002.sst");
        let prev_sst3_remote_path = format!("{prev_remote_path}/00003.sst");

        prev_metadata.track_file(
            prev_sst1_remote_path.clone(),
            expected_prev_sst1.checksum.clone(),
        );
        prev_metadata.track_file(
            prev_sst2_remote_path.clone(),
            expected_prev_sst2.checksum.clone(),
        );
        prev_metadata.track_file(
            prev_sst3_remote_path.clone(),
            expected_prev_sst3.checksum.clone(),
        );

        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let sequence = 1001;
        let consumer_offset = 100;
        let producer_offset = 200;
        let local_checkpoint_attempt_dir = temp_dir
            .path()
            .join(topic)
            .join(partition_number.to_string())
            .join(&checkpoint_id);

        // Create test files from what would have been current
        // checkpoint attempt, identical to original attempt
        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00002.sst"), b"data2").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00003.sst"), b"data3").unwrap();

        let plan = plan_checkpoint(
            &local_checkpoint_attempt_dir,
            remote_bucket_namespace.to_string(),
            partition,
            attempt_timestamp,
            sequence,
            consumer_offset,
            producer_offset,
            Some(&prev_metadata),
        )
        .unwrap();

        // file1, file2 and file3 should be reused, so no uploads in current checkpoint attempt
        assert!(plan.files_to_upload.is_empty());
        assert_eq!(plan.info.metadata.files.len(), 3);

        // Check that previously uploaded file1, file2 and file3 are in
        // metadata with remote paths referencing previous checkpoint
        let sst1_file_meta = plan
            .info
            .metadata
            .files
            .iter()
            .find(|f| f.remote_filepath == prev_sst1_remote_path)
            .unwrap();
        let sst2_file_meta = plan
            .info
            .metadata
            .files
            .iter()
            .find(|f| f.remote_filepath == prev_sst2_remote_path)
            .unwrap();
        let sst3_file_meta = plan
            .info
            .metadata
            .files
            .iter()
            .find(|f| f.remote_filepath == prev_sst3_remote_path)
            .unwrap();

        // checksums & sizes should match across tracked file metadata
        // and the original checkpoint attempt's local files
        assert_eq!(&sst1_file_meta.checksum, &expected_prev_sst1.checksum);
        assert_eq!(&sst2_file_meta.checksum, &expected_prev_sst2.checksum);
        assert_eq!(&sst3_file_meta.checksum, &expected_prev_sst3.checksum);
    }

    #[test]
    fn test_plan_checkpoint_with_previous_and_non_sst_types() {
        let temp_dir = TempDir::new().unwrap();
        let remote_bucket_namespace = "checkpoints";
        let topic = "test-topic";
        let partition_number = 0;
        let partition = Partition::new(topic.to_string(), partition_number);
        let prev_attempt_timestamp = Utc::now() - Duration::hours(1);
        let prev_checkpoint_id = CheckpointMetadata::generate_id(prev_attempt_timestamp);
        let prev_sequence = 1000;
        let prev_consumer_offset = 0;
        let prev_producer_offset = 100;

        // Create previous metadata with file1 and file2
        let mut prev_metadata = CheckpointMetadata::new(
            partition.topic().to_string(),
            partition.partition_number(),
            prev_attempt_timestamp,
            prev_sequence,
            prev_consumer_offset,
            prev_producer_offset,
        );

        let prev_local_attempt_dir = temp_dir
            .path()
            .join(topic)
            .join(partition.to_string())
            .join(&prev_checkpoint_id);

        // Create test files that won't be changed in the next checkpoint attempt
        std::fs::create_dir_all(&prev_local_attempt_dir).unwrap();
        std::fs::write(prev_local_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00002.sst"), b"data2").unwrap();
        std::fs::write(prev_local_attempt_dir.join("MANIFEST-000000"), b"data3").unwrap();
        std::fs::write(prev_local_attempt_dir.join("OPTIONS-000000"), b"data4").unwrap();
        std::fs::write(prev_local_attempt_dir.join("CURRENT"), b"data5").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00001.log"), b"data6").unwrap();

        let expected_prev_sst1 =
            build_candidate_file(&prev_local_attempt_dir.join("00001.sst")).unwrap();
        let expected_prev_sst2 =
            build_candidate_file(&prev_local_attempt_dir.join("00002.sst")).unwrap();
        let expected_prev_manifest =
            build_candidate_file(&prev_local_attempt_dir.join("MANIFEST-000000")).unwrap();
        let expected_prev_options =
            build_candidate_file(&prev_local_attempt_dir.join("OPTIONS-000000")).unwrap();
        let expected_prev_current =
            build_candidate_file(&prev_local_attempt_dir.join("CURRENT")).unwrap();
        let expected_prev_log =
            build_candidate_file(&prev_local_attempt_dir.join("00001.log")).unwrap();

        let prev_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{prev_checkpoint_id}",);
        let prev_sst1_remote_path = format!("{prev_remote_path}/00001.sst");
        let prev_sst2_remote_path = format!("{prev_remote_path}/00002.sst");
        let prev_manifest_remote_path = format!("{prev_remote_path}/MANIFEST-000000");
        let prev_options_remote_path = format!("{prev_remote_path}/OPTIONS-000000");
        let prev_current_remote_path = format!("{prev_remote_path}/CURRENT");
        let prev_log_remote_path = format!("{prev_remote_path}/00001.log");

        prev_metadata.track_file(
            prev_sst1_remote_path.clone(),
            expected_prev_sst1.checksum.clone(),
        );
        prev_metadata.track_file(
            prev_sst2_remote_path.clone(),
            expected_prev_sst2.checksum.clone(),
        );
        prev_metadata.track_file(
            prev_manifest_remote_path.clone(),
            expected_prev_manifest.checksum.clone(),
        );
        prev_metadata.track_file(
            prev_options_remote_path.clone(),
            expected_prev_options.checksum.clone(),
        );
        prev_metadata.track_file(
            prev_current_remote_path.clone(),
            expected_prev_current.checksum.clone(),
        );
        prev_metadata.track_file(
            prev_log_remote_path.clone(),
            expected_prev_log.checksum.clone(),
        );

        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let sequence = 1001;
        let consumer_offset = 100;
        let producer_offset = 200;
        let local_checkpoint_attempt_dir = temp_dir
            .path()
            .join(topic)
            .join(partition.to_string())
            .join(&checkpoint_id);

        // Create test files
        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00001.sst"), b"data1").unwrap(); // no change, always retain
        std::fs::write(local_checkpoint_attempt_dir.join("00002.sst"), b"data2").unwrap(); // no change, always retain
        std::fs::write(local_checkpoint_attempt_dir.join("00003.sst"), b"data7").unwrap(); // new file, should upload
        std::fs::write(
            local_checkpoint_attempt_dir.join("MANIFEST-000000"),
            b"data3",
        )
        .unwrap(); // unchanged, should retain
        std::fs::write(
            local_checkpoint_attempt_dir.join("OPTIONS-000000"),
            b"data4",
        )
        .unwrap(); // unchanged, should retain
        std::fs::write(local_checkpoint_attempt_dir.join("CURRENT"), b"data5").unwrap(); // unchanged, but always uploaded
        std::fs::write(
            local_checkpoint_attempt_dir.join("00001.log"),
            b"data6_APPENDED",
        )
        .unwrap(); // mutated, should upload

        let plan = plan_checkpoint(
            &local_checkpoint_attempt_dir,
            remote_bucket_namespace.to_string(),
            partition,
            attempt_timestamp,
            sequence,
            consumer_offset,
            producer_offset,
            Some(&prev_metadata),
        )
        .unwrap();

        // 00003.sst, 00001.log, and CURRENT should be uploaded
        assert_eq!(plan.files_to_upload.len(), 3);
        assert!(plan
            .files_to_upload
            .iter()
            .any(|f| f.filename == "00003.sst"));
        assert!(plan
            .files_to_upload
            .iter()
            .any(|f| f.filename == "00001.log"));
        assert!(plan.files_to_upload.iter().any(|f| f.filename == "CURRENT"));

        // total of 7 tracked files now: 4 from previous checkpoint, 3 from current
        assert_eq!(plan.info.metadata.files.len(), 7);

        // validate the right checkpoint metadata was retained from previous vs. current checkpoint attempts
        let current_attempt_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{checkpoint_id}");
        let sst1_remote_path = format!("{prev_remote_path}/00001.sst");
        let sst2_remote_path = format!("{prev_remote_path}/00002.sst");
        let sst3_remote_path = format!("{current_attempt_remote_path}/00003.sst");
        let manifest_remote_path = format!("{prev_remote_path}/MANIFEST-000000");
        let options_remote_path = format!("{prev_remote_path}/OPTIONS-000000");
        let current_remote_path = format!("{current_attempt_remote_path}/CURRENT");
        let log_remote_path = format!("{current_attempt_remote_path}/00001.log");

        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|f| f.remote_filepath == sst1_remote_path));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|f| f.remote_filepath == sst2_remote_path));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|f| f.remote_filepath == sst3_remote_path));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|f| f.remote_filepath == manifest_remote_path));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|f| f.remote_filepath == options_remote_path));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|f| f.remote_filepath == current_remote_path));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|f| f.remote_filepath == log_remote_path));
    }
}
