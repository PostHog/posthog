use std::collections::{HashMap, HashSet};

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
use temporalio_common::protos::temporal::api::enums::v1::{
    TaskQueueKind, WorkflowIdConflictPolicy, WorkflowIdReusePolicy,
};
use temporalio_common::protos::temporal::api::taskqueue::v1::TaskQueue;
use temporalio_common::protos::temporal::api::workflowservice::v1::StartWorkflowExecutionRequest;
use uuid::Uuid;

use crate::core::error::UnhandledError;
use crate::core::types::notification::{IssueCreated, IssueSnapshot};
use crate::modes::notifications::config::NotificationsConfig;

const WORKFLOW_NAME: &str = "error-tracking-issue-created";
const WORKFLOW_ID_PREFIX: &str = "error-tracking-issue-created";
const WORKFLOW_STARTS_TOTAL: &str = "cymbal_issue_created_workflow_starts_total";
const WORKFLOW_ROUTES_TOTAL: &str = "cymbal_issue_created_workflow_routes_total";

#[derive(Clone, Default)]
pub struct MaybeIssueCreatedWorkflowStarter(Option<IssueCreatedWorkflowStarter>);

impl MaybeIssueCreatedWorkflowStarter {
    pub async fn from_config(config: &NotificationsConfig) -> Result<Self, UnhandledError> {
        if !config.issue_created_workflow_enabled {
            return Ok(Self::default());
        }

        Ok(Self(Some(
            IssueCreatedWorkflowStarter::from_config(config).await?,
        )))
    }

    pub async fn start_if_enabled(
        &self,
        notification: &IssueCreated,
    ) -> Result<bool, UnhandledError> {
        let Some(starter) = &self.0 else {
            metrics::counter!(WORKFLOW_ROUTES_TOTAL, "route" => "legacy").increment(1);
            return Ok(false);
        };
        if !starter.is_enabled_for_team(notification.meta.team_id) {
            metrics::counter!(WORKFLOW_ROUTES_TOTAL, "route" => "legacy").increment(1);
            return Ok(false);
        }

        starter.start(notification).await?;
        metrics::counter!(WORKFLOW_ROUTES_TOTAL, "route" => "temporal").increment(1);
        Ok(true)
    }
}

#[derive(Clone)]
struct IssueCreatedWorkflowStarter {
    client: Client,
    task_queue: String,
    enabled_team_ids: Option<HashSet<i32>>,
    encryption_key: Fernet,
}

impl IssueCreatedWorkflowStarter {
    async fn from_config(config: &NotificationsConfig) -> Result<Self, UnhandledError> {
        require_config("TEMPORAL_HOST", &config.temporal_host)?;
        require_config("TEMPORAL_NAMESPACE", &config.temporal_namespace)?;
        require_config("TEMPORAL_CLIENT_CERT", &config.temporal_client_cert)?;
        require_config("TEMPORAL_CLIENT_KEY", &config.temporal_client_key)?;
        require_config("TEMPORAL_SECRET_KEY", &config.temporal_secret_key)?;

        let target = reqwest::Url::parse(&format!(
            "https://{}:{}",
            config.temporal_host, config.temporal_port
        ))
        .map_err(|error| UnhandledError::Other(format!("invalid Temporal target: {error}")))?;
        let tls_options = TlsOptions {
            server_root_ca_cert: config
                .temporal_client_root_ca
                .as_ref()
                .filter(|value| !value.is_empty())
                .map(|value| value.as_bytes().to_vec()),
            domain: Some(config.temporal_host.clone()),
            client_tls_options: Some(ClientTlsOptions {
                client_cert: config.temporal_client_cert.as_bytes().to_vec(),
                client_private_key: config.temporal_client_key.as_bytes().to_vec(),
            }),
            server_cert_verifier: None,
        };
        let connection_options = ConnectionOptions::new(target)
            .identity("cymbal-notifications")
            .tls_options(tls_options)
            .build();
        let connection = Connection::connect(connection_options)
            .await
            .map_err(|error| {
                UnhandledError::Other(format!("failed to connect to Temporal: {error}"))
            })?;
        let client = Client::new(
            connection,
            ClientOptions::new(config.temporal_namespace.clone()).build(),
        )
        .map_err(|error| {
            UnhandledError::Other(format!("failed to create Temporal client: {error}"))
        })?;

        Ok(Self {
            client,
            task_queue: config.error_tracking_lifecycle_task_queue.clone(),
            enabled_team_ids: parse_team_ids(&config.issue_created_workflow_team_ids)?,
            encryption_key: temporal_encryption_key(&config.temporal_secret_key)?,
        })
    }

    fn is_enabled_for_team(&self, team_id: i32) -> bool {
        self.enabled_team_ids
            .as_ref()
            .is_none_or(|team_ids| team_ids.contains(&team_id))
    }

