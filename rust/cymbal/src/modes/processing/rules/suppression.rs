use std::collections::HashMap;

use chrono::{DateTime, Utc};
use common_types::TeamId;
use hogvm::{ExecutionContext, Program, StepOutcome, VmError};
use serde::Serialize;
use serde_json::Value;
use uuid::Uuid;

use crate::metric_consts::{SUPPRESSION_RULES_DISABLED, SUPPRESSION_RULES_TRIED};

const SAMPLING_MODULO: u128 = 10_000;

#[derive(Debug, Clone)]
pub struct SuppressionRule {
    pub id: Uuid,
    pub team_id: TeamId,
    pub order_key: i32,
    pub bytecode: Value,
    pub sampling_rate: f64,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl SuppressionRule {
    pub async fn load_for_team<'c, E>(conn: E, team_id: TeamId) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as!(
            SuppressionRule,
            r#"
                SELECT id, team_id, order_key, bytecode, sampling_rate, created_at, updated_at
                FROM posthog_errortrackingsuppressionrule
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
                UPDATE posthog_errortrackingsuppressionrule
                SET disabled_data = $1, updated_at = NOW()
                WHERE id = $2
            "#,
            serde_json::to_value(data).expect("Can serialize"),
            self.id
        )
        .execute(conn)
        .await?;

        metrics::counter!(SUPPRESSION_RULES_DISABLED).increment(1);
        Ok(())
    }

    /// Check whether this rule should suppress an event. Uses the event UUID
    /// for deterministic sampling — the same event always produces the same
    /// suppress/keep decision regardless of which replica processes it.
    pub fn should_suppress(&self, props: &Value, event_uuid: &Uuid) -> Result<bool, VmError> {
        let matched = self.try_match(props)?;
        if !matched {
            return Ok(false);
        }
        if self.sampling_rate >= 1.0 {
            return Ok(true);
        }
        if self.sampling_rate <= 0.0 {
            return Ok(false);
        }
        let bucket = event_uuid.as_u128() % SAMPLING_MODULO;
        let threshold = (self.sampling_rate * SAMPLING_MODULO as f64) as u128;
        Ok(bucket < threshold)
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

        metrics::counter!(SUPPRESSION_RULES_TRIED).increment(1);

        let mut i = 0;
        while i < context.max_steps {
            let step_result = vm.step()?;
            match step_result {
                StepOutcome::Finished(Value::Bool(b)) => return Ok(b),
                StepOutcome::Finished(res) => {
                    return Err(VmError::Other(format!(
                        "Suppression rule returned {res:?}, expected a boolean value"
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

    use super::SuppressionRule;

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

    fn get_test_rule() -> SuppressionRule {
        SuppressionRule {
            id: Uuid::new_v4(),
            team_id: 1,
            order_key: 1,
            bytecode: rule_bytecode(),
            sampling_rate: 1.0,
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

    #[test]
    fn test_should_suppress_with_full_rate() {
        let rule = get_test_rule();
        let props = json!({"test_value": "test_value"});
        let event_id = Uuid::new_v4();
        // sampling_rate = 1.0 should always suppress matching events
        assert!(rule.should_suppress(&props, &event_id).unwrap());
    }

    #[test]
    fn test_should_suppress_with_zero_rate() {
        let mut rule = get_test_rule();
        rule.sampling_rate = 0.0;
        let props = json!({"test_value": "test_value"});
        let event_id = Uuid::new_v4();
        // sampling_rate = 0.0 should never suppress even matching events
        assert!(!rule.should_suppress(&props, &event_id).unwrap());
    }

    #[test]
    fn test_should_suppress_no_match_regardless_of_rate() {
        let rule = get_test_rule();
        let props = json!({"test_value": "other_value"});
        let event_id = Uuid::new_v4();
        // non-matching events should never be suppressed
        assert!(!rule.should_suppress(&props, &event_id).unwrap());
    }

    #[test]
    fn test_should_suppress_deterministic_for_same_uuid() {
        let mut rule = get_test_rule();
        rule.sampling_rate = 0.5;
        let props = json!({"test_value": "test_value"});
        let event_id = Uuid::new_v4();
        let first = rule.should_suppress(&props, &event_id).unwrap();
        // Same UUID always gives same result
        assert_eq!(first, rule.should_suppress(&props, &event_id).unwrap());
        assert_eq!(first, rule.should_suppress(&props, &event_id).unwrap());
    }

    #[test]
    fn test_should_suppress_sampling_respects_rate() {
        let mut rule = get_test_rule();
        rule.sampling_rate = 0.5;
        let props = json!({"test_value": "test_value"});
        // With enough UUIDs, roughly half should be suppressed
        let mut suppressed = 0;
        let total = 10_000;
        for i in 0..total {
            let event_id = Uuid::from_u128(i);
            if rule.should_suppress(&props, &event_id).unwrap() {
                suppressed += 1;
            }
        }
        // Allow 5% tolerance
        assert!(
            (4500..=5500).contains(&suppressed),
            "Expected ~5000 suppressed, got {suppressed}"
        );
    }
}
