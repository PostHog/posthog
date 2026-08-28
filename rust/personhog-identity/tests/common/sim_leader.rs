//! A stateful simulated leader for lifecycle saga tests. Unlike a
//! record-only fake, it enforces the real leader's admission rules so a
//! saga that violates the protocol fails the test instead of merely
//! logging a suspicious call sequence:
//!
//! - It owns a fence map: a fence installed by one op rejects every other
//!   actor with the leader's typed rejection (FAILED_PRECONDITION plus
//!   `x-person-fenced` metadata — mirrors `fenced_status` in
//!   personhog-leader/src/fence.rs, which is not imported to keep that
//!   heavy crate out of this one's dev-dependencies).
//! - A committed release verifies the op's live mark row before producing
//!   a death document, and absorbs duplicates once one exists — the real
//!   leader's fail-closed rule, enforced here rather than just recorded.
//! - Failures are scripted per RPC and per person, so a test can fail one
//!   source's fence or release while its sibling succeeds.
//! - [`SimLeader::admit_write`] is the probe for "would the leader accept
//!   an ordinary write right now": tests call it mid-saga to assert that
//!   in-between states are never exposed to other actors.
//!
//! Its "cache" is the live Postgres row — what the real leader holds in a
//! quiet system — plus the death documents it has produced, which answer
//! as authoritative not-found exactly like the real cache's tombstones.

use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;

use async_trait::async_trait;
use chrono::Utc;
use sqlx::postgres::PgPool;
use tonic::Status;
use uuid::Uuid;

use personhog_common::grpc::semantic_refusal;
use personhog_identity::leader::{LifecycleLeader, PropertyWriter};
use personhog_proto::personhog::types::v1::{
    FencePersonRequest, FencePersonResponse, FoldPersonDocumentRequest, FoldPersonDocumentResponse,
    LifecycleOpType, Person, ReleaseFenceRequest, ReleaseFenceResponse, ReleaseOutcome,
    UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};

/// Which RPC a scripted failure applies to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Rpc {
    Fence,
    Fold,
    Release,
    PropertyPush,
}

/// A person's live fence in the simulated leader.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Fence {
    pub op_id: Uuid,
    pub op_type: LifecycleOpType,
    pub creator_event_uuid: Option<Uuid>,
}

/// A death document produced by a committed release.
#[derive(Debug, Clone, PartialEq)]
pub struct DeathDocument {
    pub person_id: i64,
    pub person_uuid: String,
    pub version: i64,
    pub created_at: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub enum LeaderCall {
    Fence {
        person_id: i64,
        op_type: LifecycleOpType,
    },
    Fold {
        target_person_id: i64,
        snapshot_versions: Vec<i64>,
        /// The folded document's max-merged `last_seen_at`.
        folded_last_seen_at: Option<i64>,
    },
    ReleaseCommitted {
        person_id: i64,
        sealed_version: i64,
        /// The source's `lifecycle_op_person.status` observed at release
        /// time. The sim also *enforces* mark liveness (see the module
        /// docs); the recorded value lets tests assert the exact status.
        mark_status_at_release: Option<String>,
    },
    ReleaseAborted {
        person_id: i64,
    },
    PropertyPush {
        person_id: i64,
        is_identified: Option<bool>,
    },
}

/// Metadata keys carried on fenced-write rejections; must stay in sync
/// with personhog-leader/src/fence.rs.
pub const FENCED_METADATA_KEY: &str = "x-person-fenced";
pub const FENCED_OP_ID_METADATA_KEY: &str = "x-person-fenced-op-id";
pub const FENCED_CREATOR_METADATA_KEY: &str = "x-person-fenced-creator";

fn fenced_status(fence: &Fence) -> Status {
    let what = match fence.op_type {
        LifecycleOpType::Delete => "PERSON_DELETING",
        LifecycleOpType::Merge => "PERSON_MERGING",
        LifecycleOpType::Unspecified => "PERSON_FENCED",
    };
    let mut status = Status::failed_precondition(format!(
        "{what}: person is fenced by lifecycle op {}",
        fence.op_id
    ));
    if let Ok(value) = fence.op_type.as_op_type_str().parse() {
        status.metadata_mut().insert(FENCED_METADATA_KEY, value);
    }
    if let Ok(value) = fence.op_id.to_string().parse() {
        status
            .metadata_mut()
            .insert(FENCED_OP_ID_METADATA_KEY, value);
    }
    if let Some(creator) = fence.creator_event_uuid {
        if let Ok(value) = creator.to_string().parse() {
            status
                .metadata_mut()
                .insert(FENCED_CREATOR_METADATA_KEY, value);
        }
    }
    status
}

pub struct SimLeader {
    pool: PgPool,
    person_table: String,
    calls: Mutex<Vec<LeaderCall>>,
    fences: Mutex<HashMap<i64, Fence>>,
    deaths: Mutex<HashMap<i64, DeathDocument>>,
    scripted: Mutex<HashMap<(Rpc, i64), VecDeque<Status>>>,
    /// Sealed `is_identified` overrides per person: the leader's state can
    /// be ahead of Postgres, which is exactly what the seal-time re-check
    /// exists for.
    sealed_identified: Mutex<HashMap<i64, bool>>,
    /// Injected `last_seen_at` per person: leader-side state with no
    /// Postgres column.
    last_seen: Mutex<HashMap<i64, i64>>,
}

impl SimLeader {
    pub fn new(pool: PgPool, person_table: String) -> Self {
        Self {
            pool,
            person_table,
            calls: Mutex::new(Vec::new()),
            fences: Mutex::new(HashMap::new()),
            deaths: Mutex::new(HashMap::new()),
            scripted: Mutex::new(HashMap::new()),
            sealed_identified: Mutex::new(HashMap::new()),
            last_seen: Mutex::new(HashMap::new()),
        }
    }

