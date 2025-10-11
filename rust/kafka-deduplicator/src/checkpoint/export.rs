use std::time::Instant;

use super::{CheckpointMetadata, CheckpointMode, CheckpointUploader};

use anyhow::{Context, Result};
use metrics;
use tracing::{error, info, warn};

const CHECKPOINT_UPLOAD_DURATION_HISTOGRAM: &str = "checkpoint_upload_duration_seconds";
const CHECKPOINT_UPLOADS_COUNTER: &str = "checkpoint_upload_errors";

#[derive(Debug)]
pub struct CheckpointExporter {
    uploader: Box<dyn CheckpointUploader>,
}

impl CheckpointExporter {
    pub fn new(uploader: Box<dyn CheckpointUploader>) -> Self {
        Self { uploader }
    }

    // returns the remote key prefix for this checkpoint or an error
    pub async fn export_checkpoint(&self, metadata: &CheckpointMetadata) -> Result<String> {
        let local_path_tag = metadata.target.local_path_tag();
        let mode: CheckpointMode = metadata.checkpoint_type.into();

        let local_checkpoint_path = metadata
            .target
            .local_attempt_path()
            .context("In export_checkpoint")?;
        let remote_key_prefix = metadata
            .target
            .remote_attempt_path()
            .context("In export_checkpoint")?;

        // Upload to remote storage in background
        if self.is_available().await {
            let upload_start = Instant::now();

            match self
                .uploader
                .upload_checkpoint_dir(&local_checkpoint_path, &remote_key_prefix)
                .await
            {
                Ok(uploaded_files) => {
                    let upload_duration = upload_start.elapsed();

                    let tags = [("mode", mode.as_str()), ("result", "success")];
                    metrics::histogram!(CHECKPOINT_UPLOAD_DURATION_HISTOGRAM, &tags)
                        .record(upload_duration.as_secs_f64());
                    metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, &tags).increment(1);
                    info!(
                        local_path = local_path_tag,
                        remote_path = remote_key_prefix,
                        uploaded_file_count = uploaded_files.len(),
                        elapsed_seconds = upload_duration.as_secs_f64(),
                        checkpoint_mode = mode.as_str(),
                        "Export successful: checkpoint uploaded",
                    );
                }

                Err(e) => {
                    let tags = [("mode", mode.as_str()), ("result", "error")];
                    metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, &tags).increment(1);
                    error!(
                        local_path = local_path_tag,
                        remote_path = remote_key_prefix,
                        checkpoint_mode = mode.as_str(),
                        "Export failed: uploading checkpoint: {}",
                        e
                    );
                    return Err(e);
                }
            };

            Ok(remote_key_prefix)
        } else {
            let tags = [("mode", mode.as_str()), ("result", "unavailable")];
            metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, &tags).increment(1);
            warn!(
                local_path = local_path_tag,
                remote_path = remote_key_prefix,
                checkpoint_mode = mode.as_str(),
                "Export failed: uploader not available"
            );

            Err(anyhow::anyhow!("Uploader not available"))
        }
    }

    pub async fn export_metadata(&self, metadata: &CheckpointMetadata) -> Result<()> {
        let local_metadata_path = metadata
            .target
            .local_metadata_file()
            .context("In export_metadata")?;
        let remote_metadata_path = metadata
            .target
            .remote_metadata_file()
            .context("In export_metadata")?;

        self.uploader
            .upload_metadata_file(&local_metadata_path, &remote_metadata_path)
            .await
    }

    pub async fn is_available(&self) -> bool {
        self.uploader.is_available().await
    }
}
