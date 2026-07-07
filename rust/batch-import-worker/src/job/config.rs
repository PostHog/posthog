use std::{collections::HashMap, net::IpAddr, path::PathBuf, sync::Arc, time::Duration};

use anyhow::Error;
use aws_config::{retry::RetryConfig, timeout::TimeoutConfig, BehaviorVersion, Region};
use aws_sdk_s3::config::ProvideCredentials;
use base64::{prelude::BASE64_URL_SAFE, Engine};
use chrono::{DateTime, Utc};
use fernet::MultiFernet;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    context::AppContext,
    emit::{
        capture::CaptureEmitter, kafka::KafkaEmitter, Emitter, FileEmitter, NoOpEmitter,
        StdoutEmitter,
    },
    error::{ToUserError, UserError},
    extractor::ExtractorType,
    parse::format::FormatConfig,
    source::{
        date_range_export::{AuthConfig, DateRangeExportSource},
        folder::FolderSource,
        s3::S3Source,
        s3_gzip::GzipS3Source,
        url_list::UrlList,
        DataSource,
    },
};

use super::model::JobModel;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct JobConfig {
    pub source: SourceConfig,
    // What format is the data in, e.g. Mixpanel events stored in json-lines
    pub data_format: FormatConfig,
    pub sink: SinkConfig,
    #[serde(default = "JobConfig::default_import_events")]
    pub import_events: bool,
    #[serde(default = "JobConfig::default_generate_identify_events")]
    pub generate_identify_events: bool,
    #[serde(default = "JobConfig::default_generate_group_identify_events")]
    pub generate_group_identify_events: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum SourceConfig {
    Folder(FolderSourceConfig),
    UrlList(UrlListConfig),
    S3(S3SourceConfig),
    S3Gzip(S3SourceConfig),
    DateRangeExport(DateRangeExportSourceConfig),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct UrlListConfig {
    urls_key: String,
    #[serde(default)]
    allow_internal_ips: bool,
    #[serde(default = "UrlListConfig::default_timeout_seconds")]
    timeout_seconds: u64,
    #[serde(default = "UrlListConfig::default_retries")]
    retries: usize,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FolderSourceConfig {
    pub path: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct S3SourceConfig {
    #[serde(default)]
    access_key_id_key: Option<String>,
    #[serde(default)]
    secret_access_key_key: Option<String>,
    // Cross-account IAM role auth: the customer's role assumed via STS, with the per-team
    // external id their trust policy conditions on (confused-deputy guard). Mutually
    // exclusive with the access-key fields above.
    #[serde(default)]
    role_arn: Option<String>,
    #[serde(default)]
    external_id: Option<String>,
    bucket: String,
    prefix: String,
    region: String,
    #[serde(default)]
    endpoint_url: Option<String>,
    #[serde(default)]
    allow_internal_ips: bool,
}

// The exactly-one auth method a valid S3SourceConfig resolves to; see S3SourceConfig::auth.
enum S3Auth<'a> {
    Role {
        role_arn: &'a str,
        external_id: &'a str,
    },
    Keys {
        access_key_id_key: &'a str,
        secret_access_key_key: &'a str,
    },
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DateRangeExportSourceConfig {
    base_url: String,
    #[serde(default)]
    extractor_type: ExtractorType,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    start_qp: String,
    end_qp: String,
    auth: AuthSourceConfig,
    interval_duration: i64,
    #[serde(default = "DateRangeExportSourceConfig::default_retries")]
    retries: usize,
    #[serde(default = "DateRangeExportSourceConfig::default_timeout_seconds")]
    timeout_seconds: u64,
    #[serde(default = "DateRangeExportSourceConfig::default_date_format")]
    date_format: String,
    #[serde(default)]
    headers: HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum AuthSourceConfig {
    None,
    ApiKey {
        header_name: String,
        key_secret: String,
    },
    BearerToken {
        token_secret: String,
    },
    BasicAuth {
        username_secret: String,
        password_secret: String,
    },
    // Annoyingly mixpanel does its own thing
    MixpanelAuth {
        secret_key_secret: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum SinkConfig {
    Stdout {
        as_json: bool,
    },
    File {
        path: String,
        as_json: bool,
        cleanup: bool,
    },
    Kafka(KafkaEmitterConfig),
    Capture(CaptureEmitterConfig),
    NoOp,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KafkaEmitterConfig {
    pub topic: String,
    pub send_rate: u64,
    pub transaction_timeout_seconds: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureEmitterConfig {
    pub send_rate: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobSecrets {
    pub secrets: HashMap<String, Value>,
}

// Jobsecrets is a json object, encrypted using fernet and then base64 urlsafe encoded.
impl JobSecrets {
    // Data is base64 url-safe encoded
    pub fn decrypt(data: &str, keys: &[String]) -> Result<Self, Error> {
        // Matching the plugin server, each key is 32 btyes of utf8 data, which we
        // then, treating as raw bytes, b64 encode before passing into fernet. I'm
        // a little thrown off by this - seems like keys could just be the already
        // encoded strings, but :shrug:, this is how it's done there, so it's how
        // I'll do it here
        let fernets: Vec<_> = keys
            .iter()
            .map(|k| k.as_bytes())
            .map(|b| BASE64_URL_SAFE.encode(b))
            .filter_map(|k| fernet::Fernet::new(&k))
            .collect();
        let fernet = MultiFernet::new(fernets);
        let decrypted = fernet.decrypt(data)?;
        let secrets = serde_json::from_slice(&decrypted)?;
        Ok(Self { secrets })
    }

    pub fn encrypt(&self, keys: &[String]) -> Result<String, Error> {
        let fernet = MultiFernet::new(keys.iter().filter_map(|k| fernet::Fernet::new(k)).collect());
        let serialized = serde_json::to_vec(&self.secrets)?;
        let encrypted = fernet.encrypt(&serialized);
        Ok(encrypted)
    }

    fn get_str(&self, key: &str, what: &str) -> Result<&str, Error> {
        self.secrets
            .get(key)
            .ok_or(Error::msg(format!("Missing {what} as secret {key}")))?
            .as_str()
            .ok_or(Error::msg(format!("{what} secret {key} is not a string")))
    }
}

impl SourceConfig {
    pub async fn construct(
        &self,
        secrets: &JobSecrets,
        context: Arc<AppContext>,
        is_restarting: bool,
    ) -> Result<Box<dyn DataSource>, Error> {
        let staging_dir = context.config.staging_dir();
        let staging_max_bytes = context.config.staging_dir_max_bytes;
        match self {
            SourceConfig::Folder(config) => Ok(Box::new(config.create_source().await?)),
            SourceConfig::UrlList(config) => Ok(Box::new(
                // We skip validating the URL list if we're restarting, as fully-downloaded files
                // may have been deleted, for example.
                config.create_source(secrets, !is_restarting).await?,
            )),
            SourceConfig::S3(config) => Ok(Box::new(config.create_source(secrets).await?)),
            SourceConfig::S3Gzip(config) => Ok(Box::new(
                config
                    .create_gzip_source(secrets, staging_dir, staging_max_bytes)
                    .await?,
            )),
            SourceConfig::DateRangeExport(config) => Ok(Box::new(
                config
                    .create_source(secrets, staging_dir, staging_max_bytes)
                    .await?,
            )),
        }
    }
}

impl SinkConfig {
    pub async fn construct(
        &self,
        context: Arc<AppContext>,
        model: &JobModel,
    ) -> Result<Box<dyn Emitter>, Error> {
        match self {
            SinkConfig::Stdout { as_json } => Ok(Box::new(StdoutEmitter { as_json: *as_json })),
            SinkConfig::NoOp => Ok(Box::new(NoOpEmitter {})),
            SinkConfig::File {
                path,
                as_json,
                cleanup,
            } => Ok(Box::new(
                FileEmitter::new(path.clone(), *as_json, *cleanup).await?,
            )),
            SinkConfig::Kafka(kafka_emitter_config) => {
                // resolve logical topic to env var configured topic
                let actual_topic = context
                    .config
                    .resolve_kafka_topic(&kafka_emitter_config.topic)?;
                let resolved_config = KafkaEmitterConfig {
                    topic: actual_topic,
                    send_rate: kafka_emitter_config.send_rate,
                    transaction_timeout_seconds: kafka_emitter_config.transaction_timeout_seconds,
                };
                Ok(Box::new(
                    // We use the job id as the kafka transactional id, since it's persistent across
                    // e.g. restarts and worker-job-passing, but still allows multiple jobs/workers to
                    // emit to kafka at the same time.
                    KafkaEmitter::new(resolved_config, &model.id.to_string(), context).await?,
                ))
            }
            SinkConfig::Capture(capture_config) => {
                let token = context.get_token_for_team_id(model.team_id).await?;
                let options = posthog_rs::ClientOptionsBuilder::default()
                    .api_key(token)
                    .host(&context.config.capture_url)
                    .request_timeout_seconds(30u64)
                    .max_capture_attempts(6u32)
                    .retry_initial_backoff_ms(1000u64)
                    .retry_max_backoff_ms(30000u64)
                    .build()
                    .map_err(|e| {
                        Error::msg(format!("Failed to build capture client options: {e}"))
                    })?;
                let client = posthog_rs::client(options).await;
                Ok(Box::new(CaptureEmitter::new(
                    client,
                    capture_config.send_rate,
                )))
            }
        }
    }
}

impl FolderSourceConfig {
    pub async fn create_source(&self) -> Result<FolderSource, Error> {
        FolderSource::new(self.path.clone()).await
    }
}

impl UrlListConfig {
    pub async fn create_source(
        &self,
        secrets: &JobSecrets,
        validate_urls: bool,
    ) -> Result<UrlList, Error> {
        let urls = secrets
            .secrets
            .get(&self.urls_key)
            .ok_or(Error::msg(format!("Missing urls as key {}", self.urls_key)))?;

        let urls: Vec<String> = serde_json::from_value(urls.clone())?;

        UrlList::new(
            urls,
            self.allow_internal_ips,
            Duration::from_secs(self.timeout_seconds),
            self.retries,
            validate_urls,
        )
        .await
    }

    fn default_timeout_seconds() -> u64 {
        30
    }

    fn default_retries() -> usize {
        3
    }
}

impl S3SourceConfig {
    /// Reject endpoint URLs that point to private/internal IPs.
    /// Catches literal IP addresses that would bypass DNS-level SSRF protection.
    fn validate_endpoint_url(url: &str, allow_internal_ips: bool) -> Result<(), Error> {
        if allow_internal_ips {
            return Ok(());
        }

        let parsed = url::Url::parse(url)
            .map_err(|e| Error::msg(format!("Invalid endpoint URL '{}': {}", url, e)))?;

        let host = parsed
            .host()
            .ok_or_else(|| Error::msg(format!("Endpoint URL '{}' has no host", url)))?;

        let ip = match host {
            url::Host::Ipv4(v4) => Some(IpAddr::V4(v4)),
            url::Host::Ipv6(v6) => Some(IpAddr::V6(v6)),
            url::Host::Domain(_) => None,
        };

        if let Some(ip) = ip {
            if !common_dns::is_global_ip(&ip) {
                return Err(Error::msg(format!(
                    "Endpoint URL '{}' resolves to non-public IP address",
                    url
                )));
            }
        }

        Ok(())
    }

    /// The single validated auth method resolved from the config's optional field pairs.
    fn auth(&self) -> Result<S3Auth<'_>, Error> {
        let has_key_fields =
            self.access_key_id_key.is_some() || self.secret_access_key_key.is_some();

        match (&self.role_arn, has_key_fields) {
            (Some(_), true) => Err(Error::msg(
                "S3 source config sets both role_arn and access keys, but exactly one auth method is required",
            )),
            (Some(role_arn), false) => {
                let external_id = self
                    .external_id
                    .as_deref()
                    .ok_or(Error::msg("Missing external_id in role-auth source config"))?;
                Ok(S3Auth::Role {
                    role_arn,
                    external_id,
                })
            }
            (None, true) => {
                if self.external_id.is_some() {
                    return Err(Error::msg(
                        "S3 source config sets external_id, which is only valid with role_arn",
                    ));
                }
                let access_key_id_key = self
                    .access_key_id_key
                    .as_deref()
                    .ok_or(Error::msg("Missing access_key_id_key in source config"))?;
                let secret_access_key_key = self
                    .secret_access_key_key
                    .as_deref()
                    .ok_or(Error::msg("Missing secret_access_key_key in source config"))?;
                Ok(S3Auth::Keys {
                    access_key_id_key,
                    secret_access_key_key,
                })
            }
            (None, false) => Err(Error::from(UserError::new(
                "S3 source has no authentication configured. Provide an IAM role or access keys",
            ))),
        }
    }

    fn static_key_credentials(
        secrets: &JobSecrets,
        access_key_id_key: &str,
        secret_access_key_key: &str,
    ) -> Result<aws_sdk_s3::config::Credentials, Error> {
        let access_key_id = secrets.get_str(access_key_id_key, "access key id")?;
        let secret_access_key = secrets.get_str(secret_access_key_key, "secret access key")?;

        Ok(aws_sdk_s3::config::Credentials::new(
            access_key_id,
            secret_access_key,
            None,
            None,
            "job_config",
        ))
    }

    // Session policy pinning every assumed-role session to read-only access on the configured
    // bucket/prefix, regardless of how broad the customer's role permissions are.
    fn session_policy(&self) -> String {
        serde_json::json!({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket"],
                    "Resource": format!("arn:aws:s3:::{}", self.bucket),
                    // ListBucket is bucket-level, so the prefix restriction has to be a
                    // condition on the request's prefix parameter, not part of the resource.
                    "Condition": {
                        "StringLike": {
                            "s3:prefix": [format!("{}*", self.prefix)],
                        },
                    },
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject"],
                    "Resource": format!("arn:aws:s3:::{}/{}*", self.bucket, self.prefix),
                },
            ],
        })
        .to_string()
    }

    async fn assume_role_credentials(
        &self,
        role_arn: &str,
        external_id: &str,
    ) -> Result<aws_config::sts::AssumeRoleProvider, Error> {
        if self.endpoint_url.is_some() {
            return Err(Error::from(UserError::new(
                "IAM role authentication only works with AWS S3. S3-compatible stores must use access keys",
            )));
        }

        let provider = aws_config::sts::AssumeRoleProvider::builder(role_arn)
            .session_name("posthog-batch-import")
            .external_id(external_id)
            .region(Region::new(self.region.clone()))
            .session_length(Duration::from_secs(3600))
            .policy(self.session_policy())
            .build()
            .await;

        // Fail fast so a misconfigured trust policy pauses the job with an actionable
        // message instead of surfacing as an opaque S3 error mid-import.
        provider.provide_credentials().await.user_error(format!(
            "PostHog could not assume IAM role {role_arn}. Verify the role exists, its trust \
             policy allows PostHog's import role, and the External ID matches the one shown in \
             the migration setup."
        ))?;

        Ok(provider)
    }

    async fn build_s3_config(
        &self,
        secrets: &JobSecrets,
    ) -> Result<aws_sdk_s3::config::Builder, Error> {
        let mut builder = aws_sdk_s3::config::Builder::new()
            .region(Region::new(self.region.clone()))
            .behavior_version(BehaviorVersion::latest())
            // S3-compatible stores (GCS) return whole-object checksums on ranged GETs, which the
            // SDK then validates against the partial body and fails. Only validate when requested.
            .response_checksum_validation(
                aws_sdk_s3::config::ResponseChecksumValidation::WhenRequired,
            )
            .timeout_config(
                TimeoutConfig::builder()
                    .operation_timeout(Duration::from_secs(30))
                    .build(),
            )
            .retry_config(RetryConfig::standard());

        builder = match self.auth()? {
            S3Auth::Role {
                role_arn,
                external_id,
            } => builder
                .credentials_provider(self.assume_role_credentials(role_arn, external_id).await?),
            S3Auth::Keys {
                access_key_id_key,
                secret_access_key_key,
            } => builder.credentials_provider(Self::static_key_credentials(
                secrets,
                access_key_id_key,
                secret_access_key_key,
            )?),
        };

        if let Some(ref url) = self.endpoint_url {
            Self::validate_endpoint_url(url, self.allow_internal_ips)?;
            builder = builder.endpoint_url(url).force_path_style(true);

            if !self.allow_internal_ips {
                let http_client = aws_smithy_http_client::Builder::new()
                    .tls_provider(aws_smithy_http_client::tls::Provider::Rustls(
                        aws_smithy_http_client::tls::rustls_provider::CryptoMode::AwsLc,
                    ))
                    .build_with_resolver(common_dns::PublicIPv4SmithyResolver);
                builder = builder.http_client(http_client);
            }
        }

        Ok(builder)
    }

    async fn build_client(&self, secrets: &JobSecrets) -> Result<aws_sdk_s3::Client, Error> {
        let builder = self.build_s3_config(secrets).await?;
        Ok(aws_sdk_s3::Client::from_conf(builder.build()))
    }

    pub async fn create_source(&self, secrets: &JobSecrets) -> Result<S3Source, Error> {
        let client = self.build_client(secrets).await?;

        Ok(S3Source::new(
            client,
            self.bucket.clone(),
            self.prefix.clone(),
        ))
    }

    pub async fn create_gzip_source(
        &self,
        secrets: &JobSecrets,
        staging_dir: PathBuf,
        staging_max_bytes: u64,
    ) -> Result<GzipS3Source, Error> {
        let client = self.build_client(secrets).await?;

        Ok(GzipS3Source::new(
            client,
            self.bucket.clone(),
            self.prefix.clone(),
            ExtractorType::PlainGzip.create_extractor(),
            staging_dir,
            staging_max_bytes,
        ))
    }
}
impl DateRangeExportSourceConfig {
    pub async fn create_source(
        &self,
        secrets: &JobSecrets,
        staging_dir: PathBuf,
        staging_max_bytes: u64,
    ) -> Result<DateRangeExportSource, Error> {
        let auth_config = match &self.auth {
            AuthSourceConfig::None => AuthConfig::None,
            AuthSourceConfig::ApiKey {
                header_name,
                key_secret,
            } => AuthConfig::ApiKey {
                header_name: header_name.clone(),
                key: secrets.get_str(key_secret, "API key")?.to_string(),
            },
            AuthSourceConfig::BearerToken { token_secret } => AuthConfig::BearerToken {
                token: secrets.get_str(token_secret, "bearer token")?.to_string(),
            },
            AuthSourceConfig::BasicAuth {
                username_secret,
                password_secret,
            } => AuthConfig::BasicAuth {
                username: secrets.get_str(username_secret, "username")?.to_string(),
                password: secrets.get_str(password_secret, "password")?.to_string(),
            },
            AuthSourceConfig::MixpanelAuth { secret_key_secret } => AuthConfig::MixpanelAuth {
                secret_key: secrets
                    .get_str(secret_key_secret, "secret key")?
                    .to_string(),
            },
        };

        let extractor = self.extractor_type.create_extractor();

        DateRangeExportSource::builder(
            self.base_url.clone(),
            self.start,
            self.end,
            self.interval_duration,
            extractor,
            staging_dir,
        )
        .with_query_params(self.start_qp.clone(), self.end_qp.clone())
        .with_timeout(Duration::from_secs(self.timeout_seconds))
        .with_retries(self.retries)
        .with_auth(auth_config)
        .with_date_format(self.date_format.clone())
        .with_headers(self.headers.clone())
        .with_staging_max_bytes(staging_max_bytes)
        .build()
    }

    fn default_timeout_seconds() -> u64 {
        30
    }

    fn default_retries() -> usize {
        3
    }

    fn default_date_format() -> String {
        "%Y-%m-%d %H:%M:%S".to_string()
    }
}

impl JobConfig {
    fn default_import_events() -> bool {
        true
    }

    fn default_generate_identify_events() -> bool {
        false
    }

    fn default_generate_group_identify_events() -> bool {
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_job_config() -> JobConfig {
        JobConfig {
            source: SourceConfig::Folder(FolderSourceConfig {
                path: "/tmp/test".to_string(),
            }),
            data_format: crate::parse::format::FormatConfig::JsonLines {
                skip_blanks: false,
                content: crate::parse::content::ContentType::Captured,
            },
            sink: SinkConfig::NoOp,
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: false,
        }
    }

    #[test]
    fn test_job_config_defaults() {
        // Test that defaults are applied correctly when fields are missing
        let json_config = r#"
        {
            "source": {
                "type": "folder",
                "path": "/tmp/test"
            },
            "data_format": {
                "type": "json_lines",
                "skip_blanks": false,
                "content": {
                    "type": "captured"
                }
            },
            "sink": {
                "type": "noop"
            }
        }
        "#;

        let config: JobConfig = serde_json::from_str(json_config).unwrap();
        assert!(config.import_events); // Should use default
        assert!(!config.generate_identify_events); // Should use default
        assert!(!config.generate_group_identify_events); // Should use default
    }

    #[test]
    fn test_job_config_explicit_values() {
        // Test that explicit values override defaults
        let json_config = r#"
        {
            "source": {
                "type": "folder",
                "path": "/tmp/test"
            },
            "data_format": {
                "type": "json_lines",
                "skip_blanks": false,
                "content": {
                    "type": "captured"
                }
            },
            "sink": {
                "type": "noop"
            },
            "import_events": false,
            "generate_identify_events": true
        }
        "#;

        let config: JobConfig = serde_json::from_str(json_config).unwrap();
        assert!(!config.import_events); // Should use explicit value
        assert!(config.generate_identify_events); // Should use explicit value
    }

    #[test]
    fn test_job_config_serialization() {
        let config = create_test_job_config();

        // Test serialization
        let serialized = serde_json::to_string(&config).unwrap();
        let deserialized: JobConfig = serde_json::from_str(&serialized).unwrap();

        // Verify round-trip works correctly
        assert_eq!(config.import_events, deserialized.import_events);
        assert_eq!(
            config.generate_identify_events,
            deserialized.generate_identify_events
        );
        // Note: We can't directly compare source/sink due to missing PartialEq derives
        // But the import_events and generate_identify_events are what we're primarily testing
    }

    #[test]
    fn test_job_config_partial_serialization() {
        // Test that only the new fields are serialized when they differ from defaults
        let config = create_test_job_config();

        let serialized = serde_json::to_string(&config).unwrap();
        let json_value: serde_json::Value = serde_json::from_str(&serialized).unwrap();

        // Should contain both fields explicitly when they match defaults
        assert!(json_value.get("import_events").is_some());
        assert!(json_value.get("generate_identify_events").is_some());
    }

    #[test]
    fn test_job_config_default_functions() {
        // Test the default functions directly
        assert!(JobConfig::default_import_events());
        assert!(!JobConfig::default_generate_identify_events());
    }

    #[test]
    fn test_job_config_with_different_source_types() {
        // Test with different source configurations
        let folder_config = JobConfig {
            source: SourceConfig::Folder(FolderSourceConfig {
                path: "/tmp/folder".to_string(),
            }),
            data_format: crate::parse::format::FormatConfig::JsonLines {
                skip_blanks: false,
                content: crate::parse::content::ContentType::Captured,
            },
            sink: SinkConfig::NoOp,
            import_events: false,
            generate_identify_events: true,
            generate_group_identify_events: false,
        };

        // Test serialization works with different source types
        let serialized = serde_json::to_string(&folder_config).unwrap();
        let deserialized: JobConfig = serde_json::from_str(&serialized).unwrap();

        assert_eq!(folder_config.import_events, deserialized.import_events);
        assert_eq!(
            folder_config.generate_identify_events,
            deserialized.generate_identify_events
        );
        // Note: Can't compare source directly due to missing PartialEq
    }

    #[test]
    fn test_job_config_with_different_sink_types() {
        // Test with different sink configurations
        let stdout_config = JobConfig {
            source: SourceConfig::Folder(FolderSourceConfig {
                path: "/tmp/test".to_string(),
            }),
            data_format: crate::parse::format::FormatConfig::JsonLines {
                skip_blanks: false,
                content: crate::parse::content::ContentType::Captured,
            },
            sink: SinkConfig::Stdout { as_json: true },
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: false,
        };

        let serialized = serde_json::to_string(&stdout_config).unwrap();
        let deserialized: JobConfig = serde_json::from_str(&serialized).unwrap();

        assert_eq!(stdout_config.import_events, deserialized.import_events);
        assert_eq!(
            stdout_config.generate_identify_events,
            deserialized.generate_identify_events
        );
        // Note: Can't compare sink directly due to missing PartialEq
    }

    #[test]
    fn test_job_config_edge_cases() {
        // Test edge cases for the new fields
        let test_cases = vec![(true, true), (true, false), (false, true), (false, false)];

        for (import_events, generate_identify_events) in test_cases {
            let config = JobConfig {
                source: SourceConfig::Folder(FolderSourceConfig {
                    path: "/tmp/test".to_string(),
                }),
                data_format: crate::parse::format::FormatConfig::JsonLines {
                    skip_blanks: false,
                    content: crate::parse::content::ContentType::Captured,
                },
                sink: SinkConfig::NoOp,
                import_events,
                generate_identify_events,
                generate_group_identify_events: false,
            };

            // Test serialization/deserialization
            let serialized = serde_json::to_string(&config).unwrap();
            let deserialized: JobConfig = serde_json::from_str(&serialized).unwrap();

            assert_eq!(config.import_events, deserialized.import_events);
            assert_eq!(
                config.generate_identify_events,
                deserialized.generate_identify_events
            );
            // Note: Can't compare full config due to missing PartialEq derives
        }
    }

    #[test]
    fn test_job_secrets_serialization() {
        // Test JobSecrets serialization
        let mut secrets = HashMap::new();
        secrets.insert(
            "api_key".to_string(),
            Value::String("secret123".to_string()),
        );
        secrets.insert("token".to_string(), Value::String("token456".to_string()));

        let job_secrets = JobSecrets {
            secrets: secrets.clone(),
        };

        let serialized = serde_json::to_string(&job_secrets).unwrap();
        let deserialized: JobSecrets = serde_json::from_str(&serialized).unwrap();

        assert_eq!(job_secrets.secrets, deserialized.secrets);
    }

    #[test]
    fn test_source_config_serialization() {
        // Test SourceConfig serialization with different variants
        let folder_config = SourceConfig::Folder(FolderSourceConfig {
            path: "/tmp/test".to_string(),
        });

        let serialized = serde_json::to_string(&folder_config).unwrap();
        let deserialized: SourceConfig = serde_json::from_str(&serialized).unwrap();

        // Note: Can't use assert_eq! due to missing PartialEq derive
        // But serde round-trip should work correctly
        match (&folder_config, &deserialized) {
            (SourceConfig::Folder(orig), SourceConfig::Folder(deser)) => {
                assert_eq!(orig.path, deser.path)
            }
            _ => panic!("SourceConfig variants don't match"),
        }
    }

    #[test]
    fn test_s3_source_config_allow_internal_ips_defaults_false() {
        let json = r#"{
            "access_key_id_key": "ak",
            "secret_access_key_key": "sk",
            "bucket": "b",
            "prefix": "p",
            "region": "us-east-1"
        }"#;
        let config: S3SourceConfig = serde_json::from_str(json).unwrap();
        assert!(!config.allow_internal_ips);
    }

    #[test]
    fn test_s3_source_config_allow_internal_ips_explicit_true() {
        let json = r#"{
            "access_key_id_key": "ak",
            "secret_access_key_key": "sk",
            "bucket": "b",
            "prefix": "p",
            "region": "us-east-1",
            "allow_internal_ips": true
        }"#;
        let config: S3SourceConfig = serde_json::from_str(json).unwrap();
        assert!(config.allow_internal_ips);
    }

    #[test]
    fn test_s3_source_config_legacy_key_auth_deserializes() {
        let json = r#"{
            "access_key_id_key": "ak",
            "secret_access_key_key": "sk",
            "bucket": "b",
            "prefix": "p",
            "region": "us-east-1"
        }"#;
        let config: S3SourceConfig = serde_json::from_str(json).unwrap();
        assert_eq!(config.access_key_id_key.as_deref(), Some("ak"));
        assert_eq!(config.secret_access_key_key.as_deref(), Some("sk"));
        assert!(config.role_arn.is_none());
        assert!(config.external_id.is_none());
    }

    #[test]
    fn test_s3_source_config_role_auth_deserializes() {
        let json = r#"{
            "bucket": "b",
            "prefix": "p",
            "region": "us-east-1",
            "role_arn": "arn:aws:iam::123456789012:role/posthog-import",
            "external_id": "posthog-us-some-team-uuid"
        }"#;
        let config: S3SourceConfig = serde_json::from_str(json).unwrap();
        assert_eq!(
            config.role_arn.as_deref(),
            Some("arn:aws:iam::123456789012:role/posthog-import")
        );
        assert_eq!(
            config.external_id.as_deref(),
            Some("posthog-us-some-team-uuid")
        );
        assert!(config.access_key_id_key.is_none());
        assert!(config.secret_access_key_key.is_none());
    }

    fn role_auth_config(json_patch: Value) -> S3SourceConfig {
        let mut base = serde_json::json!({
            "bucket": "b",
            "prefix": "p",
            "region": "us-east-1",
            "role_arn": "arn:aws:iam::123456789012:role/posthog-import",
            "external_id": "posthog-us-some-team-uuid"
        });
        base.as_object_mut()
            .unwrap()
            .extend(json_patch.as_object().unwrap().clone());
        serde_json::from_value(base).unwrap()
    }

    fn empty_secrets() -> JobSecrets {
        JobSecrets {
            secrets: HashMap::new(),
        }
    }

    // These rejection paths all error before any credentials provider is built, so no
    // network access happens.
    #[tokio::test]
    async fn test_build_s3_config_rejects_role_with_endpoint_url() {
        let config = role_auth_config(
            serde_json::json!({"endpoint_url": "https://acct123.r2.cloudflarestorage.com"}),
        );
        let err = config
            .build_s3_config(&empty_secrets())
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("IAM role authentication only works with AWS S3"));
    }

    #[tokio::test]
    async fn test_build_s3_config_rejects_role_without_external_id() {
        let mut config = role_auth_config(serde_json::json!({}));
        config.external_id = None;
        let err = config
            .build_s3_config(&empty_secrets())
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("external_id"));
    }

    #[tokio::test]
    async fn test_build_s3_config_accepts_legacy_key_auth() {
        let json = r#"{
            "access_key_id_key": "ak",
            "secret_access_key_key": "sk",
            "bucket": "b",
            "prefix": "p",
            "region": "us-east-1"
        }"#;
        let config: S3SourceConfig = serde_json::from_str(json).unwrap();
        let mut secrets = HashMap::new();
        secrets.insert("ak".to_string(), Value::String("key-id".to_string()));
        secrets.insert("sk".to_string(), Value::String("key-secret".to_string()));
        let secrets = JobSecrets { secrets };
        assert!(config.build_s3_config(&secrets).await.is_ok());
    }

    #[tokio::test]
    async fn test_build_s3_config_errors_when_key_secret_missing() {
        let json = r#"{
            "access_key_id_key": "ak",
            "secret_access_key_key": "sk",
            "bucket": "b",
            "prefix": "p",
            "region": "us-east-1"
        }"#;
        let config: S3SourceConfig = serde_json::from_str(json).unwrap();
        let err = config
            .build_s3_config(&empty_secrets())
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("Missing access key id as secret ak"));
    }

    #[tokio::test]
    async fn test_build_s3_config_rejects_mixed_auth_methods() {
        let cases = [
            // Full key pair alongside role_arn.
            serde_json::json!({"access_key_id_key": "ak", "secret_access_key_key": "sk"}),
            // A partial key pair must not silently win the role path either.
            serde_json::json!({"access_key_id_key": "ak"}),
            serde_json::json!({"secret_access_key_key": "sk"}),
        ];
        for patch in cases {
            let config = role_auth_config(patch.clone());
            let err = config
                .build_s3_config(&empty_secrets())
                .await
                .unwrap_err()
                .to_string();
            assert!(
                err.contains("exactly one auth method"),
                "patch {patch}: unexpected error {err}"
            );
        }
    }

    #[tokio::test]
    async fn test_build_s3_config_rejects_external_id_with_key_auth() {
        let json = r#"{
            "access_key_id_key": "ak",
            "secret_access_key_key": "sk",
            "bucket": "b",
            "prefix": "p",
            "region": "us-east-1",
            "external_id": "posthog-us-some-team-uuid"
        }"#;
        let config: S3SourceConfig = serde_json::from_str(json).unwrap();
        let err = config
            .build_s3_config(&empty_secrets())
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("only valid with role_arn"));
    }

    #[tokio::test]
    async fn test_build_s3_config_rejects_missing_auth() {
        let json = r#"{"bucket": "b", "prefix": "p", "region": "us-east-1"}"#;
        let config: S3SourceConfig = serde_json::from_str(json).unwrap();
        let err = config
            .build_s3_config(&empty_secrets())
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("no authentication configured"));
    }

    #[test]
    fn test_session_policy_scopes_to_bucket_and_prefix() {
        let config = role_auth_config(serde_json::json!({}));
        let policy: Value = serde_json::from_str(&config.session_policy()).unwrap();
        let statements = policy["Statement"].as_array().unwrap();
        assert_eq!(statements[0]["Resource"], "arn:aws:s3:::b");
        assert_eq!(
            statements[0]["Condition"]["StringLike"]["s3:prefix"],
            serde_json::json!(["p*"])
        );
        assert_eq!(statements[1]["Resource"], "arn:aws:s3:::b/p*");
    }

    #[test]
    fn test_validate_endpoint_url_rejects_metadata_service() {
        let result = S3SourceConfig::validate_endpoint_url("http://169.254.169.254", false);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("non-public IP address"));
    }

    #[test]
    fn test_validate_endpoint_url_rejects_private_ip() {
        let result = S3SourceConfig::validate_endpoint_url("http://10.0.0.1:9000", false);
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_endpoint_url_rejects_loopback() {
        let result = S3SourceConfig::validate_endpoint_url("http://127.0.0.1:9000", false);
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_endpoint_url_rejects_ipv6_loopback() {
        let result = S3SourceConfig::validate_endpoint_url("http://[::1]:9000", false);
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_endpoint_url_accepts_public_hostname() {
        let result = S3SourceConfig::validate_endpoint_url(
            "https://acct123.r2.cloudflarestorage.com",
            false,
        );
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_endpoint_url_accepts_internal_when_allowed() {
        let result = S3SourceConfig::validate_endpoint_url("http://localhost:9000", true);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_endpoint_url_rejects_invalid_url() {
        let result = S3SourceConfig::validate_endpoint_url("not-a-url", false);
        assert!(result.is_err());
    }

    #[test]
    fn test_sink_config_serialization() {
        // Test SinkConfig serialization with different variants
        let test_cases = vec![
            SinkConfig::NoOp,
            SinkConfig::Stdout { as_json: true },
            SinkConfig::Stdout { as_json: false },
            SinkConfig::File {
                path: "/tmp/output.json".to_string(),
                as_json: true,
                cleanup: false,
            },
        ];

        for sink_config in test_cases {
            let serialized = serde_json::to_string(&sink_config).unwrap();
            let deserialized: SinkConfig = serde_json::from_str(&serialized).unwrap();
            // Note: Can't use assert_eq! due to missing PartialEq derive
            // But serde round-trip should work correctly for all variants
            match (&sink_config, &deserialized) {
                (SinkConfig::NoOp, SinkConfig::NoOp) => (),
                (SinkConfig::Stdout { as_json: orig }, SinkConfig::Stdout { as_json: deser }) => {
                    assert_eq!(orig, deser)
                }
                (
                    SinkConfig::File {
                        path: orig_path,
                        as_json: orig_json,
                        cleanup: orig_cleanup,
                    },
                    SinkConfig::File {
                        path: deser_path,
                        as_json: deser_json,
                        cleanup: deser_cleanup,
                    },
                ) => {
                    assert_eq!(orig_path, deser_path);
                    assert_eq!(orig_json, deser_json);
                    assert_eq!(orig_cleanup, deser_cleanup);
                }
                _ => panic!("SinkConfig variants don't match"),
            }
        }
    }

    // ---- ENCRYPTION_KEYS multi-key / two-step rotation ----
    // The batch-import-worker shares the key material that Django/Node expose as ENCRYPTION_SALT_KEYS
    // (here it's the ENCRYPTION_KEYS env var). It only decrypts BatchImport.secrets. These tests mirror
    // the Python/Node coverage so all three implementations are verified against the same contract:
    // the first key encrypts, every key is tried for decryption.

    fn old_key() -> String {
        "o".repeat(32)
    }

    fn new_key() -> String {
        "n".repeat(32)
    }

    fn sample_secrets() -> JobSecrets {
        let mut secrets = HashMap::new();
        secrets.insert(
            "api_key".to_string(),
            Value::String("super-secret-value".to_string()),
        );
        JobSecrets { secrets }
    }

    // Simulate a writer app (Django/Node) running with the given key list: the first key encrypts, and
    // each raw 32-byte key is base64-urlsafe-encoded before Fernet — matching JobSecrets::decrypt.
    fn encrypt_with(key_list: &[String], secrets: &JobSecrets) -> String {
        let fernets: Vec<_> = key_list
            .iter()
            .map(|k| BASE64_URL_SAFE.encode(k.as_bytes()))
            .filter_map(|k| fernet::Fernet::new(&k))
            .collect();
        let serialized = serde_json::to_vec(&secrets.secrets).unwrap();
        MultiFernet::new(fernets).encrypt(&serialized)
    }

    #[test]
    fn test_decrypt_tries_every_key_in_the_list() {
        let secrets = sample_secrets();
        let token = encrypt_with(&[new_key()], &secrets);

        for reader in [vec![new_key(), old_key()], vec![old_key(), new_key()]] {
            let decrypted = JobSecrets::decrypt(&token, &reader).unwrap();
            assert_eq!(decrypted.secrets, secrets.secrets);
        }
    }

    #[test]
    fn test_two_step_rotation_coexisting_apps_decrypt_each_others_writes() {
        // step 1: [old] -> [old, new]      new added for decryption; old still encrypts
        // step 2: [old, new] -> [new, old] new now encrypts; old kept for decryption
        let secrets = sample_secrets();
        let steps = [
            ("step 1", vec![vec![old_key()], vec![old_key(), new_key()]]),
            (
                "step 2",
                vec![vec![old_key(), new_key()], vec![new_key(), old_key()]],
            ),
        ];

        for (name, coexisting) in steps {
            for writer in &coexisting {
                let token = encrypt_with(writer, &secrets);
                for reader in &coexisting {
                    let decrypted = JobSecrets::decrypt(&token, reader).unwrap_or_else(|e| {
                        panic!("{name}: reader {reader:?} could not decrypt writer {writer:?}: {e}")
                    });
                    assert_eq!(decrypted.secrets, secrets.secrets);
                }
            }
        }
    }

    #[test]
    fn test_step_1_apps_always_encrypt_with_the_old_key() {
        // While [old] and [old, new] apps coexist, old is always first, so no app emits new-encrypted
        // data that an un-upgraded [old]-only app could not read.
        let secrets = sample_secrets();

        for writer in [vec![old_key()], vec![old_key(), new_key()]] {
            let token = encrypt_with(&writer, &secrets);
            assert!(JobSecrets::decrypt(&token, &[old_key()]).is_ok());
            assert!(JobSecrets::decrypt(&token, &[new_key()]).is_err());
        }
    }

    #[test]
    fn test_skipping_step_1_breaks_un_upgraded_worker() {
        // A writer that jumped straight to [new, old] encrypts with new; a worker still on [old] cannot read it.
        let secrets = sample_secrets();
        let token = encrypt_with(&[new_key(), old_key()], &secrets);

        assert!(JobSecrets::decrypt(&token, &[old_key()]).is_err());
    }
}
