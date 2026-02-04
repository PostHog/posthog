use sha2::{Digest, Sha512};

use crate::{
    error::UnhandledError,
    fingerprinting::{grouping_rules::evaluate_grouping_rules, Fingerprint, FingerprintRecordPart},
    stages::grouping::GroupingStage,
    types::{event::ExceptionEvent, operator::Operator},
};

#[derive(Clone, Default)]
pub struct FingerprintGenerator;

impl Operator for FingerprintGenerator {
    type Context = GroupingStage;
    type Item = ExceptionEvent;
    type Error = UnhandledError;

    async fn execute(
        &self,
        mut input: ExceptionEvent,
        ctx: GroupingStage,
    ) -> Result<ExceptionEvent, UnhandledError> {
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

        Ok(input)
    }
}
