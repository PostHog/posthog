use std::fmt::Display;

use chrono::{DateTime, Utc};
use common_types::TeamId;
use hogvm::{ExecutionContext, Program, StepOutcome, VmError};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::{FromRow, PgConnection};
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    issue_resolution::Issue,
    metric_consts::{
        SEVERITY_RULES_DISABLED, SEVERITY_RULES_FOUND, SEVERITY_RULES_MATCHED,
        SEVERITY_RULES_PROCESSING_TIME, SEVERITY_RULES_TRIED,
    },
    teams::TeamManager,
    types::ProcessedExceptionProperties,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuleSeverity {
    Low,
    Medium,
    High,
    Critical,
}

impl Display for RuleSeverity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RuleSeverity::Low => write!(f, "low"),
            RuleSeverity::Medium => write!(f, "medium"),
            RuleSeverity::High => write!(f, "high"),
            RuleSeverity::Critical => write!(f, "critical"),
        }
    }
}

#[derive(Debug, Clone, FromRow)]
pub struct SeverityRule {
    pub id: Uuid,
    pub team_id: TeamId,
    pub severity: String,
    pub order_key: i32,
    pub bytecode: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl SeverityRule {
    pub async fn load_for_team<'c, E>(
        executor: E,
        team_id: TeamId,
    ) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as::<_, SeverityRule>(
            r#"
                SELECT id, team_id, severity, order_key, bytecode, created_at, updated_at
                FROM posthog_errortrackingseverityrule
                WHERE team_id = $1 AND disabled_data IS NULL
                ORDER BY order_key, created_at, id
            "#,
        )
        .bind(team_id)
        .fetch_all(executor)
        .await
    }

    pub async fn disable<'c, E>(
        &self,
        executor: E,
        message: String,
        issue: Value,
        properties: Value,
    ) -> Result<(), sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        #[derive(Serialize)]
        struct DisabledData {
            message: String,
            issue: Value,
            properties: Value,
        }

        let disabled_data = DisabledData {
            message,
            issue,
            properties,
        };
        sqlx::query(
            r#"
                UPDATE posthog_errortrackingseverityrule
                SET disabled_data = $1, updated_at = NOW()
                WHERE id = $2
            "#,
        )
        .bind(serde_json::to_value(disabled_data).expect("Can serialize"))
        .bind(self.id)
        .execute(executor)
        .await?;

        metrics::counter!(SEVERITY_RULES_DISABLED).increment(1);
        Ok(())
    }

    fn parsed_severity(&self) -> Result<RuleSeverity, VmError> {
        match self.severity.as_str() {
            "low" => Ok(RuleSeverity::Low),
            "medium" => Ok(RuleSeverity::Medium),
            "high" => Ok(RuleSeverity::High),
            "critical" => Ok(RuleSeverity::Critical),
            severity => Err(VmError::Other(format!(
                "Invalid severity rule value {severity:?}"
            ))),
        }
    }

    pub fn try_match(
        &self,
        issue: &Value,
        properties: &Value,
    ) -> Result<Option<RuleSeverity>, VmError> {
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
            ("properties".to_string(), properties.clone()),
        ]));
        let program = Program::new(rule_bytecode.clone())?;
        let context = ExecutionContext::with_defaults(program).with_globals(globals);
        let mut vm = context.to_vm()?;

        metrics::counter!(SEVERITY_RULES_TRIED).increment(1);

        let mut steps = 0;
        while steps < context.max_steps {
            match vm.step()? {
                StepOutcome::Finished(Value::Bool(true)) => {
                    return self.parsed_severity().map(Some)
                }
                StepOutcome::Finished(Value::Bool(false)) => return Ok(None),
                StepOutcome::Finished(result) => {
                    return Err(VmError::Other(format!(
                        "Severity rule returned {result:?}, expected a boolean value"
                    )))
                }
                StepOutcome::NativeCall(name, args) => {
                    context.execute_native_function_call(&mut vm, &name, args)?
                }
                StepOutcome::Continue => {}
            }
            steps += 1;
        }

        Err(VmError::OutOfResource("steps".to_string()))
    }
}

pub async fn try_severity_rules(
    connection: &mut PgConnection,
    team_manager: &TeamManager,
    issue: &Issue,
    exception_properties: &ProcessedExceptionProperties,
) -> Result<Option<RuleSeverity>, UnhandledError> {
    let timing = common_metrics::timing_guard(SEVERITY_RULES_PROCESSING_TIME, &[]);
    let mut rules = team_manager
        .get_severity_rules(&mut *connection, issue.team_id)
        .await?;

    metrics::counter!(SEVERITY_RULES_FOUND).increment(rules.len() as u64);
    if rules.is_empty() {
        timing.label("outcome", "no_match").fin();
        return Ok(None);
    }

    rules.sort_unstable_by_key(|rule| (rule.order_key, rule.created_at, rule.id));

    #[derive(Serialize, Deserialize)]
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
    let properties_json = serde_json::to_value(exception_properties)?;

    for rule in rules {
        match rule.try_match(&issue_json, &properties_json) {
            Ok(None) => continue,
            Ok(Some(severity)) => {
                metrics::counter!(SEVERITY_RULES_MATCHED).increment(1);
                timing.label("outcome", "match").fin();
                return Ok(Some(severity));
            }
            Err(VmError::OutOfResource(resource)) if resource == "steps" => {
                tracing::warn!(
                    rule_id = %rule.id,
                    team_id = %rule.team_id,
                    "severity rule exceeded HogVM step budget for this event, skipping"
                );
            }
            Err(error) => {
                rule.disable(
                    &mut *connection,
                    error.to_string(),
                    issue_json.clone(),
                    properties_json.clone(),
                )
                .await?;
                team_manager.severity_rules.invalidate(&issue.team_id);
            }
        }
    }

    timing.label("outcome", "no_match").fin();
    Ok(None)
}
