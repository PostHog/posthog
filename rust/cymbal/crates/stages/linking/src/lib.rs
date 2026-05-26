//! Cymbal linking stage crate.
//!
//! This crate owns issue linking and suppression orchestration behind explicit
//! dependency traits. The default stage remains a pass-through until runtime
//! wiring supplies repositories; tests exercise the full behavior with mocks.

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use cymbal_core::{
    run_buffered, PipelineStage, StageConcurrencyLimiter, StageError, StageInput, StageType,
};
use cymbal_domain::{EventOutcome, EventResult, ExceptionProperties};
use cymbal_grouping::GroupedEvent;
use cymbal_repositories::{
    FingerprintIssueState, Issue, IssueFingerprintOverride, IssueStatus, IssueWithFirstSeen,
};
use cymbal_rules::{Assignment, AssignmentIssue, AssignmentRule, NewAssignment, SuppressionRule};
use hogvm::VmError;
use moka::future::{Cache, CacheBuilder};
use serde_json::Value;
use thiserror::Error;
use uuid::Uuid;

pub const LINKING_STAGE_ID: &str = "linking:v1";
pub const LINKING_STAGE_TYPE: StageType = StageType {
    namespace: "cymbal.stage",
    name: "linking",
    version: 1,
};
pub const FINGERPRINT_ISSUE_STATE_METADATA_KEY: &str = "error_tracking_fingerprint_issue_state";
const BATCH_ISSUE_CACHE_CAPACITY: u64 = 10_000;
const ISSUE_CACHE_CAPACITY: u64 = 1_000;
const DEFAULT_LINKING_STAGE_CONCURRENCY: usize = 8;

#[derive(Debug, Error)]
pub enum LinkingError {
    #[error("repository error: {0}")]
    Repository(String),
    #[error("serde error: {0}")]
    Serde(#[from] serde_json::Error),
    #[error("missing required field: {0}")]
    MissingField(&'static str),
}

#[async_trait]
pub trait IssueRepository: Send + Sync {
    async fn load_by_fingerprint(
        &self,
        team_id: i32,
        fingerprint: &str,
    ) -> Result<Option<IssueWithFirstSeen>, LinkingError>;

    async fn load(&self, team_id: i32, issue_id: Uuid) -> Result<Option<Issue>, LinkingError>;

    async fn insert_new(
        &self,
        team_id: i32,
        name: String,
        description: String,
    ) -> Result<Issue, LinkingError>;

    async fn maybe_reopen(&self, issue: &mut Issue) -> Result<bool, LinkingError>;

    async fn create_or_load_fingerprint(
        &self,
        team_id: i32,
        fingerprint: &str,
        issue: &Issue,
        first_seen: DateTime<Utc>,
    ) -> Result<IssueFingerprintOverride, LinkingError>;

    async fn existing_assignments(&self, issue_id: Uuid) -> Result<Vec<Assignment>, LinkingError>;

    async fn apply_assignment(
        &self,
        new_assignment: &NewAssignment,
        issue_id: Uuid,
    ) -> Result<Assignment, LinkingError>;
}

#[async_trait]
pub trait LinkingRuleRepository: Send + Sync {
    async fn suppression_rules(&self, team_id: i32) -> Result<Vec<SuppressionRule>, LinkingError>;

    async fn disable_suppression_rule(
        &self,
        rule: &SuppressionRule,
        message: String,
        props: Value,
    ) -> Result<(), LinkingError>;

    async fn assignment_rules(&self, team_id: i32) -> Result<Vec<AssignmentRule>, LinkingError>;

    async fn disable_assignment_rule(
        &self,
        rule: &AssignmentRule,
        message: String,
        issue: Value,
        props: Value,
    ) -> Result<(), LinkingError>;
}

#[async_trait]
pub trait LinkingSideEffects: Send + Sync {
    async fn issue_created(
        &self,
        _issue: &Issue,
        _assignment: Option<&Assignment>,
        _properties: &ExceptionProperties,
        _first_seen: DateTime<Utc>,
    ) -> Result<(), LinkingError> {
        Ok(())
    }

    async fn issue_reopened(
        &self,
        _issue: &Issue,
        _assignment: Option<&Assignment>,
        _properties: &ExceptionProperties,
        _first_seen: DateTime<Utc>,
    ) -> Result<(), LinkingError> {
        Ok(())
    }

    async fn new_fingerprint(
        &self,
        _issue: &Issue,
        _properties: &ExceptionProperties,
    ) -> Result<(), LinkingError> {
        Ok(())
    }
}

#[derive(Debug, Default)]
pub struct NoopLinkingRuleRepository;

#[async_trait]
impl LinkingRuleRepository for NoopLinkingRuleRepository {
    async fn suppression_rules(&self, _team_id: i32) -> Result<Vec<SuppressionRule>, LinkingError> {
        Ok(Vec::new())
    }

    async fn disable_suppression_rule(
        &self,
        _rule: &SuppressionRule,
        _message: String,
        _props: Value,
    ) -> Result<(), LinkingError> {
        Ok(())
    }

    async fn assignment_rules(&self, _team_id: i32) -> Result<Vec<AssignmentRule>, LinkingError> {
        Ok(Vec::new())
    }

    async fn disable_assignment_rule(
        &self,
        _rule: &AssignmentRule,
        _message: String,
        _issue: Value,
        _props: Value,
    ) -> Result<(), LinkingError> {
        Ok(())
    }
}

#[derive(Debug, Default)]
pub struct NoopLinkingSideEffects;

#[async_trait]
impl LinkingSideEffects for NoopLinkingSideEffects {}

#[derive(Clone)]
pub struct LinkingDeps {
    pub issue_repository: Arc<dyn IssueRepository>,
    pub rule_repository: Arc<dyn LinkingRuleRepository>,
    pub side_effects: Arc<dyn LinkingSideEffects>,
    pub issue_cache: Cache<(i32, String), Uuid>,
}

impl std::fmt::Debug for LinkingDeps {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LinkingDeps")
            .field("issue_repository", &"<dyn IssueRepository>")
            .field("rule_repository", &"<dyn LinkingRuleRepository>")
            .field("side_effects", &"<dyn LinkingSideEffects>")
            .finish_non_exhaustive()
    }
}

impl LinkingDeps {
    pub fn new(issue_repository: Arc<dyn IssueRepository>) -> Self {
        Self {
            issue_repository,
            rule_repository: Arc::new(NoopLinkingRuleRepository),
            side_effects: Arc::new(NoopLinkingSideEffects),
            issue_cache: default_issue_cache(),
        }
    }

