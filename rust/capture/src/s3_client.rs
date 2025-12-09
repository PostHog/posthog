use aws_config::BehaviorVersion;
use aws_sdk_s3::{
    config::{Credentials, Region},
    primitives::ByteStream,
    Client,
};
use bytes::Bytes;
use tracing::{error, info};

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
    pub async fn new(config: S3Config) -> Self {
        let region = Region::new(config.region);

        let mut s3_config_builder = aws_sdk_s3::Config::builder()
            .behavior_version(BehaviorVersion::latest())
            .region(region)
            .force_path_style(true); // Required for MinIO/localstack compatibility

        if let Some(endpoint) = &config.endpoint {
            s3_config_builder = s3_config_builder.endpoint_url(endpoint);
        }

        if let (Some(access_key), Some(secret_key)) =
            (&config.access_key_id, &config.secret_access_key)
        {
            let credentials = Credentials::new(access_key, secret_key, None, None, "env");
            s3_config_builder = s3_config_builder.credentials_provider(credentials);
        }

        let s3_config = s3_config_builder.build();
        let client = Client::from_conf(s3_config);

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
        self.client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(ByteStream::from(data))
            .content_type(content_type)
            .send()
            .await
            .map_err(|e| {
                error!(
                    bucket = self.bucket,
                    key = key,
                    error = %e,
                    "Failed to upload to S3"
                );
                S3Error::UploadFailed(e.to_string())
            })?;

        Ok(())
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
