//! The lifecycle fence RPCs: a fence freezes a person for one op and
//! seals its state, and a release closes the fence with the op's outcome.
//! The single-call and batch handlers share the per-person helpers here.

use std::time::Instant;

use futures::StreamExt;
use metrics::{counter, histogram};
use personhog_common::grpc::is_semantic_refusal;
use personhog_proto::personhog::types::v1::{
    FencePersonRequest, FencePersonResponse, FencePersonsRequest, FencePersonsResponse,
    FencedPersonSeal, LifecycleOpType, Person, ReleaseFenceRequest, ReleaseFenceResponse,
    ReleaseFencesRequest, ReleaseFencesResponse, ReleaseOutcome,
};
use tonic::{Request, Response, Status};
use uuid::Uuid;

use crate::cache::{approx_person_bytes, CachedPerson, PersonCacheKey};
use crate::fence::{fenced_status, mark_status, mark_statuses, semantic_refusal, FenceState};
use crate::pg::PgFallback;

use super::{cached_person_to_proto, partition_from_metadata, PersonHogLeaderService};

/// The ceiling on persons per `FencePersons` or `ReleaseFences` call. The
/// lifecycle service splits its calls at this size, so a larger batch is a
/// caller bug, not load.
const MAX_LIFECYCLE_BATCH_SIZE: usize = 100;

/// Fences or releases of one batch call in flight at once. Above the
/// fallback pool's size, extra loads only queue at the pool while the
/// batch holds the partition's handoff drain.
const LIFECYCLE_BATCH_CONCURRENCY: usize = 16;

/// The one error a batch answers for: a semantic refusal is the final
/// answer for its person and must not hide behind a sibling's transient
/// error, which the saga would retry.
#[allow(clippy::result_large_err)]
fn first_batch_failure(failures: Vec<Status>) -> Result<(), Status> {
    let mut failures = failures.into_iter();
    let Some(first) = failures.next() else {
        return Ok(());
    };
    Err(failures
        .find(is_semantic_refusal)
        .filter(|_| !is_semantic_refusal(&first))
        .unwrap_or(first))
}

/// The per-person inputs of a committed release, validated the same way
/// whether they arrive alone or in a batch.
struct CommittedRelease {
    person_id: i64,
    person_uuid: String,
    sealed_version: i64,
    created_at: i64,
}

impl CommittedRelease {
    #[allow(clippy::result_large_err)]
    fn validate(
        person_id: i64,
        person_uuid: String,
        sealed_version: Option<i64>,
        created_at: i64,
    ) -> Result<Self, Status> {
        // 0 is a legitimate sealed version (a fresh stub's), which is why
        // the field is explicitly optional in the proto.
        let Some(sealed_version) = sealed_version else {
            return Err(Status::invalid_argument(
                "sealed_version is required for a committed release",
            ));
        };
        if sealed_version < 0 {
            return Err(Status::invalid_argument(
                "sealed_version must not be negative",
            ));
        }
        if created_at <= 0 {
            return Err(Status::invalid_argument(
                "created_at is required for a committed release",
            ));
        }
        if Uuid::parse_str(&person_uuid).is_err() {
            return Err(Status::invalid_argument(
                "person_uuid must be a valid UUID for a committed release",
            ));
        }
        Ok(Self {
            person_id,
            person_uuid,
            sealed_version,
            created_at,
        })
    }
}

/// A mark lookup that failed is rejected retriably: the op may well hold
/// the person, but the leader could not prove it — fail closed.
fn mark_lookup_failed(e: sqlx::Error) -> Status {
    tracing::warn!(error = %e, "mark verification failed; rejecting (fail closed)");
    Status::unavailable("could not verify the lifecycle op against its mark; retry")
}

/// Per-phase wall time of a committed release; the RPC histogram alone
/// cannot separate the lock, the load, the mark check, and the produce.
fn record_release_phase(phase: &'static str, started: Instant) {
    histogram!("personhog_leader_release_phase_ms", "phase" => phase)
        .record(started.elapsed().as_secs_f64() * 1000.0);
}

impl PersonHogLeaderService {
    #[allow(clippy::result_large_err)]
    fn lifecycle_db(&self) -> Result<&PgFallback, Status> {
        self.fallback.as_ref().ok_or_else(|| {
            semantic_refusal(
                "no lifecycle database configured; refusing to produce a death document",
                "no-lifecycle-db",
            )
        })
    }