    pub fn with_rule_repository(mut self, rule_repository: Arc<dyn LinkingRuleRepository>) -> Self {
        self.rule_repository = rule_repository;
        self
    }

    pub fn with_side_effects(mut self, side_effects: Arc<dyn LinkingSideEffects>) -> Self {
        self.side_effects = side_effects;
        self
    }

    pub fn with_issue_cache(mut self, issue_cache: Cache<(i32, String), Uuid>) -> Self {
        self.issue_cache = issue_cache;
        self
    }
}

fn default_issue_cache() -> Cache<(i32, String), Uuid> {
    CacheBuilder::new(ISSUE_CACHE_CAPACITY)
        .time_to_live(Duration::from_secs(60))
        .build()
}

#[derive(Clone)]
pub struct LinkingStage {
    deps: Option<LinkingDeps>,
    batch_issue_cache: Cache<(i32, String), Issue>,
    stage_concurrency_limiter: StageConcurrencyLimiter,
}

struct LinkedIssue {
    issue: Issue,
    fingerprint_issue_state: Option<FingerprintIssueState>,
}

impl std::fmt::Debug for LinkingStage {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LinkingStage")
            .field("deps", &self.deps)
            .field(
                "stage_concurrency",
                &self.stage_concurrency_limiter.capacity(),
            )
            .finish_non_exhaustive()
    }
}

impl Default for LinkingStage {
    fn default() -> Self {
        Self::new()
    }
}

impl LinkingStage {
    pub fn new() -> Self {
        Self {
            deps: None,
            batch_issue_cache: default_batch_issue_cache(),
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_LINKING_STAGE_CONCURRENCY,
            ),
        }
    }

    pub fn with_deps(deps: LinkingDeps) -> Self {
        Self {
            deps: Some(deps),
            batch_issue_cache: default_batch_issue_cache(),
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_LINKING_STAGE_CONCURRENCY,
            ),
        }
    }

    pub fn with_batch_issue_cache(
        mut self,
        batch_issue_cache: Cache<(i32, String), Issue>,
    ) -> Self {
        self.batch_issue_cache = batch_issue_cache;
        self
    }

    /// Cap the number of in-flight per-event link operations across every
    /// `process()` call to this stage on the pod.
    pub fn with_stage_concurrency(mut self, stage_concurrency: usize) -> Self {
        self.stage_concurrency_limiter = StageConcurrencyLimiter::new(stage_concurrency);
        self
    }

    pub fn default_batch_issue_cache() -> Cache<(i32, String), Issue> {
        default_batch_issue_cache()
    }

    async fn link_event(&self, event: GroupedEvent) -> Result<EventResult, StageError> {
        let event_id = event.event_id.clone();
        let Some(deps) = &self.deps else {
            return Ok(grouped_event_to_next_result(event));
        };

        match link_event_with_deps(event, deps.clone(), self.batch_issue_cache.clone()).await {
            Ok(result) => Ok(result),
            Err(error) => Ok(EventResult {
                event_id,
                outcome: EventOutcome::Error {
                    message: error.to_string(),
                    code: Some("linking_error".to_string()),
                    retryable: Some(false),
                },
            }),
        }
    }
}

#[async_trait]
impl PipelineStage for LinkingStage {
    type Input = GroupedEvent;
    type Output = EventResult;

    fn id(&self) -> StageType {
        LINKING_STAGE_TYPE
    }

    async fn process(
        &self,
        input: StageInput<Self::Input>,
    ) -> Result<Vec<Self::Output>, StageError> {
        let stage = self.clone();
        run_buffered(&self.stage_concurrency_limiter, input.items, move |event| {
            let stage = stage.clone();
            async move { stage.link_event(event).await }
        })
        .await
    }
}

fn default_batch_issue_cache() -> Cache<(i32, String), Issue> {
    CacheBuilder::new(BATCH_ISSUE_CACHE_CAPACITY).build()
}

async fn link_event_with_deps(
    event: GroupedEvent,
    deps: LinkingDeps,
    batch_issue_cache: Cache<(i32, String), Issue>,
) -> Result<EventResult, LinkingError> {
    if event.properties.exception_list_is_empty() {
        return Ok(grouped_event_to_next_result(event));
    }
    let mut exception_properties = event.properties;

    let team_id = event.team_id as i32;
    let props_json = serde_json::to_value(&exception_properties)?;
    if let Some(rule_id) = suppressing_rule_id(
        deps.rule_repository.as_ref(),
        team_id,
        props_json,
        event_uuid(&event.event_id),
    )
    .await?
    {
        return Ok(EventResult {
            event_id: event.event_id,
            outcome: EventOutcome::Drop {
                reason: format!("suppressed_by_rule:{rule_id}"),
            },
        });
    }

    let fingerprint = exception_properties
        .fingerprint
        .clone()
        .ok_or(LinkingError::MissingField("$exception_fingerprint"))?;
    let linked_issue = resolve_via_caches(
        &exception_properties,
        team_id,
        &fingerprint,
        deps.clone(),
        batch_issue_cache,
    )
    .await?;
    let issue = linked_issue.issue;

    if issue.status == IssueStatus::Suppressed {
        return Ok(EventResult {
            event_id: event.event_id,
            outcome: EventOutcome::Drop {
                reason: "suppressed_issue".to_string(),
            },
        });
    }

    exception_properties.issue_id = Some(issue.id);

    let mut metadata = event.metadata;
    if let Some(fingerprint_issue_state) = linked_issue.fingerprint_issue_state {
        metadata.insert(
            FINGERPRINT_ISSUE_STATE_METADATA_KEY.to_string(),
            serde_json::to_string(&fingerprint_issue_state)?,
        );
    }

    Ok(EventResult {
        event_id: event.event_id,
        outcome: EventOutcome::Next {
            properties: Some(exception_properties),
            metadata,
        },
    })
}