    async fn start(&self, notification: &IssueCreated) -> Result<(), UnhandledError> {
        let request = build_start_request(
            notification,
            &self.client.options().namespace,
            &self.task_queue,
            &self.encryption_key,
        )?;

        match self
            .client
            .clone()
            .start_workflow_execution(request.into_request())
            .await
        {
            Ok(_) => {
                metrics::counter!(WORKFLOW_STARTS_TOTAL, "outcome" => "started").increment(1);
                Ok(())
            }
            Err(status) if status.code() == Code::AlreadyExists => {
                metrics::counter!(WORKFLOW_STARTS_TOTAL, "outcome" => "already_started")
                    .increment(1);
                Ok(())
            }
            Err(status) => {
                metrics::counter!(WORKFLOW_STARTS_TOTAL, "outcome" => "error").increment(1);
                Err(UnhandledError::Other(format!(
                    "failed to start issue-created workflow: {status}"
                )))
            }
        }
    }
}

fn build_start_request(
    notification: &IssueCreated,
    namespace: &str,
    task_queue: &str,
    encryption_key: &Fernet,
) -> Result<StartWorkflowExecutionRequest, UnhandledError> {
    let input = IssueCreatedWorkflowInput::from(notification);
    let payload = encrypted_json_payload(&input, encryption_key)?;
    Ok(StartWorkflowExecutionRequest {
        namespace: namespace.to_string(),
        workflow_id: format!("{WORKFLOW_ID_PREFIX}-{}", notification.meta.notification_id),
        workflow_type: Some(WorkflowType {
            name: WORKFLOW_NAME.to_string(),
        }),
        task_queue: Some(TaskQueue {
            name: task_queue.to_string(),
            kind: TaskQueueKind::Unspecified as i32,
            normal_name: String::new(),
        }),
        input: Some(Payloads {
            payloads: vec![payload],
        }),
        request_id: notification.meta.notification_id.to_string(),
        workflow_id_reuse_policy: WorkflowIdReusePolicy::AllowDuplicateFailedOnly as i32,
        workflow_id_conflict_policy: WorkflowIdConflictPolicy::UseExisting as i32,
        identity: "cymbal-notifications".to_string(),
        ..Default::default()
    })
}

#[derive(Serialize)]
struct IssueCreatedWorkflowInput<'a> {
    notification_id: Uuid,
    team_id: i32,
    issue_id: Uuid,
    issue: &'a IssueSnapshot,
    fingerprint: &'a str,
    event_uuid: Uuid,
    event_timestamp: &'a str,
    assignee: Option<&'a str>,
}

impl<'a> From<&'a IssueCreated> for IssueCreatedWorkflowInput<'a> {
    fn from(notification: &'a IssueCreated) -> Self {
        Self {
            notification_id: notification.meta.notification_id,
            team_id: notification.meta.team_id,
            issue_id: notification.issue.issue_id,
            issue: &notification.issue.issue,
            fingerprint: &notification.fingerprint,
            event_uuid: notification.event_uuid,
            event_timestamp: &notification.event_timestamp,
            assignee: notification.assignee.as_deref(),
        }
    }
}

