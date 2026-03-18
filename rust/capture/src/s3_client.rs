use aws_config::BehaviorVersion;
use aws_sdk_s3::{
    config::{Credentials, Region},
    error::SdkError,
    primitives::ByteStream,
    Client,
};
use bytes::Bytes;
use metrics::{counter, histogram};
use std::time::Instant;
use tracing::{error, info};

// Metric names
const S3_UPLOAD_BODY_SIZE_BYTES: &str = "capture_s3_upload_body_size_bytes";
const S3_UPLOAD_DURATION_SECONDS: &str = "capture_s3_upload_duration_seconds";
const S3_UPLOAD_TOTAL: &str = "capture_s3_upload_total";

/// Extract error reason from SdkError for metrics labeling
fn extract_error_reason<E: std::fmt::Debug>(err: &SdkError<E>) -> String {
    match err {
        SdkError::ConstructionFailure(_) => "construction_failure".to_string(),
        SdkError::TimeoutError(_) => "timeout".to_string(),
        SdkError::DispatchFailure(_) => "connection_error".to_string(),
        SdkError::ResponseError(err) => {
            format!("response_error_{}", err.raw().status().as_u16())
        }
        SdkError::ServiceError(err) => {
            format!("status_{}", err.raw().status().as_u16())
        }
        _ => "unknown".to_string(),
    }
}

/// Generic S3 client wrapper for uploading data.
#[derive(Clone)]
pub struct S3Client {
    client: Client,
    bucket: String,
}

/// Configuration for creating an S3 client.
pub struct S3Config {
    pub bucket: String,
    pub region: String,
    pub endpoint: Option<String>,
    pub access_key_id: Option<String>,
    pub secret_access_key: Option<String>,
}

impl S3Client {
    /// Create a new S3 client from configuration.
    ///
    /// Uses the default AWS credential chain (IRSA, env vars, instance profile, etc.)
    /// unless explicit credentials are provided in the config.
    pub async fn new(config: S3Config) -> Self {
        let region = Region::new(config.region.clone());

        // Load default AWS config to get credentials from the default chain
        // (IRSA web identity, env vars, instance profile, etc.)
        let aws_config = aws_config::defaults(BehaviorVersion::latest())
            .region(region.clone())
            .load()
            .await;

        let mut s3_config_builder = aws_sdk_s3::config::Builder::from(&aws_config)
            .region(region)
            .force_path_style(true); // Required for MinIO/localstack compatibility

        if let Some(endpoint) = &config.endpoint {
            s3_config_builder = s3_config_builder.endpoint_url(endpoint);
        }

        // Override with explicit credentials if provided (e.g., for local dev with MinIO)
        if let (Some(access_key), Some(secret_key)) =
            (&config.access_key_id, &config.secret_access_key)
        {
            let credentials = Credentials::new(access_key, secret_key, None, None, "env");
            s3_config_builder = s3_config_builder.credentials_provider(credentials);
        }

        let client = Client::from_conf(s3_config_builder.build());

        info!(
            bucket = config.bucket,
            endpoint = config.endpoint,
            "S3 client initialized"
        );

        Self {
            client,
            bucket: config.bucket,
        }
    }

    /// Upload data to S3.
    /// Returns the full S3 key on success.
    pub async fn put_object(
        &self,
        key: &str,
        data: Bytes,
        content_type: &str,
    ) -> Result<(), S3Error> {
        let body_size = data.len();
        histogram!(S3_UPLOAD_BODY_SIZE_BYTES).record(body_size as f64);

        let start = Instant::now();
        let result = self
            .client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(ByteStream::from(data))
            .content_type(content_type)
            .send()
            .await;

        let duration = start.elapsed().as_secs_f64();
        histogram!(S3_UPLOAD_DURATION_SECONDS).record(duration);

        match result {
            Ok(_) => {
                counter!(S3_UPLOAD_TOTAL, "outcome" => "success", "reason" => "ok").increment(1);
                Ok(())
            }
            Err(e) => {
                let reason = extract_error_reason(&e);
                counter!(S3_UPLOAD_TOTAL, "outcome" => "error", "reason" => reason.clone())
                    .increment(1);
                error!(
                    bucket = self.bucket,
                    key = key,
                    error = %e,
                    reason = reason,
                    "Failed to upload to S3"
                );
                Err(S3Error::UploadFailed(e.to_string()))
            }
        }
    }

    /// Check S3 connectivity by verifying bucket access.
    pub async fn check_health(&self) -> bool {
        match self.client.head_bucket().bucket(&self.bucket).send().await {
            Ok(_) => true,
            Err(e) => {
                error!(bucket = self.bucket, error = %e, "S3 health check failed");
                false
            }
        }
    }

    pub fn bucket(&self) -> &str {
        &self.bucket
    }
}

#[derive(Debug, thiserror::Error)]
pub enum S3Error {
    #[error("Failed to upload: {0}")]
    UploadFailed(String),
}
