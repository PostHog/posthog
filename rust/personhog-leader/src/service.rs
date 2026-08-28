use std::sync::Arc;
use std::time::Instant;

use common_kafka::kafka_producer::KafkaContext;
use dashmap::DashMap;
use metrics::{counter, histogram};
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeader;
use personhog_proto::personhog::types::v1::{
    FencePersonRequest, FencePersonResponse, FoldPersonDocumentRequest, FoldPersonDocumentResponse,
    GetPersonRequest, GetPersonResponse, LifecycleOpType, Person, ReleaseFenceRequest,
    ReleaseFenceResponse, ReleaseOutcome, SealedSourceSnapshot, UpdatePersonPropertiesRequest,
    UpdatePersonPropertiesResponse,
};
use rdkafka::producer::FutureProducer;
use tokio::sync::Mutex;
use tonic::{Request, Response, Status};
use uuid::Uuid;

use personhog_common::partitioning::partition_for_person;

use personhog_coordination::authority::AuthorityClock;

use crate::cache::{
    approx_person_bytes, CacheLookup, CachedPerson, DirtyIndex, DirtyMark, PartitionedCache,
    PersonCacheKey,
};
use crate::emitted::{EmittedVersionGuard, EmittedVersions};
use crate::fence::{
    fenced_status, mark_status, semantic_refusal, target_mark_status, FenceHealer, FenceMap,
    FenceState,
};
use crate::fencing::{FencedChangelogProducers, FencedProduceError};
use crate::inflight::InflightTracker;
use crate::kafka::produce_person_changelog;
use crate::person_update::{apply_property_updates, compute_event_property_updates};
use crate::pg::{load_person_from_pg, PgFallback};
use crate::recovery::ChangelogRecovery;
use crate::warnings::{SizeViolationWarning, WarningsProducer};
use personhog_common::properties::{
    can_trim_property, jsonb_column_size, sanitize_for_jsonb, trim_properties_to_fit_size,
    trim_properties_with_candidates, SanitizeStats, TrimResult,
};

/// Mirrors the config's `fence_map_max_entries` default; production
/// overrides via [`PersonHogLeaderService::with_fence_capacity`].
const DEFAULT_FENCE_MAP_MAX_ENTRIES: usize = 250_000;

/// Admission-time property size limits, in `pg_column_size` (JSONB
/// binary) terms — the same units as the `check_properties_size`
/// constraint they exist to enforce.
#[derive(Clone, Copy)]
pub struct PropertySizeLimits {
    /// Reject or trim above this (the constraint's ceiling).
    pub threshold: usize,
    /// Trim down to this, leaving headroom under the threshold.
    pub trim_target: usize,
}

impl PropertySizeLimits {
    /// Panics if `trim_target > threshold`: an inverted configuration would
    /// let admission pass documents above the threshold untrimmed, silently
    /// weakening the applyability guarantee. Refusing to construct makes the
    /// admission path's `TrimResult::Fits` arm unreachable.
    pub fn new(threshold: usize, trim_target: usize) -> Self {
        assert!(
            trim_target <= threshold,
            "properties_trim_target ({trim_target}) must not exceed \
             properties_size_threshold ({threshold})"
        );
        Self {
            threshold,
            trim_target,
        }
    }
}

pub struct PersonHogLeaderService {
    cache: Arc<PartitionedCache>,
    /// Per-key locks to serialize concurrent updates for the same person.
    /// Prevents lost updates from concurrent get -> compute -> produce -> put
    /// sequences, and thundering herd on PG fallback.
    locks: Arc<DashMap<PersonCacheKey, Arc<Mutex<()>>>>,
    producer: FutureProducer<KafkaContext>,
    changelog_topic: String,
    /// Read-only PG fallback (pool + the table it reads) for cache miss.
    fallback: Option<PgFallback>,
    /// Per-partition inflight counter used to drive the handoff drain phase.
    inflight: Arc<InflightTracker>,
    /// Total changelog partition count, read from etcd at startup (the same
    /// source the router uses). Used to validate the router's routing
    /// decision against each request's key.
    num_partitions: u32,
    /// Persons whose latest acked state the writer may not have applied to
    /// PG yet. Consulted on every cache miss: marked persons recover from
    /// the changelog, unmarked persons' PG rows are known current.
    dirty_index: Arc<DirtyIndex>,
    recovery: Arc<ChangelogRecovery>,
    size_limits: PropertySizeLimits,
    warnings: WarningsProducer,
    /// The in-process copy of the fence state (see the fence module for the
    /// durability model: the marks in Postgres are the source of truth,
    /// this map exists so the write path rejects without a database read).
    /// Mutated only under the per-key lock.
    fences: FenceMap,
    /// Ghost-fence recovery, derived from the fallback pool at
    /// construction. Absent without one (dev fixtures) — ghost fences
    /// then last until the partition changes hands, as before.
    fence_healer: Option<Arc<FenceHealer>>,
    /// Memory fuse for the fence map (see `fence_map_max_entries` in the
    /// config for the full policy): at this many live fences, FencePerson
    /// sheds new fences with RESOURCE_EXHAUSTED.
    fence_map_max_entries: usize,
    /// Present when broker-enforced epoch fencing is on; the write
    /// path produces through the partition's transaction window.
    fenced: Option<Arc<FencedChangelogProducers>>,
    /// This pod's claim to serve, consulted before answering a strong
    /// read. Present only when lease-gated reads are enabled.
    authority: Option<Arc<AuthorityClock>>,
    /// Versions emitted without a confirmed outcome, so a later write for
    /// the same person cannot reuse one.
    emitted_versions: Arc<EmittedVersions>,
}

