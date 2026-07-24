use std::collections::HashSet;

use chrono::{DateTime, Utc};
use common_temporal::{
    StartWorkflowOptions, StartWorkflowOutcome, TemporalClientConfig, TemporalWorkflowClient,
};
use serde::Serialize;
use uuid::Uuid;

use crate::core::error::UnhandledError;
use crate::core::types::notification::{IssueCreated, IssueReopened, IssueSnapshot, IssueSpiking};
use crate::modes::notifications::config::NotificationsConfig;

#[derive(Clone, Copy)]
struct WorkflowDefinition {
    name: &'static str,
    starts_metric: &'static str,
    routes_metric: &'static str,
}

#[derive(Clone, Copy)]
enum IssueLifecycleKind {
    Created,
    Reopened,
    Spiking,
}

impl IssueLifecycleKind {
    const fn workflow(self) -> WorkflowDefinition {
        match self {
            Self::Created => WorkflowDefinition {
                name: "error-tracking-issue-created",
                starts_metric: "cymbal_issue_created_workflow_starts_total",
                routes_metric: "cymbal_issue_created_workflow_routes_total",
            },
            Self::Reopened => WorkflowDefinition {
                name: "error-tracking-issue-reopened",
                starts_metric: "cymbal_issue_reopened_workflow_starts_total",
                routes_metric: "cymbal_issue_reopened_workflow_routes_total",
            },
            Self::Spiking => WorkflowDefinition {
                name: "error-tracking-issue-spiking",
                starts_metric: "cymbal_issue_spiking_workflow_starts_total",
                routes_metric: "cymbal_issue_spiking_workflow_routes_total",
            },
        }
    }
}

const ISSUE_CREATED_WORKFLOW: WorkflowDefinition = IssueLifecycleKind::Created.workflow();
const ISSUE_REOPENED_WORKFLOW: WorkflowDefinition = IssueLifecycleKind::Reopened.workflow();
const ISSUE_SPIKING_WORKFLOW: WorkflowDefinition = IssueLifecycleKind::Spiking.workflow();

#[derive(Clone)]
struct LifecycleWorkflowRoute {
    enabled_team_ids: Option<HashSet<i32>>,
}

impl LifecycleWorkflowRoute {
    fn is_enabled_for_team(&self, team_id: i32) -> bool {
        self.enabled_team_ids
            .as_ref()
            .is_none_or(|team_ids| team_ids.contains(&team_id))
    }
}

#[derive(Clone)]
pub struct IssueLifecycleWorkflowStarters {
    client: Option<TemporalWorkflowClient>,
    task_queue: String,
    created: Option<LifecycleWorkflowRoute>,
    reopened: Option<LifecycleWorkflowRoute>,
    spiking: Option<LifecycleWorkflowRoute>,
}

impl IssueLifecycleWorkflowStarters {
    pub fn from_config(
        config: &NotificationsConfig,
        client: Option<&TemporalWorkflowClient>,
    ) -> Result<Self, UnhandledError> {
        let created = build_route(
            config.issue_created_workflow_enabled,
            &config.issue_created_workflow_team_ids,
            "ERROR_TRACKING_ISSUE_CREATED_WORKFLOW_TEAM_IDS",
        )?;
        let reopened = build_route(
            config.issue_reopened_workflow_enabled,
            &config.issue_reopened_workflow_team_ids,
            "ERROR_TRACKING_ISSUE_REOPENED_WORKFLOW_TEAM_IDS",
        )?;
        let spiking = build_route(
            config.issue_spiking_workflow_enabled,
            &config.issue_spiking_workflow_team_ids,
            "ERROR_TRACKING_ISSUE_SPIKING_WORKFLOW_TEAM_IDS",
        )?;
        if (created.is_some() || reopened.is_some() || spiking.is_some()) && client.is_none() {
            return Err(UnhandledError::Other(
                "Temporal client missing for enabled lifecycle workflow".to_string(),
            ));
        }

        Ok(Self {
            client: client.cloned(),
            task_queue: config.error_tracking_lifecycle_task_queue.clone(),
            created,
            reopened,
            spiking,
        })
    }

