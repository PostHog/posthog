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
    stages::grouping::GroupingStage,
    types::{
        exception_event::{ExceptionEvent, FingerprintData, Fingerprinted, PipelineItem, Resolved},
        ExceptionList,
    },
};

#[derive(Clone, Default)]
pub struct FingerprintGenerator;

impl FingerprintGenerator {
    pub async fn execute(
        &self,
        item: PipelineItem<Resolved>,
        ctx: GroupingStage,
    ) -> Result<PipelineItem<Fingerprinted>, UnhandledError> {
        match item {
            Err(error) => Ok(Err(error)),
            Ok(event) => self.generate(event, ctx).await.map(Ok),
        }
    }

    async fn generate(
        &self,
        mut input: ExceptionEvent<Resolved>,
        ctx: GroupingStage,
    ) -> Result<ExceptionEvent<Fingerprinted>, UnhandledError> {
        // Selection order:
        // 1. Existing input fingerprint wins and is marked manual.
        // 2. Matching grouping rule wins and is marked custom.
        // 3. Automatic versions use the newest already-saved fingerprint, or the newest version.
        // Manual and rule fingerprints intentionally do not set a fingerprint version.
        if let Some(client_fingerprint) = input.client_fingerprint() {
            let fingerprint = manual_fingerprint(client_fingerprint);
            return Ok(input.into_fingerprinted(fingerprint));
        }

        // Serializing the event to JSON is only needed when the team has grouping rules, so
        // defer it: `evaluate_grouping_rules` invokes this closure only when rules exist.
        let matched_rule =
            evaluate_grouping_rules(&ctx.connection, input.team_id(), &ctx.team_manager, || {
                Ok(input.to_grouping_value())
            })
            .await?;

        if let Some(rule) = matched_rule {
            let fingerprint = Fingerprint::from_rule(rule);
            return Ok(input.into_fingerprinted(FingerprintData {
                value: fingerprint.value,
                version: None,
                record: fingerprint.record,
            }));
        }

        // Legacy fingerprint versions keep issues keyed before wire-order
        // normalization addressable. They hash the event's pre-flip order:
        // the re-resolved snapshot while normalization still reorders this
        // SDK's payloads (byte-exact, covers resolution reshaping), or a
        // reconstruction by re-applying the SDK's reversal once the SDK has
        // flipped and only the canonical order arrives.
        let lib = input
            .properties()
            .get("$lib")
            .and_then(Value::as_str)
            .map(str::to_string);
        let legacy_list = input
            .take_legacy_order_resolved()
            .or_else(|| legacy_wire_order(lib.as_deref(), input.exception_list()));
        let (version, fingerprint) =
            select_automatic_fingerprint(&input, legacy_list.as_ref(), &ctx).await?;
        if version.is_legacy() {
            metrics::counter!(FINGERPRINT_LEGACY_VERSION_USED, "version" => version.as_str())
                .increment(1);
        }

        Ok(input.into_fingerprinted(FingerprintData {
            value: fingerprint.value,
            version: Some(version),
            record: fingerprint.record,
        }))
    }

    pub fn name(&self) -> &'static str {
        FINGERPRINT_GENERATOR_OPERATOR
    }
}

fn manual_fingerprint(value: &str) -> FingerprintData {
    let value = if value.len() > 64 {
        let mut hasher = Sha512::default();
        hasher.update(value);
        format!("{:x}", hasher.finalize())
    } else {
        value.to_string()
    };
    FingerprintData {
        value,
        version: None,
        record: vec![FingerprintRecordPart::Manual],
    }
}

// Walks versions newest-first and keeps the first fingerprint that already maps to an issue,
// falling back to the newest (canonical) version for new issues. Legacy versions hash the
// pre-flip order and participate only in matching: `all()` orders them below the canonical
// versions, so they can never be the fallback that creates a new issue.
async fn select_automatic_fingerprint(
    input: &ExceptionEvent<Resolved>,
    legacy_list: Option<&ExceptionList>,
    ctx: &GroupingStage,
) -> Result<(FingerprintVersion, Fingerprint), UnhandledError> {
    let fingerprints = FingerprintVersion::all()
        .iter()
        .filter_map(|version| {
            let list = if version.is_legacy() {
                legacy_list?
            } else {
                input.exception_list()
            };
            Some((*version, version.compute(list)))
        })
        .collect::<Vec<_>>();
    let newest = fingerprints
        .last()
        .cloned()
        .ok_or_else(|| UnhandledError::Other("No fingerprint algorithms registered".into()))?;

    // Cache pass: collect known hits without short-circuiting — a cached hit
    // for an older version must not outrank a newer version whose row exists
    // in Postgres but is not in this worker's cache.
    let mut known: HashMap<String, Uuid> = HashMap::new();
    let mut uncached: Vec<String> = Vec::new();
    for (_, fingerprint) in fingerprints.iter() {
        let cache_key = (input.team_id(), fingerprint.value.clone());
        match ctx.issue_cache.get(&cache_key).await {
            Some(issue_id) => {
                known.insert(fingerprint.value.clone(), issue_id);
            }
            None => uncached.push(fingerprint.value.clone()),
        }
    }

    // Hot path: the newest version is a known hit, so nothing can outrank it.
    if known.contains_key(&newest.1.value) {
        return Ok(newest);
    }

    // One round-trip for every candidate value the cache didn't know, instead
    // of one sequential lookup per version. Preference order is applied to the
    // merged cache + DB result set below.
    if !uncached.is_empty() {
        for record in
            IssueFingerprintOverride::load_many(&ctx.connection, input.team_id(), &uncached).await?
        {
            ctx.issue_cache
                .insert(
                    (input.team_id(), record.fingerprint.clone()),
                    record.issue_id,
                )
                .await;
            known.insert(record.fingerprint, record.issue_id);
        }
    }

    for (version, fingerprint) in fingerprints.into_iter().rev() {
        if known.contains_key(&fingerprint.value) {
            return Ok((version, fingerprint));
        }
    }

    Ok(newest)
}