fn encrypted_json_payload<T: Serialize>(
    value: &T,
    key: &Fernet,
) -> Result<Payload, UnhandledError> {
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
/// decrypt Cymbal's payloads.
fn temporal_encryption_key(raw: &str) -> Result<Fernet, UnhandledError> {
    let loaded = if let Some(value) = raw.strip_prefix("hex:") {
        hex::decode(value).map_err(|error| {
            UnhandledError::Other(format!("invalid hex TEMPORAL_SECRET_KEY: {error}"))
        })?
    } else if let Some(value) = raw.strip_prefix("base64-urlsafe:") {
        general_purpose::URL_SAFE.decode(value).map_err(|error| {
            UnhandledError::Other(format!(
                "invalid URL-safe base64 TEMPORAL_SECRET_KEY: {error}"
            ))
        })?
    } else if let Some(value) = raw.strip_prefix("base64:") {
        general_purpose::STANDARD.decode(value).map_err(|error| {
            UnhandledError::Other(format!("invalid base64 TEMPORAL_SECRET_KEY: {error}"))
        })?
    } else {
        raw.as_bytes().to_vec()
    };
    if loaded.len() < 32 {
        return Err(UnhandledError::Other(format!(
            "TEMPORAL_SECRET_KEY must contain at least 32 bytes, got {}",
            loaded.len()
        )));
    }

    let prepared = general_purpose::URL_SAFE.encode(&loaded[..32]);
    Fernet::new(&prepared)
        .ok_or_else(|| UnhandledError::Other("failed to prepare TEMPORAL_SECRET_KEY".to_string()))
}

fn parse_team_ids(raw: &str) -> Result<Option<HashSet<i32>>, UnhandledError> {
    if raw.trim().is_empty() {
        return Ok(None);
    }
    raw.split(',')
        .map(|value| {
            value.trim().parse::<i32>().map_err(|error| {
                UnhandledError::Other(format!(
                    "invalid ERROR_TRACKING_ISSUE_CREATED_WORKFLOW_TEAM_IDS entry {value:?}: {error}"
                ))
            })
        })
        .collect::<Result<HashSet<_>, _>>()
        .map(Some)
}

fn require_config(name: &str, value: &str) -> Result<(), UnhandledError> {
    if value.is_empty() {
        return Err(UnhandledError::Other(format!(
            "{name} is required when issue-created workflows are enabled"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use chrono::Utc;
    use temporalio_common::protos::temporal::api::common::v1::Payload;

    use crate::core::types::notification::{IssueNotificationContext, NotificationMeta};
    use crate::types::ProcessedExceptionProperties;

    use super::*;

    fn notification_id() -> Uuid {
        Uuid::parse_str("018f3f58-7a7b-7c00-8000-000000000001").unwrap()
    }

    fn notification() -> IssueCreated {
        IssueCreated {
            meta: NotificationMeta {
                notification_id: notification_id(),
                team_id: 42,
            },
            issue: IssueNotificationContext {
                issue_id: Uuid::nil(),
                issue: IssueSnapshot {
                    name: Some("TypeError".to_string()),
                    description: Some("boom".to_string()),
                    status: "active".to_string(),
                    created_at: Utc::now(),
                },
                event_properties: serde_json::from_value::<ProcessedExceptionProperties>(
                    serde_json::json!({
                        "$exception_list": [{"type": "TypeError", "value": "boom"}],
                        "$exception_fingerprint": "fingerprint",
                        "$exception_fingerprint_record": [],
                        "$exception_issue_id": Uuid::nil(),
                        "$exception_handled": false,
                        "$exception_types": ["TypeError"],
                        "$exception_values": ["boom"],
                        "$exception_sources": [],
                        "$exception_functions": [],
                    }),
                )
                .unwrap(),
            },
            fingerprint: "fingerprint".to_string(),
            event_uuid: Uuid::nil(),
            event_timestamp: "2026-07-21T12:00:00Z".to_string(),
            assignee: None,
        }
    }

    #[test]
    fn workflow_input_excludes_event_properties() {
        let value = serde_json::to_value(IssueCreatedWorkflowInput::from(&notification())).unwrap();

        assert_eq!(value["team_id"], 42);
        assert_eq!(value["fingerprint"], "fingerprint");
        assert!(value.get("event_properties").is_none());
    }

    #[test]
    fn encryption_matches_the_python_temporal_payload_shape() {
        let key = temporal_encryption_key(&"a".repeat(32)).unwrap();
        let payload =
            encrypted_json_payload(&IssueCreatedWorkflowInput::from(&notification()), &key)
                .unwrap();
        let token = std::str::from_utf8(&payload.data).unwrap();
        let decrypted = key.decrypt(token).unwrap();
        let inner = Payload::decode(decrypted.as_slice()).unwrap();

        assert_eq!(payload.metadata["encoding"], b"binary/encrypted");
        assert_eq!(inner.metadata["encoding"], b"json/plain");
        assert!(serde_json::from_slice::<serde_json::Value>(&inner.data).is_ok());
    }

    #[test]
    fn legacy_long_keys_match_python_truncation() {
        let long_key = temporal_encryption_key(&"a".repeat(40)).unwrap();
        let truncated_key = temporal_encryption_key(&"a".repeat(32)).unwrap();
        let token = long_key.encrypt(b"payload");

        assert_eq!(truncated_key.decrypt(&token).unwrap(), b"payload");
    }

    #[test]
    fn parses_rollout_team_allowlist() {
        assert_eq!(parse_team_ids("").unwrap(), None);
        assert_eq!(
            parse_team_ids("42, 43").unwrap(),
            Some(HashSet::from([42, 43]))
        );
        assert!(parse_team_ids("42,nope").is_err());
    }

    #[test]
    fn start_request_is_idempotent_and_targets_the_lifecycle_queue() {
        let notification = notification();
        let request = build_start_request(
            &notification,
            "posthog.prod",
            "error-tracking-lifecycle-task-queue",
            &temporal_encryption_key(&"a".repeat(32)).unwrap(),
        )
        .unwrap();

        assert_eq!(request.namespace, "posthog.prod");
        assert_eq!(
            request.workflow_id,
            format!("error-tracking-issue-created-{}", notification_id())
        );
        assert_eq!(request.request_id, notification_id().to_string());
        assert_eq!(
            request.workflow_type.unwrap().name,
            "error-tracking-issue-created"
        );
        assert_eq!(
            request.task_queue.unwrap().name,
            "error-tracking-lifecycle-task-queue"
        );
        assert_eq!(
            request.workflow_id_reuse_policy,
            WorkflowIdReusePolicy::AllowDuplicateFailedOnly as i32
        );
        assert_eq!(
            request.workflow_id_conflict_policy,
            WorkflowIdConflictPolicy::UseExisting as i32
        );
    }
}
