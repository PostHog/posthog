use sha2::{Digest, Sha512};

use crate::{
    error::{EventError, UnhandledError},
    fingerprinting::{grouping_rules::evaluate_grouping_rules, Fingerprint, FingerprintRecordPart},
    stages::grouping::GroupingStage,
    types::{
        event::ExceptionEvent,
        operator::{OperatorResult, ValueOperator},
    },
};

#[derive(Clone, Default)]
pub struct FingerprintGenerator;

impl ValueOperator for FingerprintGenerator {
    type Context = GroupingStage;
    type Item = ExceptionEvent;
    type HandledError = EventError;
    type UnhandledError = UnhandledError;

    async fn execute_value(
        &self,
        mut input: ExceptionEvent,
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

        input.proposed_fingerprint = Some(fingerprint.value.clone());

        if let Some(fp) = &input.fingerprint {
            input.fingerprint_record = Some(vec![FingerprintRecordPart::Manual]);
            if fp.len() > 64 {
                let mut hasher = Sha512::default();
                hasher.update(fp);
                input.fingerprint = Some(format!("{:x}", hasher.finalize()));
            }
        }

        Ok(Ok(input))
    }
}
