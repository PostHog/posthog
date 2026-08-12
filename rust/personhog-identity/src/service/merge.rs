//! The MergePersons entrance: request validation, identity resolution,
//! classification, inline settlement, and response assembly. This is
//! identity work — the pairs that never need a saga settle here — and the
//! lifecycle side stays blind to it: the entrance reaches the durable op
//! machinery only through [`MergeOpExecutor`], handing over a frozen
//! request and receiving a terminal op row.

use std::collections::HashMap;
use std::sync::Arc;

use personhog_common::properties::sanitize_for_jsonb;
use serde_json::Value;
use tonic::Status;

use personhog_proto::personhog::identity::v1::{
    MergePersonsRequest, MergePersonsResponse, MergeSourceOutcome, MergeSourceResult,
};
use personhog_proto::personhog::types::v1::{Person as ProtoPerson, UpdatePersonPropertiesRequest};

use crate::leader::PropertyWriter;
use crate::lifecycle::engine::OpRow;
use crate::lifecycle::merge::{
    MergeOpExecutor, MergeOutcome, MergeRequest, MergeSourceEntry, OP_TYPE_MERGE, OUTCOME_ERROR,
    OUTCOME_MERGED, OUTCOME_NOOP_SAME_PERSON, OUTCOME_SKIPPED_ALREADY_IDENTIFIED,
    OUTCOME_SKIPPED_CONFLICT, OUTCOME_SKIPPED_MOVE_LIMIT,
};
use crate::lifecycle::validation::{
    is_distinct_id_illegal, is_distinct_id_oversized, validate_merge_persons,
};
use crate::storage::{AttachOutcome, IdentityStorage};

/// Handler-decided outcomes that never reach the saga.
const OUTCOME_SKIPPED_ILLEGAL: &str = "skipped_illegal";
const OUTCOME_ATTACHED: &str = "attached";

const PAYLOAD_NUL_SANITIZED_TOTAL: &str = "personhog_identity_merge_payload_nul_sanitized_total";
const PAYLOAD_NUMBERS_CLAMPED_TOTAL: &str =
    "personhog_identity_merge_payload_numbers_clamped_total";

/// The full MergePersons flow, owned by the identity side of the crate.
pub struct MergeEntrance {
    storage: Arc<dyn IdentityStorage>,
    property_writer: Arc<dyn PropertyWriter>,
    ops: MergeOpExecutor,
}

impl MergeEntrance {
    pub fn new(
        storage: Arc<dyn IdentityStorage>,
        property_writer: Arc<dyn PropertyWriter>,
        ops: MergeOpExecutor,
    ) -> Self {
        Self {
            storage,
            property_writer,
            ops,
        }
    }