impl PersonHogLeaderService {
    /// Refuse to answer as the partition's owner once this pod's lease
    /// may have expired.
    ///
    /// The cache is only authoritative while the lease behind it is, and
    /// the keepalive's own detection cannot be relied on to notice: a
    /// process that is stopped, starved, or wedged stops renewing and
    /// stops noticing together, then keeps serving state the new owner
    /// is already changing. Reading the published stamp here makes the
    /// lapse self-enforcing — nothing has to be alive to apply it.
    ///
    /// Refusal starts at the keepalive's renewal margin, strictly before
    /// the coordinator could treat the lease as expired, so requests are
    /// turned away while ownership is merely doubtful rather than after
    /// it is wrong. `FailedPrecondition` is the admission fence's own
    /// vocabulary: the router bounces and re-resolves toward whoever
    /// actually owns the partition.
    #[allow(clippy::result_large_err)]
    fn check_authority(&self, partition: u32) -> Result<(), Status> {
        let Some(authority) = &self.authority else {
            return Ok(());
        };
        if authority.is_valid() {
            return Ok(());
        }
        let reason = if authority.is_surrendered() {
            "surrendered"
        } else {
            "stale"
        };
        counter!(
            "personhog_leader_authority_lapsed_rejections_total",
            "reason" => reason
        )
        .increment(1);
        let since = authority.since_confirmed();
        // Debug, not warn: the gate refuses *every* request for the whole
        // duration of a lapse, so this fires at the pod's full read rate
        // during exactly the incident someone would be reading logs for.
        // The labelled counter above carries the rate and the cause.
        tracing::debug!(
            partition,
            ?since,
            margin = ?authority.margin(),
            "refusing to serve: no confirmed lease renewal within the margin"
        );
        Err(Status::failed_precondition(format!(
            "serving authority lapsed: no confirmed lease renewal in {since:?}"
        )))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn new(
        cache: Arc<PartitionedCache>,
        producer: FutureProducer<KafkaContext>,
        changelog_topic: String,
        fallback: Option<PgFallback>,
        locks: Arc<DashMap<PersonCacheKey, Arc<Mutex<()>>>>,
        inflight: Arc<InflightTracker>,
        num_partitions: u32,
        dirty_index: Arc<DirtyIndex>,
        recovery: Arc<ChangelogRecovery>,
        size_limits: PropertySizeLimits,
        warnings: WarningsProducer,
        fences: FenceMap,
        fenced: Option<Arc<FencedChangelogProducers>>,
        authority: Option<Arc<AuthorityClock>>,
        emitted_versions: Arc<EmittedVersions>,
    ) -> Self {
        Self {
            cache,
            locks,
            producer,
            changelog_topic,
            fence_healer: fallback
                .as_ref()
                .map(|f| Arc::new(FenceHealer::new(f.pool.clone(), Arc::clone(&fences)))),
            fallback,
            inflight,
            num_partitions,
            dirty_index,
            recovery,
            size_limits,
            warnings,
            fences,
            fenced,
            authority,
            emitted_versions,
            fence_map_max_entries: DEFAULT_FENCE_MAP_MAX_ENTRIES,
        }
    }

    /// Override the fence-map capacity (`fence_map_max_entries` in the
    /// config). Separate from `new` so the many test fixtures keep the
    /// default without threading one more argument through.
    pub fn with_fence_capacity(mut self, max_entries: usize) -> Self {
        self.fence_map_max_entries = max_entries;
        self
    }

    /// Verify the router's routing decision against the request body: the
    /// partition a request arrived on must equal the partition derived from
    /// the key it carries. A mismatch means a client stamped wrong
    /// routing-key headers or the hash implementations diverged; serving it
    /// would read or write through the wrong partition's cache, so fail
    /// closed.
    #[allow(clippy::result_large_err)]
    fn validate_partition(
        &self,
        partition: u32,
        team_id: i64,
        person_id: i64,
    ) -> Result<(), Status> {
        let expected = partition_for_person(team_id, person_id, self.num_partitions);
        if partition != expected {
            counter!("personhog_leader_partition_mismatch_total").increment(1);
            return Err(Status::invalid_argument(format!(
                "x-partition {partition} does not match partition {expected} \
                 derived from team_id={team_id} person_id={person_id}"
            )));
        }
        Ok(())
    }

    /// The fence RPCs must never succeed on a pod that does not serve the
    /// partition. A misrouted release that removed nothing and returned
    /// OK would leave the real owner's fence in place while the saga
    /// believes it released — a person frozen with no retry coming. The
    /// handoff guard is not enough on its own: `release_partition`
    /// unfences, so a pod that has already handed the partition off looks
    /// unfenced. Rejecting sends the saga's retry to the current owner.
    #[allow(clippy::result_large_err)]
    fn validate_ownership(&self, partition: u32) -> Result<(), Status> {
        if !self.cache.has_partition(partition) {
            return Err(Status::failed_precondition(format!(
                "partition {partition} is not served by this pod"
            )));
        }
        Ok(())
    }

    fn record_cache_hit() {
        counter!(
            "personhog_leader_person_loads_total",
            "source" => "cache", "outcome" => "ok"
        )
        .increment(1);
    }

    /// Recover a cache miss from the right source. A person in the dirty
    /// index has acked state the writer may not have applied to PG yet, so
    /// the PG row cannot be trusted — recover the full latest state from
    /// the changelog record at the marked offset instead. If that fetch
    /// fails, the only honest answer is a retryable error: falling back to
    /// PG would serve exactly the staleness this index exists to prevent.
    /// Unmarked persons' PG rows are known current — but only while this
    /// pod owns the partition, so the no-mark path re-checks ownership
    /// before trusting PG. Assumes the caller holds the per-key lock.
    async fn recover_or_load(
        &self,
        partition: u32,
        key: &PersonCacheKey,
    ) -> Result<Arc<CachedPerson>, Status> {
        let Some(mark) = self.dirty_index.get(key) else {
            // "No mark" means PG is current — but only while this pod owns
            // the partition. Handoffs drain writes, not reads, so a read
            // admitted before the freeze can still be executing here when
            // `release_partition` clears the partition's marks (the new
            // owner rebuilds its own), and to that reader a still-dirty
            // person now looks safe to load from PG. Re-checking the cache
            // AFTER the index read settles which world we're in: release
            // drops the cache partition first and clears marks second, so
            // if this miss was caused by release, the partition is already
            // gone from the cache and we fail closed; if the partition is
            // still present, the marks were intact when we read them and
            // the absence is genuine. There is no interleaving that gets
            // past both checks into a stale PG read.
            return match self.cache.get(partition, key) {
                CacheLookup::Found(person) => {
                    Self::record_cache_hit();
                    Ok(person)
                }
                CacheLookup::PersonNotFound => self.load_from_pg(partition, key).await,
                CacheLookup::PartitionNotOwned => Err(Status::failed_precondition(format!(
                    "partition {partition} not owned by this leader"
                ))),
            };
        };

        let started = Instant::now();
        let result = self.recovery.fetch_person_at(&mark, key).await;
        histogram!("personhog_leader_person_load_duration_ms", "source" => "changelog")
            .record(started.elapsed().as_secs_f64() * 1000.0);
        match result {
            Ok(person) => {
                counter!(
                    "personhog_leader_person_loads_total",
                    "source" => "changelog", "outcome" => "ok"
                )
                .increment(1);
                self.cache.put(partition, key.clone(), person.clone());
                Ok(Arc::new(person))
            }
            Err(e) => {
                counter!(
                    "personhog_leader_person_loads_total",
                    "source" => "changelog", "outcome" => "error"
                )
                .increment(1);
                tracing::error!(
                    team_id = key.team_id,
                    person_id = key.person_id,
                    offset = mark.offset,
                    error = %e,
                    "changelog recovery failed for dirty person"
                );
                Err(Status::unavailable(
                    "person state is pending durable write and changelog recovery failed; retry",
                ))
            }
        }
    }

    /// Load a person from PG and populate the cache. Assumes the caller
    /// holds the per-key lock.
    async fn load_from_pg(
        &self,
        partition: u32,
        key: &PersonCacheKey,
    ) -> Result<Arc<CachedPerson>, Status> {
        let Some(fallback) = &self.fallback else {
            // With no fallback pool a cache miss is answered as absence,
            // conflating "cannot see Postgres" with "destroyed" — ingestion
            // treats NotFound as an authoritative death signal and holds a
            // 25-hour destroyed mark on it. Only safe where the cache is
            // the whole world; production always configures the pool.
            return Err(Status::not_found(format!(
                "person not found: team_id={}, person_id={}",
                key.team_id, key.person_id
            )));
        };

        let started = Instant::now();
        let result = load_person_from_pg(&fallback.pool, &fallback.table, key).await;
        histogram!("personhog_leader_person_load_duration_ms", "source" => "pg")
            .record(started.elapsed().as_secs_f64() * 1000.0);
        match result {
            Ok(Some(person)) => {
                counter!(
                    "personhog_leader_person_loads_total",
                    "source" => "pg", "outcome" => "ok"
                )
                .increment(1);
                self.cache.put(partition, key.clone(), person.clone());
                Ok(Arc::new(person))
            }
            Ok(None) => {
                counter!(
                    "personhog_leader_person_loads_total",
                    "source" => "pg", "outcome" => "not_found"
                )
                .increment(1);
                Err(Status::not_found(format!(
                    "person not found: team_id={}, person_id={}",
                    key.team_id, key.person_id
                )))
            }
            Err(e) => {
                counter!(
                    "personhog_leader_person_loads_total",
                    "source" => "pg", "outcome" => "error"
                )
                .increment(1);
                counter!("personhog_leader_pg_fallback_errors_total").increment(1);
                tracing::error!(
                    team_id = key.team_id,
                    person_id = key.person_id,
                    error = %e,
                    "PG fallback query failed"
                );
                Err(Status::internal("failed to load person from database"))
            }
        }
    }

    /// Look up a person from cache, falling back to PG on miss.
    /// Acquires a per-key lock.
    async fn lookup_or_load(
        &self,
        partition: u32,
        key: &PersonCacheKey,
    ) -> Result<Arc<CachedPerson>, Status> {
        // Fast path: cache hit (no lock needed)
        match self.cache.get(partition, key) {
            CacheLookup::Found(person) => {
                Self::record_cache_hit();
                return Ok(person);
            }
            CacheLookup::PartitionNotOwned => {
                return Err(Status::failed_precondition(format!(
                    "partition {} not owned by this leader",
                    partition
                )));
            }
            CacheLookup::PersonNotFound => {}
        }

        // Cache miss -- acquire per-key lock to prevent thundering herd
        let mutex = self.locks.entry(key.clone()).or_default().value().clone();
        let _guard = mutex.lock().await;

        // Double-check cache -- another request may have loaded it
        if let CacheLookup::Found(person) = self.cache.get(partition, key) {
            Self::record_cache_hit();
            return Ok(person);
        }

        self.recover_or_load(partition, key).await
    }

    /// Look up a person from cache, falling back to PG on miss.
    /// The caller must already hold the per-key lock.
    async fn lookup_or_load_locked(
        &self,
        partition: u32,
        key: &PersonCacheKey,
    ) -> Result<Arc<CachedPerson>, Status> {
        match self.cache.get(partition, key) {
            CacheLookup::Found(person) => {
                Self::record_cache_hit();
                Ok(person)
            }
            CacheLookup::PartitionNotOwned => Err(Status::failed_precondition(format!(
                "partition {} not owned by this leader",
                partition
            ))),
            CacheLookup::PersonNotFound => self.recover_or_load(partition, key).await,
        }
    }

    /// The shared tail of every document write: refuse unapplyable records,
    /// produce to Kafka first, then dirty-mark and update the cache — so
    /// readers only ever see durably committed state. The mark precedes the
    /// cache insert: a reader that misses the cache in the gap sees the
    /// mark and recovers this exact record from the changelog. Assumes the
    /// caller holds the per-key lock.
    async fn commit_document(
        &self,
        partition: u32,
        cache_key: &PersonCacheKey,
        person: CachedPerson,
    ) -> Result<Person, Status> {
        // A record the writer cannot bind must never reach the changelog —
        // no consumer downstream can apply or repair it.
        if let Err(reason) = assert_writeable(&person) {
            counter!("personhog_leader_unwriteable_state_total").increment(1);
            tracing::error!(
                team_id = cache_key.team_id,
                person_id = cache_key.person_id,
                reason,
                "refusing to produce an unapplyable changelog record"
            );
            return Err(Status::internal(format!(
                "person state is not writeable: {reason}"
            )));
        }

        let proto = cached_person_to_proto(&person);

        // Re-check before producing, for the same reason the read path
        // re-checks before answering: admission proves nothing about the
        // moment the record lands. Between the check at entry and here a
        // write can wait on the per-key lock behind another produce, and
        // on a changelog recovery — long enough for a starved keepalive's
        // stamp to age out, for the lease to expire at etcd, and for the
        // coordinator to warm a successor past the point this record
        // would land.
        self.check_authority(partition)?;

        // From here the record may reach the changelog whatever happens
        // to this request — including the request simply ceasing to exist
        // when the client's deadline expires. The guard is what makes the
        // version un-reusable in that case.
        let mut emitted = EmittedVersionGuard::new(
            Arc::clone(&self.emitted_versions),
            partition,
            cache_key.clone(),
            person.version,
        );
        emitted.emitting();

        // Produce to Kafka first, then update the cache on success.
        // Readers only ever see durably committed state.
        let offset = if let Some(fenced) = &self.fenced {
            match fenced.produce(partition, &proto).await {
                Ok(offset) => offset,
                // The broker fenced this pod: a newer owner holds the
                // partition, so this claim is stale. FailedPrecondition
                // is the admission fence's own vocabulary — the router
                // classifies it as a bounce and re-resolves toward the
                // real owner.
                Err(e @ FencedProduceError::Fenced) => {
                    // Rejected at the broker, so the record does not
                    // exist and its version is free.
                    emitted.discarded();
                    tracing::error!(
                        team_id = cache_key.team_id,
                        person_id = cache_key.person_id,
                        partition,
                        "changelog producer fenced; rejecting write as stale owner"
                    );
                    // Deliberately no local reaction beyond failing the
                    // write. A broker fence proves *someone* newer
                    // initialized the transactional id, not that this pod
                    // lost the partition: a zombie waking inside its
                    // lease window re-acquires on the way to noticing it
                    // is dead, which fences the legitimate owner. So the
                    // fence is given up here as unusable and nothing
                    // more; `heal_fence`, on the next convergence to
                    // Serving, re-takes the epoch once the authority
                    // stamp confirms this pod's standing. Reads stay
                    // served meanwhile under the same stamp — the
                    // `check_authority` calls at admission and before
                    // answering are what refuse them once the claim
                    // lapses.
                    return Err(Status::failed_precondition(format!(
                        "partition ownership fenced: {e}"
                    )));
                }
                // This pod holds no producer for the partition — an
                // ownership statement, in the same vocabulary the
                // admission fence uses, so the router bounces and
                // re-resolves instead of surfacing a hard error.
                // The partition moved *and* this window's outcome was
                // never settled. The router still needs the ownership
                // answer, but the version cannot be handed back: the
                // commit may have succeeded on an attempt librdkafka
                // re-issued internally.
                Err(e @ FencedProduceError::FencedUncertain(_)) => {
                    // Deliberately not settled: the partition moved and
                    // the window's own outcome never came back, so the
                    // record may or may not be in the log. Keeping the
                    // version spent is the whole of what safety needs.
                    counter!(
                        "personhog_leader_indeterminate_outcomes_total",
                        "fenced" => "true"
                    )
                    .increment(1);
                    tracing::error!(
                        team_id = cache_key.team_id,
                        person_id = cache_key.person_id,
                        partition,
                        error = %e,
                        "changelog producer fenced with an unknown outcome; version kept spent"
                    );
                    return Err(Status::failed_precondition(format!(
                        "partition ownership fenced: {e}"
                    )));
                }
                Err(e @ FencedProduceError::NotAcquired) => {
                    emitted.discarded();
                    tracing::warn!(
                        team_id = cache_key.team_id,
                        person_id = cache_key.person_id,
                        partition,
                        "no changelog fence held for partition; rejecting write"
                    );
                    return Err(Status::failed_precondition(format!(
                        "partition fence not held: {e}"
                    )));
                }
                // The commit's outcome is unknown, so this pod cannot
                // say whether the record became visible. A caller
                // retrying against a cache still holding the pre-write
                // version would produce a second record at the same
                // version as the one that may already have committed,
                // and the writer's strict guard keeps whichever arrived
                // first — which the floor prevents by holding the
                // version spent.
                Err(e @ FencedProduceError::Indeterminate(_)) => {
                    // Deliberately not settled: whether the record exists
                    // is exactly what is unknown, so the version stays
                    // spent and the retry derives past it.
                    counter!(
                        "personhog_leader_indeterminate_outcomes_total",
                        "fenced" => "false"
                    )
                    .increment(1);
                    tracing::error!(
                        team_id = cache_key.team_id,
                        person_id = cache_key.person_id,
                        partition,
                        error = %e,
                        "changelog commit outcome unknown; version kept spent"
                    );
                    return Err(Status::unknown(format!(
                        "person state may or may not have been stored: {e}"
                    )));
                }
                // The window aborted, so no record became visible: the
                // write is safe to retry, and ABORTED is the code the
                // clients actually retry on.
                Err(e) => {
                    // The window aborted, so no record became visible and
                    // the version can be derived again.
                    emitted.discarded();
                    tracing::error!(
                        team_id = cache_key.team_id,
                        person_id = cache_key.person_id,
                        error = %e,
                        "failed to produce person state changelog (fenced path)"
                    );
                    return Err(Status::aborted(format!(
                        "failed to durably store person state: {e}"
                    )));
                }
            }
        } else {
            match produce_person_changelog(&self.producer, &self.changelog_topic, partition, &proto)
                .await
            {
                Ok(offset) => offset,
                Err(e) => {
                    // Deliberately not settled. This path collapses an
                    // enqueue that never left the client with a delivery
                    // that timed out after the broker may already have
                    // appended it, and idempotence is off by default, so
                    // the record's fate is genuinely unknown. Freeing the
                    // version here let a retry derive the same number and
                    // put a second record behind one that may be in the
                    // log — the writer's strict guard then keeps whichever
                    // arrived first and discards the acked one.
                    //
                    // The floor alone carries that: the next write
                    // derives past it whether or not the cache still
                    // holds the pre-write state. The entry stays, so
                    // reads may answer with a version older than the
                    // changelog until a later write for this person
                    // settles one. Evicting instead would resolve
                    // nothing — recovery reads the last *marked* offset,
                    // which is the previous write that did succeed — and
                    // would answer NOT_FOUND outright once that mark is
                    // pruned and no fallback pool is configured.
                    tracing::error!(
                        team_id = cache_key.team_id,
                        person_id = cache_key.person_id,
                        error = %e,
                        "failed to produce person state changelog"
                    );
                    return Err(Status::internal(format!(
                        "failed to durably store person state: {e}"
                    )));
                }
            }
        };

        // Mark before the cache insert: a reader that misses the cache in
        // the gap sees the mark and recovers this exact record from the
        // changelog. The mark outlives eviction and is pruned once the
        // writer's committed offset passes it.
        self.dirty_index.mark(
            cache_key.clone(),
            DirtyMark {
                version: person.version,
                offset,
                partition,
            },
        );
        self.cache.put(partition, cache_key.clone(), person);
        // The cache carries the version now, so the floor has nothing
        // left to say.
        emitted.resolved();
        Ok(proto)
    }

    /// The write path's fence conditional: an in-memory lookup and nothing
    /// else. The map is authoritative here — a fence that outlives its op
    /// is not the leader's to detect, because the op being unfinished is
    /// exactly what a live mark means (see the fence module's ownership
    /// model). Returns the fence to reject with, or None when the person
    /// is writable. Assumes the caller holds the per-key lock.
    fn check_fence(&self, cache_key: &PersonCacheKey) -> Option<FenceState> {
        self.fences.get(cache_key).map(|entry| *entry.value())
    }
}

/// Upper bound on the epoch-millisecond timestamps the leader will put in
/// a changelog record: the last instant of year 9999. Comfortably inside
/// both chrono's representable range and Postgres's `timestamptz` range,
/// so any value under this bound is bindable by the writer.
const MAX_EPOCH_MS_YEAR_9999: i64 = 253_402_300_799_999;

/// The granularity `last_seen_at` is stored at. Matches ingestion's own
/// hourly truncation so both write paths produce identical stored values.
const MS_PER_HOUR: i64 = 3_600_000;

/// The changelog contract: every produced record must be applyable by the
/// writer's upsert verbatim. Properties are guaranteed by admission
/// (NUL sanitization plus the exact size measure); this checks the
/// remaining writer-bound fields against the writer's bind conversions —
/// uuid must parse, team_id must fit the column's `integer`, and the
/// timestamps must sit inside a sanity range ([1970, 9999]) any
/// legitimate value satisfies. The legacy jsonb columns have no cache
/// field and are unconditionally empty in `cached_person_to_proto`, so a
/// record structurally cannot carry values the writer would refuse there.
fn assert_writeable(p: &CachedPerson) -> Result<(), String> {
    if Uuid::parse_str(&p.uuid).is_err() {
        return Err("uuid does not parse as a UUID".to_string());
    }
    if p.team_id <= 0 || p.team_id > i32::MAX as i64 {
        return Err(format!(
            "team_id {} is outside the column's integer range",
            p.team_id
        ));
    }
    if p.created_at < 0 || p.created_at > MAX_EPOCH_MS_YEAR_9999 {
        return Err(format!(
            "created_at epoch {} is outside sane bounds",
            p.created_at
        ));
    }
    if let Some(t) = p.last_seen_at {
        if !(0..=MAX_EPOCH_MS_YEAR_9999).contains(&t) {
            return Err(format!("last_seen_at epoch {t} is outside sane bounds"));
        }
    }
    Ok(())
}

fn cached_person_to_proto(p: &CachedPerson) -> Person {
    let properties_bytes = p.properties.clone();
    Person {
        id: p.id,
        uuid: p.uuid.clone(),
        team_id: p.team_id,
        properties: properties_bytes,
        properties_last_updated_at: Vec::new(),
        properties_last_operation: Vec::new(),
        created_at: p.created_at,
        version: p.version,
        is_identified: p.is_identified,
        is_user_id: None,
        last_seen_at: p.last_seen_at,
        is_deleted: p.is_deleted,
    }
}

/// Parse a JSON-map wire field (empty bytes mean an empty map), refusing
/// anything that is not a JSON object.
// See `partition_from_metadata` for why `result_large_err` is allowed.
#[allow(clippy::result_large_err)]
fn parse_json_object_field(bytes: &[u8], field: &str) -> Result<serde_json::Value, Status> {
    if bytes.is_empty() {
        return Ok(serde_json::Value::Object(serde_json::Map::new()));
    }
    let value: serde_json::Value = serde_json::from_slice(bytes)
        .map_err(|e| Status::invalid_argument(format!("invalid {field} JSON: {e}")))?;
    if !value.is_object() {
        return Err(Status::invalid_argument(format!(
            "{field} must be a JSON object"
        )));
    }
    Ok(value)
}

/// A sealed source snapshot after admission: identity-checked against the
/// fold's target, JSON-parsed, and sanitized.
#[derive(Debug)]
struct SealedSnapshot {
    ordinal: i32,
    properties: serde_json::Value,
    version: i64,
    created_at: i64,
    last_seen_at: Option<i64>,
}

/// Admit the fold request's sealed snapshots: validate, parse, and
/// sanitize each, returning them in ordinal order plus what sanitization
/// rewrote. Every refusal is a deterministic `InvalidArgument`: each
/// snapshot must be a plausible living source of the target — same team,
/// a different person, not a death document — and ordinals must be
/// unique, or precedence would be ambiguous. A mismatch can only be a
/// saga bug, and folding it silently would launder it into the target.
// See `partition_from_metadata` for why `result_large_err` is allowed.
#[allow(clippy::result_large_err)]
fn parse_sealed_snapshots(
    sealed_snapshots: &[SealedSourceSnapshot],
    team_id: i64,
    person_id: i64,
) -> Result<(Vec<SealedSnapshot>, SanitizeStats), Status> {
    let mut stats = SanitizeStats::default();
    let mut seen_ordinals = std::collections::HashSet::with_capacity(sealed_snapshots.len());
    let mut snapshots: Vec<SealedSnapshot> = Vec::with_capacity(sealed_snapshots.len());
    for snapshot in sealed_snapshots {
        let Some(person) = &snapshot.person else {
            return Err(Status::invalid_argument(
                "sealed snapshot is missing its person",
            ));
        };
        if person.team_id != team_id {
            return Err(Status::invalid_argument(
                "sealed snapshot belongs to a different team than the target",
            ));
        }
        if person.id == person_id {
            return Err(Status::invalid_argument(
                "sealed snapshot is the merge target itself",
            ));
        }
        if person.is_deleted {
            return Err(Status::invalid_argument(
                "sealed snapshot is a death document; only living sealed state folds",
            ));
        }
        if !seen_ordinals.insert(snapshot.ordinal) {
            return Err(Status::invalid_argument(
                "sealed snapshots carry a duplicate ordinal; precedence would be ambiguous",
            ));
        }
        let mut properties =
            parse_json_object_field(&person.properties, "sealed snapshot properties")?;
        let snapshot_stats = sanitize_for_jsonb(&mut properties);
        stats.nul_strings += snapshot_stats.nul_strings;
        stats.clamped_numbers += snapshot_stats.clamped_numbers;
        snapshots.push(SealedSnapshot {
            ordinal: snapshot.ordinal,
            properties,
            version: person.version,
            created_at: person.created_at,
            last_seen_at: person.last_seen_at,
        });
    }
    // Precedence comes from the recorded pair order, not from the
    // request: a re-drive that lists sources differently must fold the
    // same document.
    snapshots.sort_by_key(|snapshot| snapshot.ordinal);
    Ok((snapshots, stats))
}

/// Extract the routing partition from the `x-partition` request-metadata
/// header. The router stamps this on every leader call after hashing
/// `(team_id, person_id)`; its absence means a misrouted or malformed
/// request, so we fail closed with `InvalidArgument` rather than guessing.
// `Status` is the idiomatic tonic error throughout this service; the small
// `Ok(u32)` against a large `Status` trips `result_large_err`, but boxing
// here would diverge from every other handler's signature.
#[allow(clippy::result_large_err)]
fn partition_from_metadata<T>(request: &Request<T>) -> Result<u32, Status> {
    request
        .metadata()
        .get("x-partition")
        .ok_or_else(|| Status::invalid_argument("missing x-partition metadata"))?
        .to_str()
        .map_err(|_| Status::invalid_argument("x-partition metadata is not valid ASCII"))?
        .parse::<u32>()
        .map_err(|_| Status::invalid_argument("x-partition metadata is not a valid u32"))
}

#[tonic::async_trait]
impl PersonHogLeader for PersonHogLeaderService {
    async fn get_person(
        &self,
        request: Request<GetPersonRequest>,
    ) -> Result<Response<GetPersonResponse>, Status> {
        let partition = partition_from_metadata(&request)?;
        let req = request.into_inner();
        self.validate_partition(partition, req.team_id, req.person_id)?;
        self.check_authority(partition)?;
        let cache_key = PersonCacheKey {
            team_id: req.team_id,
            person_id: req.person_id,
        };

        let person = self.lookup_or_load(partition, &cache_key).await?;
        // Re-check before answering. The load can wait — on the per-key
        // lock behind another request's produce, or on a changelog
        // recovery — for long enough that a claim valid at admission has
        // lapsed by the time there is something to return, and it is the
        // answer, not the arrival, that has to be backed by ownership.
        self.check_authority(partition)?;

        // A recovered death document is an authoritative not-found: the
        // person was destroyed and this entry closes its stream.
        if person.is_deleted {
            return Err(Status::not_found("person is destroyed"));
        }

        Ok(Response::new(GetPersonResponse {
            person: Some(cached_person_to_proto(&person)),
        }))
    }

