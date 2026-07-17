use chrono::{DateTime, Utc};
use common_types::TeamId;
use hogvm::{ExecutionContext, Program, StepOutcome, VmError};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::PgConnection;
use uuid::Uuid;

use crate::metric_consts::{
    ASSIGNMENT_RULES_DISABLED, ASSIGNMENT_RULES_FOUND, ASSIGNMENT_RULES_PROCESSING_TIME,
    ASSIGNMENT_RULES_TRIED, AUTO_ASSIGNMENTS,
};

use crate::teams::TeamManager;
use crate::{error::UnhandledError, issue_resolution::Issue, types::OutputErrProps};

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

impl NewAssignment {
    pub async fn apply<'c, E>(&self, conn: E, issue_id: Uuid) -> Result<Assignment, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // TODO - should we respect existing assignments? This does, and I think that's right, but :shrug:
        let assignment = sqlx::query_as!(
            Assignment,
            r#"
                INSERT INTO posthog_errortrackingissueassignment (id, issue_id, user_id, role_id, created_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (issue_id) DO UPDATE SET issue_id = $2 -- no-op to get a returned row
                RETURNING id, issue_id, user_id, role_id, created_at
            "#,
            Uuid::now_v7(),
            issue_id,
            self.user_id,
            self.role_id,
        ).fetch_one(conn).await?;

        Ok(assignment)
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
    type Error = UnhandledError;

    fn try_from(a: &Assignment) -> Result<Self, Self::Error> {
        match (a.user_id, a.role_id) {
            (Some(user_id), None) => Ok(Assignee::User(user_id)),
            (None, Some(role_id)) => Ok(Assignee::Role(role_id)),
            (None, None) => Err(UnhandledError::Other(format!(
                "No assignee specified in assignment {}",
                a.id
            ))),
            _ => Err(UnhandledError::Other(format!(
                "Multiple assignee types set in assignment {}",
                a.id
            ))),
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

impl AssignmentRule {
    pub async fn load_for_team<'c, E>(conn: E, team_id: TeamId) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as!(
            AssignmentRule,
            r#"
                SELECT id, team_id, user_id, role_id, order_key, bytecode, created_at, updated_at
                FROM posthog_errortrackingassignmentrule
                WHERE team_id = $1 AND disabled_data IS NULL
            "#,
            team_id
        )
        .fetch_all(conn)
        .await
    }

    pub async fn disable<'c, E>(
        &self,
        conn: E,
        message: String,
        issue: Value,
        props: Value,
    ) -> Result<(), sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        #[derive(Serialize)]
        struct DisabledData {
            message: String,
            issue: Value,
            props: Value,
        }

        let data = DisabledData {
            message,
            issue,
            props,
        };

        sqlx::query!(
            r#"
                UPDATE posthog_errortrackingassignmentrule
                SET disabled_data = $1, updated_at = NOW()
                WHERE id = $2
            "#,
            serde_json::to_value(data).expect("Can serialize"),
            self.id
        )
        .execute(conn)
        .await?;

        metrics::counter!(ASSIGNMENT_RULES_DISABLED).increment(1);
        Ok(())
    }

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

        let globals = Value::Object(serde_json::Map::from_iter([
            ("issue".to_string(), issue.clone()),
            ("properties".to_string(), props.clone()),
        ]));
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

pub async fn try_assignment_rules(
    con: &mut PgConnection,
    team_manager: &TeamManager,
    issue: Issue,
    exception_properties: &OutputErrProps,
) -> Result<Option<NewAssignment>, UnhandledError> {
    let timing = common_metrics::timing_guard(ASSIGNMENT_RULES_PROCESSING_TIME, &[]);

    let mut rules = team_manager
        .get_assignment_rules(&mut *con, issue.team_id)
        .await?;

    metrics::counter!(ASSIGNMENT_RULES_FOUND).increment(rules.len() as u64);

    // Most teams have no assignment rules; skip serializing the issue and the
    // (expensive) event properties unless a rule might actually match.
    if rules.is_empty() {
        timing.label("outcome", "no_match").fin();
        return Ok(None);
    }

    rules.sort_unstable_by_key(|r| r.order_key);

    #[derive(Debug, Clone, Serialize, Deserialize)]
    struct IssueJson {
        status: String,
        name: Option<String>,
        description: Option<String>,
    }

    let issue_json = serde_json::to_value(IssueJson {
        status: issue.status.to_string(),
        name: issue.name.clone(),
        description: issue.description.clone(),
    })?;

    let props_json = serde_json::to_value(exception_properties)?;

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
                rule.disable(
                    &mut *con,
                    err.to_string(),
                    issue_json.clone(),
                    props_json.clone(),
                )
                .await?
            }
        }
    }

    timing.label("outcome", "no_match").fin();

    Ok(None)
}