async fn suppressing_rule_id(
    repository: &dyn LinkingRuleRepository,
    team_id: i32,
    props_json: Value,
    event_uuid: Option<Uuid>,
) -> Result<Option<Uuid>, LinkingError> {
    let mut rules = repository.suppression_rules(team_id).await?;
    rules.sort_unstable_by_key(|rule| rule.order_key);

    for rule in rules {
        match rule.should_suppress(&props_json, event_uuid.as_ref()) {
            Ok(false) => continue,
            Ok(true) => return Ok(Some(rule.id)),
            Err(VmError::OutOfResource(resource)) if resource == "steps" => {
                tracing::warn!(
                    rule_id = %rule.id,
                    team_id = %rule.team_id,
                    "suppression rule exceeded HogVM step budget for this event, skipping"
                );
                continue;
            }
            Err(error) => {
                repository
                    .disable_suppression_rule(&rule, error.to_string(), props_json.clone())
                    .await?;
            }
        }
    }

    Ok(None)
}

async fn resolve_via_caches(
    properties: &LinkingExceptionProperties,
    team_id: i32,
    fingerprint: &str,
    deps: LinkingDeps,
    batch_issue_cache: Cache<(i32, String), Issue>,
) -> Result<LinkedIssue, LinkingError> {
    let key = (team_id, fingerprint.to_string());
    if let Some(issue) = batch_issue_cache.get(&key).await {
        return Ok(LinkedIssue {
            issue,
            fingerprint_issue_state: None,
        });
    }

    let linked_issue = resolve_via_issue_id_cache(properties, team_id, fingerprint, deps).await?;
    batch_issue_cache
        .insert(key, linked_issue.issue.clone())
        .await;
    Ok(linked_issue)
}

async fn resolve_via_issue_id_cache(
    properties: &LinkingExceptionProperties,
    team_id: i32,
    fingerprint: &str,
    deps: LinkingDeps,
) -> Result<LinkedIssue, LinkingError> {
    let key = (team_id, fingerprint.to_string());
    if let Some(issue_id) = deps.issue_cache.get(&key).await {
        if let Some(linked_issue) =
            load_and_maybe_reopen(properties, team_id, issue_id, fingerprint, &deps).await?
        {
            return Ok(linked_issue);
        }
        deps.issue_cache.invalidate(&key).await;
    }

    let linked_issue = fetch_or_create_issue(properties, team_id, fingerprint, &deps).await?;
    deps.issue_cache.insert(key, linked_issue.issue.id).await;
    Ok(linked_issue)
}

async fn fetch_or_create_issue(
    properties: &LinkingExceptionProperties,
    team_id: i32,
    fingerprint: &str,
    deps: &LinkingDeps,
) -> Result<LinkedIssue, LinkingError> {
    let event_timestamp = Utc::now();
    if let Some(result) = deps
        .issue_repository
        .load_by_fingerprint(team_id, fingerprint)
        .await?
    {
        let (mut issue, fingerprint_first_seen) = result.into_issue();
        if deps.issue_repository.maybe_reopen(&mut issue).await? {
            let first_seen = fingerprint_first_seen.unwrap_or(issue.created_at);
            let assignment = process_assignment(&issue, properties, deps).await?;
            deps.side_effects
                .issue_reopened(&issue, assignment.as_ref(), properties, first_seen)
                .await?;
            return Ok(LinkedIssue {
                fingerprint_issue_state: Some(FingerprintIssueState::new(
                    &issue,
                    fingerprint,
                    assignment.as_ref(),
                    first_seen,
                )),
                issue,
            });
        }
        return Ok(LinkedIssue {
            issue,
            fingerprint_issue_state: None,
        });
    }

    let issue = deps
        .issue_repository
        .insert_new(
            team_id,
            issue_name(properties),
            issue_description(properties),
        )
        .await?;
    let issue_override = deps
        .issue_repository
        .create_or_load_fingerprint(team_id, fingerprint, &issue, event_timestamp)
        .await?;

    let mut issue = issue;
    if issue_override.issue_id != issue.id {
        if let Some(result) = deps
            .issue_repository
            .load_by_fingerprint(team_id, fingerprint)
            .await?
        {
            let (existing, fingerprint_first_seen) = result.into_issue();
            issue = existing;
            if deps.issue_repository.maybe_reopen(&mut issue).await? {
                let first_seen = fingerprint_first_seen.unwrap_or(issue.created_at);
                let assignment = process_assignment(&issue, properties, deps).await?;
                deps.side_effects
                    .issue_reopened(&issue, assignment.as_ref(), properties, first_seen)
                    .await?;
                return Ok(LinkedIssue {
                    fingerprint_issue_state: Some(FingerprintIssueState::new(
                        &issue,
                        fingerprint,
                        assignment.as_ref(),
                        first_seen,
                    )),
                    issue,
                });
            }
        }
        return Ok(LinkedIssue {
            issue,
            fingerprint_issue_state: None,
        });
    }

    let assignment = process_assignment(&issue, properties, deps).await?;
    deps.side_effects
        .new_fingerprint(&issue, properties)
        .await?;
    deps.side_effects
        .issue_created(&issue, assignment.as_ref(), properties, event_timestamp)
        .await?;
    Ok(LinkedIssue {
        fingerprint_issue_state: Some(FingerprintIssueState::new(
            &issue,
            fingerprint,
            assignment.as_ref(),
            event_timestamp,
        )),
        issue,
    })
}