    async fn update_person_properties(
        &self,
        request: Request<UpdatePersonPropertiesRequest>,
    ) -> Result<Response<UpdatePersonPropertiesResponse>, Status> {
        let partition = partition_from_metadata(&request)?;
        let req = request.into_inner();
        self.validate_partition(partition, req.team_id, req.person_id)?;
        // A write is serving too. Broker-enforced fencing covers this
        // path when it is on, but it cannot be turned on first — startup
        // refuses fencing without the gate — so every fleet passes
        // through a window where the gate is the only thing standing
        // between a pod that stopped renewing and a write the successor
        // will never see. The lease-loss path surrenders before it
        // drains, deliberately, and until this check existed only reads
        // honoured that: writes stayed admitted until the local fence
        // landed, behind a watch teardown and a task join.
        self.check_authority(partition)?;

        // Admit the write as inflight, unless the partition is fenced. A
        // fenced partition has drained for handoff: every router acked the
        // freeze, so this write can only come from a router with a stale
        // view — accepting it would produce past the Kafka HWM that the new
        // owner's warming snapshots, silently losing the write. Admission
        // and the fence check are one atomic operation (`try_begin`): the
        // inflight increment precedes the check, so the drain either waits
        // for this write or this write sees the fence. Reads are unaffected
        // — the frozen state stays the latest until cutover. The handoff
        // protocol waits for the per-partition inflight count to drop to
        // zero before advancing; combined with sync-acked produces, a zero
        // count implies every acked write is durable in Kafka. Using a
        // non-`_` prefixed binding so the RAII guard is held for the full
        // handler lifetime (see the `let_underscore_drop` lint).
        let Some(_inflight_guard) = self.inflight.try_begin(partition) else {
            return Err(Status::failed_precondition(format!(
                "partition {partition} is fenced for handoff; writes are rejected"
            )));
        };

        let cache_key = PersonCacheKey {
            team_id: req.team_id,
            person_id: req.person_id,
        };

        // Parse JSON before acquiring the per-key lock to minimize lock hold time
        let set_properties: serde_json::Value = if req.set_properties.is_empty() {
            serde_json::Value::Object(serde_json::Map::new())
        } else {
            serde_json::from_slice(&req.set_properties).map_err(|e| {
                Status::invalid_argument(format!("invalid set_properties JSON: {e}"))
            })?
        };

        let set_once_properties: serde_json::Value = if req.set_once_properties.is_empty() {
            serde_json::Value::Object(serde_json::Map::new())
        } else {
            serde_json::from_slice(&req.set_once_properties).map_err(|e| {
                Status::invalid_argument(format!("invalid set_once_properties JSON: {e}"))
            })?
        };

        // Sanitize the request values before diffing so no-op detection
        // compares in sanitized space: cached state holds the sanitized
        // form, and an unsanitized repeat of the same value must hit the
        // no-change fast path instead of producing a fresh record every
        // time. The post-merge sanitize below stays as the admission
        // guarantee (it also covers legacy dirt already in the cache).
        let mut set_properties = set_properties;
        let mut set_once_properties = set_once_properties;
        let input_stats = {
            let mut stats = sanitize_for_jsonb(&mut set_properties);
            let once = sanitize_for_jsonb(&mut set_once_properties);
            stats.nul_strings += once.nul_strings;
            stats.clamped_numbers += once.clamped_numbers;
            stats
        };
        if input_stats.nul_strings > 0 {
            counter!("personhog_leader_properties_nul_sanitized_total")
                .increment(input_stats.nul_strings);
        }
        if input_stats.clamped_numbers > 0 {
            counter!("personhog_leader_properties_numbers_clamped_total")
                .increment(input_stats.clamped_numbers);
        }
        // Unset targets must match keys as stored, i.e. sanitized.
        let unset_properties: Vec<String> = req
            .unset_properties
            .iter()
            .map(|k| k.replace('\u{0000}', "\u{FFFD}"))
            .collect();

        // Per-key lock serializes concurrent updates for the same person.
        // The wait is measured because it is the queueing component of
        // handler latency: with every acked write holding the lock
        // through its acks=all produce, per-person throughput is capped
        // near 1/produce-latency, and contending updates spend their
        // time here — invisible in the produce histogram.
        let mutex = self
            .locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let lock_wait = std::time::Instant::now();
        let _guard = mutex.lock().await;
        histogram!("personhog_leader_person_lock_wait_ms")
            .record(lock_wait.elapsed().as_secs_f64() * 1000.0);

        // Admission check before any work: if the dirty index is at
        // capacity and this person is not already marked, acking the write
        // would leave it durable but unmarked — reopening the
        // stale-fallback hole on eviction. Shed instead; the index drains
        // (and admission resumes) as the writer catches up.
        if !self.dirty_index.can_admit(&cache_key) {
            counter!("personhog_leader_writes_shed_total", "reason" => "dirty_index_full")
                .increment(1);
            return Err(Status::resource_exhausted(
                "dirty index at capacity: the writer is behind and this person's write cannot \
                 be tracked; retry later",
            ));
        }

        // A person fenced by a live lifecycle op rejects writes until the
        // fence is released; reads are unaffected. Checked under the
        // per-key lock so a concurrent FencePerson cannot be missed.
        if let Some(fence) = self.check_fence(&cache_key) {
            counter!("personhog_leader_writes_fenced_total").increment(1);
            // Off the request path: if this fence is a ghost (its op
            // already settled), the healer drops it and a retry goes
            // through.
            if let Some(healer) = &self.fence_healer {
                healer.maybe_heal(cache_key.clone(), fence);
            }
            return Err(fenced_status(&fence));
        }

        let person = self.lookup_or_load_locked(partition, &cache_key).await?;

        // A destroyed person answers not-found — the caller re-resolves;
        // post-death the distinct id may have been reborn as a new person.
        if person.is_deleted {
            return Err(Status::not_found("person is destroyed"));
        }

        // One parse per update: the cache stores properties serialized,
        // and this handler reads them as a map throughout.
        let person_properties = person
            .parse_properties()
            .map_err(|e| Status::internal(format!("cached properties unparseable: {e}")))?;

        // Compute property updates
        let updates = compute_event_property_updates(
            &req.event_name,
            &set_properties,
            &set_once_properties,
            &unset_properties,
            &person_properties,
        );

        // OR-merge: identification never reverts through this RPC, so
        // only a true that finds false is a change. It counts as one on
        // its own — an $identify with no property diffs must still
        // produce a record.
        let identified_now = person.is_identified || req.is_identified == Some(true);
        let identity_changed = identified_now != person.is_identified;

        // last_seen_at is request-borne and best-effort: an out-of-range
        // value is discarded rather than failing the update, so the
        // acked ⇒ writeable invariant never hinges on it. In-range values
        // are floored to the hour — Node's startOf('hour') on its
        // UTC-normalized timestamps, expressed in epoch terms — so record
        // volume is bounded at one per person-hour by construction, not
        // by trusting callers to coarsen.
        let requested_last_seen = req
            .last_seen_at
            .filter(|t| (0..=MAX_EPOCH_MS_YEAR_9999).contains(t));
        if requested_last_seen != req.last_seen_at {
            counter!("personhog_leader_last_seen_discarded_total").increment(1);
        }
        let requested_last_seen = requested_last_seen.map(|t| t - t % MS_PER_HOUR);
        // Max-merge: the stored value only ever advances, and an advance
        // is a change in its own right — ingestion's direct write path
        // persists a last-seen-only advance, so this path must too.
        let merged_last_seen = person.last_seen_at.max(requested_last_seen);
        let last_seen_changed = merged_last_seen != person.last_seen_at;

        // Fast path: no diffs detected, skip the clone in apply_property_updates
        if !updates.has_changes && !identity_changed && !last_seen_changed {
            counter!("personhog_leader_updates_total", "outcome" => "no_change").increment(1);
            return Ok(Response::new(UpdatePersonPropertiesResponse {
                person: Some(cached_person_to_proto(&person)),
                updated: false,
            }));
        }

        // Slow path: apply diffs and check if the values actually changed
        // (has_changes can be true when $set sends the same value that already exists)
        let (new_properties, actually_updated) =
            apply_property_updates(&updates, &person_properties);

        if !actually_updated && !identity_changed && !last_seen_changed {
            counter!("personhog_leader_updates_total", "outcome" => "no_change").increment(1);
            return Ok(Response::new(UpdatePersonPropertiesResponse {
                person: Some(cached_person_to_proto(&person)),
                updated: false,
            }));
        }

        // Admission-time size enforcement, hoisted from the writer: every
        // acked record must be applyable by the writer verbatim, or the
        // cache and changelog would carry state Postgres never gets (the
        // stale-serve hole the dirty index exists to close). The measure
        // is the constraint's own — pg_column_size of the JSONB encoding
        // — so admitted rows cannot violate it at apply time.
        let mut new_properties = new_properties;

        // Rewrite the merged state into jsonb-safe form before measuring:
        // NUL sanitization (Node-pipeline parity — Postgres refuses it)
        // and extreme-float clamping (Postgres's expanded numeric
        // rendering would otherwise be unparseable on the way back). The
        // measured size is then the stored size.
        let sanitize_stats = sanitize_for_jsonb(&mut new_properties);
        if sanitize_stats.nul_strings > 0 {
            counter!("personhog_leader_properties_nul_sanitized_total")
                .increment(sanitize_stats.nul_strings);
        }
        if sanitize_stats.clamped_numbers > 0 {
            counter!("personhog_leader_properties_numbers_clamped_total")
                .increment(sanitize_stats.clamped_numbers);
        }

        let jsonb_size = jsonb_column_size(&new_properties);
        if jsonb_size > self.size_limits.threshold {
            // Policy mirror of the Node pipeline's
            // `handleOversizedPersonProperties`: trimming is remediation
            // for rows already oversized in storage (they predate the
            // constraint, or another writer produced them) — the stored
            // properties are trimmed to the target and the triggering
            // update's property changes are discarded, exactly as Node
            // retries with trimmed existing state. An update that would
            // newly push a within-limit row over the ceiling is rejected
            // outright: a rejection with a warning is a deliberate,
            // visible outcome where a silent trim would be arbitrary
            // deferred data loss. Warnings and errors carry sizes, never
            // property values.
            let existing_size = jsonb_column_size(&person_properties);
            if existing_size >= self.size_limits.threshold {
                match trim_properties_to_fit_size(&person_properties, self.size_limits.trim_target)
                {
                    TrimResult::Trimmed(trimmed) => {
                        counter!("personhog_leader_properties_trimmed_total").increment(1);
                        self.warnings.emit(&SizeViolationWarning {
                            team_id: cache_key.team_id,
                            person_uuid: person.uuid.clone(),
                            message: "Oversized person properties were trimmed to fit the size \
                                      limit; the update that surfaced them was discarded"
                                .to_string(),
                        });
                        new_properties = trimmed;
                    }
                    // Reachable only when trim_target == threshold and the
                    // stored size sits exactly on it: nothing to trim, but
                    // the update still cannot apply — keep the stored
                    // state, discarding the update like the arm above.
                    TrimResult::Fits => {
                        new_properties = person_properties.clone();
                    }
                    TrimResult::CannotFit => {
                        counter!(
                            "personhog_leader_updates_total",
                            "outcome" => "rejected_unremediable"
                        )
                        .increment(1);
                        self.warnings.emit(&SizeViolationWarning {
                            team_id: cache_key.team_id,
                            person_uuid: person.uuid.clone(),
                            message: "Person properties exceed the size limit and could not be \
                                      trimmed; the update was rejected"
                                .to_string(),
                        });
                        return Err(Status::invalid_argument(format!(
                            "person properties exceed the size limit: stored state is \
                             {existing_size} bytes (jsonb) and protected properties alone exceed \
                             the {} trim target",
                            self.size_limits.trim_target,
                        )));
                    }
                }
            } else {
                counter!("personhog_leader_updates_total", "outcome" => "rejected_oversized")
                    .increment(1);
                self.warnings.emit(&SizeViolationWarning {
                    team_id: cache_key.team_id,
                    person_uuid: person.uuid.clone(),
                    message: "Person properties update would exceed the size limit and was \
                              rejected"
                        .to_string(),
                });
                return Err(Status::invalid_argument(format!(
                    "person properties update would exceed the size limit: {jsonb_size} bytes \
                     (jsonb) over the {} ceiling",
                    self.size_limits.threshold,
                )));
            }
        }

        let properties_bytes = serde_json::to_vec(&new_properties)
            .map_err(|e| Status::internal(format!("serialize updated properties: {e}")))?;
        let approx_bytes = approx_person_bytes(properties_bytes.len());
        // A version this pod already put on the wire is spent even when
        // it never learned the outcome, so the next one has to clear that
        // floor as well as the state it derived from. Reusing it produces
        // a second record at the same version, and the writer's strict
        // guard keeps only whichever arrived first.
        let base_version = self
            .emitted_versions
            .floor_for(partition, &cache_key, person.version);
        let updated_person = CachedPerson {
            id: person.id,
            uuid: person.uuid.clone(),
            team_id: person.team_id,
            properties: properties_bytes,
            created_at: person.created_at,
            version: base_version + 1,
            is_identified: identified_now,
            is_deleted: false,
            last_seen_at: merged_last_seen,
            approx_bytes,
        };

        let proto = self
            .commit_document(partition, &cache_key, updated_person)
            .await?;
        counter!("personhog_leader_updates_total", "outcome" => "updated").increment(1);

        Ok(Response::new(UpdatePersonPropertiesResponse {
            person: Some(proto),
            updated: true,
        }))
    }

