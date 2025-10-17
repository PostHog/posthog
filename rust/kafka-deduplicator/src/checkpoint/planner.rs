use std::collections::HashMap;
use std::fs::File;
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
                .track_file(remote_filepath, candidate.checksum.clone(), candidate.size);
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
            if decide_with_duplicate(&candidate, prev_file) {
                debug!("Duplicate file {} - new file will be uploaded", filename);
                metrics::counter!(CHECKPOINT_PLAN_FILE_TRACKED_COUNTER, "file" => "modified")
                    .increment(1);
                let remote_filepath = info.get_file_key(filename);
                info.metadata.track_file(
                    remote_filepath,
                    candidate.checksum.clone(),
                    candidate.size,
                );
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
                    prev_file.file_size,
                );
            }
        } else {
            // File is new - needs to be uploaded
            debug!("New file {} will be uploaded", filename);
            metrics::counter!(CHECKPOINT_PLAN_FILE_TRACKED_COUNTER, "file" => "added").increment(1);
            let remote_filepath = info.get_file_key(filename);
            info.metadata
                .track_file(remote_filepath, candidate.checksum.clone(), candidate.size);
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
fn decide_with_duplicate(candidate: &LocalCheckpointFile, prev_file: &CheckpointFile) -> bool {
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

    let mut file =
        File::open(file_path).with_context(|| format!("Failed to open file: {file_path:?}"))?;
    let mut hasher = Sha256::new();
    let file_size = std::io::copy(&mut file, &mut hasher)
        .with_context(|| format!("Failed to read and hash file: {file_path:?}"))?;

    let hash = hasher.finalize();
    let checksum = format!("{hash:x}");

    Ok(LocalCheckpointFile::new(
        filename,
        checksum,
        file_size,
        local_file_path,
    ))
}

#[derive(Debug, Clone)]
pub struct LocalCheckpointFile {
    pub filename: String,
    pub checksum: String,
    pub size: u64,
    pub local_path: PathBuf,
}

impl LocalCheckpointFile {
    pub fn new(filename: String, checksum: String, size: u64, local_path: PathBuf) -> Self {
        Self {
            filename,
            checksum,
            size,
            local_path,
        }
    }
}

mod tests {
    use super::*;
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

        // With no previous metadata, all files should be uploaded
        assert_eq!(plan.files_to_upload.len(), 2);
        assert_eq!(plan.info.metadata.files.len(), 2);

        let expected_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{checkpoint_id}");
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .all(|p| p.contains(&expected_remote_path)));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.ends_with("file1.sst")));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.ends_with("file2.sst")));
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

        let prev_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{prev_checkpoint_id}",);
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/file1.sst"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/file2.sst"));

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

        // Create test files from what would have been current checkpoint attempt
        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file1.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file2.sst"), b"data2").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file3.sst"), b"data3").unwrap();

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

        // file1 and file2 should be reused, file3 should be uploaded
        assert_eq!(plan.files_to_upload.len(), 1);
        assert_eq!(plan.info.metadata.files.len(), 3);

        let current_attempt_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{checkpoint_id}",);
        assert_eq!(plan.files_to_upload[0].0, "file3.sst");
        assert_eq!(
            plan.files_to_upload[0].1,
            format!(
                "{}/file3.sst",
                &local_checkpoint_attempt_dir.to_string_lossy()
            )
        );

        // Check that file1 and file2 are in metadata as references
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{prev_remote_path}/file1.sst").as_str())));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{prev_remote_path}/file2.sst").as_str())));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p == format!("{current_attempt_remote_path}/file3.sst").as_str()));
    }

    #[test]
    fn test_plan_checkpoint_with_already_referenced_prev_files() {
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

        let prev_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{prev_checkpoint_id}",);
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/file1.sst"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/file2.sst"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/file3.sst"));

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

        // Create test files from what would have been current checkpoint attempt
        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file1.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file2.sst"), b"data2").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file3.sst"), b"data3").unwrap();

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

        // file1 and file2 should be reused, file3 should be uploaded
        assert!(plan.files_to_upload.is_empty());
        assert_eq!(plan.info.metadata.files.len(), 3);

        // Check that previously uploaded file1, file2 and file3 are in
        // metadata with remote paths referencing previous checkpoint
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{prev_remote_path}/file1.sst").as_str())));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{prev_remote_path}/file2.sst").as_str())));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{prev_remote_path}/file3.sst").as_str())));
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

        let prev_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{prev_checkpoint_id}",);
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/file1.sst"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/file2.sst"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/MANIFEST-000000"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/OPTIONS-000000"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/CURRENT"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/00001.log"));

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
        std::fs::write(local_checkpoint_attempt_dir.join("file1.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file2.sst"), b"data2").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file3.sst"), b"data3").unwrap();
        std::fs::write(
            local_checkpoint_attempt_dir.join("MANIFEST-000000"),
            b"data4",
        )
        .unwrap();
        std::fs::write(
            local_checkpoint_attempt_dir.join("OPTIONS-000000"),
            b"data5",
        )
        .unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("CURRENT"), b"data6").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00001.log"), b"data7").unwrap();

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

        // file1 and file2 should be reused, file3 should be uploaded
        assert_eq!(plan.files_to_upload.len(), 5);
        assert_eq!(plan.info.metadata.files.len(), 7);

        let current_attempt_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{checkpoint_id}",);

        let filenames_to_upload = plan
            .files_to_upload
            .iter()
            .map(|(filename, _)| filename.clone())
            .collect::<HashSet<String>>();
        assert!(filenames_to_upload.contains("file3.sst"));
        assert!(filenames_to_upload.contains("MANIFEST-000000"));
        assert!(filenames_to_upload.contains("OPTIONS-000000"));
        assert!(filenames_to_upload.contains("CURRENT"));
        assert!(filenames_to_upload.contains("00001.log"));

        // For previously seen SST files we keep the original uploaded version for reference
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{prev_remote_path}/file1.sst").as_str())));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{prev_remote_path}/file2.sst").as_str())));

        // for new files and non-SST files we keep the latest checkponted version
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p == format!("{current_attempt_remote_path}/file3.sst").as_str()));
        assert!(
            plan.info
                .metadata
                .files
                .iter()
                .any(|p| p
                    .contains(format!("{current_attempt_remote_path}/MANIFEST-000000").as_str()))
        );
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{current_attempt_remote_path}/OPTIONS-000000").as_str())));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p == format!("{current_attempt_remote_path}/CURRENT").as_str()));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p == format!("{current_attempt_remote_path}/00001.log").as_str()));
    }

    #[test]
    fn test_plan_checkpoint_with_previous_and_new_non_sst_types() {
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

        let prev_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{prev_checkpoint_id}",);
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/file1.sst"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/file2.sst"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/MANIFEST-000000"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/OPTIONS-000000"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/CURRENT"));
        prev_metadata
            .files
            .push(format!("{prev_remote_path}/00001.log"));

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
        std::fs::write(local_checkpoint_attempt_dir.join("file1.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file2.sst"), b"data2").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file3.sst"), b"data3").unwrap();
        std::fs::write(
            local_checkpoint_attempt_dir.join("MANIFEST-000001"),
            b"data4",
        )
        .unwrap();
        std::fs::write(
            local_checkpoint_attempt_dir.join("OPTIONS-000000"),
            b"data5",
        )
        .unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("CURRENT"), b"data6").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00002.log"), b"data7").unwrap();

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

        // file1 and file2 should be reused, file3 should be uploaded
        assert_eq!(plan.files_to_upload.len(), 5);
        assert_eq!(plan.info.metadata.files.len(), 7);

        let current_attempt_remote_path =
            format!("{remote_bucket_namespace}/{topic}/{partition_number}/{checkpoint_id}",);

        let filenames_to_upload = plan
            .files_to_upload
            .iter()
            .map(|(filename, _)| filename.clone())
            .collect::<HashSet<String>>();
        assert!(filenames_to_upload.contains("file3.sst"));
        assert!(filenames_to_upload.contains("MANIFEST-000001"));
        assert!(filenames_to_upload.contains("OPTIONS-000000"));
        assert!(filenames_to_upload.contains("CURRENT"));
        assert!(filenames_to_upload.contains("00002.log"));

        // For previously seen SST files we keep the original uploaded version for reference
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{prev_remote_path}/file1.sst").as_str())));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{prev_remote_path}/file2.sst").as_str())));

        // for new files and non-SST files we keep the latest checkponted version
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p == format!("{current_attempt_remote_path}/file3.sst").as_str()));
        assert!(
            plan.info
                .metadata
                .files
                .iter()
                .any(|p| p
                    .contains(format!("{current_attempt_remote_path}/MANIFEST-000001").as_str()))
        );
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p.contains(format!("{current_attempt_remote_path}/OPTIONS-000000").as_str())));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p == format!("{current_attempt_remote_path}/CURRENT").as_str()));
        assert!(plan
            .info
            .metadata
            .files
            .iter()
            .any(|p| p == format!("{current_attempt_remote_path}/00002.log").as_str()));
    }
}
