//! The MergePersons entrance: request validation, identity resolution,
//! classification, inline settlement, and response assembly. This is
//! identity work — the pairs that never need a saga settle here — and the
//! lifecycle side stays blind to it: the entrance reaches the durable op
//! machinery only through [`MergeOpExecutor`], handing over a frozen
//! request and receiving a terminal op row.

use std::collections::HashMap;
use std::sync::Arc;

use chrono::{DateTime, Utc};
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
    record_outcome_count, MergeOpExecutor, MergeOutcome, MergeRequest, MergeSourceEntry,
    MergeSourceRecord, OP_TYPE_MERGE, OUTCOME_ERROR, OUTCOME_MERGED, OUTCOME_NOOP_SAME_PERSON,
    OUTCOME_SKIPPED_ALREADY_IDENTIFIED, OUTCOME_SKIPPED_CONFLICT, OUTCOME_SKIPPED_MOVE_LIMIT,
    OUTCOME_SKIPPED_REFUSED,
};
use crate::lifecycle::validation::{
    is_distinct_id_illegal, is_distinct_id_oversized, validate_merge_persons,
};
use crate::storage::{AttachOutcome, IdentityStorage, Person, PersonStub, StubOutcome};

/// Handler-decided outcomes that never reach the saga.
const OUTCOME_SKIPPED_ILLEGAL: &str = "skipped_illegal";
const OUTCOME_ATTACHED: &str = "attached";