    async fn fold_person_document(
        &self,
        request: Request<FoldPersonDocumentRequest>,
    ) -> Result<Response<FoldPersonDocumentResponse>, Status> {
        let partition = partition_from_metadata(&request)?;
        let req = request.into_inner();
        self.validate_partition(partition, req.team_id, req.person_id)?;
        self.check_authority(partition)?;
        let op_id = Uuid::parse_str(&req.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
        if req.sealed_snapshots.is_empty() {
            return Err(Status::invalid_argument(
                "sealed_snapshots must be non-empty: a merge with no sealed sources has nothing \
                 to fold",
            ));
        }

        let Some(_inflight_guard) = self.inflight.try_begin(partition) else {
            return Err(Status::failed_precondition(format!(
                "partition {partition} is fenced for handoff; writes are rejected"
            )));
        };

        // Parse and sanitize every JSON input before taking the per-key
        // lock. Snapshot properties were sanitized when the source's
        // leader cached them, but they crossed the wire since; sanitizing
        // again keeps the fold's admission guarantee self-contained.
        let mut sanitize_totals = SanitizeStats::default();
        let mut track = |stats: SanitizeStats| {
            sanitize_totals.nul_strings += stats.nul_strings;
            sanitize_totals.clamped_numbers += stats.clamped_numbers;
        };
        let mut event_set = parse_json_object_field(&req.event_set, "event_set")?;
        let mut event_set_once = parse_json_object_field(&req.event_set_once, "event_set_once")?;
        track(sanitize_for_jsonb(&mut event_set));
        track(sanitize_for_jsonb(&mut event_set_once));
        let (snapshots, snapshot_stats) =
            parse_sealed_snapshots(&req.sealed_snapshots, req.team_id, req.person_id)?;
        track(snapshot_stats);

        let cache_key = PersonCacheKey {
            team_id: req.team_id,
            person_id: req.person_id,
        };
        let mutex = self
            .locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let lock_wait = std::time::Instant::now();
        let _guard = mutex.lock().await;
        histogram!("personhog_leader_person_lock_wait_ms")
            .record(lock_wait.elapsed().as_secs_f64() * 1000.0);

        if !self.dirty_index.can_admit(&cache_key) {
            counter!("personhog_leader_writes_shed_total", "reason" => "dirty_index_full")
                .increment(1);
            return Err(Status::resource_exhausted(
                "dirty index at capacity: the writer is behind and this fold cannot be tracked; \
                 retry later",
            ));
        }

        // The merge target is marked, never fenced, so a fence here is
        // either a ghost from a settled op (the healer clears it and the
        // saga's retry goes through) or a bug. Same-op tolerance mirrors
        // FencePerson's re-seal semantics.
        if let Some(fence) = self.check_fence(&cache_key) {
            if fence.op_id != op_id {
                counter!("personhog_leader_writes_fenced_total").increment(1);
                if let Some(healer) = &self.fence_healer {
                    healer.maybe_heal(cache_key.clone(), fence);
                }
                return Err(fenced_status(&fence));
            }
        }

        let person = self.lookup_or_load_locked(partition, &cache_key).await?;
        if person.is_deleted {
            return Err(Status::not_found("person is destroyed"));
        }

        // The mark row — the fence's source of truth — must vouch for the
        // op holding this person as its live merge target before the fold
        // may write. The fence check above proves nothing here (the target
        // is marked, never fenced), and without this a superseded or
        // settled saga runner's late fold would still land. Mirrors
        // ReleaseFence: unverifiable requests are refused — fail closed.
        let Some(fallback) = &self.fallback else {
            return Err(semantic_refusal(
                "no lifecycle database configured; refusing to fold",
                "no-lifecycle-db",
            ));
        };
        match target_mark_status(&fallback.pool, op_id, req.team_id, req.person_id).await {
            Ok(Some(status)) if status == "marked" => {}
            Ok(_) => {
                counter!("personhog_leader_fences_total", "action" => "fold_unverified")
                    .increment(1);
                return Err(semantic_refusal(
                    "op holds no live target mark for this person; refusing to fold",
                    "fold-unverified",
                ));
            }
            Err(e) => {
                tracing::warn!(error = %e, "target mark verification failed; rejecting (fail closed)");
                return Err(Status::unavailable(
                    "could not verify the lifecycle op against its target mark; retry",
                ));
            }
        }

        // The fold: the target wins every key it has; snapshots fill
        // still-absent keys in request order; then the merge event's $set
        // overrides and $set_once fills. All inputs are sanitized, so the
        // merged document is measured in stored form.
        let mut target_properties = match person.parse_properties() {
            Ok(value) if value.is_object() => value,
            Ok(_) => serde_json::Value::Object(serde_json::Map::new()),
            Err(e) => {
                return Err(Status::internal(format!(
                    "cached properties unparseable: {e}"
                )))
            }
        };
        // The cached state is an input like any other: rows loaded from
        // Postgres or warmed from records that predate sanitization can
        // carry dirt the wire inputs cannot.
        track(sanitize_for_jsonb(&mut target_properties));
        if sanitize_totals.nul_strings > 0 {
            counter!("personhog_leader_properties_nul_sanitized_total")
                .increment(sanitize_totals.nul_strings);
        }
        if sanitize_totals.clamped_numbers > 0 {
            counter!("personhog_leader_properties_numbers_clamped_total")
                .increment(sanitize_totals.clamped_numbers);
        }
        let target_map = target_properties
            .as_object()
            .expect("target_properties was just normalized to an object");
        let mut folded = target_properties.clone();
        let folded_map = folded
            .as_object_mut()
            .expect("folded clones the normalized target");
        for snapshot in &snapshots {
            if let Some(map) = snapshot.properties.as_object() {
                for (key, value) in map {
                    if !folded_map.contains_key(key) {
                        folded_map.insert(key.clone(), value.clone());
                    }
                }
            }
        }
        if let Some(map) = event_set.as_object() {
            for (key, value) in map {
                folded_map.insert(key.clone(), value.clone());
            }
        }
        if let Some(map) = event_set_once.as_object() {
            for (key, value) in map {
                if !folded_map.contains_key(key) {
                    folded_map.insert(key.clone(), value.clone());
                }
            }
        }

        // Unlike a property update, a fold cannot be rejected for size:
        // the saga would re-drive it forever, so trimming is the only
        // completing behavior. Trim candidates are the fold's own
        // contribution — keys the target did not already hold — so a
        // within-limit target never loses a key it had to a fold. The
        // target's own keys join the candidates only when its stored
        // document already exceeded the limit (the remediation the update
        // path applies to already-oversized rows). The trim aims for the
        // hysteresis target first and, when that is unreachable, retries
        // against the hard ceiling: any document at or under the
        // threshold is still applyable by the writer. When neither bound
        // is reachable, the fold keeps the target's properties,
        // discarding its contribution.
        let jsonb_size = jsonb_column_size(&folded);
        let mut fold_outcome = "folded";
        if jsonb_size > self.size_limits.threshold {
            let target_size = jsonb_column_size(&target_properties);
            let target_oversized = target_size >= self.size_limits.threshold;
            let mut candidates: Vec<String> = folded
                .as_object()
                .expect("folded is an object")
                .keys()
                .filter(|k| !target_map.contains_key(*k) && can_trim_property(k))
                .cloned()
                .collect();
            candidates.sort();
            if target_oversized {
                let mut own: Vec<String> = target_map
                    .keys()
                    .filter(|k| can_trim_property(k))
                    .cloned()
                    .collect();
                own.sort();
                candidates.extend(own);
            }
            let trim_result = match trim_properties_with_candidates(
                &folded,
                self.size_limits.trim_target,
                candidates.clone(),
            ) {
                TrimResult::CannotFit => {
                    trim_properties_with_candidates(&folded, self.size_limits.threshold, candidates)
                }
                result => result,
            };
            match trim_result {
                TrimResult::Trimmed(trimmed) => {
                    counter!("personhog_leader_properties_trimmed_total").increment(1);
                    self.warnings.emit(&SizeViolationWarning {
                        team_id: cache_key.team_id,
                        person_uuid: person.uuid.clone(),
                        message: "Merged person properties exceeded the size limit and were \
                                  trimmed to fit"
                            .to_string(),
                    });
                    folded = trimmed;
                }
                TrimResult::Fits => {}
                TrimResult::CannotFit => {
                    self.warnings.emit(&SizeViolationWarning {
                        team_id: cache_key.team_id,
                        person_uuid: person.uuid.clone(),
                        message: "Merged person properties exceed the size limit and could not \
                                  be trimmed; the merged-in properties were discarded"
                            .to_string(),
                    });
                    if target_oversized {
                        // No applyable document exists: the stored one
                        // itself violates the size constraint (protected
                        // keys alone exceed the ceiling). Producing it
                        // anyway would halt the writer — admission
                        // promises every acked record applies verbatim,
                        // and the writer fail-stops on a violation rather
                        // than skip — and rejecting would wedge the
                        // saga's re-drive loop. The fold completes
                        // without producing: this person's fold effects
                        // (properties and scalars) are skipped. Accepted
                        // residual — README, "Admission".
                        counter!("personhog_leader_folds_total", "outcome" => "unapplyable")
                            .increment(1);
                        tracing::error!(
                            team_id = cache_key.team_id,
                            person_uuid = %person.uuid,
                            stored_size = target_size,
                            threshold = self.size_limits.threshold,
                            "fold target's stored properties exceed the size constraint; \
                             skipping the fold's document write"
                        );
                        return Ok(Response::new(FoldPersonDocumentResponse {
                            person: Some(cached_person_to_proto(&person)),
                        }));
                    }
                    fold_outcome = "unremediable";
                    folded = target_properties.clone();
                }
            }
        }

        // Scalars: created_at is the min over the target and every
        // snapshot (ignoring non-positive values a malformed snapshot
        // could carry); is_identified is unconditionally true — a merge
        // is an identify; last_seen_at max-merges like the update path —
        // the merged person was last seen whenever any constituent was
        // (snapshot values were already hour-floored when stored).
        //
        // The Postgres backend never passes last_seen_at to its merge
        // update, so it answers the target's own until the caller's
        // follow-up update advances it. The two part only where a source
        // was seen after the merge event itself, which needs out-of-order
        // events or clock skew above the hour floor.
        let created_at = snapshots
            .iter()
            .map(|snapshot| snapshot.created_at)
            .filter(|ts| *ts > 0)
            .chain(std::iter::once(person.created_at))
            .min()
            .unwrap_or(person.created_at);
        let last_seen_at = snapshots
            .iter()
            .filter_map(|snapshot| snapshot.last_seen_at)
            .chain(person.last_seen_at)
            .max();

        // The version is a max-merge over the target's floor and every
        // sealed version, plus one: at or above every source's death
        // document, which derives from the same sealed + 1 (equal when
        // the highest sealed version dominates — harmless, the streams
        // are per-person), and re-applying the fold only bumps it again
        // — convergent under at-least-once delivery.
        let base_version = self
            .emitted_versions
            .floor_for(partition, &cache_key, person.version);
        let max_sealed = snapshots
            .iter()
            .map(|snapshot| snapshot.version)
            .max()
            .unwrap_or(0);
        let version = base_version.max(max_sealed).checked_add(1).ok_or_else(|| {
            Status::invalid_argument("sealed versions leave no room for the folded version")
        })?;

        let folded_bytes = serde_json::to_vec(&folded)
            .map_err(|e| Status::internal(format!("serialize folded properties: {e}")))?;
        let approx_bytes = approx_person_bytes(folded_bytes.len());
        let folded_person = CachedPerson {
            id: person.id,
            uuid: person.uuid.clone(),
            team_id: person.team_id,
            properties: folded_bytes,
            created_at,
            version,
            is_identified: true,
            is_deleted: false,
            last_seen_at,
            approx_bytes,
        };

        let proto = self
            .commit_document(partition, &cache_key, folded_person)
            .await?;
        counter!("personhog_leader_folds_total", "outcome" => fold_outcome).increment(1);

        Ok(Response::new(FoldPersonDocumentResponse {
            person: Some(proto),
        }))
    }

    async fn fence_person(
        &self,
        request: Request<FencePersonRequest>,
    ) -> Result<Response<FencePersonResponse>, Status> {
        let partition = partition_from_metadata(&request)?;
        let req = request.into_inner();
        self.validate_partition(partition, req.team_id, req.person_id)?;
        let op_id = Uuid::parse_str(&req.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
        let op_type = req.op_type();
        if op_type == LifecycleOpType::Unspecified {
            return Err(Status::invalid_argument("op_type must be specified"));
        }
        // Advisory, so lenient: an unparseable creator fences without one
        // rather than failing the saga over a field nothing branches on.
        let creator_event_uuid = Uuid::parse_str(&req.creator_event_uuid).ok();

        // A fence installed anywhere but the current owner protects
        // nothing: the map that gates writes is the owner's. Both guards
        // are needed — ownership covers a pod that already handed the
        // partition off (release unfences), the handoff guard covers the
        // drain window before that. Refusing is what makes "a mark
        // committed after the takeover scan arrives as a FencePerson call
        // to the current owner" true: the saga's retry re-routes to the
        // new owner.
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
                // At most one lifecycle op holds a person; the loser backs
                // off or aborts. The holder may also be a ghost (its op
                // settled without this leader hearing); kick the lazy heal
                // like the write paths do, since on a low-traffic person
                // no other caller will.
                if let Some(healer) = &self.fence_healer {
                    healer.maybe_heal(cache_key.clone(), holder);
                }
                return Err(fenced_status(&holder));
            }
            true
        } else {
            false
        };

        // The memory fuse: the map has no eviction, so a surge of ops is
        // bounded here, by shedding new fences. Re-seals are exempt — the
        // person is already fenced, refusing frees nothing — and so is
        // the takeover scan, whose marks are already live. The saga's
        // retry absorbs the backpressure.
        if !refence && self.fences.len() >= self.fence_map_max_entries {
            counter!("personhog_leader_fences_total", "action" => "shed_capacity").increment(1);
            return Err(Status::resource_exhausted(format!(
                "fence map at capacity ({} live fences); retry later",
                self.fence_map_max_entries
            )));
        }

        // The seal: the newest cached state, captured under the same lock
        // that admits writes — no gap for a write to sneak into. Fencing
        // produces nothing and does not advance the version; the sealed
        // version is the person's current one raised to the emitted
        // floor, made final by the fence. The floor matters because a
        // pre-fence write with an indeterminate outcome leaves a version
        // spent above the cache's — sealing below it would derive the
        // death document at a version that may already be live. A
        // same-op re-fence takes this path too, re-sealing with fresh
        // state (the saga's seal step is safe to repeat).
        let person = self.lookup_or_load_locked(partition, &cache_key).await?;
        if person.is_deleted {
            return Err(Status::not_found("person is destroyed"));
        }

        let mut sealed = cached_person_to_proto(&person);
        sealed.version = self
            .emitted_versions
            .floor_for(partition, &cache_key, person.version);

        self.fences.insert(
            cache_key,
            FenceState {
                op_id,
                op_type,
                creator_event_uuid,
            },
        );
        counter!("personhog_leader_fences_total", "action" => "fenced").increment(1);

        Ok(Response::new(FencePersonResponse {
            sealed: Some(sealed),
        }))
    }