    pub fn calls(&self) -> Vec<LeaderCall> {
        self.calls.lock().unwrap().clone()
    }

    /// Script the next matching call for `person_id` (the fold matches on
    /// the target's id) to fail with `status`. Queued failures pop in
    /// order, one per call.
    pub fn fail_next(&self, rpc: Rpc, person_id: i64, status: Status) {
        self.scripted
            .lock()
            .unwrap()
            .entry((rpc, person_id))
            .or_default()
            .push_back(status);
    }

    /// Whether every scripted failure for this key has been consumed. Lets a
    /// test tell a rejected call from a call that never happened.
    pub fn scripted_drained(&self, rpc: Rpc, person_id: i64) -> bool {
        self.scripted
            .lock()
            .unwrap()
            .get(&(rpc, person_id))
            .is_none_or(|queue| queue.is_empty())
    }

    pub fn set_sealed_identified(&self, person_id: i64, identified: bool) {
        self.sealed_identified
            .lock()
            .unwrap()
            .insert(person_id, identified);
    }

    pub fn set_last_seen(&self, person_id: i64, epoch: i64) {
        self.last_seen.lock().unwrap().insert(person_id, epoch);
    }

    pub fn fence_for(&self, person_id: i64) -> Option<Fence> {
        self.fences.lock().unwrap().get(&person_id).copied()
    }

    /// Death documents produced so far, ordered by person id.
    pub fn death_documents(&self) -> Vec<DeathDocument> {
        let mut deaths: Vec<DeathDocument> =
            self.deaths.lock().unwrap().values().cloned().collect();
        deaths.sort_by_key(|d| d.person_id);
        deaths
    }

    /// The leader's write-admission decision for an ordinary (non-lifecycle)
    /// write right now: fenced persons reject, destroyed persons are
    /// not found. Tests probe this mid-saga to assert intermediate states
    /// are shielded from other actors.
    pub async fn admit_write(&self, team_id: i64, person_id: i64) -> Result<(), Status> {
        if let Some(fence) = self.fence_for(person_id) {
            return Err(fenced_status(&fence));
        }
        if self.deaths.lock().unwrap().contains_key(&person_id) {
            return Err(Status::not_found("person is destroyed"));
        }
        match self.live_person(team_id, person_id).await {
            Some(_) => Ok(()),
            None => Err(Status::not_found("person is destroyed")),
        }
    }

    fn take_scripted(&self, rpc: Rpc, person_id: i64) -> Option<Status> {
        self.scripted
            .lock()
            .unwrap()
            .get_mut(&(rpc, person_id))
            .and_then(|queue| queue.pop_front())
    }

