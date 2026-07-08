use std::collections::HashMap;
use std::path::{Path, PathBuf};

use super::{
    store_hash_prefix, CheckpointFile, CheckpointInfo, CheckpointMetadata, PlanningCancelledError,
    STORE_PARTITION, STORE_TOPIC,
};
use crate::observability::metrics::CHECKPOINT_PLAN_FILES_TOTAL;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use sha2::{Digest, Sha256};
use tokio_util::sync::CancellationToken;
use tracing::{debug, info};

#[derive(Debug)]
pub struct CheckpointPlan {
    pub info: CheckpointInfo,
    pub files_to_upload: Vec<LocalCheckpointFile>,
}

/// Build a checkpoint plan: new metadata plus the files to upload.
///
/// Incremental dedup keyed on filename: SST files (immutable) are reused from the previous attempt;
/// mutable files are re-uploaded only on checksum change. The cancellation token, if given, is
/// checked during the directory walk and before hashing non-SST files.
pub fn plan_checkpoint(
    local_checkpoint_attempt_dir: &Path,
    remote_bucket_namespace: String,
    attempt_timestamp: DateTime<Utc>,
    sequence: u64,
    previous_metadata: Option<&CheckpointMetadata>,
    cancel_token: Option<&CancellationToken>,
) -> Result<CheckpointPlan> {
    ensure_not_cancelled(cancel_token, "before planning start")?;
    let metadata = CheckpointMetadata::new(
        STORE_TOPIC.to_string(),
        STORE_PARTITION,
        attempt_timestamp,
        sequence,
        0,
        0,
    );
    let hash = store_hash_prefix().to_string();
    let mut info = CheckpointInfo::new(metadata, remote_bucket_namespace, Some(hash));
    let mut files_to_upload: Vec<LocalCheckpointFile> = Vec::new();

    let local_files = collect_local_files(local_checkpoint_attempt_dir, cancel_token)?;
    info!(
        "Found {} files in local checkpoint directory",
        local_files.len()
    );

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

    for candidate in local_files {
        let filename = &candidate.filename;
        if let Some(prev_file) = prev_file_map.get(filename) {
            if retain_or_replace_duplicate(&candidate, prev_file) {
                debug!("Duplicate file {} - new file will be uploaded", filename);
                metrics::counter!(CHECKPOINT_PLAN_FILES_TOTAL, "action" => "replaced").increment(1);
                let remote_filepath = info.get_file_key(filename);
                info.metadata
                    .track_file(remote_filepath, candidate.checksum.clone());
                files_to_upload.push(candidate);
            } else {
                debug!(
                    "Duplicate file {} - retaining original, skipping upload",
                    filename
                );
                metrics::counter!(CHECKPOINT_PLAN_FILES_TOTAL, "action" => "retained").increment(1);
                info.metadata.track_file(
                    prev_file.remote_filepath.clone(),
                    prev_file.checksum.clone(),
                );
            }
        } else {
            debug!("New file {} will be uploaded", filename);
            metrics::counter!(CHECKPOINT_PLAN_FILES_TOTAL, "action" => "added").increment(1);
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

fn retain_or_replace_duplicate(
    candidate: &LocalCheckpointFile,
    prev_file: &CheckpointFile,
) -> bool {
    match &candidate.filename {
        f if f == "CURRENT" => true,       // always re-uploaded
        f if f.ends_with(".sst") => false, // immutable, always reused

        // RocksDB mutates these in place; re-upload only on checksum change.
        f if f.starts_with("OPTIONS-") || f.starts_with("MANIFEST-") || f.ends_with(".log") => {
            candidate.checksum != prev_file.checksum
        }
        _ => true, // bias to keeping latest files for safety
    }
}

fn collect_local_files(
    base_attempt_path: &Path,
    cancel_token: Option<&CancellationToken>,
) -> Result<Vec<LocalCheckpointFile>> {
    let mut files = Vec::new();
    let mut stack = vec![base_attempt_path.to_path_buf()];

    while let Some(current_path) = stack.pop() {
        ensure_not_cancelled(cancel_token, "during directory walk")?;
        let entries = std::fs::read_dir(&current_path)
            .with_context(|| format!("Failed to read directory: {current_path:?}"))?;

        for entry in entries {
            ensure_not_cancelled(cancel_token, "during directory walk")?;
            let entry = entry.context(format!(
                "Failed to read directory entry from {base_attempt_path:?}"
            ))?;
            let path = entry.path();

            if path.is_dir() {
                stack.push(path);
            } else {
                let candidate =
                    build_candidate_file(&path, cancel_token).context("In build_candidate_file")?;
                files.push(candidate);
            }
        }
    }

    Ok(files)
}

fn build_candidate_file(
    file_path: &Path,
    cancel_token: Option<&CancellationToken>,
) -> Result<LocalCheckpointFile> {
    let local_file_path = file_path.to_path_buf();
    let filename = file_path
        .file_name()
        .context(format!("Failed to get filename for: {file_path:?}"))?
        .to_string_lossy()
        .to_string();

    let checksum = if filename.ends_with(".sst") {
        String::default()
    } else {
        ensure_not_cancelled(cancel_token, "before hashing non-SST file")?;
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

fn ensure_not_cancelled(
    cancel_token: Option<&CancellationToken>,
    reason: &'static str,
) -> Result<()> {
    if cancel_token.is_some_and(CancellationToken::is_cancelled) {
        return Err(PlanningCancelledError {
            reason: reason.to_string(),
        }
        .into());
    }

    Ok(())
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
    use tokio_util::sync::CancellationToken;

    fn attempt_dir(base: &Path, checkpoint_id: &str) -> PathBuf {
        base.join(STORE_TOPIC)
            .join(STORE_PARTITION.to_string())
            .join(checkpoint_id)
    }

    #[test]
    fn plan_checkpoint_no_previous() {
        let temp_dir = TempDir::new().unwrap();
        let remote_bucket_namespace = "checkpoints";
        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let sequence = 1000;
        let local_checkpoint_attempt_dir = attempt_dir(temp_dir.path(), &checkpoint_id);

        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file1.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("file2.sst"), b"data2").unwrap();

        let plan = plan_checkpoint(
            &local_checkpoint_attempt_dir,
            remote_bucket_namespace.to_string(),
            attempt_timestamp,
            sequence,
            None,
            None,
        )
        .unwrap();

        let expected_sst1 =
            build_candidate_file(&local_checkpoint_attempt_dir.join("file1.sst"), None).unwrap();
        let expected_sst2 =
            build_candidate_file(&local_checkpoint_attempt_dir.join("file2.sst"), None).unwrap();

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

        assert_eq!(plan.info.metadata.files.len(), 2);
        let hash = store_hash_prefix();
        let expected_remote_path = format!(
            "{hash}/{remote_bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}"
        );
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
        let meta_key = plan.info.get_metadata_key();
        assert!(meta_key.contains(hash));
        assert_eq!(
            meta_key,
            format!(
                "{hash}/{remote_bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}/metadata.json"
            )
        );
    }

    #[test]
    fn plan_checkpoint_with_previous() {
        let temp_dir = TempDir::new().unwrap();
        let remote_bucket_namespace = "checkpoints";
        let prev_attempt_timestamp = Utc::now() - Duration::hours(1);
        let prev_checkpoint_id = CheckpointMetadata::generate_id(prev_attempt_timestamp);
        let prev_sequence = 1000;

        let mut prev_metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            prev_attempt_timestamp,
            prev_sequence,
            0,
            0,
        );

        let prev_local_attempt_dir = attempt_dir(temp_dir.path(), &prev_checkpoint_id);

        std::fs::create_dir_all(&prev_local_attempt_dir).unwrap();
        std::fs::write(prev_local_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00002.sst"), b"data2").unwrap();

        let expected_prev_sst1 =
            build_candidate_file(&prev_local_attempt_dir.join("00001.sst"), None).unwrap();
        let expected_prev_sst2 =
            build_candidate_file(&prev_local_attempt_dir.join("00002.sst"), None).unwrap();

        let prev_remote_path = format!(
            "{remote_bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{prev_checkpoint_id}"
        );

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
        let local_checkpoint_attempt_dir = attempt_dir(temp_dir.path(), &checkpoint_id);

        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00002.sst"), b"data2").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00003.sst"), b"data3").unwrap();
        let expected_sst3 =
            build_candidate_file(&local_checkpoint_attempt_dir.join("00003.sst"), None).unwrap();

        let plan = plan_checkpoint(
            &local_checkpoint_attempt_dir,
            remote_bucket_namespace.to_string(),
            attempt_timestamp,
            sequence,
            Some(&prev_metadata),
            None,
        )
        .unwrap();

        assert_eq!(plan.files_to_upload.len(), 1);
        let got_sst3 = plan
            .files_to_upload
            .iter()
            .find(|f| f.filename == "00003.sst")
            .unwrap();
        assert_eq!(got_sst3, &expected_sst3);

        assert_eq!(plan.info.metadata.files.len(), 3);

        let hash = store_hash_prefix();
        let current_attempt_remote_path = format!(
            "{hash}/{remote_bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}"
        );

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

        assert_eq!(&sst1_file_meta.checksum, &expected_prev_sst1.checksum);
        assert_eq!(&sst2_file_meta.checksum, &expected_prev_sst2.checksum);
        assert_eq!(sst3_file_meta.checksum, expected_sst3.checksum);
    }

    #[test]
    fn plan_checkpoint_with_only_prev_files() {
        let temp_dir = TempDir::new().unwrap();
        let remote_bucket_namespace = "checkpoints";
        let prev_attempt_timestamp = Utc::now() - Duration::hours(1);
        let prev_checkpoint_id = CheckpointMetadata::generate_id(prev_attempt_timestamp);
        let prev_sequence = 1000;

        let mut prev_metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            prev_attempt_timestamp,
            prev_sequence,
            0,
            0,
        );

        let prev_local_attempt_dir = attempt_dir(temp_dir.path(), &prev_checkpoint_id);

        std::fs::create_dir_all(&prev_local_attempt_dir).unwrap();
        std::fs::write(prev_local_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00002.sst"), b"data2").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00003.sst"), b"data3").unwrap();

        let expected_prev_sst1 =
            build_candidate_file(&prev_local_attempt_dir.join("00001.sst"), None).unwrap();
        let expected_prev_sst2 =
            build_candidate_file(&prev_local_attempt_dir.join("00002.sst"), None).unwrap();
        let expected_prev_sst3 =
            build_candidate_file(&prev_local_attempt_dir.join("00003.sst"), None).unwrap();

        let prev_remote_path = format!(
            "{remote_bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{prev_checkpoint_id}"
        );
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
        let local_checkpoint_attempt_dir = attempt_dir(temp_dir.path(), &checkpoint_id);

        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00002.sst"), b"data2").unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00003.sst"), b"data3").unwrap();

        let plan = plan_checkpoint(
            &local_checkpoint_attempt_dir,
            remote_bucket_namespace.to_string(),
            attempt_timestamp,
            sequence,
            Some(&prev_metadata),
            None,
        )
        .unwrap();

        assert!(plan.files_to_upload.is_empty());
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
        let sst3_file_meta = plan
            .info
            .metadata
            .files
            .iter()
            .find(|f| f.remote_filepath == prev_sst3_remote_path)
            .unwrap();

        assert_eq!(&sst1_file_meta.checksum, &expected_prev_sst1.checksum);
        assert_eq!(&sst2_file_meta.checksum, &expected_prev_sst2.checksum);
        assert_eq!(&sst3_file_meta.checksum, &expected_prev_sst3.checksum);
    }

    #[test]
    fn plan_checkpoint_with_previous_and_non_sst_types() {
        let temp_dir = TempDir::new().unwrap();
        let remote_bucket_namespace = "checkpoints";
        let prev_attempt_timestamp = Utc::now() - Duration::hours(1);
        let prev_checkpoint_id = CheckpointMetadata::generate_id(prev_attempt_timestamp);
        let prev_sequence = 1000;

        let mut prev_metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            prev_attempt_timestamp,
            prev_sequence,
            0,
            0,
        );

        let prev_local_attempt_dir = attempt_dir(temp_dir.path(), &prev_checkpoint_id);

        std::fs::create_dir_all(&prev_local_attempt_dir).unwrap();
        std::fs::write(prev_local_attempt_dir.join("00001.sst"), b"data1").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00002.sst"), b"data2").unwrap();
        std::fs::write(prev_local_attempt_dir.join("MANIFEST-000000"), b"data3").unwrap();
        std::fs::write(prev_local_attempt_dir.join("OPTIONS-000000"), b"data4").unwrap();
        std::fs::write(prev_local_attempt_dir.join("CURRENT"), b"data5").unwrap();
        std::fs::write(prev_local_attempt_dir.join("00001.log"), b"data6").unwrap();

        let expected_prev_sst1 =
            build_candidate_file(&prev_local_attempt_dir.join("00001.sst"), None).unwrap();
        let expected_prev_sst2 =
            build_candidate_file(&prev_local_attempt_dir.join("00002.sst"), None).unwrap();
        let expected_prev_manifest =
            build_candidate_file(&prev_local_attempt_dir.join("MANIFEST-000000"), None).unwrap();
        let expected_prev_options =
            build_candidate_file(&prev_local_attempt_dir.join("OPTIONS-000000"), None).unwrap();
        let expected_prev_current =
            build_candidate_file(&prev_local_attempt_dir.join("CURRENT"), None).unwrap();
        let expected_prev_log =
            build_candidate_file(&prev_local_attempt_dir.join("00001.log"), None).unwrap();

        let prev_remote_path = format!(
            "{remote_bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{prev_checkpoint_id}"
        );
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
        let local_checkpoint_attempt_dir = attempt_dir(temp_dir.path(), &checkpoint_id);

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
            attempt_timestamp,
            sequence,
            Some(&prev_metadata),
            None,
        )
        .unwrap();

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

        assert_eq!(plan.info.metadata.files.len(), 7);

        // New files (sst3, CURRENT, log) use the hashed path; retained files keep the previous path.
        let hash = store_hash_prefix();
        let current_attempt_remote_path = format!(
            "{hash}/{remote_bucket_namespace}/{STORE_TOPIC}/{STORE_PARTITION}/{checkpoint_id}"
        );
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

    #[test]
    fn plan_checkpoint_cancelled_before_start() {
        let temp_dir = TempDir::new().unwrap();
        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let local_checkpoint_attempt_dir = attempt_dir(temp_dir.path(), &checkpoint_id);

        std::fs::create_dir_all(&local_checkpoint_attempt_dir).unwrap();
        std::fs::write(local_checkpoint_attempt_dir.join("00001.sst"), b"data1").unwrap();

        let cancel_token = CancellationToken::new();
        cancel_token.cancel();

        let err = plan_checkpoint(
            &local_checkpoint_attempt_dir,
            "checkpoints".to_string(),
            attempt_timestamp,
            1000,
            None,
            Some(&cancel_token),
        )
        .unwrap_err();

        assert!(
            err.downcast_ref::<PlanningCancelledError>().is_some(),
            "error should be PlanningCancelledError: {err}"
        );
    }

    #[test]
    fn collect_local_files_cancelled_during_directory_walk() {
        let temp_dir = TempDir::new().unwrap();
        let nested_dir = temp_dir.path().join("nested");
        std::fs::create_dir_all(&nested_dir).unwrap();
        std::fs::write(nested_dir.join("00001.sst"), b"data1").unwrap();

        let cancel_token = CancellationToken::new();
        cancel_token.cancel();

        let err = collect_local_files(temp_dir.path(), Some(&cancel_token)).unwrap_err();
        assert!(
            err.downcast_ref::<PlanningCancelledError>().is_some(),
            "error should be PlanningCancelledError: {err}"
        );
    }

    #[test]
    fn build_candidate_file_cancelled_before_hashing_non_sst() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("MANIFEST-000000");
        std::fs::write(&file_path, b"manifest-data").unwrap();

        let cancel_token = CancellationToken::new();
        cancel_token.cancel();

        let err = build_candidate_file(&file_path, Some(&cancel_token)).unwrap_err();
        assert!(
            err.downcast_ref::<PlanningCancelledError>().is_some(),
            "error should be PlanningCancelledError: {err}"
        );
    }
}