    async fn release_fence(
        &self,
        request: Request<ReleaseFenceRequest>,
    ) -> Result<Response<ReleaseFenceResponse>, Status> {
        let partition = partition_from_metadata(&request)?;
        let req = request.into_inner();
        self.validate_partition(partition, req.team_id, req.person_id)?;
        let op_id = Uuid::parse_str(&req.op_id)
            .map_err(|_| Status::invalid_argument("op_id must be a valid UUID"))?;
        let outcome = req.outcome();

        // Both outcomes: a release that removed nothing and returned OK
        // would leave the real owner's fence standing while the saga
        // believes it released — a person frozen with no retry coming.
        self.validate_ownership(partition)?;

        let cache_key = PersonCacheKey {
            team_id: req.team_id,
            person_id: req.person_id,
        };
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

        match outcome {
            ReleaseOutcome::Committed => {
                // 0 is a legitimate sealed version (a fresh stub's),
                // which is why the field is explicitly optional in the proto.
                let Some(sealed_version) = req.sealed_version else {
                    return Err(Status::invalid_argument(
                        "sealed_version is required for a committed release",
                    ));
                };
                if sealed_version < 0 {
                    return Err(Status::invalid_argument(
                        "sealed_version must not be negative",
                    ));
                }
                if req.created_at <= 0 {
                    return Err(Status::invalid_argument(
                        "created_at is required for a committed release",
                    ));
                }
                if Uuid::parse_str(&req.person_uuid).is_err() {
                    return Err(Status::invalid_argument(
                        "person_uuid must be a valid UUID for a committed release",
                    ));
                }
                // Producing to the changelog must respect the handoff
                // write freeze like any write.
                let Some(_inflight_guard) = self.inflight.try_begin(partition) else {
                    return Err(Status::failed_precondition(format!(
                        "partition {partition} is fenced for handoff; writes are rejected"
                    )));
                };

                // Release must stay idempotent for the saga's retry and the
                // sweeper, so a person the leader cannot load anymore is
                // tolerated.
                let current = match self.lookup_or_load_locked(partition, &cache_key).await {
                    Ok(person) => Some(person),
                    Err(status) if status.code() == tonic::Code::NotFound => None,
                    Err(status) => return Err(status),
                };

                // Duplicate release: the death document already exists;
                // producing another would only bump the version.
                if current.as_ref().is_some_and(|p| p.is_deleted) {
                    self.fences.remove(&cache_key);
                    return Ok(Response::new(ReleaseFenceResponse {}));
                }

                // The death document's identity comes from the request (a
                // cold leader has nothing else), so when the leader DOES
                // hold the person, the request must agree with it — the
                // writer upserts uuid verbatim, and a mismatched request
                // would rewrite the row's identity on its way out.
                if let Some(person) = &current {
                    if person.uuid != req.person_uuid {
                        return Err(semantic_refusal(
                            "person_uuid does not match the person being released",
                            "uuid-mismatch",
                        ));
                    }
                }

                // The mark row — the fence's source of truth — must vouch
                // for the op before anything is destroyed. The in-memory
                // fence is not enough: FencePerson never verified the op
                // either, so the request (plus a fence it installed
                // itself) must never be sufficient to produce a death
                // document. Unverifiable requests are refused — fail
                // closed.
                let Some(fallback) = &self.fallback else {
                    return Err(semantic_refusal(
                        "no lifecycle database configured; refusing to produce a death document",
                        "no-lifecycle-db",
                    ));
                };
                match mark_status(&fallback.pool, op_id, req.team_id, req.person_id).await {
                    // A live mark: the op holds the person; proceed.
                    Ok(Some(status)) if status == "marked" || status == "sealed" => {}
                    // The mark already settled as deleted: this release
                    // already happened and the tombstone is durable;
                    // absorb the retry.
                    Ok(Some(status)) if status == "deleted" => {
                        self.fences.remove(&cache_key);
                        return Ok(Response::new(ReleaseFenceResponse {}));
                    }
                    Ok(_) => {
                        counter!("personhog_leader_fences_total", "action" => "release_unverified")
                            .increment(1);
                        return Err(semantic_refusal(
                            "op holds no live mark for this person; \
                             refusing to produce a death document",
                            "release-unverified",
                        ));
                    }
                    Err(e) => {
                        tracing::warn!(error = %e, "mark verification failed; rejecting (fail closed)");
                        return Err(Status::unavailable(
                            "could not verify the lifecycle op against its mark; retry",
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
                // The death version: sealed + 1 per the RFC — the fence
                // makes the sealed version final. The max over the current
                // version and the emitted floor is defense in depth until
                // broker producer fencing lands (a deposed leader's
                // produce could otherwise still advance the version, and
                // an indeterminate one leaves a version spent that the
                // cache never learned of); a cold leader with no state
                // falls back to the sealed version carried by the
                // request, reproducing the death document
                // deterministically.
                let base_version = self.emitted_versions.floor_for(
                    partition,
                    &cache_key,
                    current
                        .as_ref()
                        .map(|p| p.version)
                        .unwrap_or(0)
                        .max(sealed_version),
                );
                let death_version = base_version.checked_add(1).ok_or_else(|| {
                    Status::invalid_argument("sealed_version leaves no room for the death version")
                })?;
                let death = CachedPerson {
                    id: req.person_id,
                    uuid: req.person_uuid.clone(),
                    team_id: req.team_id,
                    properties: b"{}".to_vec(),
                    // The sealed value, not the cached one: cold and warm
                    // leaders must produce the same document.
                    created_at: req.created_at,
                    version: death_version,
                    is_identified: false,
                    is_deleted: true,
                    last_seen_at: None,
                    approx_bytes: approx_person_bytes(2),
                };
                self.commit_document(partition, &cache_key, death).await?;
                // The death document stays in the cache (commit_document
                // put it there): an is_deleted entry answers reads and
                // writes with an authoritative not-found from memory, the
                // same way a recovered death document does. Removing it
                // would only re-derive it — the next attempt recovers the
                // death record via the dirty mark and re-installs it — and
                // once the mark is pruned every attempt would fall through
                // to a PG read instead.
                self.fences.remove(&cache_key);
                counter!("personhog_leader_fences_total", "action" => "released_committed")
                    .increment(1);
            }
            ReleaseOutcome::Aborted => {
                // The op backed out: drop the fence, keep the entry,
                // produce nothing. The person resumes normal life.
                self.fences.remove(&cache_key);
                counter!("personhog_leader_fences_total", "action" => "released_aborted")
                    .increment(1);
            }
            ReleaseOutcome::Unspecified => {
                return Err(Status::invalid_argument("outcome must be specified"));
            }
        }

        Ok(Response::new(ReleaseFenceResponse {}))
    }
}

/// Remove lock entries that no one is currently waiting on. Entries
/// with `Arc::strong_count == 1` are only held by the map itself, so
/// no request is actively using them. Returns the number removed.
pub fn sweep_idle_locks(locks: &DashMap<PersonCacheKey, Arc<Mutex<()>>>) -> usize {
    let before = locks.len();
    locks.retain(|_, v| Arc::strong_count(v) > 1);
    let removed = before - locks.len();
    if removed > 0 {
        tracing::debug!(removed, remaining = locks.len(), "swept idle locks");
    }
    removed
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::time::Duration;

    use common_kafka::config::KafkaConfig;
    use envconfig::Envconfig;
    use health::HealthRegistry;
    use rdkafka::ClientConfig;
    use tonic::Code;

    use super::*;
    use crate::recovery::RecoveryConfig;

    fn make_key(team_id: i64, person_id: i64) -> PersonCacheKey {
        PersonCacheKey { team_id, person_id }
    }

    fn wire_snapshot(person: Person, ordinal: i32) -> SealedSourceSnapshot {
        SealedSourceSnapshot {
            person: Some(person),
            ordinal,
        }
    }

    fn source_person(id: i64, properties: &serde_json::Value) -> Person {
        Person {
            id,
            team_id: 7,
            properties: serde_json::to_vec(properties).unwrap(),
            ..Default::default()
        }
    }

    #[test]
    fn sealed_snapshot_admission_rejects_implausible_sources() {
        let valid = serde_json::json!({});
        let cases: Vec<(&str, Vec<SealedSourceSnapshot>)> = vec![
            (
                "missing person",
                vec![SealedSourceSnapshot {
                    person: None,
                    ordinal: 0,
                }],
            ),
            (
                "wrong team",
                vec![wire_snapshot(
                    Person {
                        team_id: 8,
                        ..source_person(2, &valid)
                    },
                    0,
                )],
            ),
            (
                "snapshot is the target",
                vec![wire_snapshot(source_person(1, &valid), 0)],
            ),
            (
                "death document",
                vec![wire_snapshot(
                    Person {
                        is_deleted: true,
                        ..source_person(2, &valid)
                    },
                    0,
                )],
            ),
            (
                "duplicate ordinal",
                vec![
                    wire_snapshot(source_person(2, &valid), 0),
                    wire_snapshot(source_person(3, &valid), 0),
                ],
            ),
            (
                "non-object properties",
                vec![wire_snapshot(
                    Person {
                        properties: b"[1]".to_vec(),
                        ..source_person(2, &valid)
                    },
                    0,
                )],
            ),
        ];
        for (label, sealed) in cases {
            let status = parse_sealed_snapshots(&sealed, 7, 1).expect_err(label);
            assert_eq!(status.code(), Code::InvalidArgument, "{label}");
        }
    }

    #[test]
    fn sealed_snapshot_admission_sorts_by_ordinal_and_counts_sanitization() {
        let nul_dirty = serde_json::json!({"a": "x\u{0000}y"});
        let float_dirty = serde_json::json!({"b": 1e308});
        let (snapshots, stats) = parse_sealed_snapshots(
            &[
                wire_snapshot(
                    Person {
                        version: 9,
                        ..source_person(2, &nul_dirty)
                    },
                    1,
                ),
                wire_snapshot(
                    Person {
                        version: 4,
                        ..source_person(3, &float_dirty)
                    },
                    0,
                ),
            ],
            7,
            1,
        )
        .expect("plausible snapshots admit");
        assert_eq!(
            snapshots
                .iter()
                .map(|snapshot| snapshot.version)
                .collect::<Vec<_>>(),
            vec![4, 9],
            "returned in ordinal order, not request order"
        );
        assert_eq!(stats.nul_strings, 1);
        assert_eq!(stats.clamped_numbers, 1);
    }

    /// A service with no PG pool and a producer that never connects —
    /// enough to exercise the miss path, where no test reaches Kafka or PG.
    async fn make_test_service() -> PersonHogLeaderService {
        let kafka = KafkaConfig::init_from_hashmap(&HashMap::new()).unwrap();
        let liveness = HealthRegistry::new("test")
            .register("kafka".to_string(), Duration::from_secs(60))
            .await;
        let producer: rdkafka::producer::FutureProducer<KafkaContext> = ClientConfig::new()
            .set("bootstrap.servers", "127.0.0.1:1")
            .create_with_context(KafkaContext::from(liveness))
            .unwrap();
        PersonHogLeaderService::new(
            Arc::new(PartitionedCache::new(16)),
            producer.clone(),
            "personhog_updates".to_string(),
            None,
            Arc::new(DashMap::new()),
            Arc::new(InflightTracker::new()),
            1,
            Arc::new(DirtyIndex::new(16)),
            Arc::new(
                ChangelogRecovery::new(RecoveryConfig {
                    kafka,
                    topic: "personhog_updates".to_string(),
                    pod_name: "test".to_string(),
                    recv_timeout: Duration::from_millis(10),
                    pool_size: 1,
                })
                .expect("build recovery pool"),
            ),
            PropertySizeLimits::new(655360, 524288),
            WarningsProducer::new(producer, "clickhouse_ingestion_warnings".to_string()),
            Arc::new(DashMap::new()),
            None,
            None,
            Arc::new(EmittedVersions::new(1_000_000)),
        )
    }

    /// The guarantee the clock exists for: a pod whose renewals have
    /// stopped refuses to answer as the partition's owner, without
    /// anything running to notice they stopped. The keepalive being
    /// wedged is exactly the case the lease machinery cannot cover.
    #[tokio::test]
    async fn a_pod_whose_renewals_stopped_refuses_to_serve() {
        // A clock whose renewals stopped longer ago than the margin —
        // constructed stale rather than aged by sleeping, so no runner
        // pace can blur which side of the margin the test is on.
        let margin = Duration::from_secs(20);
        let clock = Arc::new(AuthorityClock::stale_for(
            margin,
            margin + Duration::from_secs(1),
        ));
        let service = PersonHogLeaderService {
            authority: Some(Arc::clone(&clock)),
            ..make_test_service().await
        };

        let err = service
            .check_authority(0)
            .expect_err("a lapsed lease must not serve");
        assert_eq!(err.code(), Code::FailedPrecondition);

        clock.confirm(Instant::now());
        service
            .check_authority(0)
            .expect("a confirmed renewal restores service");
    }

    /// Losing the lease is decided immediately, not after the margin:
    /// the coordinator may already be reassigning.
    #[tokio::test]
    async fn surrendering_the_lease_stops_reads_at_once() {
        let clock = Arc::new(AuthorityClock::unclaimed());
        clock.begin_session(Duration::from_secs(30), Instant::now());
        let service = PersonHogLeaderService {
            authority: Some(Arc::clone(&clock)),
            ..make_test_service().await
        };

        service.check_authority(0).expect("still the owner");
        clock.surrender();
        assert_eq!(
            service.check_authority(0).unwrap_err().code(),
            Code::FailedPrecondition
        );
    }

    /// The gate has to be wired into the RPC, not merely implemented:
    /// this drives `get_person` itself rather than the check in
    /// isolation.
    ///
    /// It does not distinguish the two checks — a read that finds its
    /// person in cache never waits, so either one refuses it, and both
    /// return the same status. `a_read_admitted_before_the_lapse_still_
    /// refuses_to_answer` is what pins the second.
    #[tokio::test]
    async fn get_person_refuses_once_authority_lapses() {
        let margin = Duration::from_secs(20);
        let clock = Arc::new(AuthorityClock::stale_for(
            margin,
            margin + Duration::from_secs(1),
        ));
        let service = PersonHogLeaderService {
            authority: Some(Arc::clone(&clock)),
            ..make_test_service().await
        };
        // The fixture's single partition makes 0 the only routing answer.
        let (team_id, person_id) = (7, 42);
        service.cache.create_partition(0);
        service.cache.put(
            0,
            PersonCacheKey { team_id, person_id },
            CachedPerson {
                id: person_id,
                uuid: "00000000-0000-0000-0000-000000000007".to_string(),
                team_id,
                properties: serde_json::to_vec(&serde_json::json!({})).unwrap(),
                created_at: 0,
                version: 1,
                is_identified: false,
                is_deleted: false,
                last_seen_at: None,
                approx_bytes: 64,
            },
        );

        let request = || {
            let mut request = Request::new(GetPersonRequest {
                team_id,
                person_id,
                read_options: None,
            });
            request
                .metadata_mut()
                .insert("x-partition", "0".parse().unwrap());
            request
        };

        let err = service
            .get_person(request())
            .await
            .expect_err("a lapsed lease must refuse the read");
        assert_eq!(err.code(), Code::FailedPrecondition);

        clock.confirm(Instant::now());
        service
            .get_person(request())
            .await
            .expect("a confirmed renewal serves the read");
    }

    /// A write is serving too, and the lease-loss path surrenders before
    /// it drains — so between the surrender and the local fence landing,
    /// this check is what stops a pod that no longer holds its lease from
    /// acking a mutation the successor will never see. Fencing covers the
    /// same ground when it is on, but it cannot be enabled first, so this
    /// is the only cover the intermediate rollout state has.
    ///
    /// Like its read-path counterpart it does not distinguish admission
    /// from the pre-produce re-check; `a_write_admitted_before_the_lapse_
    /// is_not_produced` pins the second.
    ///
    /// The person is seeded deliberately: without it a removed check
    /// would still surface `FailedPrecondition` from the ownership guard
    /// further down, and the test would pass having proved nothing.
    #[tokio::test]
    async fn update_refuses_once_authority_is_surrendered() {
        let clock = Arc::new(AuthorityClock::unclaimed());
        clock.begin_session(Duration::from_secs(30), Instant::now());
        let service = PersonHogLeaderService {
            authority: Some(Arc::clone(&clock)),
            ..make_test_service().await
        };
        let (team_id, person_id) = (7, 42);
        service.cache.create_partition(0);
        service.cache.put(
            0,
            PersonCacheKey { team_id, person_id },
            CachedPerson {
                id: person_id,
                uuid: "00000000-0000-0000-0000-000000000007".to_string(),
                team_id,
                properties: serde_json::to_vec(&serde_json::json!({})).unwrap(),
                created_at: 0,
                version: 1,
                is_identified: false,
                is_deleted: false,
                last_seen_at: None,
                approx_bytes: 64,
            },
        );

        let request = || {
            let mut request = Request::new(UpdatePersonPropertiesRequest {
                team_id,
                person_id,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({"a": 1})).unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
                is_identified: None,
                last_seen_at: None,
            });
            request
                .metadata_mut()
                .insert("x-partition", "0".parse().unwrap());
            request
        };

        // Losing the lease is decided at once, not after the margin, so
        // no sleep is needed to reach the state that matters.
        clock.surrender();

        // Bounded on purpose: with the check gone the handler runs on to
        // produce against a broker that is not there, so an unbounded
        // await would report this regression as a hung test rather than a
        // failing one.
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            service.update_person_properties(request()),
        )
        .await
        .expect("the refusal must come from the claim check, not from a produce timeout");
        let err = result.expect_err("a surrendered pod must not ack a write");
        assert_eq!(err.code(), Code::FailedPrecondition);
    }

    /// `get_person` checks the claim twice, and asserting only on the
    /// status code cannot tell the two apart: delete either and the other
    /// still answers FailedPrecondition. This one pins the second.
    ///
    /// The load is what makes it distinct. A read that finds the person
    /// in cache never waits, so the admission check is the only one it
    /// can trip; a read that has to wait — on the per-key lock, or on a
    /// changelog recovery — can be admitted under a claim that is gone by
    /// the time there is an answer, and it is the answer, not the
    /// arrival, that has to be backed by ownership.
    #[tokio::test]
    async fn a_read_admitted_before_the_lapse_still_refuses_to_answer() {
        let clock = Arc::new(AuthorityClock::unclaimed());
        clock.begin_session(Duration::from_secs(30), Instant::now());
        let service = Arc::new(PersonHogLeaderService {
            authority: Some(Arc::clone(&clock)),
            ..make_test_service().await
        });
        let (team_id, person_id) = (7, 42);
        let cache_key = PersonCacheKey { team_id, person_id };
        service.cache.create_partition(0);

        // Hold the per-key lock. The read misses the cache, reaches for
        // this lock, and parks there — which is where a changelog
        // recovery would leave it.
        let mutex = service
            .locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let held = mutex.lock().await;

        let mut request = Request::new(GetPersonRequest {
            team_id,
            person_id,
            read_options: None,
        });
        request
            .metadata_mut()
            .insert("x-partition", "0".parse().unwrap());
        let reading = tokio::spawn({
            let service = Arc::clone(&service);
            async move { service.get_person(request).await }
        });
        tokio::task::yield_now().await;

        // The claim goes while the read is parked, and the answer it was
        // waiting for arrives at the same time.
        clock.surrender();
        service.cache.put(
            0,
            cache_key.clone(),
            CachedPerson {
                id: person_id,
                uuid: "00000000-0000-0000-0000-000000000007".to_string(),
                team_id,
                properties: serde_json::to_vec(&serde_json::json!({})).unwrap(),
                created_at: 0,
                version: 1,
                is_identified: false,
                is_deleted: false,
                last_seen_at: None,
                approx_bytes: 64,
            },
        );
        drop(held);

        let err = reading
            .await
            .expect("the read task must not panic")
            .expect_err("a claim that lapsed during the load must not be answered");
        assert_eq!(err.code(), Code::FailedPrecondition);
    }

    /// The write path checks the claim twice for the same reason the read
    /// path does, and asserting only on the status code cannot tell them
    /// apart. This one pins the second.
    ///
    /// A write admitted under a valid claim can wait on the per-key lock
    /// behind another produce, and on a changelog recovery — long enough
    /// for a starved keepalive's stamp to age out, for the lease to
    /// expire, and for a successor to warm past the point this record
    /// would land. Acking it then is acked-write loss that needs only one
    /// wedged pod, not a double zombie.
    #[tokio::test]
    async fn a_write_admitted_before_the_lapse_is_not_produced() {
        let clock = Arc::new(AuthorityClock::unclaimed());
        clock.begin_session(Duration::from_secs(30), Instant::now());
        let service = Arc::new(PersonHogLeaderService {
            authority: Some(Arc::clone(&clock)),
            ..make_test_service().await
        });
        let (team_id, person_id) = (7, 42);
        let cache_key = PersonCacheKey { team_id, person_id };
        service.cache.create_partition(0);
        service.cache.put(
            0,
            cache_key.clone(),
            CachedPerson {
                id: person_id,
                uuid: "00000000-0000-0000-0000-000000000007".to_string(),
                team_id,
                properties: serde_json::to_vec(&serde_json::json!({})).unwrap(),
                created_at: 0,
                version: 1,
                is_identified: false,
                is_deleted: false,
                last_seen_at: None,
                approx_bytes: 64,
            },
        );

        // Hold the per-key lock so the write is admitted and then parks,
        // where a concurrent produce for the same person would leave it.
        let mutex = service
            .locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let held = mutex.lock().await;

        let mut request = Request::new(UpdatePersonPropertiesRequest {
            team_id,
            person_id,
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&serde_json::json!({"a": 1})).unwrap(),
            set_once_properties: vec![],
            unset_properties: vec![],
            is_identified: None,
            last_seen_at: None,
        });
        request
            .metadata_mut()
            .insert("x-partition", "0".parse().unwrap());
        let writing = tokio::spawn({
            let service = Arc::clone(&service);
            async move { service.update_person_properties(request).await }
        });
        tokio::task::yield_now().await;

        // The claim goes while the write is parked, then the lock frees.
        clock.surrender();
        drop(held);

        // Bounded: without the re-check the handler runs on to produce
        // against a broker that is not there, and an unbounded await
        // would report the regression as a hang rather than a failure.
        let result = tokio::time::timeout(Duration::from_secs(5), writing)
            .await
            .expect("the refusal must come from the claim check, not a produce timeout")
            .expect("the write task must not panic");
        let err = result.expect_err("a claim that lapsed during the wait must not be produced");
        assert_eq!(err.code(), Code::FailedPrecondition);
    }

    /// The admission checks refuse *before* the request does any work, and
    /// only the wait distinguishes them from the pre-answer re-checks: a
    /// request that reaches the per-key lock has already been admitted.
    ///
    /// Holding that lock turns the difference into a deadline. With
    /// admission intact neither call ever reaches it; without it they park
    /// there and are refused only once the lock frees, having meanwhile
    /// taken an inflight seat a handoff's drain must wait out and, on a
    /// miss, driven a Postgres fallback or a changelog recovery for a
    /// partition this pod no longer answers for.
    #[tokio::test]
    async fn a_request_arriving_after_the_lapse_is_refused_before_it_loads() {
        let clock = Arc::new(AuthorityClock::unclaimed());
        clock.begin_session(Duration::from_secs(30), Instant::now());
        let service = Arc::new(PersonHogLeaderService {
            authority: Some(Arc::clone(&clock)),
            ..make_test_service().await
        });
        let (team_id, person_id) = (7, 42);
        let cache_key = PersonCacheKey { team_id, person_id };
        // Deliberately unseeded: the read reaches the lock only on a
        // miss, and a hit would let a dropped admission check still be
        // caught by the pre-answer one, proving nothing.
        service.cache.create_partition(0);

        // Anything admitted parks here; nothing admitted ever arrives.
        let mutex = service
            .locks
            .entry(cache_key.clone())
            .or_default()
            .value()
            .clone();
        let _held = mutex.lock().await;

        clock.surrender();

        let mut read = Request::new(GetPersonRequest {
            team_id,
            person_id,
            read_options: None,
        });
        read.metadata_mut()
            .insert("x-partition", "0".parse().unwrap());
        let err = tokio::time::timeout(Duration::from_millis(200), service.get_person(read))
            .await
            .expect("the read must be refused at admission, not behind the load")
            .expect_err("a lapsed claim must not be served");
        assert_eq!(err.code(), Code::FailedPrecondition);

        let mut write = Request::new(UpdatePersonPropertiesRequest {
            team_id,
            person_id,
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&serde_json::json!({"a": 1})).unwrap(),
            set_once_properties: vec![],
            unset_properties: vec![],
            is_identified: None,
            last_seen_at: None,
        });
        write
            .metadata_mut()
            .insert("x-partition", "0".parse().unwrap());
        let err = tokio::time::timeout(
            Duration::from_millis(200),
            service.update_person_properties(write),
        )
        .await
        .expect("the write must be refused at admission, not behind the load")
        .expect_err("a lapsed claim must not be admitted");
        assert_eq!(err.code(), Code::FailedPrecondition);
    }