    async fn live_person(&self, team_id: i64, person_id: i64) -> Option<Person> {
        let live_sql = format!(
            r#"
            SELECT uuid, COALESCE(version, 0), created_at, is_identified, properties
            FROM {person_table}
            WHERE team_id = $1 AND id = $2 AND is_deleted = false
            "#,
            person_table = self.person_table,
        );
        let row: Option<(Uuid, i64, chrono::DateTime<Utc>, bool, serde_json::Value)> =
            sqlx::query_as(&live_sql)
                .bind(team_id as i32)
                .bind(person_id)
                .fetch_optional(&self.pool)
                .await
                .expect("person lookup");
        row.map(
            |(uuid, version, created_at, is_identified, properties)| Person {
                id: person_id,
                uuid: uuid.to_string(),
                team_id,
                properties: serde_json::to_vec(&properties).unwrap(),
                created_at: created_at.timestamp_millis(),
                version,
                is_identified,
                last_seen_at: self.last_seen.lock().unwrap().get(&person_id).copied(),
                ..Default::default()
            },
        )
    }

    /// The mark row the real leader consults before producing a death
    /// document (personhog-leader/src/fence.rs `mark_status`).
    async fn mark_status(&self, op_id: Uuid, team_id: i64, person_id: i64) -> Option<String> {
        sqlx::query_scalar(
            "SELECT status FROM lifecycle_op_person \
             WHERE op_id = $1 AND team_id = $2 AND person_id = $3 AND role <> 'target'",
        )
        .bind(op_id)
        .bind(team_id as i32)
        .bind(person_id)
        .fetch_optional(&self.pool)
        .await
        .expect("mark lookup")
    }

    /// The target-mark row the real leader consults before folding.
    async fn target_mark_status(
        &self,
        op_id: Uuid,
        team_id: i64,
        person_id: i64,
    ) -> Option<String> {
        sqlx::query_scalar(
            "SELECT status FROM lifecycle_op_person \
             WHERE op_id = $1 AND team_id = $2 AND person_id = $3 AND role = 'target'",
        )
        .bind(op_id)
        .bind(team_id as i32)
        .bind(person_id)
        .fetch_optional(&self.pool)
        .await
        .expect("target mark lookup")
    }

