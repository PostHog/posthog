use sha2::{Digest, Sha512};

use crate::{
    error::UnhandledError,
    fingerprinting::{Fingerprint, FingerprintRecordPart, FingerprintVersion},
    issue_resolution::IssueFingerprintOverride,
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
        // Selection order:
        // 1. Existing input fingerprint wins and is marked manual.
        // 2. Matching grouping rule wins and is marked custom.
        // 3. Automatic versions use the newest already-saved fingerprint, or the newest version.
        // Manual and rule fingerprints intentionally do not set a fingerprint version.
        if input.fingerprint.is_some() {
            apply_manual_fingerprint(&mut input)?;
            return Ok(Ok(input));
        }

        // Serializing the event to JSON is only needed when the team has grouping rules, so
        // defer it: `evaluate_grouping_rules` invokes this closure only when rules exist.
        let matched_rule =
            evaluate_grouping_rules(&ctx.connection, input.team_id, &ctx.team_manager, || {
                Ok(serde_json::to_value(&input)?)
            })
            .await?;

        if let Some(rule) = matched_rule {
            let fingerprint = Fingerprint::from_rule(rule);
            input.fingerprint = Some(fingerprint.value);
            input.fingerprint_record = Some(fingerprint.record);
            return Ok(Ok(input));
        }

        let (version, fingerprint) = select_automatic_fingerprint(&input, &ctx).await?;
        input.fingerprint = Some(fingerprint.value);
        input.fingerprint_record = Some(fingerprint.record);
        input.fingerprint_version = Some(version);

        Ok(Ok(input))
    }
}

fn apply_manual_fingerprint(input: &mut ExceptionProperties) -> Result<(), UnhandledError> {
    let Some(fp) = &input.fingerprint else {
        return Err(UnhandledError::Other("Missing manual fingerprint".into()));
    };
    input.fingerprint_record = Some(vec![FingerprintRecordPart::Manual]);
    if fp.len() > 64 {
        let mut hasher = Sha512::default();
        hasher.update(fp);
        input.fingerprint = Some(format!("{:x}", hasher.finalize()));
    }
    Ok(())
}

async fn select_automatic_fingerprint(
    input: &ExceptionProperties,
    ctx: &GroupingStage,
) -> Result<(FingerprintVersion, Fingerprint), UnhandledError> {
    let fingerprints = FingerprintVersion::all()
        .iter()
        .map(|version| (*version, version.compute(&input.exception_list)))
        .collect::<Vec<_>>();
    let newest = fingerprints
        .last()
        .cloned()
        .ok_or_else(|| UnhandledError::Other("No fingerprint algorithms registered".into()))?;

    for (version, fingerprint) in fingerprints.into_iter().rev() {
        if fingerprint_exists(ctx, input.team_id, &fingerprint.value).await? {
            return Ok((version, fingerprint));
        }
    }

    Ok(newest)
}

async fn fingerprint_exists(
    ctx: &GroupingStage,
    team_id: i32,
    fingerprint: &str,
) -> Result<bool, UnhandledError> {
    let cache_key = (team_id, fingerprint.to_string());
    if ctx.issue_cache.get(&cache_key).await.is_some() {
        return Ok(true);
    }

    let Some(override_record) =
        IssueFingerprintOverride::load(&ctx.connection, team_id, fingerprint).await?
    else {
        return Ok(false);
    };

    ctx.issue_cache
        .insert(cache_key, override_record.issue_id)
        .await;
    Ok(true)
}