    /// The committed half of a release for one person, given its mark
    /// row's status. Shared by `ReleaseFence` and `ReleaseFences` so what
    /// destroys a person is decided in one place.
    async fn release_committed(
        &self,
        partition: u32,
        team_id: i64,
        op_id: Uuid,
        release: &CommittedRelease,
        mark: Option<&str>,
    ) -> Result<(), Status> {
        let cache_key = PersonCacheKey {
            team_id,
            person_id: release.person_id,
        };
        let mutex = self
            .locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let lock_started = Instant::now();
        let guard = mutex.lock_owned().await;
        record_release_phase("lock_wait", lock_started);

        // Releasing another op's fence would break that op's seal.
        if let Some(entry) = self.fences.get(&cache_key) {
            if entry.op_id != op_id {
                return Err(fenced_status(entry.value()));
            }
        }

        // Release must stay idempotent for the saga's retry and the
        // sweeper, so a person the leader cannot load anymore is
        // tolerated.
        let load_started = Instant::now();
        let loaded = self.lookup_or_load_locked(partition, &cache_key).await;
        record_release_phase("load", load_started);
        let current = match loaded {
            Ok(person) => Some(person),
            Err(status) if status.code() == tonic::Code::NotFound => None,
            Err(status) => return Err(status),
        };

        // Duplicate release: the death document already exists;
        // producing another would only bump the version. Gate
        // first — a refused release must leave the fence.
        if current.as_ref().is_some_and(|p| p.is_deleted) {
            self.assert_authoritative(partition)?;
            self.fences.remove(&cache_key);
            return Ok(());
        }

        // The request carries the identity a cold leader has nothing else
        // for; when the leader does hold the person, the two must agree, or
        // the death document would rewrite the row's uuid on its way out.
        if let Some(person) = &current {
            if person.uuid != release.person_uuid {
                return Err(semantic_refusal(
                    "person_uuid does not match the person being released",
                    "uuid-mismatch",
                ));
            }
        }

        // The mark row must vouch for the op before anything is destroyed:
        // the in-memory fence was installed on the request's word alone, so
        // request plus fence is never enough. Unverifiable is refused.
        match mark {
            // A live mark: the op holds the person; proceed.
            Some("marked") | Some("sealed") => {}
            // The mark already settled as deleted: this release
            // already happened and the tombstone is durable;
            // absorb the retry.
            Some("deleted") => {
                self.assert_authoritative(partition)?;
                self.fences.remove(&cache_key);
                return Ok(());
            }
            _ => {
                counter!("personhog_leader_fences_total", "action" => "release_unverified")
                    .increment(1);
                return Err(semantic_refusal(
                    "op holds no live mark for this person; \
                     refusing to produce a death document",
                    "release-unverified",
                ));
            }
        }

        if !self.dirty_index.can_admit(&cache_key) {
            counter!("personhog_leader_writes_shed_total", "reason" => "dirty_index_full")
                .increment(1);
            return Err(Status::resource_exhausted(
                "dirty index at capacity: the writer is behind and this death document \
                 cannot be tracked; retry later",
            ));
        }
        // The death version is sealed + 1, floored by the emitted floor and
        // the cached version in case a deposed or indeterminate produce spent
        // a higher version; a cold leader falls back to the request's seal.
        let base_version = self.emitted_versions.floor_for(
            partition,
            &cache_key,
            current
                .as_ref()
                .map(|p| p.version)
                .unwrap_or(0)
                .max(release.sealed_version),
        );
        let death_version = base_version.checked_add(1).ok_or_else(|| {
            Status::invalid_argument("sealed_version leaves no room for the death version")
        })?;
        let death = CachedPerson {
            id: release.person_id,
            uuid: release.person_uuid.clone(),
            team_id,
            properties: b"{}".to_vec(),
            // The sealed value, not the cached one: cold and warm
            // leaders must produce the same document.
            created_at: release.created_at,
            version: death_version,
            is_identified: false,
            is_deleted: true,
            last_seen_at: None,
            approx_bytes: approx_person_bytes(2),
        };
        let produce_started = Instant::now();
        // The RPC's own guard admitted the batch; this one rides the
        // commit through its outcome.
        let inflight = self.inflight.begin(partition);
        let committed = self
            .commit_document(partition, &cache_key, death, guard, inflight)
            .await;
        record_release_phase("produce", produce_started);
        let _committed = committed?;
        // The death document stays cached while its mark stands, answering
        // not-found from memory; the prune-time settle drops it once the
        // writer confirms, and PG answers from then on.
        self.fences.remove(&cache_key);
        counter!("personhog_leader_fences_total", "action" => "released_committed").increment(1);
        Ok(())
    }

