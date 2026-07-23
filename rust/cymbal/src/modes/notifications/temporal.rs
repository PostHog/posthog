use std::collections::HashSet;

use common_temporal::{
    StartWorkflowOptions, StartWorkflowOutcome, TemporalClientConfig, TemporalWorkflowClient,
};
use serde::Serialize;
use tracing::error;
use uuid::Uuid;

use crate::core::error::UnhandledError;
use crate::core::types::notification::{IssueCreated, IssueSnapshot};
use crate::modes::notifications::config::NotificationsConfig;

const WORKFLOW_NAME: &str = "error-tracking-issue-created";
const WORKFLOW_ID_PREFIX: &str = "error-tracking-issue-created";
const WORKFLOW_STARTS_TOTAL: &str = "cymbal_issue_created_workflow_starts_total";
const WORKFLOW_ROUTES_TOTAL: &str = "cymbal_issue_created_workflow_routes_total";
const WORKFLOW_STARTER_INIT_TOTAL: &str = "cymbal_issue_created_workflow_starter_init_total";

#[derive(Clone, Default)]
pub struct MaybeIssueCreatedWorkflowStarter(Option<IssueCreatedWorkflowStarter>);

impl MaybeIssueCreatedWorkflowStarter {
    pub async fn from_config(config: &NotificationsConfig) -> Result<Self, UnhandledError> {
        if !config.issue_created_workflow_enabled {
            return Ok(Self::default());
        }

        // Parse the rollout allowlist eagerly so genuine misconfiguration still fails fast.
        let enabled_team_ids = parse_team_ids(&config.issue_created_workflow_team_ids)?;

        Ok(Self::connect_or_fallback(
            temporal_client_config(config),
            config.error_tracking_lifecycle_task_queue.clone(),
            enabled_team_ids,
        )
        .await)
    }

    /// Connect to Temporal, degrading to the legacy (non-Temporal) route on failure.
    ///
    /// A Temporal connect failure (e.g. a TLS trust-chain error, or Temporal being
    /// unreachable) must not crash the notifications consumer at boot. Falling back
    /// keeps notification processing running; the workflow route is picked back up
    /// on the next redeploy once Temporal is reachable again.
    async fn connect_or_fallback(
        client_config: TemporalClientConfig,
        task_queue: String,
        enabled_team_ids: Option<HashSet<i32>>,
    ) -> Self {
        match TemporalWorkflowClient::connect(client_config).await {
            Ok(client) => {
                metrics::counter!(WORKFLOW_STARTER_INIT_TOTAL, "outcome" => "connected")
                    .increment(1);
                Self(Some(IssueCreatedWorkflowStarter {
                    client,
                    task_queue,
                    enabled_team_ids,
                }))
            }
            Err(error) => {
                metrics::counter!(WORKFLOW_STARTER_INIT_TOTAL, "outcome" => "connect_failed")
                    .increment(1);
                error!(
                    error = %error,
                    "failed to connect to Temporal for the issue-created workflow; \
                     falling back to the legacy notification route",
                );
                Self::default()
            }
        }
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
    client: TemporalWorkflowClient,
    task_queue: String,
    enabled_team_ids: Option<HashSet<i32>>,
}

impl IssueCreatedWorkflowStarter {
    fn is_enabled_for_team(&self, team_id: i32) -> bool {
        self.enabled_team_ids
            .as_ref()
            .is_none_or(|team_ids| team_ids.contains(&team_id))
    }

    async fn start(&self, notification: &IssueCreated) -> Result<(), UnhandledError> {
        let options = start_options(notification, &self.task_queue);
        match self
            .client
            .start_workflow(&IssueCreatedWorkflowInput::from(notification), &options)
            .await
        {
            Ok(StartWorkflowOutcome::Started { .. }) => {
                metrics::counter!(WORKFLOW_STARTS_TOTAL, "outcome" => "started").increment(1);
                Ok(())
            }
            Ok(StartWorkflowOutcome::Existing { .. }) => {
                metrics::counter!(WORKFLOW_STARTS_TOTAL, "outcome" => "already_started")
                    .increment(1);
                Ok(())
            }
            Err(error) => {
                metrics::counter!(WORKFLOW_STARTS_TOTAL, "outcome" => "error").increment(1);
                Err(UnhandledError::Other(format!(
                    "failed to start issue-created workflow: {error}"
                )))
            }
        }
    }
}

fn temporal_client_config(config: &NotificationsConfig) -> TemporalClientConfig {
    TemporalClientConfig {
        host: config.temporal_host.clone(),
        port: config.temporal_port,
        namespace: config.temporal_namespace.clone(),
        client_cert: config.temporal_client_cert.clone(),
        client_key: config.temporal_client_key.clone(),
        server_root_ca_cert: config.temporal_client_root_ca.clone(),
        payload_encryption_key: config.temporal_secret_key.clone(),
        identity: "cymbal-notifications".to_string(),
    }
}

fn start_options(notification: &IssueCreated, task_queue: &str) -> StartWorkflowOptions {
    StartWorkflowOptions::idempotent(
        WORKFLOW_NAME,
        task_queue,
        format!("{WORKFLOW_ID_PREFIX}-{}", notification.meta.notification_id),
        notification.meta.notification_id.to_string(),
    )
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

#[cfg(test)]
mod tests {
    use chrono::Utc;

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
    fn start_options_are_idempotent_and_target_the_lifecycle_queue() {
        let options = start_options(&notification(), "error-tracking-lifecycle-task-queue");

        assert_eq!(options.workflow_name, "error-tracking-issue-created");
        assert_eq!(
            options.workflow_id,
            format!("error-tracking-issue-created-{}", notification_id())
        );
        assert_eq!(options.request_id, notification_id().to_string());
        assert_eq!(options.task_queue, "error-tracking-lifecycle-task-queue");
    }

    #[tokio::test]
    async fn connect_failure_falls_back_to_legacy_route() {
        // An empty client cert makes the Temporal connect fail fast, standing in for the
        // TLS trust-chain failures seen in production. Boot must degrade to the legacy
        // route instead of erroring out (which panicked the whole consumer at boot).
        let starter = MaybeIssueCreatedWorkflowStarter::connect_or_fallback(
            TemporalClientConfig {
                host: "temporal.invalid".to_string(),
                port: 7233,
                namespace: "default".to_string(),
                client_cert: String::new(),
                client_key: String::new(),
                server_root_ca_cert: None,
                payload_encryption_key: "a".repeat(32),
                identity: "cymbal-notifications-test".to_string(),
            },
            "error-tracking-lifecycle-task-queue".to_string(),
            None,
        )
        .await;

        assert!(!starter.start_if_enabled(&notification()).await.unwrap());
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
}