    pub async fn start_created_if_enabled(
        &self,
        notification: &IssueCreated,
    ) -> Result<bool, UnhandledError> {
        if !route_is_enabled(
            &self.created,
            notification.meta.team_id,
            ISSUE_CREATED_WORKFLOW,
        ) {
            return Ok(false);
        }

        self.start(
            notification.meta.notification_id,
            &IssueCreatedWorkflowInput::from(notification),
            ISSUE_CREATED_WORKFLOW,
        )
        .await?;
        record_route(ISSUE_CREATED_WORKFLOW, "temporal");
        Ok(true)
    }

    pub async fn start_reopened_if_enabled(
        &self,
        notification: &IssueReopened,
    ) -> Result<bool, UnhandledError> {
        if !has_event_reference(notification.event_uuid, &notification.event_timestamp) {
            record_route(ISSUE_REOPENED_WORKFLOW, "legacy_missing_event_reference");
            return Ok(false);
        }
        if !route_is_enabled(
            &self.reopened,
            notification.meta.team_id,
            ISSUE_REOPENED_WORKFLOW,
        ) {
            return Ok(false);
        }

        self.start(
            notification.meta.notification_id,
            &IssueReopenedWorkflowInput::from(notification),
            ISSUE_REOPENED_WORKFLOW,
        )
        .await?;
        record_route(ISSUE_REOPENED_WORKFLOW, "temporal");
        Ok(true)
    }

    pub async fn start_spiking_if_enabled(
        &self,
        notification: &IssueSpiking,
    ) -> Result<bool, UnhandledError> {
        if !has_event_reference(notification.event_uuid, &notification.event_timestamp) {
            record_route(ISSUE_SPIKING_WORKFLOW, "legacy_missing_event_reference");
            return Ok(false);
        }
        if !route_is_enabled(
            &self.spiking,
            notification.meta.team_id,
            ISSUE_SPIKING_WORKFLOW,
        ) {
            return Ok(false);
        }

        self.start(
            notification.meta.notification_id,
            &IssueSpikingWorkflowInput::from(notification),
            ISSUE_SPIKING_WORKFLOW,
        )
        .await?;
        record_route(ISSUE_SPIKING_WORKFLOW, "temporal");
        Ok(true)
    }

    async fn start<T: Serialize>(
        &self,
        notification_id: Uuid,
        input: &T,
        workflow: WorkflowDefinition,
    ) -> Result<(), UnhandledError> {
        let options = start_options(notification_id, &self.task_queue, workflow);
        let client = self.client.as_ref().ok_or_else(|| {
            UnhandledError::Other(
                "Temporal client missing for enabled lifecycle workflow".to_string(),
            )
        })?;
        match client.start_workflow(input, &options).await {
            Ok(StartWorkflowOutcome::Started { .. }) => {
                metrics::counter!(workflow.starts_metric, "outcome" => "started").increment(1);
                Ok(())
            }
            Ok(StartWorkflowOutcome::Existing { .. }) => {
                metrics::counter!(workflow.starts_metric, "outcome" => "already_started")
                    .increment(1);
                Ok(())
            }
            Err(error) => {
                metrics::counter!(workflow.starts_metric, "outcome" => "error").increment(1);
                Err(UnhandledError::Other(format!(
                    "failed to start {} workflow: {error}",
                    workflow.name
                )))
            }
        }
    }
}

pub async fn build_issue_lifecycle_temporal_client(
    config: &NotificationsConfig,
) -> Result<Option<TemporalWorkflowClient>, UnhandledError> {
    if !config.issue_created_workflow_enabled
        && !config.issue_reopened_workflow_enabled
        && !config.issue_spiking_workflow_enabled
    {
        return Ok(None);
    }

    TemporalWorkflowClient::connect(TemporalClientConfig {
        host: config.temporal_host.clone(),
        port: config.temporal_port,
        namespace: config.temporal_namespace.clone(),
        client_cert: config.temporal_client_cert.clone(),
        client_key: config.temporal_client_key.clone(),
        // Temporal Cloud's server certificate chains to a public CA. Match the
        // Python workers and use native roots rather than the injected CA,
        // which is not the server certificate issuer.
        server_root_ca_cert: None,
        payload_encryption_key: config.temporal_secret_key.clone(),
        identity: "cymbal-notifications".to_string(),
    })
    .await
    .map(Some)
    .map_err(|error| UnhandledError::Other(error.to_string()))
}

