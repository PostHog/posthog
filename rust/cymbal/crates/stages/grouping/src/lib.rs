//! Cymbal grouping stage crate.
//!
//! This crate owns exception fingerprint selection: custom grouping rules take
//! precedence over automatic fingerprints, and manual `$exception_fingerprint`
//! overrides still win at the integration boundary.

use std::sync::Arc;

use async_trait::async_trait;
use cymbal_core::{
    run_buffered, Metadata, PipelineStage, StageConcurrencyLimiter, StageError, StageInput,
    StagePayload, StageType,
};
use cymbal_domain::ExceptionProperties;
use cymbal_fingerprinting::Fingerprint;
use cymbal_resolution::ResolvedEvent;
use cymbal_rules::GroupingRule;
use hogvm::VmError;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

pub const GROUPING_STAGE_ID: &str = "grouping:v1";
pub const GROUPING_STAGE_TYPE: StageType = StageType {
    namespace: "cymbal.stage",
    name: "grouping",
    version: 1,
};
const DEFAULT_GROUPING_STAGE_CONCURRENCY: usize = 16;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GroupedEvent {
    pub event_id: String,
    pub team_id: i64,
    pub properties: ExceptionProperties,
    pub metadata: Metadata,
}

impl StagePayload for GroupedEvent {
    const TYPE: StageType = StageType {
        namespace: "cymbal.grouping",
        name: "GroupedEvent",
        version: 2,
    };
}

impl GroupedEvent {
    pub fn from_resolved_event(event: ResolvedEvent) -> Self {
        Self {
            event_id: event.event_id,
            team_id: event.team_id,
            properties: event.properties,
            metadata: event.metadata,
        }
    }
}

#[derive(Debug, Error)]
pub enum GroupingError {
    #[error("grouping rule repository error: {0}")]
    Repository(String),
    #[error("serde error: {0}")]
    Serde(#[from] serde_json::Error),
}

#[async_trait]
pub trait GroupingRuleRepository: Send + Sync {
    async fn grouping_rules(&self, team_id: i32) -> Result<Vec<GroupingRule>, GroupingError>;

    async fn disable_grouping_rule(
        &self,
        rule: &GroupingRule,
        message: String,
        props: Value,
    ) -> Result<(), GroupingError>;
}

#[derive(Debug, Default)]
pub struct NoopGroupingRuleRepository;

#[async_trait]
impl GroupingRuleRepository for NoopGroupingRuleRepository {
    async fn grouping_rules(&self, _team_id: i32) -> Result<Vec<GroupingRule>, GroupingError> {
        Ok(Vec::new())
    }

    async fn disable_grouping_rule(
        &self,
        _rule: &GroupingRule,
        _message: String,
        _props: Value,
    ) -> Result<(), GroupingError> {
        Ok(())
    }
}

#[derive(Clone)]
pub struct GroupingDeps {
    pub grouping_rules: Arc<dyn GroupingRuleRepository>,
    pub stage_concurrency_limiter: StageConcurrencyLimiter,
}

impl std::fmt::Debug for GroupingDeps {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("GroupingDeps")
            .field("grouping_rules", &"<dyn GroupingRuleRepository>")
            .field(
                "stage_concurrency",
                &self.stage_concurrency_limiter.capacity(),
            )
            .field(
                "stage_concurrency_limiter_available_permits",
                &self.stage_concurrency_limiter.available_permits(),
            )
            .finish()
    }
}

impl Default for GroupingDeps {
    fn default() -> Self {
        Self {
            grouping_rules: Arc::new(NoopGroupingRuleRepository),
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_GROUPING_STAGE_CONCURRENCY,
            ),
        }
    }
}

impl GroupingDeps {
    pub fn new(grouping_rules: Arc<dyn GroupingRuleRepository>) -> Self {
        Self {
            grouping_rules,
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_GROUPING_STAGE_CONCURRENCY,
            ),
        }
    }

    pub fn with_stage_concurrency(mut self, stage_concurrency: usize) -> Self {
        self.stage_concurrency_limiter = StageConcurrencyLimiter::new(stage_concurrency);
        self
    }
}

#[derive(Clone, Debug, Default)]
pub struct GroupingStage {
    deps: GroupingDeps,
}

impl GroupingStage {
    pub fn new() -> Self {
        Self::with_deps(GroupingDeps::default())
    }

