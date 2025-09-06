use std::path::Path;
use std::time::Instant;

use super::{CheckpointConfig, CheckpointUploader};

use anyhow::Result;
use metrics;
use tracing::{error, info, warn};

const CHECKPOINT_UPLOAD_DURATION_HISTOGRAM: &str = "checkpoint_upload_duration_seconds";

#[derive(Debug)]
pub struct CheckpointExporter {
    config: CheckpointConfig,
    uploader: Box<dyn CheckpointUploader>,
}

impl CheckpointExporter {
    pub fn new(config: CheckpointConfig, uploader: Box<dyn CheckpointUploader>) -> Self {
        Self { config, uploader }
    }
    // returns the remote key prefix for this checkpoint or an error
    pub async fn export_checkpoint(
        &self,
        local_checkpoint_path: &Path,
        checkpoint_name: &str,
        is_full_upload: bool,
    ) -> Result<String> {
        let remote_key_prefix = if is_full_upload {
            format!("{}/full/{}", self.config.s3_key_prefix, checkpoint_name)
        } else {
            format!(
                "{}/incremental/{}",
                self.config.s3_key_prefix, checkpoint_name
            )
        };
        let local_path_tag = local_checkpoint_path.to_string_lossy().to_string();

        // Upload to remote storage in background
        if self.is_available().await {
            let upload_start = Instant::now();

            match self
                .uploader
                .upload_checkpoint_dir(local_checkpoint_path, &remote_key_prefix)
                .await
            {
                Ok(uploaded_files) => {
                    let checkpoint_type = if is_full_upload {
                        "full"
                    } else {
                        "incremental"
                    };
                    let upload_duration = upload_start.elapsed();
                    metrics::histogram!(CHECKPOINT_UPLOAD_DURATION_HISTOGRAM, "checkpoint_type" => checkpoint_type)
                        .record(upload_duration.as_secs_f64());
                    info!(
                        local_path = local_path_tag,
                        remote_path = remote_key_prefix,
                        uploaded_file_count = uploaded_files.len(),
                        elapsed_seconds = upload_duration.as_secs_f64(),
                        checkpoint_type,
                        "Export successful: checkpoint uploaded",
                    );
                }

                Err(e) => {
                    error!(
                        local_path = local_path_tag,
                        remote_path = remote_key_prefix,
                        "Export failed: uploading checkpoint: {}",
                        e
                    );
                    return Err(e);
                }
            };

            Ok(remote_key_prefix)
        } else {
            // TODO(eli): stat this
            warn!(
                local_path = local_path_tag,
                remote_path = remote_key_prefix,
                "Export failed: uploader not available"
            );

            Err(anyhow::anyhow!("Uploader not available"))
        }
    }

    pub async fn is_available(&self) -> bool {
        self.uploader.is_available().await
    }
}
