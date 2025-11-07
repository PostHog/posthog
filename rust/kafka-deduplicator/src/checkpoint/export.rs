use std::time::Instant;

use super::{CheckpointPlan, CheckpointUploader};
use crate::metrics_const::{CHECKPOINT_UPLOADS_COUNTER, CHECKPOINT_UPLOAD_DURATION_HISTOGRAM};

use anyhow::Result;
use metrics;
use tracing::{error, info, warn};

#[derive(Debug)]
pub struct CheckpointExporter {
    uploader: Box<dyn CheckpointUploader>,
}

impl CheckpointExporter {
    pub fn new(uploader: Box<dyn CheckpointUploader>) -> Self {
        Self { uploader }
    }

    /// Export checkpoint using a plan with incremental deduplication
    pub async fn export_checkpoint_with_plan(&self, plan: &CheckpointPlan) -> Result<()> {
        if !self.is_available().await {
            metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, "result" => "unavailable").increment(1);
            warn!(
                remote_metadata_path = plan.info.get_metadata_key(),
                "Export failed: uploader not available"
            );
            return Err(anyhow::anyhow!("Uploader not available"));
        }

        let upload_start = Instant::now();

        match self.uploader.upload_checkpoint_with_plan(plan).await {
            Ok(uploaded_files) => {
                let upload_duration = upload_start.elapsed();
                let total_files = plan.info.metadata.files.len();
                let new_files = plan.files_to_upload.len();
                let reused_files = total_files - new_files;

                metrics::histogram!(CHECKPOINT_UPLOAD_DURATION_HISTOGRAM, "result" => "success")
                    .record(upload_duration.as_secs_f64());
                metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, "result" => "success").increment(1);

                info!(
                    remote_path = plan.info.get_metadata_key(),
                    uploaded_file_count = uploaded_files.len(),
                    total_files = total_files,
                    new_files = new_files,
                    reused_files = reused_files,
                    elapsed_seconds = upload_duration.as_secs_f64(),
                    "Export successful: checkpoint uploaded with deduplication",
                );

                Ok(())
            }

            Err(e) => {
                metrics::counter!(CHECKPOINT_UPLOADS_COUNTER, "result" => "error").increment(1);
                error!(
                    remote_path = plan.info.get_metadata_key(),
                    "Export failed: uploading checkpoint: {}", e
                );
                Err(e)
            }
        }
    }

    pub async fn is_available(&self) -> bool {
        self.uploader.is_available().await
    }
}
