use std::collections::HashMap;

use serde_json::Value;
use sha2::{Digest, Sha512};
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    fingerprinting::{Fingerprint, FingerprintRecordPart, FingerprintVersion},
    issue_resolution::IssueFingerprintOverride,
    metric_consts::{FINGERPRINT_GENERATOR_OPERATOR, FINGERPRINT_LEGACY_VERSION_USED},
    modes::processing::normalization::legacy_wire_order,
    modes::processing::rules::grouping::evaluate_grouping_rules,
    stages::{grouping::GroupingStage, pipeline::HandledError},
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
        ExceptionList,
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
            input.fingerprint_version = None;
            input.fingerprint_record = Some(fingerprint.record);
            return Ok(Ok(input));
        }

        // Legacy fingerprint versions keep issues keyed before wire-order
        // normalization addressable. They hash the event's pre-flip order:
        // the re-resolved snapshot while normalization still reorders this
        // SDK's payloads (byte-exact, covers resolution reshaping), or a
        // reconstruction by re-applying the SDK's reversal once the SDK has
        // flipped and only the canonical order arrives.
        let lib = input.props.get("$lib").and_then(Value::as_str);
        let legacy_list = input
            .legacy_order_resolved
            .take()
            .or_else(|| legacy_wire_order(lib, &input.exception_list));
        let (version, fingerprint) =
            select_automatic_fingerprint(&input, legacy_list.as_ref(), &ctx).await?;
        if version.is_legacy() {
            metrics::counter!(FINGERPRINT_LEGACY_VERSION_USED, "version" => version.as_str())
                .increment(1);
        }
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
    input.fingerprint_version = None;
    input.fingerprint_record = Some(vec![FingerprintRecordPart::Manual]);
    if fp.len() > 64 {
        let mut hasher = Sha512::default();
        hasher.update(fp);
        input.fingerprint = Some(format!("{:x}", hasher.finalize()));
    }
    Ok(())
}

// Walks versions newest-first and keeps the first fingerprint that already maps to an issue,
// falling back to the newest (canonical) version for new issues. Legacy versions hash the
// pre-flip order and participate only in matching: `all()` orders them below the canonical
// versions, so they can never be the fallback that creates a new issue.
async fn select_automatic_fingerprint(
    input: &ExceptionProperties,
    legacy_list: Option<&ExceptionList>,
    ctx: &GroupingStage,
) -> Result<(FingerprintVersion, Fingerprint), UnhandledError> {
    let fingerprints = FingerprintVersion::all()
        .iter()
        .filter_map(|version| {
            let list = if version.is_legacy() {
                legacy_list?
            } else {
                &input.exception_list
            };
            Some((*version, version.compute(list)))
        })
        .collect::<Vec<_>>();
    let newest = fingerprints
        .last()
        .cloned()
        .ok_or_else(|| UnhandledError::Other("No fingerprint algorithms registered".into()))?;

    // Cache pass, newest-first: an issue whose newest fingerprint is hot
    // resolves with no DB traffic at all.
    for (version, fingerprint) in fingerprints.iter().rev() {
        let cache_key = (input.team_id, fingerprint.value.clone());
        if ctx.issue_cache.get(&cache_key).await.is_some() {
            return Ok((*version, fingerprint.clone()));
        }
    }

    // One round-trip for every candidate value the cache didn't know, instead
    // of one sequential lookup per version (the cache stores hits only, so a
    // per-version walk pays a round-trip per miss — the common case for new
    // errors). Preference order is applied to the result set below, so the
    // outcome is identical to the sequential newest-first walk.
    let values: Vec<String> = fingerprints
        .iter()
        .map(|(_, fingerprint)| fingerprint.value.clone())
        .collect();
    let known: HashMap<String, Uuid> =
        IssueFingerprintOverride::load_many(&ctx.connection, input.team_id, &values)
            .await?
            .into_iter()
            .map(|record| (record.fingerprint, record.issue_id))
            .collect();
    for (value, issue_id) in &known {
        ctx.issue_cache
            .insert((input.team_id, value.clone()), *issue_id)
            .await;
    }

    for (version, fingerprint) in fingerprints.into_iter().rev() {
        if known.contains_key(&fingerprint.value) {
            return Ok((version, fingerprint));
        }
    }

    Ok(newest)
}