async fn load_and_maybe_reopen(
    properties: &LinkingExceptionProperties,
    team_id: i32,
    issue_id: Uuid,
    fingerprint: &str,
    deps: &LinkingDeps,
) -> Result<Option<LinkedIssue>, LinkingError> {
    let Some(mut issue) = deps.issue_repository.load(team_id, issue_id).await? else {
        return Ok(None);
    };

    if deps.issue_repository.maybe_reopen(&mut issue).await? {
        let assignment = process_assignment(&issue, properties, deps).await?;
        let first_seen = deps
            .issue_repository
            .load_by_fingerprint(team_id, fingerprint)
            .await?
            .and_then(|result| result.fingerprint_first_seen)
            .unwrap_or(issue.created_at);
        deps.side_effects
            .issue_reopened(&issue, assignment.as_ref(), properties, first_seen)
            .await?;
        return Ok(Some(LinkedIssue {
            fingerprint_issue_state: Some(FingerprintIssueState::new(
                &issue,
                fingerprint,
                assignment.as_ref(),
                first_seen,
            )),
            issue,
        }));
    }

    Ok(Some(LinkedIssue {
        issue,
        fingerprint_issue_state: None,
    }))
}

async fn process_assignment(
    issue: &Issue,
    properties: &LinkingExceptionProperties,
    deps: &LinkingDeps,
) -> Result<Option<Assignment>, LinkingError> {
    let new_assignment =
        evaluate_assignment_rules(issue, properties, deps.rule_repository.as_ref()).await?;
    if let Some(new_assignment) = new_assignment {
        return Ok(Some(
            deps.issue_repository
                .apply_assignment(&new_assignment, issue.id)
                .await?,
        ));
    }

    Ok(deps
        .issue_repository
        .existing_assignments(issue.id)
        .await?
        .first()
        .cloned())
}

async fn evaluate_assignment_rules(
    issue: &Issue,
    properties: &LinkingExceptionProperties,
    repository: &dyn LinkingRuleRepository,
) -> Result<Option<NewAssignment>, LinkingError> {
    let issue_json = serde_json::to_value(AssignmentIssue {
        team_id: issue.team_id,
        status: issue.status.to_string(),
        name: issue.name.clone(),
        description: issue.description.clone(),
    })?;
    let props_json = serde_json::to_value(properties)?;
    let mut rules = repository.assignment_rules(issue.team_id).await?;
    rules.sort_unstable_by_key(|rule| rule.order_key);

    for rule in rules {
        match rule.try_match(&issue_json, &props_json) {
            Ok(None) => continue,
            Ok(Some(new_assignment)) => return Ok(Some(new_assignment)),
            Err(VmError::OutOfResource(resource)) if resource == "steps" => {
                tracing::warn!(
                    rule_id = %rule.id,
                    team_id = %rule.team_id,
                    "assignment rule exceeded HogVM step budget for this event, skipping"
                );
                continue;
            }
            Err(error) => {
                repository
                    .disable_assignment_rule(
                        &rule,
                        error.to_string(),
                        issue_json.clone(),
                        props_json.clone(),
                    )
                    .await?;
            }
        }
    }

    Ok(None)
}

fn grouped_event_to_next_result(event: GroupedEvent) -> EventResult {
    EventResult {
        event_id: event.event_id,
        outcome: EventOutcome::Next {
            properties: Some(event.properties),
            metadata: event.metadata,
        },
    }
}

fn issue_name(properties: &LinkingExceptionProperties) -> String {
    properties
        .proposed_issue_name
        .clone()
        .or_else(|| {
            properties
                .exception_list
                .as_ref()
                .and_then(|exception_list| exception_list.0.first())
                .and_then(|exception| exception.exception_type.clone())
        })
        .unwrap_or_else(|| "Unknown exception".to_string())
}

fn issue_description(properties: &LinkingExceptionProperties) -> String {
    properties
        .proposed_issue_description
        .clone()
        .or_else(|| {
            properties
                .exception_list
                .as_ref()
                .and_then(|exception_list| exception_list.0.first())
                .and_then(|exception| exception.exception_message.clone())
        })
        .unwrap_or_default()
}

fn event_uuid(event_id: &str) -> Option<Uuid> {
    Uuid::parse_str(event_id).ok()
}

pub type LinkingExceptionProperties = ExceptionProperties;

#[cfg(test)]
mod tests {
    use std::collections::{HashMap, HashSet};
    use std::sync::Mutex;

    use chrono::Utc;
    use cymbal_core::{BatchContext, Metadata};
    use serde_json::json;

    use cymbal_core::{PipelineStage, StageInput};

    use super::*;

    #[derive(Default)]
    struct MockIssueRepository {
        issues: Mutex<HashMap<Uuid, Issue>>,
        fingerprints: Mutex<HashMap<(i32, String), Uuid>>,
        load_by_fingerprint_errors: Mutex<HashMap<String, String>>,
        assignments: Mutex<HashMap<Uuid, Vec<Assignment>>>,
        applied_assignments: Mutex<Vec<NewAssignment>>,
        race_issue_id: Mutex<Option<Uuid>>,
        load_calls: Mutex<usize>,
    }

    #[async_trait]
    impl IssueRepository for MockIssueRepository {
        async fn load_by_fingerprint(
            &self,
            team_id: i32,
            fingerprint: &str,
        ) -> Result<Option<IssueWithFirstSeen>, LinkingError> {
            if let Some(message) = self
                .load_by_fingerprint_errors
                .lock()
                .unwrap()
                .get(fingerprint)
                .cloned()
            {
                return Err(LinkingError::Repository(message));
            }
            let Some(issue_id) = self
                .fingerprints
                .lock()
                .unwrap()
                .get(&(team_id, fingerprint.to_string()))
                .copied()
            else {
                return Ok(None);
            };
            let issue = self.issues.lock().unwrap().get(&issue_id).cloned().unwrap();
            Ok(Some(IssueWithFirstSeen {
                id: issue.id,
                team_id: issue.team_id,
                status: issue.status,
                name: issue.name,
                description: issue.description,
                created_at: issue.created_at,
                fingerprint_first_seen: Some(issue.created_at),
            }))
        }

        async fn load(&self, team_id: i32, issue_id: Uuid) -> Result<Option<Issue>, LinkingError> {
            *self.load_calls.lock().unwrap() += 1;
            Ok(self
                .issues
                .lock()
                .unwrap()
                .get(&issue_id)
                .filter(|issue| issue.team_id == team_id)
                .cloned())
        }