    /// With the gate off the pod serves exactly as before, so the flag
    /// is a real off switch rather than a partial one.
    #[tokio::test]
    async fn an_ungated_service_serves_regardless_of_renewals() {
        let service = make_test_service().await;
        assert!(service.authority.is_none());
        service.check_authority(0).expect("no gate, no refusal");
    }

    #[test]
    #[should_panic(expected = "must not exceed")]
    fn inverted_size_limits_refuse_to_construct() {
        PropertySizeLimits::new(655_360, 655_361);
    }

    #[tokio::test]
    async fn unmarked_miss_fails_closed_once_partition_is_released() {
        let service = make_test_service().await;
        let key = make_key(1, 1);

        // Owned and unmarked: PG is trusted (NOT_FOUND, since the test
        // service has no pool).
        service.cache.create_partition(0);
        let err = service.recover_or_load(0, &key).await.unwrap_err();
        assert_eq!(err.code(), Code::NotFound);

        // Released mid-miss (cache dropped, then marks cleared — release
        // order): the same lookup must fail closed rather than trust a
        // possibly-stale PG row the cleared mark no longer guards.
        service.cache.drop_partition(0);
        service.dirty_index.clear_partition(0);
        let err = service.recover_or_load(0, &key).await.unwrap_err();
        assert_eq!(err.code(), Code::FailedPrecondition);
    }

