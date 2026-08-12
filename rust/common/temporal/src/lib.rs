//! Shared client for starting PostHog Python workflows from Rust services.
//!
//! Temporal payload encryption is application-defined rather than provided by
//! the SDK. This crate emits the same Fernet-wrapped `binary/encrypted` payloads
//! as `posthog.temporal.common.codec.EncryptionCodec`.

use std::collections::HashMap;
use std::time::Duration;

use base64::{engine::general_purpose, Engine};
use fernet::Fernet;
use prost14::Message;
use serde::Serialize;
use temporalio_client::grpc::WorkflowService;
use temporalio_client::tonic::{Code, IntoRequest};
use temporalio_client::{
    Client, ClientOptions, ClientTlsOptions, Connection, ConnectionOptions, TlsOptions,
};
use temporalio_common::protos::temporal::api::common::v1::{Payload, Payloads, WorkflowType};
use temporalio_common::protos::temporal::api::enums::v1::TaskQueueKind;
pub use temporalio_common::protos::temporal::api::enums::v1::{
    WorkflowIdConflictPolicy, WorkflowIdReusePolicy,
};
use temporalio_common::protos::temporal::api::taskqueue::v1::TaskQueue;
use temporalio_common::protos::temporal::api::workflowservice::v1::StartWorkflowExecutionRequest;
use thiserror::Error;

/// Connection and encryption settings for a PostHog Temporal namespace.
#[derive(Clone, Debug)]
pub struct TemporalClientConfig {
    pub host: String,
    pub port: u16,
    pub namespace: String,
    pub client_cert: String,
    pub client_key: String,
    pub server_root_ca_cert: Option<String>,
    pub payload_encryption_key: String,
    pub identity: String,
}

/// Options that identify and route one workflow execution.
#[derive(Clone, Debug)]
pub struct StartWorkflowOptions {
    pub workflow_name: String,
    pub task_queue: String,
    pub workflow_id: String,
    pub request_id: String,
    pub id_reuse_policy: WorkflowIdReusePolicy,
    pub id_conflict_policy: WorkflowIdConflictPolicy,
    pub execution_timeout: Option<Duration>,
    pub run_timeout: Option<Duration>,
    pub task_timeout: Option<Duration>,
}