        async fn insert_new(
            &self,
            team_id: i32,
            name: String,
            description: String,
        ) -> Result<Issue, LinkingError> {
            let issue = Issue {
                id: Uuid::now_v7(),
                team_id,
                status: IssueStatus::Active,
                name: Some(name),
                description: Some(description),
                created_at: Utc::now(),
            };
            self.issues.lock().unwrap().insert(issue.id, issue.clone());
            Ok(issue)
        }

        async fn maybe_reopen(&self, issue: &mut Issue) -> Result<bool, LinkingError> {
            if matches!(issue.status, IssueStatus::Active | IssueStatus::Suppressed) {
                return Ok(false);
            }
            issue.status = IssueStatus::Active;
            self.issues.lock().unwrap().insert(issue.id, issue.clone());
            Ok(true)
        }

        async fn create_or_load_fingerprint(
            &self,
            team_id: i32,
            fingerprint: &str,
            issue: &Issue,
            _first_seen: DateTime<Utc>,
        ) -> Result<IssueFingerprintOverride, LinkingError> {
            let mut race_issue_id = self.race_issue_id.lock().unwrap();
            let issue_id = race_issue_id.take().unwrap_or(issue.id);
            self.fingerprints
                .lock()
                .unwrap()
                .insert((team_id, fingerprint.to_string()), issue_id);
            Ok(IssueFingerprintOverride {
                id: Uuid::now_v7(),
                team_id,
                issue_id,
                fingerprint: fingerprint.to_string(),
                version: 0,
            })
        }

        async fn existing_assignments(
            &self,
            issue_id: Uuid,
        ) -> Result<Vec<Assignment>, LinkingError> {
            Ok(self
                .assignments
                .lock()
                .unwrap()
                .get(&issue_id)
                .cloned()
                .unwrap_or_default())
        }

        async fn apply_assignment(
            &self,
            new_assignment: &NewAssignment,
            issue_id: Uuid,
        ) -> Result<Assignment, LinkingError> {
            self.applied_assignments
                .lock()
                .unwrap()
                .push(new_assignment.clone());
            let assignment = Assignment {
                id: Uuid::now_v7(),
                issue_id,
                user_id: new_assignment.user_id,
                role_id: new_assignment.role_id,
                created_at: Utc::now(),
            };
            self.assignments
                .lock()
                .unwrap()
                .entry(issue_id)
                .or_default()
                .push(assignment.clone());
            Ok(assignment)
        }
    }

    #[derive(Default)]
    struct MockRuleRepository {
        suppression_rules: Vec<SuppressionRule>,
        assignment_rules: Vec<AssignmentRule>,
        disabled_suppression_rules: Mutex<Vec<Uuid>>,
        disabled_assignment_rules: Mutex<Vec<Uuid>>,
    }

    #[async_trait]
    impl LinkingRuleRepository for MockRuleRepository {
        async fn suppression_rules(
            &self,
            _team_id: i32,
        ) -> Result<Vec<SuppressionRule>, LinkingError> {
            Ok(self.suppression_rules.clone())
        }

        async fn disable_suppression_rule(
            &self,
            rule: &SuppressionRule,
            _message: String,
            _props: Value,
        ) -> Result<(), LinkingError> {
            self.disabled_suppression_rules
                .lock()
                .unwrap()
                .push(rule.id);
            Ok(())
        }

        async fn assignment_rules(
            &self,
            _team_id: i32,
        ) -> Result<Vec<AssignmentRule>, LinkingError> {
            Ok(self.assignment_rules.clone())
        }

        async fn disable_assignment_rule(
            &self,
            rule: &AssignmentRule,
            _message: String,
            _issue: Value,
            _props: Value,
        ) -> Result<(), LinkingError> {
            self.disabled_assignment_rules.lock().unwrap().push(rule.id);
            Ok(())
        }
    }

    #[derive(Default)]
    struct MockSideEffects {
        created: Mutex<Vec<Uuid>>,
        reopened: Mutex<Vec<Uuid>>,
        new_fingerprints: Mutex<Vec<Uuid>>,
    }

    #[async_trait]
    impl LinkingSideEffects for MockSideEffects {
        async fn issue_created(
            &self,
            issue: &Issue,
            _assignment: Option<&Assignment>,
            _properties: &LinkingExceptionProperties,
            _first_seen: DateTime<Utc>,
        ) -> Result<(), LinkingError> {
            self.created.lock().unwrap().push(issue.id);
            Ok(())
        }

        async fn issue_reopened(
            &self,
            issue: &Issue,
            _assignment: Option<&Assignment>,
            _properties: &LinkingExceptionProperties,
            _first_seen: DateTime<Utc>,
        ) -> Result<(), LinkingError> {
            self.reopened.lock().unwrap().push(issue.id);
            Ok(())
        }

        async fn new_fingerprint(
            &self,
            issue: &Issue,
            _properties: &LinkingExceptionProperties,
        ) -> Result<(), LinkingError> {
            self.new_fingerprints.lock().unwrap().push(issue.id);
            Ok(())
        }
    }

    fn rule_bytecode(expected_value: &str) -> Value {
        json!([
            "_H",
            1,
            32,
            expected_value,
            32,
            "test_value",
            32,
            "properties",
            1,
            2,
            11,
            38
        ])
    }

