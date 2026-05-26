use std::collections::HashMap;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use common_types::TeamId;
use hogvm::{ExecutionContext, Program, StepOutcome, VmError};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    ASSIGNMENT_RULES_DISABLED, ASSIGNMENT_RULES_FOUND, ASSIGNMENT_RULES_PROCESSING_TIME,
    ASSIGNMENT_RULES_TRIED, AUTO_ASSIGNMENTS,
};

#[derive(Debug, Clone)]
pub struct NewAssignment {
    pub user_id: Option<i32>,
    pub role_id: Option<Uuid>,
}

impl NewAssignment {
    // Returns None if this cannot be used to construct a valid assignment, ensuring all
    // NewAssignments have at least one of user_id or role_id set.
    pub fn try_new(user_id: Option<i32>, role_id: Option<Uuid>) -> Option<Self> {
        if user_id.is_none() && role_id.is_none() {
            None
        } else {
            Some(NewAssignment { user_id, role_id })
        }
    }
}

#[derive(Debug, Clone)]
pub struct Assignment {
    pub id: Uuid,
    pub issue_id: Uuid,
    pub user_id: Option<i32>,
    pub role_id: Option<Uuid>,
    pub created_at: DateTime<Utc>,
}

#[derive(Serialize)]
#[serde(tag = "type", content = "id", rename_all = "lowercase")]
pub enum Assignee {
    User(i32),
    Role(Uuid),
}

impl TryFrom<&Assignment> for Assignee {
    type Error = String;

    fn try_from(assignment: &Assignment) -> Result<Self, Self::Error> {
        match (assignment.user_id, assignment.role_id) {
            (Some(user_id), None) => Ok(Assignee::User(user_id)),
            (None, Some(role_id)) => Ok(Assignee::Role(role_id)),
            (None, None) => Err(format!(
                "No assignee specified in assignment {}",
                assignment.id
            )),
            _ => Err(format!(
                "Multiple assignee types set in assignment {}",
                assignment.id
            )),
        }
    }
}

#[derive(Debug, Clone)]
pub struct AssignmentRule {
    pub id: Uuid,
    pub team_id: TeamId,
    pub user_id: Option<i32>,
    pub role_id: Option<Uuid>,
    pub order_key: i32,
    pub bytecode: Value,
    // We don't bother loading the original filter, as we never use it in cymbal
    //pub filters: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AssignmentIssue {
    pub team_id: TeamId,
    pub status: String,
    pub name: Option<String>,
    pub description: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct AssignmentRuleDisabledData {
    pub message: String,
    pub issue: Value,
    pub props: Value,
}

#[async_trait(?Send)]
pub trait AssignmentRuleRepository {
    type Error: From<serde_json::Error>;

    async fn assignment_rules(
        &mut self,
        team_id: TeamId,
    ) -> Result<Vec<AssignmentRule>, Self::Error>;

    async fn disable_assignment_rule(
        &mut self,
        rule: &AssignmentRule,
        disabled_data: AssignmentRuleDisabledData,
    ) -> Result<(), Self::Error>;
}

impl AssignmentRule {
    pub fn try_match(
        &self,
        issue: &Value,
        props: &Value,
    ) -> Result<Option<NewAssignment>, VmError> {
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
        globals.insert("issue".to_string(), issue.clone());
        globals.insert("properties".to_string(), props.clone());
        let globals: Value = serde_json::to_value(globals)
            .expect("Can construct a json object from a hashmap of String:JsonValue");
        let program = Program::new(rule_bytecode.clone())?;
        let context = ExecutionContext::with_defaults(program).with_globals(globals);
        let mut vm = context.to_vm()?;

        metrics::counter!(ASSIGNMENT_RULES_TRIED).increment(1);

        let mut i = 0;
        while i < context.max_steps {
            let step_result = vm.step()?;
            match step_result {
                StepOutcome::Finished(Value::Bool(true)) => {
                    return Ok(NewAssignment::try_new(self.user_id, self.role_id));
                }
                StepOutcome::Finished(Value::Bool(false)) => {
                    return Ok(None);
                }
                StepOutcome::Finished(res) => {
                    return Err(VmError::Other(format!(
                        "Assignment rule returned {res:?}, expected a boolean value"
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
}

pub async fn evaluate_assignment_rules<R: AssignmentRuleRepository>(
    repository: &mut R,
    issue: AssignmentIssue,
    props_json: Value,
) -> Result<Option<NewAssignment>, R::Error> {
    let timing = common_metrics::timing_guard(ASSIGNMENT_RULES_PROCESSING_TIME, &[]);
    let issue_json = serde_json::to_value(&issue)?;

    let mut rules = repository.assignment_rules(issue.team_id).await?;

    metrics::counter!(ASSIGNMENT_RULES_FOUND).increment(rules.len() as u64);

    rules.sort_unstable_by_key(|r| r.order_key);

    for rule in rules {
        match rule.try_match(&issue_json, &props_json) {
            Ok(None) => continue,
            Ok(Some(new_assignment)) => {
                timing.label("outcome", "match").fin();
                metrics::counter!(AUTO_ASSIGNMENTS).increment(1);
                return Ok(Some(new_assignment));
            }
            // The HogVM ran out of its per-event step budget on this event. The rule
            // itself isn't necessarily broken — a single oversized event can blow the
            // budget for an otherwise-fine rule (e.g. a long `$exception_sources` array
            // pushing an `arrayExists` chain past max_steps). Skip the rule for this
            // event rather than disabling it permanently for every future event.
            // Other `OutOfResource` variants (heap memory, (de)serialization depth)
            // fall through to the catch-all and still disable the rule.
            Err(VmError::OutOfResource(resource)) if resource == "steps" => {
                tracing::warn!(
                    rule_id = %rule.id,
                    team_id = %rule.team_id,
                    "assignment rule exceeded HogVM step budget for this event, skipping"
                );
                continue;
            }
            Err(err) => {
                repository
                    .disable_assignment_rule(
                        &rule,
                        AssignmentRuleDisabledData {
                            message: err.to_string(),
                            issue: issue_json.clone(),
                            props: props_json.clone(),
                        },
                    )
                    .await?;
                metrics::counter!(ASSIGNMENT_RULES_DISABLED).increment(1);
            }
        }
    }

    timing.label("outcome", "no_match").fin();

    Ok(None)
}
