//! The MergePersons entrance: request validation, identity resolution,
//! classification, inline settlement, and response assembly. This is
//! identity work — the pairs that never need a saga settle here — and the
//! lifecycle side stays blind to it: the entrance reaches the durable op
//! machinery only through [`MergeOpExecutor`], handing over a frozen
//! request and receiving a terminal op row.

use std::collections::HashMap;
use std::sync::Arc;

use chrono::{DateTime, Utc};
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
use crate::lifecycle::validation::{is_distinct_id_illegal, validate_merge_persons};
use crate::storage::{AttachOutcome, IdentityStorage, Person, PersonStub, StubOutcome};

/// Handler-decided outcomes that never reach the saga.
const OUTCOME_SKIPPED_ILLEGAL: &str = "skipped_illegal";
const OUTCOME_ATTACHED: &str = "attached";

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
        let event_set = parse_json_map(&request.event_set, "event_set")?;
        let event_set_once = parse_json_map(&request.event_set_once, "event_set_once")?;
        let original = merge_original(&request, &event_set, &event_set_once);

        // Attach-first: classification below is time-dependent (a retry
        // after the merge committed would re-classify every merged pair as
        // a no-op and freeze a different request), so an existing op is
        // compared on the ORIGINAL call and driven with its own frozen
        // request — never re-classified. Two racing FIRST calls can still
        // classify divergently and the insert loser then sees the engine's
        // full-request mismatch; that surfaces as FAILED_PRECONDITION once
        // and self-heals — the next retry attaches here.
        if let Some(row) = self.ops.find(op_id).await? {
            if row.op_type != OP_TYPE_MERGE
                || row.team_id != request.team_id
                || row.request.get("original") != Some(&original)
            {
                return Err(Status::failed_precondition(format!(
                    "op_id {op_id} was already used for a different request"
                )));
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
        let target_person = match resolved.get(&target_key) {
            Some(target) => target.clone(),
            None => self.establish_target(&request, &resolved).await?,
        };

        let mut inline_results: HashMap<String, String> = HashMap::new();
        let mut attach: Vec<String> = Vec::new();
        let mut saga_sources: Vec<MergeSourceEntry> = Vec::new();
        for source in &request.sources {
            let did = &source.source_distinct_id;
            if is_distinct_id_illegal(did) {
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
    /// resolved legal source's person survives and the target distinct id
    /// attaches to it; when nothing in the call resolves, the target
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

        let first_resolved = request
            .sources
            .iter()
            .filter(|s| !is_distinct_id_illegal(&s.source_distinct_id))
            .find_map(|s| resolved.get(&(request.team_id, s.source_distinct_id.clone())));
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

        // Nothing in the call resolves: birth the target person. An
        // identify with only illegal sources still creates the target (the
        // caller's event needs a person) but proves no identity, so it is
        // born unidentified.
        let any_legal_source = request
            .sources
            .iter()
            .any(|s| !is_distinct_id_illegal(&s.source_distinct_id));
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
                is_identified: any_legal_source,
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
    serde_json::json!({
        "target_distinct_id": request.target_distinct_id,
        "sources": request
            .sources
            .iter()
            .map(|s| serde_json::json!({
                "distinct_id": s.source_distinct_id,
                "event_uuid": s.event_uuid,
            }))
            .collect::<Vec<_>>(),
        "event_set": event_set,
        "event_set_once": event_set_once,
        "allow_identified_sources": request.allow_identified_sources,
        "move_limit": request.move_limit,
        "created_at": request.created_at,
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
    let original_sources: Vec<String> = row
        .request
        .get("original")
        .and_then(|o| o.get("sources"))
        .and_then(|s| s.as_array())
        .map(|sources| {
            sources
                .iter()
                .filter_map(|s| s.get("distinct_id").and_then(|d| d.as_str()))
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();

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