    fn suppression_rule(expected_value: &str) -> SuppressionRule {
        SuppressionRule {
            id: Uuid::now_v7(),
            team_id: 1,
            order_key: 1,
            bytecode: rule_bytecode(expected_value),
            sampling_rate: 1.0,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    fn assignment_rule(expected_value: &str, user_id: i32) -> AssignmentRule {
        AssignmentRule {
            id: Uuid::now_v7(),
            team_id: 1,
            user_id: Some(user_id),
            role_id: None,
            order_key: 1,
            bytecode: rule_bytecode(expected_value),
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    mod fixtures {
        use super::*;

        pub fn context() -> BatchContext {
            BatchContext {
                batch_id: "batch".to_string(),
                metadata: Metadata::new(),
            }
        }

        pub fn grouped_event(extra: Value) -> GroupedEvent {
            let mut properties = json!({
                "$exception_list": [{
                    "type": "Error",
                    "value": "boom"
                }],
                "$exception_fingerprint": "fingerprint",
                "$exception_proposed_fingerprint": "fingerprint",
                "$exception_fingerprint_record": [{ "type": "exception", "id": null, "pieces": ["Exception Type"] }]
            });
            properties.as_object_mut().unwrap().extend(
                extra
                    .as_object()
                    .unwrap()
                    .iter()
                    .map(|(key, value)| (key.clone(), value.clone())),
            );

            GroupedEvent {
                event_id: Uuid::now_v7().to_string(),
                team_id: 1,
                properties: ExceptionProperties::from_map(properties.as_object().unwrap().clone())
                    .unwrap(),
                metadata: Metadata::new(),
            }
        }
    }

    use fixtures::{context, grouped_event};

    async fn run_stage(stage: LinkingStage, event: GroupedEvent) -> EventResult {
        let output: Vec<EventResult> = stage
            .process(StageInput::from_items(context(), vec![event]))
            .await
            .unwrap();
        output.into_iter().next().unwrap()
    }

    #[tokio::test]
    async fn linking_stage_converts_grouped_events_to_next_results_without_deps() {
        let stage = LinkingStage::new();
        let event = grouped_event(json!({}));
        let expected_properties = event.properties.clone();

        let output = run_stage(stage, event).await;

        assert!(matches!(
            output.outcome,
            EventOutcome::Next {
                properties: Some(ref properties),
                ..
            } if properties == &expected_properties
        ));
    }

    #[tokio::test]
    async fn linking_creates_issue_and_writes_issue_id() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let side_effects = Arc::new(MockSideEffects::default());
        let deps =
            LinkingDeps::new(issue_repository.clone()).with_side_effects(side_effects.clone());
        let stage = LinkingStage::with_deps(deps);

        let output = run_stage(stage, grouped_event(json!({}))).await;

        let EventOutcome::Next {
            properties: Some(properties),
            metadata,
        } = output.outcome
        else {
            panic!("expected next outcome")
        };
        assert!(properties.issue_id.is_some());
        let state: Value = serde_json::from_str(
            metadata
                .get(FINGERPRINT_ISSUE_STATE_METADATA_KEY)
                .expect("expected fingerprint issue state metadata"),
        )
        .unwrap();
        assert_eq!(state["team_id"], 1);
        assert_eq!(state["fingerprint"], "fingerprint");
        assert_eq!(state["issue_status"], "active");
        assert_eq!(issue_repository.issues.lock().unwrap().len(), 1);
        assert_eq!(side_effects.created.lock().unwrap().len(), 1);
        assert_eq!(side_effects.new_fingerprints.lock().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn linking_reuses_existing_fingerprint_and_reopens_resolved_issue() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let issue = Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status: IssueStatus::Resolved,
            name: Some("existing".to_string()),
            description: Some("existing".to_string()),
            created_at: Utc::now(),
        };
        issue_repository
            .issues
            .lock()
            .unwrap()
            .insert(issue.id, issue.clone());
        issue_repository
            .fingerprints
            .lock()
            .unwrap()
            .insert((1, "fingerprint".to_string()), issue.id);
        let side_effects = Arc::new(MockSideEffects::default());
        let deps =
            LinkingDeps::new(issue_repository.clone()).with_side_effects(side_effects.clone());
        let stage = LinkingStage::with_deps(deps);

        let output = run_stage(stage, grouped_event(json!({}))).await;

        let EventOutcome::Next { metadata, .. } = output.outcome else {
            panic!("expected next outcome")
        };
        let state: Value = serde_json::from_str(
            metadata
                .get(FINGERPRINT_ISSUE_STATE_METADATA_KEY)
                .expect("expected fingerprint issue state metadata"),
        )
        .unwrap();
        assert_eq!(state["issue_id"], issue.id.to_string());
        assert_eq!(state["issue_status"], "active");
        assert_eq!(
            issue_repository
                .issues
                .lock()
                .unwrap()
                .get(&issue.id)
                .unwrap()
                .status,
            IssueStatus::Active
        );
        assert_eq!(&*side_effects.reopened.lock().unwrap(), &vec![issue.id]);
    }

    #[tokio::test]
    async fn linking_handles_fingerprint_create_race() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let existing_issue = Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status: IssueStatus::Active,
            name: Some("winner".to_string()),
            description: Some("winner".to_string()),
            created_at: Utc::now(),
        };
        issue_repository
            .issues
            .lock()
            .unwrap()
            .insert(existing_issue.id, existing_issue.clone());
        *issue_repository.race_issue_id.lock().unwrap() = Some(existing_issue.id);
        let deps = LinkingDeps::new(issue_repository.clone());
        let stage = LinkingStage::with_deps(deps);

        let output = run_stage(stage, grouped_event(json!({}))).await;

        let EventOutcome::Next {
            properties: Some(properties),
            ..
        } = output.outcome
        else {
            panic!("expected next outcome")
        };
        assert_eq!(properties.issue_id, Some(existing_issue.id));
    }

    #[tokio::test]
    async fn suppression_rules_drop_before_issue_linking() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let rules = Arc::new(MockRuleRepository {
            suppression_rules: vec![suppression_rule("match")],
            ..Default::default()
        });
        let deps = LinkingDeps::new(issue_repository.clone()).with_rule_repository(rules);
        let stage = LinkingStage::with_deps(deps);

        let output = run_stage(stage, grouped_event(json!({ "test_value": "match" }))).await;

        assert!(
            matches!(output.outcome, EventOutcome::Drop { reason } if reason.starts_with("suppressed_by_rule:"))
        );
        assert!(issue_repository.issues.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn suppression_sampling_without_uuid_does_not_fabricate_random_decisions() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let mut sampled_rule = suppression_rule("match");
        sampled_rule.sampling_rate = 0.5;
        let rules = Arc::new(MockRuleRepository {
            suppression_rules: vec![sampled_rule],
            ..Default::default()
        });
        let deps = LinkingDeps::new(issue_repository.clone()).with_rule_repository(rules);
        let stage = LinkingStage::with_deps(deps);
        let mut event = grouped_event(json!({ "test_value": "match" }));
        event.event_id = "not-a-uuid".to_string();

        let output = run_stage(stage, event).await;

        assert!(matches!(output.outcome, EventOutcome::Next { .. }));
        assert_eq!(issue_repository.issues.lock().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn linking_repository_errors_are_per_event_results() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        issue_repository
            .load_by_fingerprint_errors
            .lock()
            .unwrap()
            .insert(
                "bad-status".to_string(),
                "invalid issue status: snoozed".to_string(),
            );
        let stage = LinkingStage::with_deps(LinkingDeps::new(issue_repository));
        let input = StageInput::from_items(
            context(),
            vec![
                grouped_event(json!({ "$exception_fingerprint": "bad-status" })),
                grouped_event(json!({ "$exception_fingerprint": "ok-status" })),
            ],
        );

        let output: Vec<EventResult> = stage.process(input).await.unwrap();

        assert_eq!(output.len(), 2);
        assert!(matches!(
            output[0].outcome,
            EventOutcome::Error { ref message, .. }
                if message.contains("invalid issue status: snoozed")
        ));
        assert!(matches!(output[1].outcome, EventOutcome::Next { .. }));
    }

    #[tokio::test]
    async fn suppressed_issue_drops_after_linking() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let issue = Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status: IssueStatus::Suppressed,
            name: Some("suppressed".to_string()),
            description: Some("suppressed".to_string()),
            created_at: Utc::now(),
        };
        issue_repository
            .issues
            .lock()
            .unwrap()
            .insert(issue.id, issue.clone());
        issue_repository
            .fingerprints
            .lock()
            .unwrap()
            .insert((1, "fingerprint".to_string()), issue.id);
        let stage = LinkingStage::with_deps(LinkingDeps::new(issue_repository));

        let output = run_stage(stage, grouped_event(json!({}))).await;

        assert!(
            matches!(output.outcome, EventOutcome::Drop { reason } if reason == "suppressed_issue")
        );
    }