    fn record(&self, call: LeaderCall) {
        self.calls.lock().unwrap().push(call);
    }
}

#[async_trait]
impl LifecycleLeader for SimLeader {
    async fn fence_person(
        &self,
        request: FencePersonRequest,
    ) -> Result<FencePersonResponse, Status> {
        if let Some(status) = self.take_scripted(Rpc::Fence, request.person_id) {
            return Err(status);
        }
        let op_id = Uuid::parse_str(&request.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
        if let Some(existing) = self.fence_for(request.person_id) {
            if existing.op_id != op_id {
                return Err(fenced_status(&existing));
            }
        }
        if self.deaths.lock().unwrap().contains_key(&request.person_id) {
            return Err(Status::not_found("person is destroyed"));
        }
        let Some(mut person) = self.live_person(request.team_id, request.person_id).await else {
            return Err(Status::not_found("person is destroyed"));
        };
        if let Some(identified) = self
            .sealed_identified
            .lock()
            .unwrap()
            .get(&request.person_id)
        {
            person.is_identified = *identified;
        }
        let creator_event_uuid = Uuid::parse_str(&request.creator_event_uuid).ok();
        self.fences.lock().unwrap().insert(
            request.person_id,
            Fence {
                op_id,
                op_type: request.op_type(),
                creator_event_uuid,
            },
        );
        self.record(LeaderCall::Fence {
            person_id: request.person_id,
            op_type: request.op_type(),
        });
        Ok(FencePersonResponse {
            sealed: Some(person),
        })
    }

    async fn release_fence(
        &self,
        request: ReleaseFenceRequest,
    ) -> Result<ReleaseFenceResponse, Status> {
        if let Some(status) = self.take_scripted(Rpc::Release, request.person_id) {
            return Err(status);
        }
        let op_id = Uuid::parse_str(&request.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
        if let Some(existing) = self.fence_for(request.person_id) {
            if existing.op_id != op_id {
                return Err(fenced_status(&existing));
            }
        }
        match request.outcome() {
            ReleaseOutcome::Aborted => {
                self.fences.lock().unwrap().remove(&request.person_id);
                self.record(LeaderCall::ReleaseAborted {
                    person_id: request.person_id,
                });
                Ok(ReleaseFenceResponse {})
            }
            ReleaseOutcome::Committed => {
                let Some(sealed_version) = request.sealed_version else {
                    return Err(Status::invalid_argument(
                        "sealed_version is required for a committed release",
                    ));
                };
                if request.created_at <= 0 {
                    return Err(Status::invalid_argument(
                        "created_at is required for a committed release",
                    ));
                }
                if Uuid::parse_str(&request.person_uuid).is_err() {
                    return Err(Status::invalid_argument(
                        "person_uuid must be a valid UUID for a committed release",
                    ));
                }
                let mark_status = self
                    .mark_status(op_id, request.team_id, request.person_id)
                    .await;
                self.record(LeaderCall::ReleaseCommitted {
                    person_id: request.person_id,
                    sealed_version,
                    mark_status_at_release: mark_status.clone(),
                });

                // A death document already exists: absorb the retry, like
                // the real leader's is_deleted cache entry does.
                if self.deaths.lock().unwrap().contains_key(&request.person_id) {
                    self.fences.lock().unwrap().remove(&request.person_id);
                    return Ok(ReleaseFenceResponse {});
                }

                match mark_status.as_deref() {
                    Some("marked") | Some("sealed") => {}
                    Some("deleted") => {
                        self.fences.lock().unwrap().remove(&request.person_id);
                        return Ok(ReleaseFenceResponse {});
                    }
                    _ => {
                        return Err(semantic_refusal(
                            "op holds no live mark for this person; \
                             refusing to produce a death document",
                            "release-unverified",
                        ));
                    }
                }

                let current = self.live_person(request.team_id, request.person_id).await;
                if let Some(person) = &current {
                    if person.uuid != request.person_uuid {
                        return Err(semantic_refusal(
                            "person_uuid does not match the person being released",
                            "uuid-mismatch",
                        ));
                    }
                }
                let base_version = current
                    .as_ref()
                    .map(|p| p.version)
                    .unwrap_or(0)
                    .max(sealed_version);
                self.deaths.lock().unwrap().insert(
                    request.person_id,
                    DeathDocument {
                        person_id: request.person_id,
                        person_uuid: request.person_uuid.clone(),
                        version: base_version + 1,
                        created_at: request.created_at,
                    },
                );
                self.fences.lock().unwrap().remove(&request.person_id);
                Ok(ReleaseFenceResponse {})
            }
            ReleaseOutcome::Unspecified => {
                Err(Status::invalid_argument("outcome must be specified"))
            }
        }
    }

    async fn fold_person_document(
        &self,
        request: FoldPersonDocumentRequest,
    ) -> Result<FoldPersonDocumentResponse, Status> {
        if let Some(status) = self.take_scripted(Rpc::Fold, request.person_id) {
            return Err(status);
        }
        let op_id = Uuid::parse_str(&request.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
        if let Some(existing) = self.fence_for(request.person_id) {
            if existing.op_id != op_id {
                return Err(fenced_status(&existing));
            }
        }
        if self.deaths.lock().unwrap().contains_key(&request.person_id) {
            return Err(Status::not_found("person is destroyed"));
        }
        let Some(target) = self.live_person(request.team_id, request.person_id).await else {
            return Err(Status::not_found("person is destroyed"));
        };
        // The real leader refuses a fold unless the op holds a live
        // target mark.
        match self
            .target_mark_status(op_id, request.team_id, request.person_id)
            .await
            .as_deref()
        {
            Some("marked") => {}
            _ => {
                return Err(semantic_refusal(
                    "op holds no live target mark for this person; refusing to fold",
                    "fold-unverified",
                ));
            }
        }
        // The real fold: the target wins every key it has, snapshots fill
        // still-absent keys in ordinal order (the leader sorts, not the
        // caller), then the merge event's $set overrides and $set_once
        // fills; `last_seen_at` max-merges across the target and every
        // snapshot.
        let mut folded: serde_json::Map<String, serde_json::Value> =
            serde_json::from_slice(&target.properties).unwrap();
        let mut created_at = target.created_at;
        let mut max_sealed = 0;
        let mut snapshot_versions = Vec::new();
        let mut last_seen_at = target.last_seen_at;
        let mut ordered = request.sealed_snapshots.clone();
        ordered.sort_by_key(|snapshot| snapshot.ordinal);
        for snapshot in &ordered {
            let person = snapshot
                .person
                .as_ref()
                .ok_or_else(|| Status::invalid_argument("sealed snapshot is missing its person"))?;
            let properties: serde_json::Map<String, serde_json::Value> =
                serde_json::from_slice(&person.properties).unwrap();
            for (key, value) in properties {
                folded.entry(key).or_insert(value);
            }
            if person.created_at > 0 {
                created_at = created_at.min(person.created_at);
            }
            max_sealed = max_sealed.max(person.version);
            snapshot_versions.push(person.version);
            last_seen_at = last_seen_at.max(person.last_seen_at);
        }
        if !request.event_set.is_empty() {
            let event_set: serde_json::Map<String, serde_json::Value> =
                serde_json::from_slice(&request.event_set).unwrap();
            for (key, value) in event_set {
                folded.insert(key, value);
            }
        }
        if !request.event_set_once.is_empty() {
            let event_set_once: serde_json::Map<String, serde_json::Value> =
                serde_json::from_slice(&request.event_set_once).unwrap();
            for (key, value) in event_set_once {
                folded.entry(key).or_insert(value);
            }
        }
        self.record(LeaderCall::Fold {
            target_person_id: request.person_id,
            snapshot_versions,
            folded_last_seen_at: last_seen_at,
        });
        Ok(FoldPersonDocumentResponse {
            person: Some(Person {
                properties: serde_json::to_vec(&folded).unwrap(),
                created_at,
                version: target.version.max(max_sealed) + 1,
                is_identified: true,
                last_seen_at,
                ..target
            }),
        })
    }
}

/// The RPC's inline path pushes the merge event's properties through the
/// ordinary write surface; the sim applies the same admission rules as
/// any other write, so a push to a fenced or destroyed person fails the
/// test.
#[async_trait]
impl PropertyWriter for SimLeader {
    async fn update_person_properties(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status> {
        if let Some(status) = self.take_scripted(Rpc::PropertyPush, request.person_id) {
            return Err(status);
        }
        if let Some(fence) = self.fence_for(request.person_id) {
            return Err(fenced_status(&fence));
        }
        if self.deaths.lock().unwrap().contains_key(&request.person_id) {
            return Err(Status::not_found("person is destroyed"));
        }
        let mut person = self
            .live_person(request.team_id, request.person_id)
            .await
            .ok_or_else(|| Status::not_found("person is destroyed"))?;
        // Properties are applied and persisted, because the seal reads them
        // back out of Postgres: without this the sim cannot tell a write
        // that landed from one that was never sent, which is exactly what
        // the carried-operation path needs to prove.
        let decode = |bytes: &[u8]| {
            serde_json::from_slice::<serde_json::Map<String, serde_json::Value>>(bytes)
                .unwrap_or_default()
        };
        let mut properties = decode(&person.properties);
        // The real leader's $unset removes only keys present BEFORE the op,
        // so a pair (set/set_once and unset of one key in one op) keeps the
        // written value where the key was absent. Mirrored here or a
        // carried-pair test would certify the wrong semantics.
        let present_before: std::collections::HashSet<String> =
            properties.keys().cloned().collect();
        for (key, value) in decode(&request.set_once_properties) {
            properties.entry(key).or_insert(value);
        }
        for (key, value) in decode(&request.set_properties) {
            properties.insert(key, value);
        }
        for key in &request.unset_properties {
            if present_before.contains(key) {
                properties.remove(key);
            }
        }
        let encoded = serde_json::Value::Object(properties);
        // The identity flip persists too, because the seal reads the row:
        // a carried is_identified that the real leader would surface at
        // fence time has to be visible to the saga's identified re-check,
        // or the one interaction the flip exists for goes unmodeled.
        let flip = request.is_identified == Some(true);
        let update_sql = format!(
            "UPDATE {person_table} SET properties = $3::jsonb, is_identified = is_identified OR $4 \
             WHERE team_id = $1 AND id = $2",
            person_table = self.person_table,
        );
        sqlx::query(&update_sql)
            .bind(request.team_id as i32)
            .bind(request.person_id)
            .bind(&encoded)
            .bind(flip)
            .execute(&self.pool)
            .await
            .expect("property write");
        person.properties = serde_json::to_vec(&encoded).expect("serialize properties");
        // The real leader OR-merges the flip and answers with the updated person.
        person.is_identified = person.is_identified || flip;
        self.record(LeaderCall::PropertyPush {
            person_id: request.person_id,
            is_identified: request.is_identified,
        });
        Ok(UpdatePersonPropertiesResponse {
            person: Some(person),
            updated: true,
        })
    }
}