    // tonic Status is a large Err variant; boxing would diverge from the
    // handler signatures this feeds into.
    #[allow(clippy::result_large_err)]
    pub async fn handle(
        &self,
        request: MergePersonsRequest,
    ) -> Result<MergePersonsResponse, Status> {
        let (op_id, move_limit) = validate_merge_persons(&request)?;
        let mut event_set = parse_json_map(&request.event_set, "event_set")?;
        let mut event_set_once = parse_json_map(&request.event_set_once, "event_set_once")?;
        // The frozen op row and the retry comparisons live in jsonb
        // round-trip space: what Postgres hands back must equal what was
        // written, or the freeze insert fails outright (NUL) and every
        // retry is rejected as a different request (rewritten numbers).
        // sanitize_for_jsonb is that canonical form — the leader applies
        // the same one when the properties land, so nothing downstream
        // sees a value the sync plane didn't.
        let mut stats = sanitize_for_jsonb(&mut event_set);
        let once_stats = sanitize_for_jsonb(&mut event_set_once);
        stats.nul_strings += once_stats.nul_strings;
        stats.clamped_numbers += once_stats.clamped_numbers;
        if stats.nul_strings > 0 {
            common_metrics::inc(PAYLOAD_NUL_SANITIZED_TOTAL, &[], stats.nul_strings);
        }
        if stats.clamped_numbers > 0 {
            common_metrics::inc(PAYLOAD_NUMBERS_CLAMPED_TOTAL, &[], stats.clamped_numbers);
        }
        let original = merge_original(&request, &event_set, &event_set_once);

        // Attach-first: classification below is time-dependent (a retry
        // after the merge committed would re-classify every merged pair as
        // a no-op and freeze a different request), so an existing op is
        // compared on the ORIGINAL call and driven with its own frozen
        // request — never re-classified. Two racing FIRST calls can still
        // classify divergently and the insert loser then sees the engine's
        // full-request mismatch; that surfaces as retryable UNAVAILABLE
        // (see MergeOpExecutor::execute) and the retry attaches here.
        if let Some(row) = self.ops.find(op_id).await? {
            if row.op_type != OP_TYPE_MERGE
                || row.team_id != request.team_id
                || row.request.get("original") != Some(&original)
            {
                return Err(personhog_common::grpc::semantic_refusal(
                    format!("op_id {op_id} was already used for a different request"),
                    "op_id_reused",
                ));
            }
            let frozen = row.request.clone();
            let row = self.ops.execute(op_id, row.team_id, &frozen).await?;
            return merge_response(&row);
        }

        // Classify: resolve everything once on the primary, settle what
        // never needs the saga, collect the two-person set (the only
        // destructive shape). The saga re-resolves
        // authoritatively at claim time; this pass only decides shape.
        let mut keys: Vec<(i64, String)> =
            vec![(request.team_id, request.target_distinct_id.clone())];
        keys.extend(
            request
                .sources
                .iter()
                .map(|s| (request.team_id, s.source_distinct_id.clone())),
        );
        let resolved = self
            .storage
            .resolve_distinct_ids(&keys)
            .await
            .map_err(|e| Status::internal(format!("resolution failed: {e}")))?;

        let target_key = (request.team_id, request.target_distinct_id.clone());
        let Some(target_person) = resolved.get(&target_key) else {
            // Unresolved-target merges (attach the target to a resolved
            // source's person, or birth a fresh target) are not
            // implemented yet; the caller keeps them on its own path. The
            // refusal reason is the branch signal — callers route on it,
            // not on the message text.
            return Err(personhog_common::grpc::semantic_refusal(
                "target distinct id resolves to no person; \
                 create it first (unresolved-target merges are not implemented)",
                "unresolved_target",
            ));
        };
        let target_person = target_person.clone();

        let mut inline_results: HashMap<String, String> = HashMap::new();
        let mut attach: Vec<String> = Vec::new();
        let mut saga_sources: Vec<MergeSourceEntry> = Vec::new();
        for source in &request.sources {
            let did = &source.source_distinct_id;
            // Oversized ids share the illegal settlement: they cannot
            // exist in the varchar(400) column, so they can never resolve
            // — and attaching one would fail the insert.
            if is_distinct_id_illegal(did) || is_distinct_id_oversized(did) {
                inline_results.insert(did.clone(), OUTCOME_SKIPPED_ILLEGAL.to_string());
                continue;
            }
            match resolved.get(&(request.team_id, did.clone())) {
                None => attach.push(did.clone()),
                Some(person) if person.id == target_person.id => {
                    inline_results.insert(did.clone(), OUTCOME_NOOP_SAME_PERSON.to_string());
                }
                Some(_) => saga_sources.push(MergeSourceEntry {
                    distinct_id: did.clone(),
                    event_uuid: source.event_uuid.clone(),
                }),
            }
        }

        // Unresolved sources attach to the target with plain mapping
        // inserts. A source that resolved elsewhere between classification
        // and attach is a retryable conflict, unless it landed on the
        // target anyway.
        if !attach.is_empty() {
            let attached = self
                .storage
                .attach_distinct_ids(request.team_id, target_person.id, &attach)
                .await
                .map_err(|e| Status::internal(format!("attach failed: {e}")))?;
            for did in attach {
                let outcome = match attached.get(&did) {
                    Some(AttachOutcome::Attached { .. }) => OUTCOME_ATTACHED,
                    Some(AttachOutcome::AlreadyMapped { person_id })
                        if *person_id == target_person.id =>
                    {
                        OUTCOME_ATTACHED
                    }
                    Some(AttachOutcome::AlreadyMapped { .. }) | None => OUTCOME_SKIPPED_CONFLICT,
                };
                inline_results.insert(did, outcome.to_string());
            }
        }

        if saga_sources.is_empty() {
            // Nothing to destroy, so no op row. Inline settlement is
            // idempotent: a retry re-executes against the current world,
            // the same at-least-once semantics as event redelivery — and
            // the only semantics available, since recorded outcomes are
            // GC'd after retention and a late replay re-classifies
            // regardless. The op row resumes interrupted destruction; it
            // is not a dedupe of idempotent work (an attached source
            // re-answers noop_same_person). The event's properties still
            // reach the survivor.
            let pushed = self
                .push_event_properties(&request, target_person.id)
                .await?;
            let results = request
                .sources
                .iter()
                .map(|s| MergeSourceResult {
                    source_distinct_id: s.source_distinct_id.clone(),
                    outcome: outcome_enum(
                        inline_results
                            .get(&s.source_distinct_id)
                            .map(String::as_str)
                            .unwrap_or(OUTCOME_ERROR),
                    )
                    .into(),
                })
                .collect();
            return Ok(MergePersonsResponse {
                op_id: op_id.to_string(),
                survivor: Some(pushed.unwrap_or_else(|| target_person.into())),
                results,
            });
        }

        // The saga: freeze the classified request (the driver's shape) plus
        // the original call (retry comparison) and the inline outcomes (so
        // a retried finished op reproduces the full per-did answer).
        let merge_request = MergeRequest {
            target_distinct_id: request.target_distinct_id.clone(),
            sources: saga_sources,
            event_set,
            event_set_once,
            allow_identified_sources: request.allow_identified_sources,
            move_limit,
        };
        let mut frozen = serde_json::to_value(&merge_request)
            .map_err(|e| Status::internal(format!("failed to freeze request: {e}")))?;
        frozen["original"] = original;
        frozen["inline_results"] = serde_json::to_value(&inline_results)
            .map_err(|e| Status::internal(format!("failed to freeze inline results: {e}")))?;

        let row = self.ops.execute(op_id, request.team_id, &frozen).await?;
        merge_response(&row)
    }

