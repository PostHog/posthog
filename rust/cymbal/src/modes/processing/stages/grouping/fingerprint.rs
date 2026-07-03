use sha2::{Digest, Sha512};

use crate::{
    error::UnhandledError,
    fingerprinting::{Fingerprint, FingerprintRecordPart},
    metric_consts::FINGERPRINT_GENERATOR_OPERATOR,
    modes::processing::rules::grouping::evaluate_grouping_rules,
    stages::{grouping::GroupingStage, pipeline::HandledError},
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
    },
};

#[derive(Clone, Default)]
pub struct FingerprintGenerator;

impl ValueOperator for FingerprintGenerator {
    type Context = GroupingStage;
    type Item = ExceptionProperties;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        FINGERPRINT_GENERATOR_OPERATOR
    }

    async fn execute_value(
        &self,
        mut input: ExceptionProperties,
        ctx: GroupingStage,
    ) -> OperatorResult<Self> {
        // Generate fingerprint (uses resolved frames for hashing, or applies grouping rules).
        // Serializing the event to JSON is only needed when the team has grouping rules, so
        // defer it: `evaluate_grouping_rules` invokes this closure only when rules exist.
        let grouping_rule =
            evaluate_grouping_rules(&ctx.connection, input.team_id, &ctx.team_manager, || {
                Ok(serde_json::to_value(&input)?)
            })
            .await?;
        let used_grouping_rule = grouping_rule.is_some();
        let fingerprint: Fingerprint = match grouping_rule {
            Some(rule) => Fingerprint::from_rule(rule),
            None => Fingerprint::from_exception_list(&input.exception_list),
        };

        // Always set proposed_fingerprint to the computed value
        input.proposed_fingerprint = Some(fingerprint.value.clone());

        // When wire-order normalization reordered the payload, also compute the
        // fingerprint the event would have had in its original order. Issue
        // linking uses it to alias the canonical fingerprint onto a
        // pre-normalization issue instead of forking a new one. Only meaningful
        // for the stack-derived fingerprint: a user-supplied fingerprint or a
        // grouping-rule fingerprint is order-independent, so continuity is moot.
        let legacy_list = input.legacy_order_resolved.take();
        if !used_grouping_rule && input.fingerprint.is_none() {
            if let Some(legacy_list) = legacy_list {
                input.legacy_fingerprint =
                    Some(Fingerprint::from_exception_list(&legacy_list).value);
            }
        }

        // User sent us a custom fingerprint, let's use it.
        if let Some(fp) = &input.fingerprint {
            input.fingerprint_record = Some(vec![FingerprintRecordPart::Manual]);
            if fp.len() > 64 {
                let mut hasher = Sha512::default();
                hasher.update(fp);
                input.fingerprint = Some(format!("{:x}", hasher.finalize()));
            }
        } else {
            input.fingerprint = Some(fingerprint.value);
            input.fingerprint_record = Some(fingerprint.record);
        }

        Ok(Ok(input))
    }
}
