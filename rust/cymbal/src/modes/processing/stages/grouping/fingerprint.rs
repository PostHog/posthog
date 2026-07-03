use sha2::{Digest, Sha512};

use crate::{
    error::UnhandledError,
    fingerprinting::{Fingerprint, FingerprintRecordPart, FingerprintVersion},
    issue_resolution::IssueFingerprintOverride,
    metric_consts::FINGERPRINT_GENERATOR_OPERATOR,
    modes::processing::rules::grouping::{evaluate_grouping_rules, GroupingRule},
    stages::{grouping::GroupingStage, pipeline::HandledError},
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
    },
};

#[derive(Clone, Default)]
pub struct FingerprintGenerator;

struct AutomaticFingerprintSelection {
    selected: Fingerprint,
    newest: Fingerprint,
}

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
        // Serializing the event to JSON is only needed when the team has grouping rules, so
        // defer it: `evaluate_grouping_rules` invokes this closure only when rules exist.
        let matched_rule =
            evaluate_grouping_rules(&ctx.connection, input.team_id, &ctx.team_manager, || {
                Ok(serde_json::to_value(&input)?)
            })
            .await?;

        if input.fingerprint.is_some() {
            apply_manual_fingerprint(&mut input, matched_rule)?;
            return Ok(Ok(input));
        }

        if let Some(rule) = matched_rule {
            let fingerprint = Fingerprint::from_rule(rule);
            input.proposed_fingerprint = Some(fingerprint.value.clone());
            input.fingerprint = Some(fingerprint.value);
            input.fingerprint_record = Some(fingerprint.record);
            return Ok(Ok(input));
        }

        let selection = select_automatic_fingerprint(&input, &ctx).await?;
        input.proposed_fingerprint = Some(selection.newest.value);
        input.fingerprint = Some(selection.selected.value);
        input.fingerprint_record = Some(selection.selected.record);

        Ok(Ok(input))
    }
}

fn apply_manual_fingerprint(
    input: &mut ExceptionProperties,
    matched_rule: Option<GroupingRule>,
) -> Result<(), UnhandledError> {
    input.proposed_fingerprint = Some(match matched_rule {
        Some(rule) => Fingerprint::from_rule(rule).value,
        None => newest_automatic_fingerprint(input)?.value,
    });

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
) -> Result<AutomaticFingerprintSelection, UnhandledError> {
    let fingerprints = automatic_fingerprints(input);
    let newest = fingerprints
        .last()
        .cloned()
        .ok_or_else(|| UnhandledError::Other("No fingerprint algorithms registered".into()))?;

    for fingerprint in &fingerprints {
        if fingerprint_exists(ctx, input.team_id, &fingerprint.value).await? {
            return Ok(AutomaticFingerprintSelection {
                selected: fingerprint.clone(),
                newest,
            });
        }
    }

    Ok(AutomaticFingerprintSelection {
        selected: newest.clone(),
        newest,
    })
}

fn newest_automatic_fingerprint(
    input: &ExceptionProperties,
) -> Result<Fingerprint, UnhandledError> {
    automatic_fingerprints(input)
        .last()
        .cloned()
        .ok_or_else(|| UnhandledError::Other("No fingerprint algorithms registered".into()))
}

fn automatic_fingerprints(input: &ExceptionProperties) -> Vec<Fingerprint> {
    FingerprintVersion::all()
        .iter()
        .map(|version| version.compute(&input.exception_list))
        .collect()
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
