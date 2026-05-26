use std::collections::HashMap;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use common_types::TeamId;
use hogvm::{ExecutionContext, Program, StepOutcome, VmError};
use serde::Serialize;
use serde_json::Value;
use uuid::Uuid;

use crate::{
    assignment::NewAssignment, CUSTOM_GROUPED_EVENTS, GROUPING_RULES_DISABLED,
    GROUPING_RULES_FOUND, GROUPING_RULES_PROCESSING_TIME, GROUPING_RULES_TRIED,
};

#[derive(Debug, Clone)]
pub struct GroupingRule {
    pub id: Uuid,
    pub team_id: TeamId,

    // If a rule has been custom grouped, it might also be auto-assigned
    pub user_id: Option<i32>,
    pub role_id: Option<Uuid>,
    pub order_key: i32,
    pub bytecode: Value,
    // We don't bother loading the original filter, as we never use it in cymbal
    //pub filters: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GroupingRuleDisabledData {
    pub message: String,
    pub props: Value,
}

#[async_trait(?Send)]
pub trait GroupingRuleRepository {
    type Error;

    async fn grouping_rules(&mut self, team_id: TeamId) -> Result<Vec<GroupingRule>, Self::Error>;

    async fn disable_grouping_rule(
        &mut self,
        rule: &GroupingRule,
        disabled_data: GroupingRuleDisabledData,
    ) -> Result<(), Self::Error>;
}

impl GroupingRule {
    pub fn try_match(&self, props: &Value) -> Result<bool, VmError> {
        let rule_bytecode = match &self.bytecode {
            Value::Array(ops) => ops,
            _ => {
                return Err(VmError::Other(format!(
                    "Invalid rule bytecode - expected array, got {:?}",
                    self.bytecode
                )))
            }
        };

        let mut globals = HashMap::new();
        globals.insert("properties".to_string(), props.clone());
        let globals: Value = serde_json::to_value(globals)
            .expect("Can construct a json object from a hashmap of String:JsonValue");
        let program = Program::new(rule_bytecode.clone())?;
        let context = ExecutionContext::with_defaults(program).with_globals(globals);
        let mut vm = context.to_vm()?;

        metrics::counter!(GROUPING_RULES_TRIED).increment(1);

        let mut i = 0;
        while i < context.max_steps {
            let step_result = vm.step()?;
            match step_result {
                StepOutcome::Finished(Value::Bool(b)) => return Ok(b),
                StepOutcome::Finished(res) => {
                    return Err(VmError::Other(format!(
                        "Grouping rule returned {res:?}, expected a boolean value"
                    )))
                }
                StepOutcome::NativeCall(name, args) => {
                    context.execute_native_function_call(&mut vm, &name, args)?
                }
                StepOutcome::Continue => {}
            }
            i += 1;
        }

        Err(VmError::OutOfResource("steps".to_string()))
    }

    pub fn assignment(&self) -> Option<NewAssignment> {
        NewAssignment::try_new(self.user_id, self.role_id)
    }
}

pub async fn evaluate_grouping_rules<R: GroupingRuleRepository>(
    repository: &mut R,
    team_id: TeamId,
    props: Value,
) -> Result<Option<GroupingRule>, R::Error> {
    let timing = common_metrics::timing_guard(GROUPING_RULES_PROCESSING_TIME, &[]);

    let mut rules = repository.grouping_rules(team_id).await?;

    metrics::counter!(GROUPING_RULES_FOUND).increment(rules.len() as u64);

    rules.sort_unstable_by_key(|r| r.order_key);

    for rule in rules {
        match rule.try_match(&props) {
            Ok(false) => continue,
            Ok(true) => {
                timing.label("outcome", "match").fin();
                metrics::counter!(CUSTOM_GROUPED_EVENTS).increment(1);
                return Ok(Some(rule));
            }
            // See assignment rules for the rationale: step-budget exhaustion
            // is a per-event cost issue, not a logic bug in the rule. Skip this rule
            // for this event rather than disabling it permanently. Other
            // `OutOfResource` variants still fall through to the disable path.
            Err(VmError::OutOfResource(resource)) if resource == "steps" => {
                tracing::warn!(
                    rule_id = %rule.id,
                    team_id = %rule.team_id,
                    "grouping rule exceeded HogVM step budget for this event, skipping"
                );
                continue;
            }
            Err(err) => {
                repository
                    .disable_grouping_rule(
                        &rule,
                        GroupingRuleDisabledData {
                            message: err.to_string(),
                            props: props.clone(),
                        },
                    )
                    .await?;
                metrics::counter!(GROUPING_RULES_DISABLED).increment(1);
            }
        }
    }

    timing.label("outcome", "no_match").fin();

    Ok(None)
}

#[cfg(test)]
mod test {
    use chrono::Utc;
    use serde_json::{json, Value as JsonValue};
    use uuid::Uuid;

    use super::GroupingRule;

    fn rule_bytecode() -> JsonValue {
        // return properties.test_value = 'test_value'
        json!([
            "_H",
            1,
            32,
            "test_value",
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

    fn get_test_rule() -> GroupingRule {
        GroupingRule {
            id: Uuid::new_v4(),
            team_id: 1,
            user_id: None,
            role_id: None,
            order_key: 1,
            bytecode: rule_bytecode(),
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    #[test]
    fn test_try_match_returns_true_on_match() {
        let rule = get_test_rule();
        let props = json!({"test_value": "test_value"});
        assert!(rule.try_match(&props).unwrap());
    }

    #[test]
    fn test_try_match_returns_false_on_no_match() {
        let rule = get_test_rule();
        let props = json!({"test_value": "other_value"});
        assert!(!rule.try_match(&props).unwrap());
    }

    #[test]
    fn test_try_match_returns_error_on_invalid_bytecode() {
        let mut rule = get_test_rule();
        rule.bytecode = json!("not_an_array");
        let props = json!({"test_value": "test_value"});
        assert!(rule.try_match(&props).is_err());
    }
}