    /// Apply the merge event's $set/$set_once to the survivor when no saga
    /// runs (the fold carries them when one does). The ack means the
    /// properties are durable in the changelog.
    async fn push_event_properties(
        &self,
        request: &MergePersonsRequest,
        person_id: i64,
    ) -> Result<Option<ProtoPerson>, Status> {
        if request.event_set.is_empty() && request.event_set_once.is_empty() {
            return Ok(None);
        }
        let response = self
            .property_writer
            .update_person_properties(UpdatePersonPropertiesRequest {
                team_id: request.team_id,
                person_id,
                event_name: "$identify".to_string(),
                set_properties: request.event_set.clone(),
                set_once_properties: request.event_set_once.clone(),
                unset_properties: Vec::new(),
                is_identified: None,
                last_seen_at: None,
            })
            .await?;
        Ok(response.person)
    }
}

/// Decode a JSON-map wire field (empty bytes mean an empty map).
// See `MergeEntrance::handle` for why result_large_err is allowed.
#[allow(clippy::result_large_err)]
fn parse_json_map(bytes: &[u8], field: &str) -> Result<Value, Status> {
    if bytes.is_empty() {
        return Ok(Value::Object(serde_json::Map::new()));
    }
    let value: Value = serde_json::from_slice(bytes)
        .map_err(|e| Status::invalid_argument(format!("invalid {field} JSON: {e}")))?;
    if !value.is_object() {
        return Err(Status::invalid_argument(format!(
            "{field} must be a JSON object"
        )));
    }
    Ok(value)
}

/// The canonical form of a MergePersons call, embedded in the frozen op
/// request as `original`. Classification is time-dependent, so a retry must
/// be compared against what was originally ASKED, not what was classified —
/// this is what keeps a legitimate retry from tripping the engine's
/// request-equality guard after the merge already moved the world.
fn merge_original(
    request: &MergePersonsRequest,
    event_set: &Value,
    event_set_once: &Value,
) -> Value {
    // event_uuid is deliberately absent: the proto documents it as
    // advisory data the merge never reads, so a retry that regenerated
    // its event uuids must still match the recorded request.
    serde_json::json!({
        "target_distinct_id": request.target_distinct_id,
        "sources": request
            .sources
            .iter()
            .map(|s| &s.source_distinct_id)
            .collect::<Vec<_>>(),
        "event_set": event_set,
        "event_set_once": event_set_once,
        "allow_identified_sources": request.allow_identified_sources,
        "move_limit": request.move_limit,
    })
}

