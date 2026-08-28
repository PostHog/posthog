//! The MergePersons entrance: request validation, identity resolution,
//! classification, inline settlement, and response assembly. This is
//! identity work — the pairs that never need a saga settle here — and the
//! lifecycle side stays blind to it: the entrance reaches the durable op
//! machinery only through [`MergeOpExecutor`], handing over a frozen
//! request and receiving a terminal op row.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use futures::stream::{self, StreamExt};

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
const CARRIED_WRITES: &str = "personhog_identity_merge_carried_writes_total";

/// Carried writes to distinct persons commute, so their groups run
/// concurrently; the bound is on leader connections, not correctness.
/// Entries that resolved to one person are a different matter — see
/// apply_carried_operations, which serializes them.
const CARRIED_WRITE_CONCURRENCY: usize = 8;

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
            // A replay reproduces a recorded outcome without re-applying
            // anything, carried operations included, so it names none.
            return merge_response(&row, delivered, Vec::new());
        }

        // Classify: resolve everything once on the primary, settle what
        // never needs the saga, collect the two-person set (the only
        // destructive shape). The saga re-resolves
        // authoritatively at claim time; this pass only decides shape.
        //
        // Illegal and oversized sources settle here, before resolution,
        // and stay out of the resolve batch: their verdict does not
        // depend on the world (nothing downstream reads their
        // resolutions — see establish_target's own illegal filter), and
        // resolving them would let a caller pump arbitrarily large ids
        // through the primary for free. Carried ids never need this;
        // validation rejects illegal and oversized carried entries
        // outright.
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
        // Carried distinct ids resolve here rather than in a call of their
        // own, so the person an operation lands on is the person this call
        // classified against.
        let named: HashSet<&str> = keys.iter().map(|(_, did)| did.as_str()).collect();
        let extra: Vec<(i64, String)> = request
            .carried_operations
            .iter()
            .filter(|entry| !named.contains(entry.distinct_id.as_str()))
            .map(|entry| (request.team_id, entry.distinct_id.clone()))
            .collect();
        keys.extend(extra);
        let resolved = self
            .storage
            .resolve_distinct_ids(&keys)
            .await
            .map_err(|e| Status::internal(format!("resolution failed: {e}")))?;

        let target_key = (request.team_id, request.target_distinct_id.clone());
        let target_person = match resolved.get(&target_key) {
            Some(target) => target.clone(),
            None => self.establish_target(&request, &resolved).await?,
        };

        // Before classification reaches the saga, so no source is fenced
        // yet and every write is still accepted.
        let carried_applied = self
            .apply_carried_operations(&request, &resolved, &target_person)
            .await;

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
                .push_event_properties(&request, &target_person, flip_identified)
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
                carried_applied,
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
        let delivered = self.deliver_aborted_writes(&request, &row).await?;
        merge_response(&row, delivered, carried_applied)
    }

    /// Apply the caller's buffered operations to the persons their distinct
    /// ids resolve to, and answer which ones landed.
    ///
    /// A failure here does not fail the merge. The echo is the whole
    /// contract: a caller keeps everything this does not name and sends it
    /// the ordinary way, where the merge's own precedence rules still
    /// govern the result. Failing the call instead would turn a property
    /// write's bad day into a merge that never happens.
    async fn apply_carried_operations(
        &self,
        request: &MergePersonsRequest,
        resolved: &HashMap<(i64, String), Person>,
        target: &Person,
    ) -> Vec<String> {
        let updates: Vec<(String, UpdatePersonPropertiesRequest)> = request
            .carried_operations
            .iter()
            .filter_map(|entry| {
                // The target may have been established a moment ago, so it
                // is the one distinct id the resolution map can miss.
                let person_id = if entry.distinct_id == request.target_distinct_id {
                    Some(target.id)
                } else {
                    resolved
                        .get(&(request.team_id, entry.distinct_id.clone()))
                        .map(|person| person.id)
                }?;
                // The caller buffered these ops for a specific person; the
                // distinct id may have been repointed by another pod since.
                // Applying to whoever owns the id now would misdirect the
                // write and the echo would make the caller discard it, so a
                // mismatch skips: unechoed, the caller keeps the ops and its
                // own flush path delivers them with the person-not-found
                // handling that path already has.
                if let Some(expected) = entry.expected_person_id {
                    if expected != person_id {
                        // The only signal this path emits: the skip is
                        // deliberately unechoed, so without the counter a
                        // cross-pod repoint would be invisible.
                        common_metrics::inc(
                            CARRIED_WRITES,
                            &[("outcome".to_string(), "skipped_person_moved".to_string())],
                            1,
                        );
                        return None;
                    }
                }
                Some((
                    entry.distinct_id.clone(),
                    UpdatePersonPropertiesRequest {
                        team_id: request.team_id,
                        person_id,
                        event_name: entry.event_name.clone(),
                        set_properties: entry.set_properties.clone(),
                        set_once_properties: entry.set_once_properties.clone(),
                        unset_properties: entry.unset_properties.clone(),
                        is_identified: entry.is_identified,
                        last_seen_at: entry.last_seen_at,
                    },
                ))
            })
            .collect();
        // Group by resolved person, keeping request order within a group.
        // Distinct ids are unique (validation rejects duplicates), but two
        // of them can resolve to one person — a caller without
        // expected_person_id, or one whose lanes are not person-keyed —
        // and $set, $set_once, and $unset are order-sensitive, so writes
        // to one person must land sequentially in request order. Groups
        // for distinct persons commute and run concurrently.
        let mut groups: Vec<(i64, Vec<(String, UpdatePersonPropertiesRequest)>)> = Vec::new();
        for (did, update) in updates {
            match groups
                .iter_mut()
                .find(|(person_id, _)| *person_id == update.person_id)
            {
                Some((_, group)) => group.push((did, update)),
                None => groups.push((update.person_id, vec![(did, update)])),
            }
        }
        let results: Vec<_> = stream::iter(groups.into_iter().map(|(_, entries)| {
            let writer = Arc::clone(&self.property_writer);
            async move {
                let mut settled = Vec::with_capacity(entries.len());
                for (did, update) in entries {
                    let result = writer.update_person_properties(update).await;
                    settled.push((did, result));
                }
                settled
            }
        }))
        .buffer_unordered(CARRIED_WRITE_CONCURRENCY)
        .collect()
        .await;

        let mut applied = Vec::new();
        for (distinct_id, result) in results.into_iter().flatten() {
            match result {
                Ok(_) => {
                    common_metrics::inc(
                        CARRIED_WRITES,
                        &[("outcome".to_string(), "applied".to_string())],
                        1,
                    );
                    applied.push(distinct_id)
                }
                Err(status) => {
                    // Labelled by code so an expected fence bounce is
                    // separable from a leader in trouble; this counter is
                    // the only signal, since the failure is swallowed.
                    common_metrics::inc(
                        CARRIED_WRITES,
                        &[
                            ("outcome".to_string(), "failed".to_string()),
                            ("code".to_string(), status.code().to_string()),
                        ],
                        1,
                    );
                    tracing::warn!(
                        team_id = request.team_id,
                        distinct_id = %distinct_id,
                        error = %status,
                        "carried operations not applied; the caller still holds them"
                    );
                }
            }
        }
        applied
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
        let pushed = self.push_event_properties(request, &survivor, true).await?;
        Ok(Some(pushed.unwrap_or_else(|| survivor.into())))
    }

    /// Apply the merge event's $set/$set_once and the identified flip to
    /// the survivor when no saga runs (the fold carries both when one
    /// does). The ack means the changes are durable in the changelog.
    /// Skipped entirely when there is nothing to change — a repeat
    /// identify of an already-identified survivor with no new properties
    /// costs no leader round trip.
    async fn push_event_properties(
        &self,
        request: &MergePersonsRequest,
        survivor: &Person,
        flip_identified: bool,
    ) -> Result<Option<ProtoPerson>, Status> {
        let flip = flip_identified && !survivor.is_identified;
        if request.event_set.is_empty() && request.event_set_once.is_empty() && !flip {
            return Ok(None);
        }
        let response = self
            .property_writer
            .update_person_properties(UpdatePersonPropertiesRequest {
                team_id: request.team_id,
                person_id: survivor.id,
                event_name: "$identify".to_string(),
                set_properties: request.event_set.clone(),
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
    ) -> Result<Person, Status> {
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
                Some(AttachOutcome::Attached { .. }) => Ok(survivor.clone()),
                // The target distinct id got mapped concurrently; that
                // mapping wins and its person is the survivor.
                Some(AttachOutcome::AlreadyMapped { .. }) => {
                    self.resolve_target_after_race(request).await
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
            Some(StubOutcome::Committed { person, .. }) => Ok(person),
            Some(StubOutcome::LostRace) | None => self.resolve_target_after_race(request).await,
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
/// `created_at` comes from the event's timestamp, which ingestion derives
/// from the wall clock when the event carries none, so two deliveries of one
/// event legitimately disagree on it. Holding a retry to it would answer
/// FAILED_PRECONDITION for a merge that already ran, and that error is not
/// retryable. `move_limit` is deliberately NOT stripped: the client folds it
/// into the op id, so calls with different limits are different ops, and a
/// same-id call with a different recorded limit is a genuine mismatch.
const MERGE_PARAMETERS: [&str; 1] = ["created_at"];

/// Whether a retry is describing the merge the recorded op performed.
///
/// Compared on identity only. The full original is still what gets stored,
/// so a pod running the previous release keeps comparing it the way it
/// always did and a roll needs no coordination.
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
/// in the original request's source order. An aborted outcome records no
/// survivor; `delivered` fills it with the person the aborted delivery
/// wrote to, so the caller still learns the event's person.
// See `MergeEntrance::handle` for why result_large_err is allowed.
#[allow(clippy::result_large_err)]
fn merge_response(
    row: &OpRow,
    delivered: Option<ProtoPerson>,
    carried_applied: Vec<String>,
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
        carried_applied,
    })
}
