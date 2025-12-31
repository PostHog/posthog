use aws_config::{retry::RetryConfig, timeout::TimeoutConfig, BehaviorVersion, Region};
use aws_sdk_s3::Client;
use tracing::info;

use super::config::CheckpointConfig;

pub async fn create_s3_client(config: &CheckpointConfig) -> Client {
    let timeout_config = TimeoutConfig::builder()
        .operation_timeout(config.s3_operation_timeout)
        .operation_attempt_timeout(config.s3_attempt_timeout)
        .build();

    let s3_config = if std::env::var("AWS_ROLE_ARN").is_ok()
        && std::env::var("AWS_WEB_IDENTITY_TOKEN_FILE").is_ok()
    {
        info!("AWS role and token file detected, using IAM credentials");
        aws_sdk_s3::config::Builder::from(&aws_config::load_from_env().await)
            .timeout_config(timeout_config)
            .retry_config(RetryConfig::adaptive())
            .force_path_style(config.s3_force_path_style)
            .build()
    } else {
        info!("Using explicit S3 credentials from config");
        let credentials = aws_sdk_s3::config::Credentials::new(
            &config.s3_access_key_id,
            &config.s3_secret_access_key,
            None,
            None,
            "environment",
        );
        let mut builder = aws_sdk_s3::config::Builder::new()
            .region(Region::new(config.aws_region.clone()))
            .credentials_provider(credentials)
            .behavior_version(BehaviorVersion::latest())
            .timeout_config(timeout_config)
            .retry_config(RetryConfig::adaptive())
            .force_path_style(config.s3_force_path_style);

        if let Some(ref endpoint) = config.s3_endpoint {
            builder = builder.endpoint_url(endpoint);
        }
        builder.build()
    };

    Client::from_conf(s3_config)
}
