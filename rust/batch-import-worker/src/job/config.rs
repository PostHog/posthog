use std::{collections::HashMap, sync::Arc, time::Duration};

use anyhow::Error;
use aws_config::{retry::RetryConfig, timeout::TimeoutConfig, BehaviorVersion, Region};
use base64::{prelude::BASE64_URL_SAFE, Engine};
use chrono::{DateTime, Utc};
use fernet::MultiFernet;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    context::AppContext,
    emit::{kafka::KafkaEmitter, Emitter, FileEmitter, NoOpEmitter, StdoutEmitter},
    extractor::ExtractorType,
    parse::format::FormatConfig,
    source::{
        date_range_export::{AuthConfig, DateRangeExportSource},
        folder::FolderSource,
        s3::S3Source,
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
    access_key_id_key: String,
    secret_access_key_key: String,
    bucket: String,
    prefix: String,
    region: String,
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
    NoOp,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KafkaEmitterConfig {
    pub topic: String,
    pub send_rate: u64,
    pub transaction_timeout_seconds: u64,
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
}

impl SourceConfig {
    pub async fn construct(
        &self,
        secrets: &JobSecrets,
        _context: Arc<AppContext>,
        is_restarting: bool,
    ) -> Result<Box<dyn DataSource>, Error> {
        match self {
            SourceConfig::Folder(config) => Ok(Box::new(config.create_source().await?)),
            SourceConfig::UrlList(config) => Ok(Box::new(
                // We skip validating the URL list if we're restarting, as fully-downloaded files
                // may have been deleted, for example.
                config.create_source(secrets, !is_restarting).await?,
            )),
            SourceConfig::S3(config) => Ok(Box::new(config.create_source(secrets).await?)),
            SourceConfig::DateRangeExport(config) => {
                Ok(Box::new(config.create_source(secrets).await?))
            }
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
    pub async fn create_source(&self, secrets: &JobSecrets) -> Result<S3Source, Error> {
        let access_key_id = secrets
            .secrets
            .get(&self.access_key_id_key)
            .ok_or(Error::msg(format!(
                "Missing access key id as key {}",
                self.access_key_id_key
            )))?
            .as_str()
            .ok_or(Error::msg(format!(
                "Access key id as key {} is not a string",
                self.access_key_id_key
            )))?;

        let secret_access_key = secrets
            .secrets
            .get(&self.secret_access_key_key)
            .ok_or(Error::msg(format!(
                "Missing secret access key as key {}",
                self.secret_access_key_key
            )))?
            .as_str()
            .ok_or(Error::msg(format!(
                "Secret access key as key {} is not a string",
                self.secret_access_key_key
            )))?;

        let aws_credentials = aws_sdk_s3::config::Credentials::new(
            access_key_id,
            secret_access_key,
            None,
            None,
            "job_config",
        );

        let aws_conf = aws_sdk_s3::config::Builder::new()
            .region(Region::new(self.region.clone()))
            .credentials_provider(aws_credentials)
            .behavior_version(BehaviorVersion::latest())
            .timeout_config(
                TimeoutConfig::builder()
                    .operation_timeout(Duration::from_secs(30))
                    .build(),
            )
            .retry_config(RetryConfig::standard())
            .build();
        let client = aws_sdk_s3::Client::from_conf(aws_conf);

        Ok(S3Source::new(
            client,
            self.bucket.clone(),
            self.prefix.clone(),
        ))
    }
}
impl DateRangeExportSourceConfig {
    pub async fn create_source(
        &self,
        secrets: &JobSecrets,
    ) -> Result<DateRangeExportSource, Error> {
        let auth_config = match &self.auth {
            AuthSourceConfig::None => AuthConfig::None,
            AuthSourceConfig::ApiKey {
                header_name,
                key_secret,
            } => {
                let key = secrets
                    .secrets
                    .get(key_secret)
                    .ok_or(Error::msg(format!(
                        "Missing API key as secret {key_secret}"
                    )))?
                    .as_str()
                    .ok_or(Error::msg(format!(
                        "API key secret {key_secret} is not a string"
                    )))?;
                AuthConfig::ApiKey {
                    header_name: header_name.clone(),
                    key: key.to_string(),
                }
            }
            AuthSourceConfig::BearerToken { token_secret } => {
                let token = secrets
                    .secrets
                    .get(token_secret)
                    .ok_or(Error::msg(format!(
                        "Missing bearer token as secret {token_secret}"
                    )))?
                    .as_str()
                    .ok_or(Error::msg(format!(
                        "Bearer token secret {token_secret} is not a string"
                    )))?;
                AuthConfig::BearerToken {
                    token: token.to_string(),
                }
            }
            AuthSourceConfig::BasicAuth {
                username_secret,
                password_secret,
            } => {
                let username = secrets
                    .secrets
                    .get(username_secret)
                    .ok_or(Error::msg(format!(
                        "Missing username as secret {username_secret}",
                    )))?
                    .as_str()
                    .ok_or(Error::msg(format!(
                        "Username secret {username_secret} is not a string",
                    )))?;
                let password = secrets
                    .secrets
                    .get(password_secret)
                    .ok_or(Error::msg(format!(
                        "Missing password as secret {password_secret}",
                    )))?
                    .as_str()
                    .ok_or(Error::msg(format!(
                        "Password secret {password_secret} is not a string",
                    )))?;
                AuthConfig::BasicAuth {
                    username: username.to_string(),
                    password: password.to_string(),
                }
            }
            AuthSourceConfig::MixpanelAuth { secret_key_secret } => {
                let secret_key = secrets
                    .secrets
                    .get(secret_key_secret)
                    .ok_or(Error::msg(format!(
                        "Missing secret key as secret {secret_key_secret}"
                    )))?
                    .as_str()
                    .ok_or(Error::msg(format!(
                        "Secret key secret {secret_key_secret} is not a string"
                    )))?;
                AuthConfig::MixpanelAuth {
                    secret_key: secret_key.to_string(),
                }
            }
        };

        let extractor = self.extractor_type.create_extractor();

        DateRangeExportSource::builder(
            self.base_url.clone(),
            self.start,
            self.end,
            self.interval_duration,
            extractor,
        )
        .with_query_params(self.start_qp.clone(), self.end_qp.clone())
        .with_timeout(Duration::from_secs(self.timeout_seconds))
        .with_retries(self.retries)
        .with_auth(auth_config)
        .with_date_format(self.date_format.clone())
        .with_headers(self.headers.clone())
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
}
