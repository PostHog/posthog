use aws_config::{retry::RetryConfig, timeout::TimeoutConfig, BehaviorVersion, Region};
use aws_sdk_s3::Client;
use tracing::info;

use super::config::CheckpointConfig;

pub async fn create_s3_client(config: &CheckpointConfig) -> Client {
    let timeout_config = TimeoutConfig::builder()
        .operation_timeout(config.s3_operation_timeout)
        .operation_attempt_timeout(config.s3_attempt_timeout)
        .build();

    let mut builder = if std::env::var("AWS_ROLE_ARN").is_ok()
        && std::env::var("AWS_WEB_IDENTITY_TOKEN_FILE").is_ok()
    {
        info!("AWS role and token file detected, using IAM credentials");
        aws_sdk_s3::config::Builder::from(&aws_config::load_from_env().await)
    } else if let (Some(ref access_key), Some(ref secret_key)) =
        (&config.s3_access_key_id, &config.s3_secret_access_key)
    {
        info!("Using explicit S3 credentials from config");
        let credentials =
            aws_sdk_s3::config::Credentials::new(access_key, secret_key, None, None, "environment");
        aws_sdk_s3::config::Builder::new().credentials_provider(credentials)
    } else {
        info!("No explicit S3 credentials, falling back to default credential chain");
        aws_sdk_s3::config::Builder::from(&aws_config::load_from_env().await)
    };

    builder = builder
        .timeout_config(timeout_config)
        .retry_config(RetryConfig::adaptive())
        .force_path_style(config.s3_force_path_style)
        .behavior_version(BehaviorVersion::latest());

    if let Some(ref region) = config.aws_region {
        builder = builder.region(Region::new(region.clone()));
    }
    if let Some(ref endpoint) = config.s3_endpoint {
        builder = builder.endpoint_url(endpoint);
    }

    Client::from_conf(builder.build())
}