impl StartWorkflowOptions {
    /// Build options for an idempotent start. Active executions are reused and
    /// only failed closed executions may reuse the workflow ID.
    pub fn idempotent(
        workflow_name: impl Into<String>,
        task_queue: impl Into<String>,
        workflow_id: impl Into<String>,
        request_id: impl Into<String>,
    ) -> Self {
        Self {
            workflow_name: workflow_name.into(),
            task_queue: task_queue.into(),
            workflow_id: workflow_id.into(),
            request_id: request_id.into(),
            id_reuse_policy: WorkflowIdReusePolicy::AllowDuplicateFailedOnly,
            id_conflict_policy: WorkflowIdConflictPolicy::UseExisting,
            execution_timeout: None,
            run_timeout: None,
            task_timeout: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StartWorkflowOutcome {
    Started { run_id: String },
    Existing { run_id: Option<String> },
}

#[derive(Debug, Error)]
pub enum TemporalClientError {
    #[error("missing Temporal client configuration: {0}")]
    MissingConfig(&'static str),
    #[error("invalid Temporal target: {0}")]
    InvalidTarget(#[from] url::ParseError),
    #[error("invalid Temporal payload encryption key: {0}")]
    InvalidEncryptionKey(String),
    #[error("failed to connect to Temporal: {0}")]
    Connect(#[from] temporalio_client::errors::ClientConnectError),
    #[error("failed to create Temporal client: {0}")]
    CreateClient(#[from] temporalio_client::errors::ClientNewError),
    #[error("failed to serialize workflow input: {0}")]
    Serialize(#[from] serde_json::Error),
    #[error("invalid workflow start options: {0}")]
    InvalidStartOptions(&'static str),
    #[error("failed to start workflow: {0}")]
    Start(temporalio_client::tonic::Status),
}

/// A cheap-to-clone, namespace-bound Temporal client that serializes Rust
/// inputs for Python workflows and encrypts them with PostHog's payload codec.
#[derive(Clone)]
pub struct TemporalWorkflowClient {
    client: Client,
    identity: String,
    encryption_key: Fernet,
}

impl TemporalWorkflowClient {
    pub async fn connect(config: TemporalClientConfig) -> Result<Self, TemporalClientError> {
        require_config("TEMPORAL_HOST", &config.host)?;
        require_config("TEMPORAL_NAMESPACE", &config.namespace)?;
        require_config("TEMPORAL_CLIENT_CERT", &config.client_cert)?;
        require_config("TEMPORAL_CLIENT_KEY", &config.client_key)?;
        require_config("TEMPORAL_SECRET_KEY", &config.payload_encryption_key)?;
        require_config("identity", &config.identity)?;

        let target = url::Url::parse(&format!("https://{}:{}", config.host, config.port))?;
        let tls_options = TlsOptions {
            server_root_ca_cert: config
                .server_root_ca_cert
                .as_ref()
                .filter(|value| !value.is_empty())
                .map(|value| value.as_bytes().to_vec()),
            domain: Some(config.host.clone()),
            client_tls_options: Some(ClientTlsOptions {
                client_cert: config.client_cert.as_bytes().to_vec(),
                client_private_key: config.client_key.as_bytes().to_vec(),
            }),
            server_cert_verifier: None,
        };
        let connection_options = ConnectionOptions::new(target)
            .identity(config.identity.clone())
            .tls_options(tls_options)
            .build();
        let connection = Connection::connect(connection_options).await?;
        let client = Client::new(connection, ClientOptions::new(config.namespace).build())?;

        Ok(Self {
            client,
            identity: config.identity,
            encryption_key: temporal_encryption_key(&config.payload_encryption_key)?,
        })
    }

    /// Start a workflow using Temporal's stable request and workflow ID
    /// deduplication. `AlreadyExists` is returned as a successful outcome.
    pub async fn start_workflow<T: Serialize>(
        &self,
        input: &T,
        options: &StartWorkflowOptions,
    ) -> Result<StartWorkflowOutcome, TemporalClientError> {
        validate_start_options(options)?;
        let request = build_start_request(
            input,
            &self.client.options().namespace,
            &self.identity,
            options,
            &self.encryption_key,
        )?;

        match self
            .client
            .clone()
            .start_workflow_execution(request.into_request())
            .await
        {
            Ok(response) => {
                let response = response.into_inner();
                if response.started {
                    Ok(StartWorkflowOutcome::Started {
                        run_id: response.run_id,
                    })
                } else {
                    Ok(StartWorkflowOutcome::Existing {
                        run_id: Some(response.run_id),
                    })
                }
            }
            Err(status) if status.code() == Code::AlreadyExists => {
                Ok(StartWorkflowOutcome::Existing { run_id: None })
            }
            Err(status) => Err(TemporalClientError::Start(status)),
        }
    }
}

fn build_start_request<T: Serialize>(
    input: &T,
    namespace: &str,
    identity: &str,
    options: &StartWorkflowOptions,
    encryption_key: &Fernet,
) -> Result<StartWorkflowExecutionRequest, TemporalClientError> {
    let payload = encrypted_json_payload(input, encryption_key)?;
    Ok(StartWorkflowExecutionRequest {
        namespace: namespace.to_string(),
        workflow_id: options.workflow_id.clone(),
        workflow_type: Some(WorkflowType {
            name: options.workflow_name.clone(),
        }),
        task_queue: Some(TaskQueue {
            name: options.task_queue.clone(),
            kind: TaskQueueKind::Unspecified as i32,
            normal_name: String::new(),
        }),
        input: Some(Payloads {
            payloads: vec![payload],
        }),
        request_id: options.request_id.clone(),
        workflow_id_reuse_policy: options.id_reuse_policy as i32,
        workflow_id_conflict_policy: options.id_conflict_policy as i32,
        workflow_execution_timeout: options
            .execution_timeout
            .and_then(|value| value.try_into().ok()),
        workflow_run_timeout: options.run_timeout.and_then(|value| value.try_into().ok()),
        workflow_task_timeout: options.task_timeout.and_then(|value| value.try_into().ok()),
        identity: identity.to_string(),
        ..Default::default()
    })
}

fn encrypted_json_payload<T: Serialize>(
    value: &T,
    key: &Fernet,
) -> Result<Payload, TemporalClientError> {
    let plain_payload = Payload {
        metadata: HashMap::from([("encoding".to_string(), b"json/plain".to_vec())]),
        data: serde_json::to_vec(value)?,
        ..Default::default()
    };
    let token = key.encrypt(&plain_payload.encode_to_vec());
    Ok(Payload {
        metadata: HashMap::from([("encoding".to_string(), b"binary/encrypted".to_vec())]),
        data: token.into_bytes(),
        ..Default::default()
    })
}

/// Mirrors `posthog.temporal.common.codec._load_as_bytes` and `_prepare_key`.
/// Legacy raw keys and truncation to 32 bytes are intentional compatibility
/// behavior: deriving a stricter key here would make Python workers unable to
/// decrypt Rust-produced payloads.
fn temporal_encryption_key(raw: &str) -> Result<Fernet, TemporalClientError> {
    let loaded = if let Some(value) = raw.strip_prefix("hex:") {
        hex::decode(value)
            .map_err(|error| TemporalClientError::InvalidEncryptionKey(error.to_string()))?
    } else if let Some(value) = raw.strip_prefix("base64-urlsafe:") {
        general_purpose::URL_SAFE
            .decode(value)
            .map_err(|error| TemporalClientError::InvalidEncryptionKey(error.to_string()))?
    } else if let Some(value) = raw.strip_prefix("base64:") {
        general_purpose::STANDARD
            .decode(value)
            .map_err(|error| TemporalClientError::InvalidEncryptionKey(error.to_string()))?
    } else {
        raw.as_bytes().to_vec()
    };
    if loaded.len() < 32 {
        return Err(TemporalClientError::InvalidEncryptionKey(format!(
            "expected at least 32 bytes, got {}",
            loaded.len()
        )));
    }

    let prepared = general_purpose::URL_SAFE.encode(&loaded[..32]);
    Fernet::new(&prepared).ok_or_else(|| {
        TemporalClientError::InvalidEncryptionKey("failed to prepare Fernet key".to_string())
    })
}

fn validate_start_options(options: &StartWorkflowOptions) -> Result<(), TemporalClientError> {
    if options.workflow_name.is_empty() {
        return Err(TemporalClientError::InvalidStartOptions(
            "workflow_name is empty",
        ));
    }
    if options.task_queue.is_empty() {
        return Err(TemporalClientError::InvalidStartOptions(
            "task_queue is empty",
        ));
    }
    if options.workflow_id.is_empty() {
        return Err(TemporalClientError::InvalidStartOptions(
            "workflow_id is empty",
        ));
    }
    if options.request_id.is_empty() {
        return Err(TemporalClientError::InvalidStartOptions(
            "request_id is empty",
        ));
    }
    Ok(())
}

fn require_config(name: &'static str, value: &str) -> Result<(), TemporalClientError> {
    if value.is_empty() {
        return Err(TemporalClientError::MissingConfig(name));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use prost14::Message;
    use serde::Serialize;

    use super::*;

    #[derive(Serialize)]
    struct TestInput<'a> {
        team_id: i32,
        name: &'a str,
    }

    fn options() -> StartWorkflowOptions {
        StartWorkflowOptions::idempotent(
            "python-workflow",
            "python-task-queue",
            "workflow-id",
            "request-id",
        )
    }

    #[test]
    fn builds_encrypted_python_workflow_request() {
        let key = temporal_encryption_key(&"a".repeat(32)).unwrap();
        let request = build_start_request(
            &TestInput {
                team_id: 42,
                name: "test",
            },
            "posthog.prod",
            "rust-service",
            &options(),
            &key,
        )
        .unwrap();

        assert_eq!(request.namespace, "posthog.prod");
        assert_eq!(request.workflow_id, "workflow-id");
        assert_eq!(request.request_id, "request-id");
        assert_eq!(request.workflow_type.unwrap().name, "python-workflow");
        assert_eq!(request.task_queue.unwrap().name, "python-task-queue");
        assert_eq!(
            request.workflow_id_reuse_policy,
            WorkflowIdReusePolicy::AllowDuplicateFailedOnly as i32
        );
        assert_eq!(
            request.workflow_id_conflict_policy,
            WorkflowIdConflictPolicy::UseExisting as i32
        );

        let payload = &request.input.unwrap().payloads[0];
        let token = std::str::from_utf8(&payload.data).unwrap();
        let inner = Payload::decode(key.decrypt(token).unwrap().as_slice()).unwrap();
        let value: serde_json::Value = serde_json::from_slice(&inner.data).unwrap();
        assert_eq!(payload.metadata["encoding"], b"binary/encrypted");
        assert_eq!(inner.metadata["encoding"], b"json/plain");
        assert_eq!(value["team_id"], 42);
        assert_eq!(value["name"], "test");
    }

    #[test]
    fn legacy_long_keys_match_python_truncation() {
        let long_key = temporal_encryption_key(&"a".repeat(40)).unwrap();
        let truncated_key = temporal_encryption_key(&"a".repeat(32)).unwrap();
        let token = long_key.encrypt(b"payload");

        assert_eq!(truncated_key.decrypt(&token).unwrap(), b"payload");
    }

    #[test]
    fn rejects_empty_idempotency_fields() {
        let mut options = options();
        options.request_id.clear();

        assert!(matches!(
            validate_start_options(&options),
            Err(TemporalClientError::InvalidStartOptions(
                "request_id is empty"
            ))
        ));
    }
}
