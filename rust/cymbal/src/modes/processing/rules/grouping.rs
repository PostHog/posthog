use chrono::{DateTime, Utc};
use common_types::TeamId;
use hogvm::{ExecutionContext, Program, StepOutcome, VmError};
use serde::Serialize;
use serde_json::Value;
use sqlx::PgPool;
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    metric_consts::{
        CUSTOM_GROUPED_EVENTS, GROUPING_RULES_DISABLED, GROUPING_RULES_FOUND,
        GROUPING_RULES_PROCESSING_TIME, GROUPING_RULES_TRIED,
    },
    teams::TeamManager,
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

impl GroupingRule {
    pub async fn load_for_team<'c, E>(conn: E, team_id: TeamId) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as!(
            GroupingRule,
            r#"
                SELECT id, team_id, user_id, role_id, order_key, bytecode, created_at, updated_at
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

        let globals = Value::Object(serde_json::Map::from_iter([(
            "properties".to_string(),
            props.clone(),
        )]));
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
}

pub async fn evaluate_grouping_rules<F>(
    pool: &PgPool,
    team_id: TeamId,
    team_manager: &TeamManager,
    props: F,
) -> Result<Option<GroupingRule>, UnhandledError>
where
    F: FnOnce() -> Result<Value, UnhandledError>,
{
    let timing = common_metrics::timing_guard(GROUPING_RULES_PROCESSING_TIME, &[]);

    // Pass the pool (not a checked-out connection): `get_grouping_rules` is cache-backed
    // and only touches the DB on a miss, so nothing holds a connection across the cache
    // lookup, `props()` serialization, or HogVM rule evaluation below.
    let mut rules = team_manager.get_grouping_rules(pool, team_id).await?;

    metrics::counter!(GROUPING_RULES_FOUND).increment(rules.len() as u64);

    // Most teams have no grouping rules. Bail before materializing `props`, which
    // the caller defers (serializing the event to JSON is expensive per-event work).
    if rules.is_empty() {
        timing.label("outcome", "no_match").fin();
        return Ok(None);
    }

    rules.sort_unstable_by_key(|r| r.order_key);

    let props = props()?;

    for rule in rules {
        match rule.try_match(&props) {
            Ok(false) => continue,
            Ok(true) => {
                timing.label("outcome", "match").fin();
                metrics::counter!(CUSTOM_GROUPED_EVENTS).increment(1);
                return Ok(Some(rule));
            }
            // See `try_assignment_rules` for the rationale: step-budget exhaustion
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
            Err(err) => rule.disable(pool, err.to_string(), props.clone()).await?,
        }
    }

    timing.label("outcome", "no_match").fin();

    Ok(None)
}

#[cfg(test)]
mod test {
    use chrono::Utc;
    use serde_json::{json, Value as JsonValue};
    use sqlx::PgPool;
    use uuid::Uuid;

    use crate::{fingerprinting::Fingerprint, test_utils::create_test_context};

    use super::{evaluate_grouping_rules, GroupingRule};

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

    fn test_props(test_value: JsonValue) -> JsonValue {
        json!({
            "$exception_list": [],
            "test_value": test_value,
        })
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_grouping_rules(db: PgPool) {
        let ctx = create_test_context(db).await;

        let test_team_id = 1;
        let props = test_props(JsonValue::from("test_value"));

        let rule = get_test_rule();
        let expected_fingerprint = format!("custom-rule:{}", rule.id);
        // Insert the rule, so we skip the DB lookup
        ctx.team_manager
            .grouping_rules
            .insert(test_team_id, vec![rule]);

        let matched =
            evaluate_grouping_rules(&ctx.posthog_pool, test_team_id, &ctx.team_manager, || {
                Ok(props.clone())
            })
            .await
            .unwrap();
        let fingerprint = Fingerprint::from_rule(matched.expect("rule should match"));

        assert_eq!(fingerprint.value, expected_fingerprint);

        // Insert a different value - simply removing the value would cause the rule to be disabled, since it
        // tries to access an undefined global
        let props = test_props(JsonValue::from("no_match"));

        let matched =
            evaluate_grouping_rules(&ctx.posthog_pool, test_team_id, &ctx.team_manager, || {
                Ok(props)
            })
            .await
            .unwrap();

        assert!(matched.is_none());
    }
}
