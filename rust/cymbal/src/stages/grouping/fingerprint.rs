use sha2::{Digest, Sha512};

use crate::{
    error::UnhandledError,
    fingerprinting::{grouping_rules::evaluate_grouping_rules, Fingerprint, FingerprintRecordPart},
    metric_consts::FINGERPRINT_GENERATOR_OPERATOR,
    stages::{grouping::GroupingStage, pipeline::ExceptionEventHandledError},
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
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        FINGERPRINT_GENERATOR_OPERATOR
    }

    async fn execute_value(
        &self,
        mut input: ExceptionProperties,
        ctx: GroupingStage,
    ) -> OperatorResult<Self> {
        // Generate fingerprint (uses resolved frames for hashing, or applies grouping rules)
        let props = serde_json::to_value(&input)?;
        let mut conn = ctx.connection.acquire().await?;
        let fingerprint: Fingerprint =
            match evaluate_grouping_rules(&mut conn, input.team_id, &ctx.team_manager, props)
                .await?
            {
                Some(rule) => Fingerprint::from_rule(rule),
                None => Fingerprint::from_exception_list(&input.exception_list),
            };

        // Always set proposed_fingerprint to the computed value
        input.proposed_fingerprint = Some(fingerprint.value.clone());

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
