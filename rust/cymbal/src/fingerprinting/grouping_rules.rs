use std::collections::HashMap;

use chrono::{DateTime, Utc};
use common_types::TeamId;
use hogvm::{ExecutionContext, Program, StepOutcome, VmError};
use serde::Serialize;
use serde_json::Value;
use sqlx::PgConnection;
use uuid::Uuid;

use crate::{
    assignment_rules::NewAssignment,
    error::UnhandledError,
    metric_consts::{
        CUSTOM_GROUPED_EVENTS, GROUPING_RULES_DISABLED, GROUPING_RULES_FOUND,
        GROUPING_RULES_PROCESSING_TIME, GROUPING_RULES_TRIED,
    },
    teams::TeamManager,
    types::RawErrProps,
};

#[derive(Debug, Clone)]
pub struct GroupingRule {
    pub id: Uuid,
    pub team_id: TeamId,

    // If a rule has been custom grouped, it might also be auto-assigned
    pub user_id: Option<i32>,
    pub user_group_id: Option<Uuid>,
    pub role_id: Option<Uuid>,
    pub order_key: i32,
    pub bytecode: Value,
    // We don't bother loading the original filter, as we never use it in cymbal
    //pub filters: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl GroupingRule {
    pub async fn load_for_team<'c, E>(conn: E, team_id: TeamId) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as!(
            GroupingRule,
            r#"
                SELECT id, team_id, user_id, user_group_id, role_id, order_key, bytecode, created_at, updated_at
                FROM posthog_errortrackinggroupingrule
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
        props: Value,
    ) -> Result<(), sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        #[derive(Serialize)]
        struct DisabledData {
            message: String,
            props: Value,
        }

        let data = DisabledData { message, props };

        sqlx::query!(
            r#"
                UPDATE posthog_errortrackinggroupingrule
                SET disabled_data = $1, updated_at = NOW()
                WHERE id = $2
            "#,
            serde_json::to_value(data).expect("Can serialize"),
            self.id
        )
        .execute(conn)
        .await?;

        metrics::counter!(GROUPING_RULES_DISABLED).increment(1);
        Ok(())
    }

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

    pub fn assignment(&self) -> Option<NewAssignment> {
        NewAssignment::try_new(self.user_id, self.user_group_id, self.role_id)
    }
}

pub async fn try_grouping_rules(
    con: &mut PgConnection,
    team_id: TeamId,
    team_manager: &TeamManager,
    exception_properties: &RawErrProps,
) -> Result<Option<GroupingRule>, UnhandledError> {
    let timing = common_metrics::timing_guard(GROUPING_RULES_PROCESSING_TIME, &[]);

    let props_json = serde_json::to_value(exception_properties)?;

    let mut rules = team_manager.get_grouping_rules(&mut *con, team_id).await?;

    metrics::counter!(GROUPING_RULES_FOUND).increment(rules.len() as u64);

    rules.sort_unstable_by_key(|r| r.order_key);

    for rule in rules {
        match rule.try_match(&props_json) {
            Ok(false) => continue,
            Ok(true) => {
                timing.label("outcome", "match").fin();
                metrics::counter!(CUSTOM_GROUPED_EVENTS).increment(1);
                return Ok(Some(rule));
            }
            Err(err) => {
                rule.disable(&mut *con, err.to_string(), props_json.clone())
                    .await?
            }
        }
    }

    timing.label("outcome", "no_match").fin();

    // If none of the rules matched, grab the existing assignment, in case one exists,
    // and return that (or None)
    Ok(None)
}
