use chrono::{DateTime, Utc};
use common_types::TeamId;
use hogvm::{ExecutionContext, Program, StepOutcome, VmError};
use serde::Serialize;
use serde_json::Value;
use uuid::Uuid;

use crate::metric_consts::{BYPASS_RULES_DISABLED, BYPASS_RULES_TRIED};

/// A rate-limit bypass rule. When an incoming exception event matches an enabled
/// rule, the rate-limiting stage keeps it and charges no tokens (neither the
/// per-issue nor the project bucket), recording a "bypassed" outcome. Matching is
/// identical to suppression rules — the bytecode runs against the event's
/// `properties` — but there is no sampling: a match always bypasses.
#[derive(Debug, Clone)]
pub struct BypassRule {
    pub id: Uuid,
    pub team_id: TeamId,
    pub order_key: i32,
    pub bytecode: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl BypassRule {
    pub async fn load_for_team<'c, E>(conn: E, team_id: TeamId) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as!(
            BypassRule,
            r#"
                SELECT id, team_id, order_key, bytecode, created_at, updated_at
                FROM posthog_errortrackingbypassrule
                WHERE team_id = $1 AND disabled_data IS NULL AND bytecode IS NOT NULL
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
                UPDATE posthog_errortrackingbypassrule
                SET disabled_data = $1, updated_at = NOW()
                WHERE id = $2
            "#,
            serde_json::to_value(data).expect("Can serialize"),
            self.id
        )
        .execute(conn)
        .await?;

        metrics::counter!(BYPASS_RULES_DISABLED).increment(1);
        Ok(())
    }

    /// Whether this rule matches the event's properties, meaning the event should
    /// bypass rate limiting entirely.
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

        let globals = Value::Object(serde_json::Map::from_iter([(
            "properties".to_string(),
            props.clone(),
        )]));
        let program = Program::new(rule_bytecode.clone())?;
        let context = ExecutionContext::with_defaults(program).with_globals(globals);
        let mut vm = context.to_vm()?;

        metrics::counter!(BYPASS_RULES_TRIED).increment(1);

        let mut i = 0;
        while i < context.max_steps {
            let step_result = vm.step()?;
            match step_result {
                StepOutcome::Finished(Value::Bool(b)) => return Ok(b),
                StepOutcome::Finished(res) => {
                    return Err(VmError::Other(format!(
                        "Bypass rule returned {res:?}, expected a boolean value"
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

#[cfg(test)]
mod test {
    use chrono::Utc;
    use serde_json::{json, Value as JsonValue};
    use uuid::Uuid;

    use super::BypassRule;

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

    fn get_test_rule() -> BypassRule {
        BypassRule {
            id: Uuid::new_v4(),
            team_id: 1,
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