fn build_route(
    enabled: bool,
    team_ids: &str,
    team_ids_env_var: &'static str,
) -> Result<Option<LifecycleWorkflowRoute>, UnhandledError> {
    if !enabled {
        return Ok(None);
    }
    Ok(Some(LifecycleWorkflowRoute {
        enabled_team_ids: parse_team_ids(team_ids, team_ids_env_var)?,
    }))
}

fn route_is_enabled(
    route: &Option<LifecycleWorkflowRoute>,
    team_id: i32,
    workflow: WorkflowDefinition,
) -> bool {
    let Some(route) = route else {
        record_route(workflow, "legacy");
        return false;
    };
    if !route.is_enabled_for_team(team_id) {
        record_route(workflow, "legacy");
        return false;
    }
    true
}

fn has_event_reference(event_uuid: Uuid, event_timestamp: &str) -> bool {
    !event_uuid.is_nil() && !event_timestamp.is_empty()
}

fn record_route(workflow: WorkflowDefinition, route: &'static str) {
    metrics::counter!(workflow.routes_metric, "route" => route).increment(1);
}

fn start_options(
    notification_id: Uuid,
    task_queue: &str,
    workflow: WorkflowDefinition,
) -> StartWorkflowOptions {
    StartWorkflowOptions::idempotent(
        workflow.name,
        task_queue,
        format!("{}-{notification_id}", workflow.name),
        notification_id.to_string(),
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

#[derive(Serialize)]
struct IssueReopenedWorkflowInput<'a> {
    notification_id: Uuid,
    team_id: i32,
    issue_id: Uuid,
    issue: &'a IssueSnapshot,
    fingerprint: &'a str,
    event_uuid: Uuid,
    event_timestamp: &'a str,
    assignee: Option<&'a str>,
}

impl<'a> From<&'a IssueReopened> for IssueReopenedWorkflowInput<'a> {
    fn from(notification: &'a IssueReopened) -> Self {
        Self {
            notification_id: notification.meta.notification_id,
            team_id: notification.meta.team_id,
            issue_id: notification.issue.issue_id,
            issue: &notification.issue.issue,
            fingerprint: notification.issue.event_properties.fingerprint(),
            event_uuid: notification.event_uuid,
            event_timestamp: &notification.event_timestamp,
            assignee: notification.assignee.as_deref(),
        }
    }
}

#[derive(Serialize)]
struct IssueSpikingWorkflowInput<'a> {
    notification_id: Uuid,
    team_id: i32,
    issue_id: Uuid,
    issue: &'a IssueSnapshot,
    fingerprint: &'a str,
    event_uuid: Uuid,
    event_timestamp: &'a str,
    detected_at: DateTime<Utc>,
    computed_baseline: f64,
    current_bucket_value: f64,
    assignee: Option<&'a str>,
}

impl<'a> From<&'a IssueSpiking> for IssueSpikingWorkflowInput<'a> {
    fn from(notification: &'a IssueSpiking) -> Self {
        Self {
            notification_id: notification.meta.notification_id,
            team_id: notification.meta.team_id,
            issue_id: notification.issue.issue_id,
            issue: &notification.issue.issue,
            fingerprint: notification.issue.event_properties.fingerprint(),
            event_uuid: notification.event_uuid,
            event_timestamp: &notification.event_timestamp,
            detected_at: notification_time(notification.meta.notification_id),
            computed_baseline: notification.computed_baseline,
            current_bucket_value: notification.current_bucket_value,
            assignee: notification.assignee.as_deref(),
        }
    }
}

fn notification_time(notification_id: Uuid) -> DateTime<Utc> {
    notification_id
        .get_timestamp()
        .and_then(|timestamp| {
            let (seconds, nanos) = timestamp.to_unix();
            DateTime::from_timestamp(seconds as i64, nanos)
        })
        .unwrap_or_else(Utc::now)
}

