use sha2::{Digest, Sha512};

use crate::{
    error::UnhandledError,
    fingerprinting::{
        Fingerprint, FingerprintRecordPart, FingerprintVersion, VersionedFingerprint,
    },
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
        let matched_rule =
            evaluate_grouping_rules(&ctx.connection, input.team_id, &ctx.team_manager, || {
                Ok(serde_json::to_value(&input)?)
            })
            .await?;
        let is_custom_grouped = matched_rule.is_some();
        let fingerprint: Fingerprint = match matched_rule {
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

            // Compute every registered algorithm version. The linking stage resolves the issue
            // against this list in order and rewrites the event fingerprint to whichever
            // version actually matched or created the issue. Manual fingerprints and custom
            // grouping rules express explicit user intent, so they get no versions.
            if !is_custom_grouped {
                input.versioned_fingerprints = FingerprintVersion::all()
                    .iter()
                    .map(|version| VersionedFingerprint {
                        version: *version,
                        fingerprint: version.compute(&input.exception_list),
                    })
                    .collect();
            }
        }

        Ok(Ok(input))
    }
}