const MERGE_SOURCES_PER_CALL: &str = "personhog_identity_merge_sources_per_call";
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
        common_metrics::histogram(MERGE_SOURCES_PER_CALL, &[], request.sources.len() as f64);
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
                || !same_merge(row.request.get("original"), &original)
            {
                return Err(personhog_common::grpc::semantic_refusal(
                    format!("op_id {op_id} was already used for a different request"),
                    "op_id_reused",
                ));
            }
            let frozen = row.request.clone();
            let row = self.ops.execute(op_id, row.team_id, &frozen).await?;
            let delivered = self.deliver_aborted_writes(&request, &row).await?;
            // Drives the recorded op with its own frozen request, so a
            // terminal row is reproduced rather than reclassified and a
            // non-terminal one is resumed. The event's own properties are
            // applied only where the op aborted; see deliver_aborted_writes.
            return merge_response(&row, delivered);
        }

        // Classify: resolve everything once on the primary, settle what
        // never needs the saga, collect the two-person set (the only
        // destructive shape). The saga re-resolves
        // authoritatively at claim time; this pass only decides shape.
        //
        // Illegal and oversized sources settle here, before resolution, and
        // stay out of the resolve batch: their verdict does not depend on the
        // world, and resolving them would let a caller pump arbitrarily large
        // ids through the primary for free.
        let mut inline_results: HashMap<String, String> = HashMap::new();
        let mut keys: Vec<(i64, String)> =
            vec![(request.team_id, request.target_distinct_id.clone())];
        for source in &request.sources {
            let did = &source.source_distinct_id;
            if is_distinct_id_illegal(did) || is_distinct_id_oversized(did) {
                inline_results.insert(did.clone(), OUTCOME_SKIPPED_ILLEGAL.to_string());
            } else {
                keys.push((request.team_id, did.clone()));
            }
        }
        let resolved = self
            .storage
            .resolve_distinct_ids(&keys)
            .await
            .map_err(|e| Status::internal(format!("resolution failed: {e}")))?;

        let target_key = (request.team_id, request.target_distinct_id.clone());
        let (target_person, target_was_born) = match resolved.get(&target_key) {
            Some(target) => (target.clone(), false),
            None => self.establish_target(&request, &resolved).await?,
        };

        let mut attach: Vec<String> = Vec::new();
        let mut saga_sources: Vec<MergeSourceEntry> = Vec::new();
        for source in &request.sources {
            let did = &source.source_distinct_id;
            // Illegal and oversized sources settled before resolution.
            if inline_results.contains_key(did.as_str()) {
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

        // Inline outcomes never reach the saga's terminal record, so they
        // are counted here at settlement. A retried call that re-classifies
        // re-counts — the same at-least-once semantics as the response
        // itself (see below); a retry that attaches to an existing op
        // returns above and never re-counts.
        let mut inline_counts: HashMap<&str, u64> = HashMap::new();
        for outcome in inline_results.values() {
            *inline_counts.entry(outcome.as_str()).or_default() += 1;
        }
        for (outcome, count) in inline_counts {
            record_outcome_count(outcome, count);
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
            // An identify that actually joined identities makes the
            // survivor identified; a call whose every pair was skipped
            // proves nothing.
            let flip_identified = inline_results
                .values()
                .any(|o| o == OUTCOME_ATTACHED || o == OUTCOME_NOOP_SAME_PERSON);
            let pushed = self
                .push_event_properties(&request, &target_person, flip_identified, target_was_born)
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
                    // This arm runs only when no source reached the saga,
                    // so nothing was destroyed and there is no id to report.
                    source_person_id: None,
                })
                .collect();
            return Ok(MergePersonsResponse {
                op_id: op_id.to_string(),
                survivor: Some(pushed.unwrap_or_else(|| target_person.into())),
                results,
                survivor_was_born: target_was_born,
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
            creator_event_uuid: request.creator_event_uuid.clone(),
        };
        let mut frozen = serde_json::to_value(&merge_request)
            .map_err(|e| Status::internal(format!("failed to freeze request: {e}")))?;
        frozen["original"] = original;
        frozen["inline_results"] = serde_json::to_value(&inline_results)
            .map_err(|e| Status::internal(format!("failed to freeze inline results: {e}")))?;

        let row = self.ops.execute(op_id, request.team_id, &frozen).await?;
        let delivered = self.deliver_aborted_writes(&request, &row).await?;
        merge_response(&row, delivered)
    }

    /// An aborted saga never folds, so the merge event's writes (its
    /// $set/$set_once and the identified flip) would otherwise reach
    /// nobody. Ingestion applies both to the target even when it refuses a
    /// merge (person-merge-service.ts sets updateIsIdentified before it
    /// looks at the source), so the RPC must too: deliver them against
    /// whatever the target distinct id resolves to now. The frozen request
    /// is not consulted for the person, because the op that caused the
    /// abort may have settled the target away since. A push failure errors
    /// the call rather than answering OK with lost writes; the retry
    /// attaches to the aborted op and re-drives this delivery.
    async fn deliver_aborted_writes(
        &self,
        request: &MergePersonsRequest,
        row: &OpRow,
    ) -> Result<Option<ProtoPerson>, Status> {
        let aborted = row
            .outcome
            .as_ref()
            .and_then(|o| o.get("aborted"))
            .and_then(Value::as_bool)
            .unwrap_or(false);
        if !aborted {
            return Ok(None);
        }
        let key = (request.team_id, request.target_distinct_id.clone());
        let mut resolved = self
            .storage
            .resolve_distinct_ids(std::slice::from_ref(&key))
            .await
            .map_err(|e| Status::internal(format!("target re-resolution failed: {e}")))?;
        // A target that no longer resolves was destroyed after the abort;
        // the writes have no person to land on, and the caller's retry
        // semantics (re-deliver the event) cover the gap.
        let Some(survivor) = resolved.remove(&key) else {
            return Ok(None);
        };
        // A saga only exists for legal resolved pairs, and ingestion marks
        // the target identified for any legal pair regardless of the merge
        // outcome, so the flip always accompanies the delivery.
        let pushed = self
            .push_event_properties(request, &survivor, true, false)
            .await?;
        Ok(Some(pushed.unwrap_or_else(|| survivor.into())))
    }

    /// Apply the merge event's $set/$set_once and the identified flip to
    /// the survivor. Called from the inline settlement, and again from
    /// `deliver_aborted_writes` when a saga ran and aborted; a saga that
    /// completes carries both through the fold instead. The ack means the changes are durable in the changelog.
    /// Skipped entirely when there is nothing to change — a repeat
    /// identify of an already-identified survivor with no new properties
    /// costs no leader round trip.
    async fn push_event_properties(
        &self,
        request: &MergePersonsRequest,
        survivor: &Person,
        flip_identified: bool,
        was_born: bool,
    ) -> Result<Option<ProtoPerson>, Status> {
        let flip = flip_identified && !survivor.is_identified;
        // A person the establish path just birthed records the event that
        // created it, which is what the Postgres backend writes at creation.
        // Only here: that backend stamps it once and never afterwards, so a
        // survivor that already existed must not gain one. It travels in
        // $set rather than on the stub row because a stub is written
        // straight to Postgres and never reaches the leader's changelog,
        // which is the same reason the stub is born unidentified.
        let stamp_creator = was_born && !request.creator_event_uuid.is_empty();
        if request.event_set.is_empty()
            && request.event_set_once.is_empty()
            && !flip
            && !stamp_creator
        {
            return Ok(None);
        }
        let set = if stamp_creator {
            with_creator_event_uuid(&request.event_set, &request.creator_event_uuid)?
        } else {
            request.event_set.clone()
        };
        let response = self
            .property_writer
            .update_person_properties(UpdatePersonPropertiesRequest {
                team_id: request.team_id,
                person_id: survivor.id,
                event_name: "$identify".to_string(),
                set_properties: set,
                set_once_properties: request.event_set_once.clone(),
                unset_properties: Vec::new(),
                is_identified: flip.then_some(true),
                last_seen_at: None,
            })
            .await?;
        Ok(response.person)
    }

    /// The unresolved-target half of the merge contract: the target
    /// distinct id resolves to no person, so the call must establish the
    /// survivor before anything can classify against it. The first
    /// eligible resolved source's person survives and the target distinct
    /// id attaches to it; when no eligible source resolves, the target
    /// person is born fresh, its uuid derived from the target distinct id
    /// so the id's implied-person events already point at it. Both writes
    /// are idempotent, so a crash between establishment and settlement
    /// re-drives through re-classification: the established target then
    /// simply resolves.
    async fn establish_target(
        &self,
        request: &MergePersonsRequest,
        resolved: &HashMap<(i64, String), Person>,
    ) -> Result<(Person, bool), Status> {
        let target_did = &request.target_distinct_id;

        // Eligibility applies the identified-source policy here, not just
        // in the saga: surviving would attach the target to the source's
        // person and settle the pair as a same-person no-op, so the saga's
        // refusal would never run and any identify request could alias its
        // unresolved target onto a known identified person. An ineligible
        // source instead classifies against the birthed target, where the
        // saga refuses it as skipped_already_identified.
        let first_resolved = request
            .sources
            .iter()
            .filter(|s| !is_distinct_id_illegal(&s.source_distinct_id))
            .filter_map(|s| resolved.get(&(request.team_id, s.source_distinct_id.clone())))
            .find(|person| request.allow_identified_sources || !person.is_identified);
        if let Some(survivor) = first_resolved {
            let attached = self
                .storage
                .attach_distinct_ids(
                    request.team_id,
                    survivor.id,
                    std::slice::from_ref(target_did),
                )
                .await
                .map_err(|e| Status::internal(format!("target attach failed: {e}")))?;
            return match attached.get(target_did) {
                Some(AttachOutcome::Attached { .. }) => Ok((survivor.clone(), false)),
                // The target distinct id got mapped concurrently; that
                // mapping wins and its person is the survivor.
                Some(AttachOutcome::AlreadyMapped { .. }) => {
                    Ok((self.resolve_target_after_race(request).await?, false))
                }
                // The survivor row vanished under the attach (a racing
                // lifecycle op committed). Nothing durable happened for
                // this op, so the retry re-classifies against the settled
                // world.
                None => Err(Status::unavailable(
                    "survivor was destroyed by a concurrent operation; retry",
                )),
            };
        }

        // No eligible source resolves: birth the target person. Born
        // unidentified even when a legal source will settle: the leader's
        // changelog is the downstream person feed and the leader only
        // records changes, so the settlement flip is what writes the
        // newborn's first changelog document. A stub born already
        // identified would make that flip a no-op and leave the person
        // invisible downstream; a crash before the flip self-heals, since
        // the still-unidentified row re-arms it on the retry.
        let created_at = if request.created_at == 0 {
            Utc::now()
        } else {
            DateTime::from_timestamp_millis(request.created_at)
                .ok_or_else(|| Status::invalid_argument("created_at is out of range"))?
        };
        let outcomes = self
            .storage
            .create_person_stubs(&[PersonStub {
                team_id: request.team_id,
                distinct_id: target_did.clone(),
                extra_distinct_ids: Vec::new(),
                created_at,
                is_identified: false,
            }])
            .await
            .map_err(|e| Status::internal(format!("target creation failed: {e}")))?;
        match outcomes.into_iter().next() {
            Some(StubOutcome::Committed { person, .. }) => Ok((person, true)),
            // Losing the race means the winner's person survives, and it
            // carries whatever creator its own establishment recorded.
            Some(StubOutcome::LostRace) | None => {
                Ok((self.resolve_target_after_race(request).await?, false))
            }
        }
    }

    /// Re-resolve the target distinct id after losing an establishment
    /// race. The winner's person is as good a survivor as ours would have
    /// been; a mapping that vanished again mid-race sends the caller back
    /// around.
    async fn resolve_target_after_race(
        &self,
        request: &MergePersonsRequest,
    ) -> Result<Person, Status> {
        let key = (request.team_id, request.target_distinct_id.clone());
        let mut resolved = self
            .storage
            .resolve_distinct_ids(std::slice::from_ref(&key))
            .await
            .map_err(|e| Status::internal(format!("target re-resolution failed: {e}")))?;
        resolved.remove(&key).ok_or_else(|| {
            Status::unavailable("target resolution raced a concurrent operation; retry")
        })
    }
}

