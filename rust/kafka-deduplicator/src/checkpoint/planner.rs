use anyhow::{Context, Result};
use std::collections::HashMap;
use std::path::Path;
use tracing::{debug, info};

use super::CheckpointMetadata;

/// Result of checkpoint planning
#[derive(Debug)]
pub struct CheckpointPlan {
    /// The new checkpoint metadata with files field populated
    pub metadata: CheckpointMetadata,
    /// Files that need to be uploaded to S3 (filename, local_full_path)
    pub files_to_upload: Vec<(String, String)>,
}

/// Create a checkpoint plan with new metadata and list of files to upload
#[allow(clippy::too_many_arguments)]
pub fn plan_checkpoint(
    local_checkpoint_dir: &Path,
    new_checkpoint_id: String,
    topic: String,
    partition: i32,
    sequence: u64,
    consumer_offset: i64,
    producer_offset: i64,
    previous_metadata: Option<&CheckpointMetadata>,
) -> Result<CheckpointPlan> {
    let mut metadata = CheckpointMetadata::new(
        new_checkpoint_id,
        topic,
        partition,
        sequence,
        consumer_offset,
        producer_offset,
    );

    let mut files_to_upload = Vec::new();

    // Collect all files in local checkpoint directory
    let local_files = collect_local_files(local_checkpoint_dir)?;

    info!(
        "Found {} files in local checkpoint directory",
        local_files.len()
    );

    // If no previous metadata, upload everything
    let Some(prev_meta) = previous_metadata else {
        info!("No previous checkpoint metadata - uploading all files");
        for (filename, local_path) in local_files {
            metadata.files.push(filename.clone());
            files_to_upload.push((filename, local_path));
        }
        return Ok(CheckpointPlan {
            metadata,
            files_to_upload,
        });
    };

    // Build map of filename -> file_path from previous checkpoint
    let mut file_map: HashMap<String, String> = HashMap::new();
    for file_path in &prev_meta.files {
        // Extract just the filename from the path
        let filename = file_path
            .rsplit('/')
            .next()
            .unwrap_or(file_path)
            .to_string();

        file_map.insert(filename.clone(), file_path.clone());
    }

    info!(
        "Built file map with {} files from previous checkpoint {}",
        file_map.len(),
        prev_meta.id
    );

    // For each local file, check if it exists in previous metadata
    for (filename, local_path) in local_files {
        if let Some(prev_file_path) = file_map.get(&filename) {
            // File exists in previous checkpoint - reuse it
            let relative_path = if prev_file_path.starts_with("../") {
                // Already a relative reference, keep it as is
                prev_file_path.clone()
            } else {
                // Create relative path to previous checkpoint
                format!("../{}/{}", prev_meta.id, filename)
            };

            metadata.files.push(relative_path);
            debug!("Reusing file {} from previous checkpoint", filename);
        } else {
            // File is new - needs to be uploaded
            metadata.files.push(filename.clone());
            files_to_upload.push((filename.clone(), local_path));
            debug!("New file {} will be uploaded", filename);
        }
    }

    info!(
        "Checkpoint plan: {} new files, {} reused files",
        files_to_upload.len(),
        metadata.files.len() - files_to_upload.len(),
    );

    Ok(CheckpointPlan {
        metadata,
        files_to_upload,
    })
}