    pub fn with_deps(deps: GroupingDeps) -> Self {
        Self { deps }
    }

    async fn group_event(&self, event: ResolvedEvent) -> Result<GroupedEvent, StageError> {
        let properties = group_properties(event.properties, event.team_id, self.deps.clone())
            .await
            .map_err(grouping_error_to_stage_error)?;
        Ok(GroupedEvent {
            event_id: event.event_id,
            team_id: event.team_id,
            properties,
            metadata: event.metadata,
        })
    }
}

#[async_trait]
impl PipelineStage for GroupingStage {
    type Input = ResolvedEvent;
    type Output = GroupedEvent;

    fn id(&self) -> StageType {
        GROUPING_STAGE_TYPE
    }

    async fn process(
        &self,
        input: StageInput<Self::Input>,
    ) -> Result<Vec<Self::Output>, StageError> {
        let stage = self.clone();
        run_buffered(
            &self.deps.stage_concurrency_limiter,
            input.items,
            move |event| {
                let stage = stage.clone();
                async move { stage.group_event(event).await }
            },
        )
        .await
    }
}

async fn group_properties(
    mut event: ExceptionProperties,
    team_id: i64,
    deps: GroupingDeps,
) -> Result<ExceptionProperties, GroupingError> {
    let Some(exception_list) = event.exception_list.as_ref() else {
        return Ok(event);
    };
    if exception_list.is_empty() {
        return Ok(event);
    }

    let props_json = serde_json::to_value(&event)?;

    let proposed_fingerprint =
        match find_matching_rule(deps.grouping_rules.as_ref(), team_id as i32, props_json).await? {
            Some(rule) => Fingerprint::from_rule(rule),
            None => Fingerprint::from_exception_list(exception_list),
        };

    event.proposed_fingerprint = Some(proposed_fingerprint.value.clone());

    if let Some(manual_fingerprint) = event.fingerprint.as_deref() {
        let mut fingerprint = proposed_fingerprint;
        fingerprint.apply_manual_override(manual_fingerprint);
        event.fingerprint = Some(fingerprint.value);
        event.fingerprint_record = Some(fingerprint.record);
    } else {
        event.fingerprint = Some(proposed_fingerprint.value);
        event.fingerprint_record = Some(proposed_fingerprint.record);
    }

    Ok(event)
}

async fn find_matching_rule(
    repository: &dyn GroupingRuleRepository,
    team_id: i32,
    props: Value,
) -> Result<Option<GroupingRule>, GroupingError> {
    let mut rules = repository.grouping_rules(team_id).await?;
    rules.sort_unstable_by_key(|rule| rule.order_key);

    for rule in rules {
        match rule.try_match(&props) {
            Ok(false) => continue,
            Ok(true) => return Ok(Some(rule)),
            Err(VmError::OutOfResource(resource)) if resource == "steps" => {
                tracing::warn!(
                    rule_id = %rule.id,
                    team_id = %rule.team_id,
                    "grouping rule exceeded HogVM step budget for this event, skipping"
                );
                continue;
            }
            Err(error) => {
                repository
                    .disable_grouping_rule(&rule, error.to_string(), props.clone())
                    .await?;
            }
        }
    }

    Ok(None)
}