/// The event's `$set` map with `$creator_event_uuid` added, for a person
/// the establish path just birthed. Rides `$set` and overwrites, because
/// the Postgres backend spreads the key last over both of the event's maps
/// at creation: the property names the event that created the person, so
/// an event carrying its own value for that key does not get to decide it.
// See `MergeEntrance::handle` for why result_large_err is allowed.
#[allow(clippy::result_large_err)]
fn with_creator_event_uuid(set: &[u8], creator_event_uuid: &str) -> Result<Vec<u8>, Status> {
    let mut value = parse_json_map(set, "event_set")?;
    let map = value
        .as_object_mut()
        .expect("parse_json_map returns an object");
    map.insert(
        "$creator_event_uuid".to_string(),
        Value::String(creator_event_uuid.to_string()),
    );
    serde_json::to_vec(&value)
        .map_err(|e| Status::internal(format!("failed to serialize event_set: {e}")))
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
        "created_at": request.created_at,
    })
}

/// Fields that describe how a merge runs rather than which merge it is.
///
/// All three drift between two deliveries of one event, so refusing on them
/// would turn an ordinary redelivery into a permanent FAILED_PRECONDITION.
/// `created_at` comes from the event timestamp, which ingestion derives from
/// the wall clock when the event carries none, and the two property fields
/// carry values later pipeline stages refresh.
///
/// Excluded from the comparison, not ignored: a replay of an aborted op
/// still delivers the event's properties, taking the incoming ones so the
/// latest delivery wins.
///
/// `move_limit` is deliberately not stripped, since the client folds it into
/// the op id, so a same-id call with a different limit is a real mismatch.
const MERGE_PARAMETERS: [&str; 3] = ["created_at", "event_set", "event_set_once"];