/// Collect all files in local checkpoint directory
fn collect_local_files(base_path: &Path) -> Result<Vec<(String, String)>> {
    let mut files = Vec::new();
    let mut stack = vec![base_path.to_path_buf()];

    while let Some(current_path) = stack.pop() {
        let entries = std::fs::read_dir(&current_path)
            .with_context(|| format!("Failed to read directory: {current_path:?}"))?;

        for entry in entries {
            let entry = entry?;
            let path = entry.path();

            if path.is_dir() {
                stack.push(path);
            } else {
                let relative_path = path
                    .strip_prefix(base_path)
                    .with_context(|| format!("Failed to get relative path for: {path:?}"))?;

                let filename = relative_path.to_string_lossy().replace('\\', "/");
                let local_path = path.to_string_lossy().to_string();

                files.push((filename, local_path));
            }
        }
    }

    Ok(files)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_plan_checkpoint_no_previous() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path();

        // Create some test files
        std::fs::write(checkpoint_dir.join("file1.sst"), b"data1").unwrap();
        std::fs::write(checkpoint_dir.join("file2.sst"), b"data2").unwrap();

        let plan = plan_checkpoint(
            checkpoint_dir,
            "2025-10-14T16-00-00Z".to_string(),
            "test-topic".to_string(),
            0,
            1000,
            100,
            50,
            None,
        )
        .unwrap();

        // With no previous metadata, all files should be uploaded
        assert_eq!(plan.files_to_upload.len(), 2);
        assert_eq!(plan.metadata.files.len(), 2);
    }

    #[test]
    fn test_plan_checkpoint_with_previous() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path();

        // Create test files
        std::fs::write(checkpoint_dir.join("file1.sst"), b"data1").unwrap();
        std::fs::write(checkpoint_dir.join("file2.sst"), b"data2").unwrap();
        std::fs::write(checkpoint_dir.join("file3.sst"), b"data3").unwrap();

        // Create previous metadata with file1 and file2
        let mut prev_metadata = CheckpointMetadata::new(
            "2025-10-14T15-00-00Z".to_string(),
            "test-topic".to_string(),
            0,
            1000,
            100,
            50,
        );
        prev_metadata.files.push("file1.sst".to_string());
        prev_metadata.files.push("file2.sst".to_string());

        let plan = plan_checkpoint(
            checkpoint_dir,
            "2025-10-14T16-00-00Z".to_string(),
            "test-topic".to_string(),
            0,
            2000,
            200,
            100,
            Some(&prev_metadata),
        )
        .unwrap();

        // file1 and file2 should be reused, file3 should be uploaded
        assert_eq!(plan.files_to_upload.len(), 1);
        assert_eq!(plan.metadata.files.len(), 3);

        // Check that file3 is in upload list
        assert!(plan
            .files_to_upload
            .iter()
            .any(|(name, _)| name == "file3.sst"));

        // Check that file1 and file2 are in metadata as references
        assert!(plan.metadata.files.iter().any(|p| p.contains("file1.sst")));
        assert!(plan.metadata.files.iter().any(|p| p.contains("file2.sst")));
        assert!(plan.metadata.files.iter().any(|p| p == "file3.sst"));
    }

    #[test]
    fn test_plan_checkpoint_with_already_referenced_files() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path();

        // Create test files
        std::fs::write(checkpoint_dir.join("file1.sst"), b"data1").unwrap();
        std::fs::write(checkpoint_dir.join("file2.sst"), b"data2").unwrap();
        std::fs::write(checkpoint_dir.join("file3.sst"), b"data3").unwrap();

        // Create previous metadata where file1 is already a reference to an older checkpoint
        let mut prev_metadata = CheckpointMetadata::new(
            "2025-10-14T16-00-00Z".to_string(),
            "test-topic".to_string(),
            0,
            2000,
            200,
            100,
        );
        prev_metadata
            .files
            .push("../2025-10-14T14-00-00Z/file1.sst".to_string());
        prev_metadata.files.push("file2.sst".to_string());

        let plan = plan_checkpoint(
            checkpoint_dir,
            "2025-10-14T17-00-00Z".to_string(),
            "test-topic".to_string(),
            0,
            3000,
            300,
            150,
            Some(&prev_metadata),
        )
        .unwrap();

        // file1 and file2 should be reused, file3 should be uploaded
        assert_eq!(plan.files_to_upload.len(), 1);
        assert_eq!(plan.metadata.files.len(), 3);

        // Check that file3 is in upload list
        assert!(plan
            .files_to_upload
            .iter()
            .any(|(name, _)| name == "file3.sst"));

        // Check that file1 keeps its existing relative reference
        assert!(plan
            .metadata
            .files
            .iter()
            .any(|p| p == "../2025-10-14T14-00-00Z/file1.sst"));

        // Check that file2 gets a new relative reference
        assert!(plan
            .metadata
            .files
            .iter()
            .any(|p| p == "../2025-10-14T16-00-00Z/file2.sst"));
    }
}