fn grouping_error_to_stage_error(error: GroupingError) -> StageError {
    StageError::Transient(error.to_string())
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use chrono::Utc;
    use cymbal_core::{BatchContext, PipelineStage, StageInput};
    use serde_json::json;
    use uuid::Uuid;

    use super::*;

    #[derive(Debug, Default)]
    struct StaticGroupingRuleRepository {
        rules: Vec<GroupingRule>,
        disabled_rules: Mutex<Vec<Uuid>>,
    }

    #[async_trait]
    impl GroupingRuleRepository for StaticGroupingRuleRepository {
        async fn grouping_rules(&self, _team_id: i32) -> Result<Vec<GroupingRule>, GroupingError> {
            Ok(self.rules.clone())
        }

        async fn disable_grouping_rule(
            &self,
            rule: &GroupingRule,
            _message: String,
            _props: Value,
        ) -> Result<(), GroupingError> {
            self.disabled_rules.lock().unwrap().push(rule.id);
            Ok(())
        }
    }

    fn rule_bytecode(expected_value: &str) -> Value {
        // return properties.test_value = expected_value
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

    fn grouping_rule(order_key: i32, expected_value: &str) -> GroupingRule {
        GroupingRule {
            id: Uuid::new_v4(),
            team_id: 1,
            user_id: None,
            role_id: None,
            order_key,
            bytecode: rule_bytecode(expected_value),
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    mod fixtures {
        use super::*;

        pub fn context() -> BatchContext {
            BatchContext {
                batch_id: "batch-1".to_string(),
                metadata: Metadata::new(),
            }
        }

        pub fn resolved_event(properties: Value) -> ResolvedEvent {
            ResolvedEvent {
                event_id: "event-1".to_string(),
                team_id: 1,
                properties: ExceptionProperties::from_map(properties.as_object().unwrap().clone())
                    .unwrap(),
                metadata: Metadata::new(),
            }
        }
    }

    use fixtures::{context, resolved_event};

    fn exception_properties(extra: Value) -> Value {
        let mut properties = json!({
            "$exception_list": [{
                "type": "Error",
                "value": "boom",
                "stacktrace": {
                    "type": "resolved",
                    "frames": [{
                        "raw_id": "raw/0",
                        "source": "app.js",
                        "function": "runExample",
                        "in_app": true,
                        "resolved": false,
                        "lang": "javascript"
                    }]
                }
            }]
        });
        properties.as_object_mut().unwrap().extend(
            extra
                .as_object()
                .unwrap()
                .iter()
                .map(|(key, value)| (key.clone(), value.clone())),
        );
        properties
    }

    #[tokio::test]
    async fn grouping_stage_adds_automatic_fingerprint_fields() {
        let stage = GroupingStage::new();
        let input = StageInput::from_items(
            context(),
            vec![resolved_event(exception_properties(json!({})))],
        );

        let output: Vec<GroupedEvent> = stage.process(input).await.unwrap();
        let payload = serde_json::to_value(&output[0].properties).unwrap();

        let fingerprint = payload
            .pointer("/$exception_fingerprint")
            .and_then(Value::as_str)
            .unwrap();
        assert_eq!(fingerprint.len(), 128);
        assert_eq!(
            payload.pointer("/$exception_proposed_fingerprint"),
            Some(&json!(fingerprint))
        );
        assert_eq!(
            payload.pointer("/$exception_fingerprint_record/0/type"),
            Some(&json!("exception"))
        );
    }

    #[tokio::test]
    async fn manual_fingerprint_overrides_computed_fingerprint_but_keeps_proposal() {
        let stage = GroupingStage::new();
        let input = StageInput::from_items(
            context(),
            vec![resolved_event(exception_properties(json!({
                "$exception_fingerprint": "manual-fingerprint"
            })))],
        );

        let output: Vec<GroupedEvent> = stage.process(input).await.unwrap();
        let payload = serde_json::to_value(&output[0].properties).unwrap();

        assert_eq!(
            payload.pointer("/$exception_fingerprint"),
            Some(&json!("manual-fingerprint"))
        );
        assert_ne!(
            payload.pointer("/$exception_proposed_fingerprint"),
            Some(&json!("manual-fingerprint"))
        );
        assert_eq!(
            payload.pointer("/$exception_fingerprint_record"),
            Some(&json!([{ "type": "manual" }]))
        );
    }

    #[tokio::test]
    async fn custom_grouping_rules_take_precedence_by_order_key() {
        let later_rule = grouping_rule(2, "match");
        let earlier_rule = grouping_rule(1, "match");
        let repository = Arc::new(StaticGroupingRuleRepository {
            rules: vec![later_rule, earlier_rule.clone()],
            disabled_rules: Mutex::new(Vec::new()),
        });
        let stage = GroupingStage::with_deps(GroupingDeps::new(repository));
        let input = StageInput::from_items(
            context(),
            vec![resolved_event(exception_properties(json!({
                "test_value": "match"
            })))],
        );

        let output: Vec<GroupedEvent> = stage.process(input).await.unwrap();
        let payload = serde_json::to_value(&output[0].properties).unwrap();

        assert_eq!(
            payload.pointer("/$exception_fingerprint"),
            Some(&json!(format!("custom-rule:{}", earlier_rule.id)))
        );
        assert_eq!(
            payload.pointer("/$exception_fingerprint_record"),
            Some(&json!([{ "type": "custom", "rule_id": earlier_rule.id }]))
        );
    }

    #[tokio::test]
    async fn grouping_rule_with_invalid_bytecode_is_disabled_and_fallback_fingerprint_used() {
        let bad_rule = GroupingRule {
            bytecode: json!("not_an_array"),
            ..grouping_rule(1, "match")
        };
        let repository = Arc::new(StaticGroupingRuleRepository {
            rules: vec![bad_rule.clone()],
            disabled_rules: Mutex::new(Vec::new()),
        });
        let stage = GroupingStage::with_deps(GroupingDeps::new(repository.clone()));
        let input = StageInput::from_items(
            context(),
            vec![resolved_event(exception_properties(json!({
                "test_value": "match"
            })))],
        );

        let output: Vec<GroupedEvent> = stage.process(input).await.unwrap();
        let payload = serde_json::to_value(&output[0].properties).unwrap();

        assert_eq!(
            repository.disabled_rules.lock().unwrap().as_slice(),
            [bad_rule.id],
            "a rule whose bytecode is not a JSON array must be disabled"
        );
        let fingerprint = payload
            .pointer("/$exception_fingerprint")
            .and_then(Value::as_str)
            .expect("fallback fingerprint must be set after disabling the only rule");
        assert!(
            !fingerprint.starts_with("custom-rule:"),
            "disabled rule must not produce a custom-rule fingerprint"
        );
    }

    #[tokio::test]
    async fn grouping_rule_exceeding_hog_step_budget_is_skipped_without_disabling() {
        // Bytecode that loops forever: Jump opcode with offset -2 produces an
        // infinite loop that exhausts the HogVM step budget and returns
        // VmError::OutOfResource("steps"). The stage must skip the rule for
        // this event without permanently disabling it.
        let looping_rule = GroupingRule {
            bytecode: json!(["_H", 1, 39, -2]),
            ..grouping_rule(1, "match")
        };
        let repository = Arc::new(StaticGroupingRuleRepository {
            rules: vec![looping_rule.clone()],
            disabled_rules: Mutex::new(Vec::new()),
        });
        let stage = GroupingStage::with_deps(GroupingDeps::new(repository.clone()));
        let input = StageInput::from_items(
            context(),
            vec![resolved_event(exception_properties(json!({})))],
        );

        let output: Vec<GroupedEvent> = stage.process(input).await.unwrap();
        let payload = serde_json::to_value(&output[0].properties).unwrap();

        assert!(
            repository.disabled_rules.lock().unwrap().is_empty(),
            "a step-budget-exhausted rule must NOT be permanently disabled"
        );
        let fingerprint = payload
            .pointer("/$exception_fingerprint")
            .and_then(Value::as_str)
            .expect("automatic fallback fingerprint must be computed after skipping the rule");
        assert!(
            !fingerprint.starts_with("custom-rule:"),
            "skipped rule must fall back to automatic fingerprint"
        );
    }

    #[tokio::test]
    async fn event_with_no_exception_list_passes_through_without_fingerprint() {
        let stage = GroupingStage::new();
        let input = StageInput::from_items(
            context(),
            vec![ResolvedEvent {
                event_id: "event-1".to_string(),
                team_id: 1,
                properties: ExceptionProperties::default(),
                metadata: Metadata::new(),
            }],
        );

        let output: Vec<GroupedEvent> = stage.process(input).await.unwrap();
        let payload = serde_json::to_value(&output[0].properties).unwrap();

        assert!(
            payload.pointer("/$exception_fingerprint").is_none(),
            "an event with no exception list must not receive a fingerprint"
        );
    }

    #[tokio::test]
    async fn event_with_empty_exception_list_passes_through_without_fingerprint() {
        let stage = GroupingStage::new();
        let props = ExceptionProperties::from_map(
            json!({ "$exception_list": [] })
                .as_object()
                .unwrap()
                .clone(),
        )
        .unwrap();
        let input = StageInput::from_items(
            context(),
            vec![ResolvedEvent {
                event_id: "event-1".to_string(),
                team_id: 1,
                properties: props,
                metadata: Metadata::new(),
            }],
        );

        let output: Vec<GroupedEvent> = stage.process(input).await.unwrap();
        let payload = serde_json::to_value(&output[0].properties).unwrap();

        assert!(
            payload.pointer("/$exception_fingerprint").is_none(),
            "an event with an empty exception list must not receive a fingerprint"
        );
    }
}
