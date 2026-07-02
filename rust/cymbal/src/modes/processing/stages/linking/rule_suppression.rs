use hogvm::VmError;
use metrics::counter;

use crate::{
    error::{EventError, UnhandledError},
    metric_consts::{RULE_SUPPRESSED_EVENTS, RULE_SUPPRESSION_OPERATOR},
    stages::{linking::LinkingStage, pipeline::HandledError},
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
    },
};

#[derive(Clone)]
pub struct RuleSuppression;

impl ValueOperator for RuleSuppression {
    type Item = ExceptionProperties;
    type Context = LinkingStage;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        RULE_SUPPRESSION_OPERATOR
    }

    async fn execute_value(&self, input: Self::Item, ctx: LinkingStage) -> OperatorResult<Self> {
        let mut rules = ctx
            .app_context
            .team_manager
            .get_suppression_rules(&ctx.app_context.posthog_pool, input.team_id)
            .await?;

        if rules.is_empty() {
            return Ok(Ok(input));
        }

        rules.sort_unstable_by_key(|r| r.order_key);

        // Only serialize the event once we know the team has suppression rules.
        let props_json = match serde_json::to_value(&input) {
            Ok(v) => v,
            Err(_) => return Ok(Ok(input)),
        };

        for rule in rules {
            match rule.should_suppress(&props_json, &input.uuid) {
                Ok(false) => continue,
                Ok(true) => {
                    counter!(RULE_SUPPRESSED_EVENTS).increment(1);
                    return Ok(Err(EventError::SuppressedByRule(rule.id)));
                }
                // See `try_assignment_rules` for the rationale: step-budget exhaustion
                // is a per-event cost issue, not a logic bug in the rule. Skip this rule
                // for this event rather than disabling it permanently. Other
                // `OutOfResource` variants still fall through to the disable path.
                Err(VmError::OutOfResource(resource)) if resource == "steps" => {
                    tracing::warn!(
                        rule_id = %rule.id,
                        team_id = %rule.team_id,
                        "suppression rule exceeded HogVM step budget for this event, skipping"
                    );
                    continue;
                }
                Err(err) => {
                    rule.disable(
                        &ctx.app_context.posthog_pool,
                        err.to_string(),
                        props_json.clone(),
                    )
                    .await
                    .map_err(UnhandledError::from)?;
                    ctx.app_context
                        .team_manager
                        .suppression_rules
                        .invalidate(&input.team_id);
                }
            }
        }

        Ok(Ok(input))
    }
}