    /// Fence one person and seal its state under its per-person lock,
    /// shared by `FencePerson` and `FencePersons`. The caller has admitted
    /// the partition: routing, authority, ownership, and the inflight guard.
    async fn fence_one(
        &self,
        partition: u32,
        cache_key: PersonCacheKey,
        op_id: Uuid,
        op_type: LifecycleOpType,
    ) -> Result<Person, Status> {
        let mutex = self
            .locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let _guard = mutex.lock().await;

        let refence = if let Some(entry) = self.fences.get(&cache_key) {
            if entry.op_id != op_id {
                let holder = *entry.value();
                drop(entry);
                // One op holds a person at a time; the loser backs off. The
                // holder may be a ghost whose op settled unheard, so kick the
                // lazy heal, since a quiet person gets no other caller.
                if let Some(healer) = &self.fence_healer {
                    healer.maybe_heal(cache_key.clone(), holder);
                }
                return Err(fenced_status(&holder));
            }
            true
        } else {
            false
        };

        // The map has no eviction, so a surge of ops is bounded by shedding
        // new fences; re-seals are exempt because refusing them frees
        // nothing. The saga's retry absorbs the backpressure.
        if !refence && self.fences.len() >= self.fence_map_max_entries {
            counter!("personhog_leader_fences_total", "action" => "shed_capacity").increment(1);
            return Err(Status::resource_exhausted(format!(
                "fence map at capacity ({} live fences); retry later",
                self.fence_map_max_entries
            )));
        }

        // The seal is the newest cached state under the write lock, raised
        // to the emitted floor: an indeterminate pre-fence write may have
        // spent a higher version. A same-op re-fence re-seals the same way.
        let person = self.lookup_or_load_locked(partition, &cache_key).await?;
        // The load can park on the per-key lock or a recovery; the seal,
        // not the arrival, must be backed by ownership.
        self.check_authority(partition)?;
        if person.is_deleted {
            return Err(Status::not_found("person is destroyed"));
        }

        let mut sealed = cached_person_to_proto(&person);
        sealed.version = self
            .emitted_versions
            .floor_for(partition, &cache_key, person.version);

        self.fences.insert(cache_key, FenceState { op_id, op_type });
        counter!("personhog_leader_fences_total", "action" => "fenced").increment(1);
        Ok(sealed)
    }

    /// The aborted half of a release for one person: drop the fence, keep
    /// the entry, produce nothing. Gated first — a refused release must
    /// leave the fence (pinned).
    async fn release_aborted(
        &self,
        partition: u32,
        team_id: i64,
        person_id: i64,
        op_id: Uuid,
    ) -> Result<(), Status> {
        let cache_key = PersonCacheKey { team_id, person_id };
        let mutex = self
            .locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let _guard = mutex.lock().await;

        // Releasing another op's fence would break that op's seal.
        if let Some(entry) = self.fences.get(&cache_key) {
            if entry.op_id != op_id {
                return Err(fenced_status(entry.value()));
            }
        }
        self.assert_authoritative(partition)?;
        self.fences.remove(&cache_key);
        counter!("personhog_leader_fences_total", "action" => "released_aborted").increment(1);
        Ok(())
    }