    #[test]
    fn sweep_removes_idle_entries() {
        let locks = DashMap::new();
        locks.insert(make_key(1, 1), Arc::new(Mutex::new(())));
        locks.insert(make_key(1, 2), Arc::new(Mutex::new(())));
        locks.insert(make_key(1, 3), Arc::new(Mutex::new(())));

        let removed = sweep_idle_locks(&locks);

        assert_eq!(removed, 3);
        assert_eq!(locks.len(), 0);
    }

    #[test]
    fn sweep_preserves_held_entries() {
        let locks = DashMap::new();
        locks.insert(make_key(1, 1), Arc::new(Mutex::new(())));
        locks.insert(make_key(1, 2), Arc::new(Mutex::new(())));
        locks.insert(make_key(1, 3), Arc::new(Mutex::new(())));

        // Simulate an active holder cloning the Arc (as lookup_or_load does)
        let _held = locks.get(&make_key(1, 2)).unwrap().clone();

        let removed = sweep_idle_locks(&locks);

        assert_eq!(removed, 2);
        assert_eq!(locks.len(), 1);
        assert!(locks.contains_key(&make_key(1, 2)));
    }

    #[test]
    fn sweep_is_noop_when_empty() {
        let locks: DashMap<PersonCacheKey, Arc<Mutex<()>>> = DashMap::new();

        let removed = sweep_idle_locks(&locks);

        assert_eq!(removed, 0);
    }
}
