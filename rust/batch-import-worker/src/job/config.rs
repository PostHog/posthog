use std::{collections::HashMap, sync::Arc, time::Duration};

use anyhow::Error;
use aws_config::{retry::RetryConfig, timeout::TimeoutConfig, BehaviorVersion, Region};
use base64::{prelude::BASE64_URL_SAFE, Engine};
use fernet::MultiFernet;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    context::AppContext,
    emit::{kafka::KafkaEmitter, Emitter, FileEmitter, NoOpEmitter, StdoutEmitter},
    parse::format::FormatConfig,
    source::{folder::FolderSource, s3::S3Source, url_list::UrlList, DataSource},
};

use super::model::JobModel;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct JobConfig {
    pub source: SourceConfig,
    // What format is the data in, e.g. Mixpanel events stored in json-lines
    pub data_format: FormatConfig,
    pub sink: SinkConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum SourceConfig {
    Folder(FolderSourceConfig),
    UrlList(UrlListConfig),
    S3(S3SourceConfig),
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

#[derive(Debug, Clone)]
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
    ) -> Result<Box<dyn DataSource>, Error> {
        match self {
            SourceConfig::Folder(config) => Ok(Box::new(config.create_source().await?)),
            SourceConfig::UrlList(config) => Ok(Box::new(config.create_source(secrets).await?)),
            SourceConfig::S3(config) => Ok(Box::new(config.create_source(secrets).await?)),
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
            SinkConfig::Kafka(kafka_emitter_config) => Ok(Box::new(
                // We use the job id as the kafka transactional id, since it's persistent across
                // e.g. restarts and worker-job-passing, but still allows multiple jobs/workers to
                // emit to kafka at the same time.
                KafkaEmitter::new(kafka_emitter_config.clone(), &model.id.to_string(), context)
                    .await?,
            )),
        }
    }
}

impl FolderSourceConfig {
    pub async fn create_source(&self) -> Result<FolderSource, Error> {
        FolderSource::new(self.path.clone()).await
    }
}

impl UrlListConfig {
    pub async fn create_source(&self, secrets: &JobSecrets) -> Result<UrlList, Error> {
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