/// Whether a retry is describing the merge the recorded op performed.
/// Compared on identity only; see MERGE_PARAMETERS for what that excludes.
fn same_merge(recorded: Option<&Value>, incoming: &Value) -> bool {
    let strip = |value: &Value| {
        let mut copy = value.clone();
        if let Some(map) = copy.as_object_mut() {
            for key in MERGE_PARAMETERS {
                map.remove(key);
            }
        }
        copy
    };
    match recorded {
        Some(recorded) => strip(recorded) == strip(incoming),
        None => false,
    }
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
        OUTCOME_SKIPPED_REFUSED => MergeSourceOutcome::SkippedRefused,
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
        // Absent in records written before the saga began carrying it, and
        // absent from a fold whose people all had none, which the wire and
        // the store both read as unset.
        last_seen_at: survivor["last_seen_at"].as_i64(),
        version: survivor["version"].as_i64().unwrap_or_default(),
        is_identified: survivor["is_identified"].as_bool().unwrap_or(true),
        ..Default::default()
    }
}

/// Assemble the response for an op that ran the saga: inline outcomes from
/// the frozen request, saga outcomes from the recorded terminal outcome,
/// in the original request's source order. An aborted outcome records no
/// survivor; `delivered` fills it with the person the aborted delivery
/// wrote to, so the caller still learns the event's person.
// See `MergeEntrance::handle` for why result_large_err is allowed.
#[allow(clippy::result_large_err)]
fn merge_response(
    row: &OpRow,
    delivered: Option<ProtoPerson>,
) -> Result<MergePersonsResponse, Status> {
    let Some(outcome) = &row.outcome else {
        return Err(Status::internal(format!(
            "op {} is terminal but has no recorded outcome",
            row.op_id
        )));
    };
    let outcome: MergeOutcome = serde_json::from_value(outcome.clone())
        .map_err(|e| Status::internal(format!("op {} outcome is malformed: {e}", row.op_id)))?;
    let saga_results: HashMap<&str, &MergeSourceRecord> = outcome
        .results
        .iter()
        .map(|r| (r.distinct_id.as_str(), r))
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
            let record = saga_results.get(did.as_str());
            let outcome = inline_results
                .get(did)
                .map(String::as_str)
                .or_else(|| record.map(|r| r.outcome.as_str()))
                .unwrap_or(OUTCOME_ERROR);
            MergeSourceResult {
                source_distinct_id: did.clone(),
                outcome: outcome_enum(outcome).into(),
                // Only a merged source names a person, because only that
                // person is permanently gone. Every other verdict either
                // destroys nothing or names one still live — including
                // noop_same_person, whose id is the survivor's.
                source_person_id: match outcome {
                    OUTCOME_MERGED => record.and_then(|r| r.person_id),
                    _ => None,
                },
            }
        })
        .collect();

    Ok(MergePersonsResponse {
        op_id: row.op_id.to_string(),
        survivor: outcome
            .survivor
            .as_ref()
            .map(|s| survivor_to_proto(s, row.team_id))
            .or(delivered),
        results,
        // Not always true: establish_target skips ineligible sources when it
        // picks a survivor, while the classification loop routes any source
        // that resolved elsewhere to the saga, so an unresolved target with
        // an already-identified source both births and runs a saga. The op
        // row does not record which, and a resume has only the row, so the
        // answer is the safe one — the caller runs its follow-up update.
        // Costs that newborn its $creator_event_uuid, which only the inline
        // path stamps. With one source there is no Postgres person to
        // compare it against, since that backend attaches the unresolved id
        // to the identified person rather than creating anyone; with several
        // it routes through its fold and the comparison is untested.
        survivor_was_born: false,
    })
}