fn outcome_enum(outcome: &str) -> MergeSourceOutcome {
    match outcome {
        OUTCOME_MERGED => MergeSourceOutcome::Merged,
        OUTCOME_NOOP_SAME_PERSON => MergeSourceOutcome::NoopSamePerson,
        OUTCOME_ATTACHED => MergeSourceOutcome::Attached,
        OUTCOME_SKIPPED_ILLEGAL => MergeSourceOutcome::SkippedIllegal,
        OUTCOME_SKIPPED_ALREADY_IDENTIFIED => MergeSourceOutcome::SkippedAlreadyIdentified,
        OUTCOME_SKIPPED_CONFLICT => MergeSourceOutcome::SkippedConflict,
        OUTCOME_SKIPPED_MOVE_LIMIT => MergeSourceOutcome::SkippedMoveLimit,
        OUTCOME_ERROR => MergeSourceOutcome::Error,
        _ => MergeSourceOutcome::Unspecified,
    }
}

/// The survivor document recorded by the saga, converted to the wire
/// person. The fold's `created_at` is already epoch millis — the leader
/// plane's wire unit — so it passes through unscaled.
fn survivor_to_proto(survivor: &Value, team_id: i64) -> ProtoPerson {
    ProtoPerson {
        id: survivor["id"].as_i64().unwrap_or_default(),
        uuid: survivor["uuid"].as_str().unwrap_or_default().to_string(),
        team_id,
        properties: serde_json::to_vec(&survivor["properties"]).unwrap_or_default(),
        created_at: survivor["created_at"].as_i64().unwrap_or_default(),
        version: survivor["version"].as_i64().unwrap_or_default(),
        is_identified: survivor["is_identified"].as_bool().unwrap_or(true),
        ..Default::default()
    }
}

/// Assemble the response for an op that ran the saga: inline outcomes from
/// the frozen request, saga outcomes from the recorded terminal outcome,
/// in the original request's source order.
// See `MergeEntrance::handle` for why result_large_err is allowed.
#[allow(clippy::result_large_err)]
fn merge_response(row: &OpRow) -> Result<MergePersonsResponse, Status> {
    let Some(outcome) = &row.outcome else {
        return Err(Status::internal(format!(
            "op {} is terminal but has no recorded outcome",
            row.op_id
        )));
    };
    let outcome: MergeOutcome = serde_json::from_value(outcome.clone())
        .map_err(|e| Status::internal(format!("op {} outcome is malformed: {e}", row.op_id)))?;
    let saga_results: HashMap<&str, &str> = outcome
        .results
        .iter()
        .map(|r| (r.distinct_id.as_str(), r.outcome.as_str()))
        .collect();
    let inline_results: HashMap<String, String> = row
        .request
        .get("inline_results")
        .cloned()
        .map(serde_json::from_value)
        .transpose()
        .map_err(|e| {
            Status::internal(format!(
                "op {} inline results are malformed: {e}",
                row.op_id
            ))
        })?
        .unwrap_or_default();
    // Loud on a misshapen frozen shape, like inline_results above: a
    // silent empty here would answer OK with no results for a corrupt
    // row.
    let original_sources: Vec<String> = row
        .request
        .get("original")
        .and_then(|o| o.get("sources"))
        .and_then(|s| s.as_array())
        .map(|sources| {
            sources
                .iter()
                .filter_map(|s| s.as_str())
                .map(str::to_string)
                .collect()
        })
        .ok_or_else(|| {
            Status::internal(format!("op {} original sources are malformed", row.op_id))
        })?;

    let results = original_sources
        .iter()
        .map(|did| {
            let outcome = inline_results
                .get(did)
                .map(String::as_str)
                .or_else(|| saga_results.get(did.as_str()).copied())
                .unwrap_or(OUTCOME_ERROR);
            MergeSourceResult {
                source_distinct_id: did.clone(),
                outcome: outcome_enum(outcome).into(),
            }
        })
        .collect();

    Ok(MergePersonsResponse {
        op_id: row.op_id.to_string(),
        survivor: outcome
            .survivor
            .as_ref()
            .map(|s| survivor_to_proto(s, row.team_id)),
        results,
    })
}