fn parse_team_ids(
    raw: &str,
    env_var: &'static str,
) -> Result<Option<HashSet<i32>>, UnhandledError> {
    if raw.trim().is_empty() {
        return Ok(None);
    }
    raw.split(',')
        .map(|value| {
            value.trim().parse::<i32>().map_err(|error| {
                UnhandledError::Other(format!("invalid {env_var} entry {value:?}: {error}"))
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

    fn issue_context() -> IssueNotificationContext {
        IssueNotificationContext {
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
        }
    }

    fn issue_created() -> IssueCreated {
        IssueCreated {
            meta: NotificationMeta {
                notification_id: notification_id(),
                team_id: 42,
            },
            issue: issue_context(),
            fingerprint: "fingerprint".to_string(),
            event_uuid: Uuid::now_v7(),
            event_timestamp: "2026-07-21T12:00:00Z".to_string(),
            assignee: None,
        }
    }

    fn issue_reopened() -> IssueReopened {
        IssueReopened {
            meta: NotificationMeta {
                notification_id: notification_id(),
                team_id: 42,
            },
            issue: issue_context(),
            event_uuid: Uuid::now_v7(),
            event_timestamp: "2026-07-21T12:00:00Z".to_string(),
            assignee: None,
        }
    }

    fn issue_spiking() -> IssueSpiking {
        IssueSpiking {
            meta: NotificationMeta {
                notification_id: notification_id(),
                team_id: 42,
            },
            issue: issue_context(),
            event_uuid: Uuid::now_v7(),
            event_timestamp: "2026-07-21T12:00:00Z".to_string(),
            computed_baseline: 2.0,
            current_bucket_value: 20.0,
            assignee: None,
        }
    }

    #[test]
    fn workflow_inputs_exclude_event_properties() {
        let values = [
            serde_json::to_value(IssueCreatedWorkflowInput::from(&issue_created())).unwrap(),
            serde_json::to_value(IssueReopenedWorkflowInput::from(&issue_reopened())).unwrap(),
            serde_json::to_value(IssueSpikingWorkflowInput::from(&issue_spiking())).unwrap(),
        ];

        for value in values {
            assert_eq!(value["team_id"], 42);
            assert_eq!(value["fingerprint"], "fingerprint");
            assert!(value.get("event_properties").is_none());
        }
    }

    #[test]
    fn start_options_are_idempotent_and_target_the_lifecycle_queue() {
        for workflow in [
            ISSUE_CREATED_WORKFLOW,
            ISSUE_REOPENED_WORKFLOW,
            ISSUE_SPIKING_WORKFLOW,
        ] {
            let options = start_options(
                notification_id(),
                "error-tracking-lifecycle-task-queue",
                workflow,
            );

            assert_eq!(options.workflow_name, workflow.name);
            assert_eq!(
                options.workflow_id,
                format!("{}-{}", workflow.name, notification_id())
            );
            assert_eq!(options.request_id, notification_id().to_string());
            assert_eq!(options.task_queue, "error-tracking-lifecycle-task-queue");
        }
    }

    #[test]
    fn parses_rollout_team_allowlist() {
        assert_eq!(parse_team_ids("", "TEAM_IDS").unwrap(), None);
        assert_eq!(
            parse_team_ids("42, 43", "TEAM_IDS").unwrap(),
            Some(HashSet::from([42, 43]))
        );
        assert!(parse_team_ids("42,nope", "TEAM_IDS").is_err());
    }

    #[test]
    fn lifecycle_routes_support_disabled_global_and_allowlisted_rollouts() {
        assert!(build_route(false, "", "TEAM_IDS").unwrap().is_none());

        let global = build_route(true, "", "TEAM_IDS").unwrap().unwrap();
        assert!(global.is_enabled_for_team(42));

        let allowlisted = build_route(true, "42,43", "TEAM_IDS").unwrap().unwrap();
        assert!(allowlisted.is_enabled_for_team(42));
        assert!(!allowlisted.is_enabled_for_team(44));
    }

    #[test]
    fn reopened_and_spiking_require_event_references() {
        assert!(has_event_reference(Uuid::now_v7(), "2026-07-21T12:00:00Z"));
        assert!(!has_event_reference(Uuid::nil(), "2026-07-21T12:00:00Z"));
        assert!(!has_event_reference(Uuid::now_v7(), ""));
    }
}