    #[tokio::test]
    async fn assignment_rules_are_applied_for_new_issue() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let rules = Arc::new(MockRuleRepository {
            assignment_rules: vec![assignment_rule("match", 7)],
            ..Default::default()
        });
        let stage = LinkingStage::with_deps(
            LinkingDeps::new(issue_repository.clone()).with_rule_repository(rules),
        );

        let output = run_stage(stage, grouped_event(json!({ "test_value": "match" }))).await;

        assert!(matches!(output.outcome, EventOutcome::Next { .. }));
        let applied = issue_repository.applied_assignments.lock().unwrap();
        assert_eq!(applied.len(), 1);
        assert_eq!(applied[0].user_id, Some(7));
    }

    #[tokio::test]
    async fn batch_issue_cache_deduplicates_same_fingerprint() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let stage = LinkingStage::with_deps(LinkingDeps::new(issue_repository.clone()));
        let input = StageInput::from_items(
            context(),
            vec![grouped_event(json!({})), grouped_event(json!({}))],
        );

        let output: Vec<EventResult> = stage.process(input).await.unwrap();

        assert_eq!(output.len(), 2);
        assert_eq!(issue_repository.issues.lock().unwrap().len(), 1);
        let issue_ids = output
            .into_iter()
            .map(|result| match result.outcome {
                EventOutcome::Next {
                    properties: Some(properties),
                    ..
                } => json!(properties.issue_id.expect("expected issue id")),
                _ => panic!("expected next"),
            })
            .collect::<HashSet<_>>();
        assert_eq!(issue_ids.len(), 1);
    }

    /// The `issue_cache` on `LinkingDeps` persists issue IDs across `process()` calls on
    /// different stage instances that share the same deps. A second call on a fresh stage
    /// (new `batch_issue_cache`) should resolve through the `issue_cache` — calling
    /// `load()` on the repository rather than `load_by_fingerprint()`.
    #[tokio::test]
    async fn issue_cache_reuses_issue_between_batches() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let deps = LinkingDeps::new(issue_repository.clone());

        // First stage run: populates both batch_issue_cache and issue_cache.
        let stage1 = LinkingStage::with_deps(deps.clone());
        let output1 = run_stage(stage1, grouped_event(json!({}))).await;
        assert!(matches!(output1.outcome, EventOutcome::Next { .. }));
        assert_eq!(issue_repository.issues.lock().unwrap().len(), 1);
        // The issue_cache path calls load(); first run goes through fetch_or_create so no load() yet.
        assert_eq!(*issue_repository.load_calls.lock().unwrap(), 0);

        // Second stage run: fresh batch_issue_cache, but same issue_cache via cloned deps.
        // load() should be called exactly once (issue_cache hit → load_and_maybe_reopen).
        let stage2 = LinkingStage::with_deps(deps);
        let output2 = run_stage(stage2, grouped_event(json!({}))).await;
        assert!(matches!(output2.outcome, EventOutcome::Next { .. }));

        assert_eq!(issue_repository.issues.lock().unwrap().len(), 1);
        assert_eq!(*issue_repository.load_calls.lock().unwrap(), 1);
    }

    /// A suppression rule whose HogVM bytecode is not an array triggers a `VmError::Other`
    /// (not a step-budget error). The rule must be disabled and the event must continue
    /// unaffected — it must NOT be suppressed.
    #[tokio::test]
    async fn invalid_suppression_rule_is_disabled_on_vm_error() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let rule = SuppressionRule {
            id: Uuid::now_v7(),
            team_id: 1,
            order_key: 1,
            bytecode: json!("not_an_array"),
            sampling_rate: 1.0,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        };
        let rule_id = rule.id;
        let rules = Arc::new(MockRuleRepository {
            suppression_rules: vec![rule],
            ..Default::default()
        });
        let stage = LinkingStage::with_deps(
            LinkingDeps::new(issue_repository.clone()).with_rule_repository(rules.clone()),
        );

        let output = run_stage(stage, grouped_event(json!({ "test_value": "match" }))).await;

        // Event continues — rule is disabled, not applied.
        assert!(matches!(output.outcome, EventOutcome::Next { .. }));
        assert!(rules
            .disabled_suppression_rules
            .lock()
            .unwrap()
            .contains(&rule_id));
    }

    /// An assignment rule whose HogVM bytecode is not an array triggers a `VmError::Other`.
    /// The rule must be disabled and the event must continue without applying the assignment.
    #[tokio::test]
    async fn invalid_assignment_rule_is_disabled_on_vm_error() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let rule = AssignmentRule {
            id: Uuid::now_v7(),
            team_id: 1,
            user_id: Some(42),
            role_id: None,
            order_key: 1,
            bytecode: json!("not_an_array"),
            created_at: Utc::now(),
            updated_at: Utc::now(),
        };
        let rule_id = rule.id;
        let rules = Arc::new(MockRuleRepository {
            assignment_rules: vec![rule],
            ..Default::default()
        });
        let stage = LinkingStage::with_deps(
            LinkingDeps::new(issue_repository.clone()).with_rule_repository(rules.clone()),
        );

        let output = run_stage(stage, grouped_event(json!({}))).await;

        // Event continues — rule is disabled, no assignment applied.
        assert!(matches!(output.outcome, EventOutcome::Next { .. }));
        assert_eq!(
            issue_repository.applied_assignments.lock().unwrap().len(),
            0
        );
        assert!(rules
            .disabled_assignment_rules
            .lock()
            .unwrap()
            .contains(&rule_id));
    }

    /// When no assignment rule matches, `process_assignment` falls back to the issue's
    /// existing assignments. For a reopened issue the existing assignment must appear in
    /// the `FingerprintIssueState` metadata so downstream consumers can use it.
    #[tokio::test]
    async fn existing_assignment_used_when_no_rule_matches() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let issue = Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status: IssueStatus::Resolved,
            name: Some("existing".to_string()),
            description: Some("existing".to_string()),
            created_at: Utc::now(),
        };
        issue_repository
            .issues
            .lock()
            .unwrap()
            .insert(issue.id, issue.clone());
        issue_repository
            .fingerprints
            .lock()
            .unwrap()
            .insert((1, "fingerprint".to_string()), issue.id);
        let existing_assignment = Assignment {
            id: Uuid::now_v7(),
            issue_id: issue.id,
            user_id: Some(99),
            role_id: None,
            created_at: Utc::now(),
        };
        issue_repository
            .assignments
            .lock()
            .unwrap()
            .insert(issue.id, vec![existing_assignment]);

        // No assignment rules — must fall back to existing assignment.
        let stage = LinkingStage::with_deps(LinkingDeps::new(issue_repository));
        let output = run_stage(stage, grouped_event(json!({}))).await;

        let EventOutcome::Next { metadata, .. } = output.outcome else {
            panic!("expected next outcome")
        };
        // Issue was reopened, so fingerprint_issue_state metadata must be present.
        let state: Value = serde_json::from_str(
            metadata
                .get(FINGERPRINT_ISSUE_STATE_METADATA_KEY)
                .expect("expected fingerprint issue state metadata"),
        )
        .unwrap();
        // Existing assignment user_id must be reflected in the state.
        assert_eq!(state["assigned_user_id"], 99);
        // No new assignment was applied — we fell back to the pre-existing one.
        // (apply_assignment is not called, so applied_assignments stays empty)
    }

    /// A suppressed issue must produce a `Drop` outcome and must not fire any
    /// `issue_created`, `issue_reopened`, or `new_fingerprint` side effects.
    #[tokio::test]
    async fn suppressed_issue_fires_no_side_effects() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let issue = Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status: IssueStatus::Suppressed,
            name: Some("suppressed".to_string()),
            description: Some("suppressed".to_string()),
            created_at: Utc::now(),
        };
        issue_repository
            .issues
            .lock()
            .unwrap()
            .insert(issue.id, issue.clone());
        issue_repository
            .fingerprints
            .lock()
            .unwrap()
            .insert((1, "fingerprint".to_string()), issue.id);
        let side_effects = Arc::new(MockSideEffects::default());
        let stage = LinkingStage::with_deps(
            LinkingDeps::new(issue_repository).with_side_effects(side_effects.clone()),
        );

        let output = run_stage(stage, grouped_event(json!({}))).await;

        assert!(
            matches!(&output.outcome, EventOutcome::Drop { reason } if reason == "suppressed_issue")
        );
        assert!(side_effects.created.lock().unwrap().is_empty());
        assert!(side_effects.reopened.lock().unwrap().is_empty());
        assert!(side_effects.new_fingerprints.lock().unwrap().is_empty());
    }

    /// An existing active issue that does not need reopening must produce a `Next` outcome
    /// with NO `FingerprintIssueState` in the metadata — state is only written for new or
    /// reopened issues.
    #[tokio::test]
    async fn active_existing_issue_has_no_fingerprint_state_metadata() {
        let issue_repository = Arc::new(MockIssueRepository::default());
        let issue = Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status: IssueStatus::Active,
            name: Some("existing".to_string()),
            description: Some("existing".to_string()),
            created_at: Utc::now(),
        };
        issue_repository
            .issues
            .lock()
            .unwrap()
            .insert(issue.id, issue.clone());
        issue_repository
            .fingerprints
            .lock()
            .unwrap()
            .insert((1, "fingerprint".to_string()), issue.id);
        let stage = LinkingStage::with_deps(LinkingDeps::new(issue_repository));

        let output = run_stage(stage, grouped_event(json!({}))).await;

        let EventOutcome::Next {
            properties: Some(properties),
            metadata,
        } = output.outcome
        else {
            panic!("expected next outcome")
        };
        assert_eq!(properties.issue_id, Some(issue.id));
        assert!(
            !metadata.contains_key(FINGERPRINT_ISSUE_STATE_METADATA_KEY),
            "active existing issue must not produce fingerprint_issue_state metadata"
        );
    }
}
