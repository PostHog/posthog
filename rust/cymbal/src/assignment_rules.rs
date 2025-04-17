use std::{collections::HashMap, sync::Arc};

use chrono::{DateTime, Utc};
use common_types::TeamId;
use hogvm::{ExecutionContext, StepOutcome, VmError};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    app_context::AppContext, error::UnhandledError, issue_resolution::Issue, types::OutputErrProps,
};

#[derive(Debug, Clone)]
pub struct Assignment {
    pub id: Uuid,
    pub issue_id: Uuid,
    pub user_id: Option<i32>,
    pub user_group_id: Option<Uuid>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct AssignmentRule {
    pub id: Uuid,
    pub team_id: TeamId,
    pub user_id: Option<i32>,
    pub user_group_id: Option<Uuid>,
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
                SELECT id, team_id, user_id, user_group_id, order_key, bytecode, created_at, updated_at
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
        Ok(())
    }

    pub async fn apply<'c, E>(&self, conn: E, issue_id: Uuid) -> Result<(), sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // TODO - should we respect existing assignments? This does, and I think that's right, but :shrug:
        sqlx::query!(
            r#"
                INSERT INTO posthog_errortrackingissueassignment (id, issue_id, user_id, user_group_id, created_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (issue_id) DO NOTHING
            "#,
            Uuid::now_v7(),
            issue_id,
            self.user_id,
            self.user_group_id
        ).execute(conn).await?;
        Ok(())
    }
}

pub async fn assign_issue(
    context: Arc<AppContext>,
    issue: Issue,
    exception_properties: OutputErrProps,
) -> Result<(), UnhandledError> {
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

    let mut rules = context
        .team_manager
        .get_rules(&context.pool, issue.team_id)
        .await?;

    rules.sort_unstable_by_key(|r| r.order_key);

    for rule in rules {
        match try_rule(&rule.bytecode, &issue_json, &props_json) {
            Ok(true) => return Ok(rule.apply(&context.pool, issue.id).await?),
            Ok(false) => continue,
            Err(err) => {
                rule.disable(
                    &context.pool,
                    err.to_string(),
                    issue_json.clone(),
                    props_json.clone(),
                )
                .await?
            }
        }
    }

    Ok(())
}

pub fn try_rule(rule_bytecode: &Value, issue: &Value, props: &Value) -> Result<bool, VmError> {
    let rule_bytecode = match rule_bytecode {
        Value::Array(ops) => ops,
        _ => {
            return Err(VmError::Other(format!(
                "Invalid rule bytecode - expected array, got {:?}",
                rule_bytecode
            )))
        }
    };

    let mut globals = HashMap::new();
    globals.insert("issue".to_string(), issue.clone());
    globals.insert("properties".to_string(), props.clone());
    let globals: Value = serde_json::to_value(globals)
        .expect("Can construct a json object from a hashmap of String:JsonValue");
    let context = ExecutionContext::with_defaults(rule_bytecode).with_globals(globals);
    let mut vm = context.to_vm()?;

    let mut i = 0;
    while i < context.max_steps {
        let step_result = vm.step()?;
        match step_result {
            StepOutcome::Finished(Value::Bool(b)) => return Ok(b),
            StepOutcome::Finished(res) => {
                return Err(VmError::Other(format!(
                    "Assignment rule returned {:?}, expected a boolean value",
                    res
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