    pub(super) async fn fence_person_rpc(
        &self,
        request: Request<FencePersonRequest>,
    ) -> Result<Response<FencePersonResponse>, Status> {
        let partition = partition_from_metadata(&request)?;
        let req = request.into_inner();
        self.validate_partition(partition, req.team_id, req.person_id)?;
        // Ownership below is in-process state, which is what a lease
        // lapse makes stale: a fence installed here gates no writes.
        self.check_authority(partition)?;
        let op_id = Uuid::parse_str(&req.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
        let op_type = req.op_type();
        if op_type == LifecycleOpType::Unspecified {
            return Err(Status::invalid_argument("op_type must be specified"));
        }
        // A fence installed anywhere but the current owner gates nothing:
        // ownership covers a pod that already handed the partition off, the
        // inflight guard covers the drain window; the saga's retry re-routes.
        self.validate_ownership(partition)?;
        let Some(_inflight_guard) = self.inflight.try_begin(partition) else {
            return Err(Status::failed_precondition(format!(
                "partition {partition} is fenced for handoff; writes are rejected"
            )));
        };

        let cache_key = PersonCacheKey {
            team_id: req.team_id,
            person_id: req.person_id,
        };
        let sealed = self.fence_one(partition, cache_key, op_id, op_type).await?;

        self.authoritative_ok(
            partition,
            FencePersonResponse {
                sealed: Some(sealed),
            },
        )
    }

    pub(super) async fn fence_persons_rpc(
        &self,
        request: Request<FencePersonsRequest>,
    ) -> Result<Response<FencePersonsResponse>, Status> {
        let partition = partition_from_metadata(&request)?;
        let req = request.into_inner();
        if req.person_ids.len() > MAX_LIFECYCLE_BATCH_SIZE {
            return Err(Status::invalid_argument(format!(
                "FencePersons carries {} persons; the cap is {MAX_LIFECYCLE_BATCH_SIZE}",
                req.person_ids.len()
            )));
        }
        let team_id = req.team_id;
        // The caller grouped its batch by partition and routed it by one
        // member, so every member must hash to the routed partition; a
        // stale partition count refuses the whole batch before any fence.
        for person_id in &req.person_ids {
            self.validate_partition(partition, team_id, *person_id)?;
        }
        self.check_authority(partition)?;
        let op_id = Uuid::parse_str(&req.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
        let op_type = req.op_type();
        if op_type == LifecycleOpType::Unspecified {
            return Err(Status::invalid_argument("op_type must be specified"));
        }
        self.validate_ownership(partition)?;
        let Some(_inflight_guard) = self.inflight.try_begin(partition) else {
            return Err(Status::failed_precondition(format!(
                "partition {partition} is fenced for handoff; writes are rejected"
            )));
        };
        histogram!("personhog_leader_fence_batch_size").record(req.person_ids.len() as f64);

        // Every fence runs to completion before the batch answers, so a
        // sibling's refusal cancels no load in flight under a lock; the
        // bound keeps the fallback pool's queue and the drain hold shallow.
        let fence_futures = req.person_ids.into_iter().map(|person_id| async move {
            let cache_key = PersonCacheKey { team_id, person_id };
            (
                person_id,
                self.fence_one(partition, cache_key, op_id, op_type).await,
            )
        });
        let results: Vec<_> = futures::stream::iter(fence_futures)
            .buffer_unordered(LIFECYCLE_BATCH_CONCURRENCY)
            .collect()
            .await;

        let mut sealed = Vec::with_capacity(results.len());
        let mut not_found = Vec::new();
        let mut failures = Vec::new();
        for (person_id, result) in results {
            match result {
                Ok(person) => sealed.push(FencedPersonSeal {
                    person_id,
                    version: person.version,
                    created_at: person.created_at,
                }),
                Err(status) if status.code() == tonic::Code::NotFound => not_found.push(person_id),
                Err(status) => failures.push(status),
            }
        }
        first_batch_failure(failures)?;

        self.authoritative_ok(partition, FencePersonsResponse { sealed, not_found })
    }

    pub(super) async fn release_fence_rpc(
        &self,
        request: Request<ReleaseFenceRequest>,
    ) -> Result<Response<ReleaseFenceResponse>, Status> {
        let partition = partition_from_metadata(&request)?;
        let req = request.into_inner();
        self.validate_partition(partition, req.team_id, req.person_id)?;
        // The aborted arm would otherwise ack under a lapsed lease; the
        // committed arm's produce and durable-fact acks need no cover.
        self.check_authority(partition)?;
        let op_id = Uuid::parse_str(&req.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;

        match req.outcome() {
            ReleaseOutcome::Committed => {
                let release = CommittedRelease::validate(
                    req.person_id,
                    req.person_uuid,
                    req.sealed_version,
                    req.created_at,
                )?;
                // Producing to the changelog must respect the handoff
                // write freeze like any write.
                let Some(_inflight_guard) = self.inflight.try_begin(partition) else {
                    return Err(Status::failed_precondition(format!(
                        "partition {partition} is fenced for handoff; writes are rejected"
                    )));
                };
                let lifecycle_db = self.lifecycle_db()?;
                let verify_started = Instant::now();
                let mark = mark_status(lifecycle_db, op_id, req.team_id, req.person_id).await;
                record_release_phase("verify_mark", verify_started);
                let mark = mark.map_err(mark_lookup_failed)?;
                self.release_committed(partition, req.team_id, op_id, &release, mark.as_deref())
                    .await?;
            }
            ReleaseOutcome::Aborted => {
                self.release_aborted(partition, req.team_id, req.person_id, op_id)
                    .await?;
            }
            ReleaseOutcome::Unspecified => {
                return Err(Status::invalid_argument("outcome must be specified"));
            }
        }

        self.authoritative_ok(partition, ReleaseFenceResponse {})
    }

    pub(super) async fn release_fences_rpc(
        &self,
        request: Request<ReleaseFencesRequest>,
    ) -> Result<Response<ReleaseFencesResponse>, Status> {
        let partition = partition_from_metadata(&request)?;
        let req = request.into_inner();
        if req.persons.len() > MAX_LIFECYCLE_BATCH_SIZE {
            return Err(Status::invalid_argument(format!(
                "ReleaseFences carries {} persons; the cap is {MAX_LIFECYCLE_BATCH_SIZE}",
                req.persons.len()
            )));
        }
        let team_id = req.team_id;
        // Same strict routing check as a batched fence: every member hashes
        // to the routed partition or the whole batch is refused untouched.
        for person in &req.persons {
            self.validate_partition(partition, team_id, person.person_id)?;
        }
        // The aborted arm would otherwise ack under a lapsed lease; the
        // committed arm's produce and durable-fact acks need no cover.
        self.check_authority(partition)?;
        self.validate_ownership(partition)?;
        let op_id = Uuid::parse_str(&req.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
        histogram!("personhog_leader_release_batch_size").record(req.persons.len() as f64);

        match req.outcome() {
            ReleaseOutcome::Committed => {
                let releases = req
                    .persons
                    .into_iter()
                    .map(|person| {
                        CommittedRelease::validate(
                            person.person_id,
                            person.person_uuid,
                            person.sealed_version,
                            person.created_at,
                        )
                    })
                    .collect::<Result<Vec<_>, Status>>()?;
                if releases.is_empty() {
                    return self.authoritative_ok(partition, ReleaseFencesResponse {});
                }
                // Producing to the changelog must respect the handoff
                // write freeze like any write.
                let Some(_inflight_guard) = self.inflight.try_begin(partition) else {
                    return Err(Status::failed_precondition(format!(
                        "partition {partition} is fenced for handoff; writes are rejected"
                    )));
                };
                let lifecycle_db = self.lifecycle_db()?;
                let person_ids: Vec<i64> = releases.iter().map(|r| r.person_id).collect();
                let verify_started = Instant::now();
                let marks = mark_statuses(lifecycle_db, op_id, team_id, &person_ids).await;
                record_release_phase("verify_mark", verify_started);
                let marks = marks.map_err(mark_lookup_failed)?;
                // The releases run together so their death documents share
                // fencing windows, and every one runs to completion: a
                // sibling's failure cancels no produce in flight.
                let release_futures: Vec<_> = releases
                    .iter()
                    .map(|release| {
                        let mark = marks.get(&release.person_id).map(String::as_str);
                        self.release_committed(partition, team_id, op_id, release, mark)
                    })
                    .collect();
                let results: Vec<_> = futures::stream::iter(release_futures)
                    .buffer_unordered(LIFECYCLE_BATCH_CONCURRENCY)
                    .collect()
                    .await;
                first_batch_failure(results.into_iter().filter_map(Result::err).collect())?;
            }
            ReleaseOutcome::Aborted => {
                let mut failures = Vec::new();
                for person in &req.persons {
                    if let Err(status) = self
                        .release_aborted(partition, team_id, person.person_id, op_id)
                        .await
                    {
                        failures.push(status);
                    }
                }
                first_batch_failure(failures)?;
            }
            ReleaseOutcome::Unspecified => {
                return Err(Status::invalid_argument("outcome must be specified"));
            }
        }

        self.authoritative_ok(partition, ReleaseFencesResponse {})
    }
}
