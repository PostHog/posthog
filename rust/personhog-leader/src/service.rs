use std::sync::Arc;
use std::time::Instant;

use common_kafka::kafka_producer::KafkaContext;
use dashmap::DashMap;
use metrics::{counter, histogram};
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeader;
use personhog_proto::personhog::types::v1::{
    GetPersonRequest, GetPersonResponse, Person, UpdatePersonPropertiesRequest,
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
use crate::fencing::{FencedChangelogProducers, FencedProduceError};
use crate::inflight::InflightTracker;
use crate::kafka::produce_person_changelog;
use crate::person_update::{apply_property_updates, compute_event_property_updates};
use crate::pg::{load_person_from_pg, PgFallback};
use crate::recovery::ChangelogRecovery;
use crate::warnings::{SizeViolationWarning, WarningsProducer};
use personhog_common::properties::{
    jsonb_column_size, sanitize_for_jsonb, trim_properties_to_fit_size, TrimResult,
};

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
        fenced: Option<Arc<FencedChangelogProducers>>,
        authority: Option<Arc<AuthorityClock>>,
        emitted_versions: Arc<EmittedVersions>,
    ) -> Self {
        Self {
            cache,
            locks,
            producer,
            changelog_topic,
            fallback,
            inflight,
            num_partitions,
            dirty_index,
            recovery,
            size_limits,
            warnings,
            fenced,
            authority,
            emitted_versions,
        }
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
    let properties_bytes = serde_json::to_vec(&p.properties).unwrap_or_default();
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
    }
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

        let person = self.lookup_or_load_locked(partition, &cache_key).await?;

        // Compute property updates
        let updates = compute_event_property_updates(
            &req.event_name,
            &set_properties,
            &set_once_properties,
            &unset_properties,
            &person.properties,
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
            apply_property_updates(&updates, &person.properties);

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
            let existing_size = jsonb_column_size(&person.properties);
            if existing_size >= self.size_limits.threshold {
                match trim_properties_to_fit_size(&person.properties, self.size_limits.trim_target)
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
                        new_properties = person.properties.clone();
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

        let approx_bytes = approx_person_bytes(jsonb_column_size(&new_properties));
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
            properties: new_properties,
            created_at: person.created_at,
            version: base_version + 1,
            is_identified: identified_now,
            last_seen_at: merged_last_seen,
            approx_bytes,
        };

        // Final applyability assertions on the identity fields, which
        // originate from earlier state rather than this request. A record
        // the writer cannot bind must never reach the changelog — no
        // consumer downstream can apply or repair it.
        if let Err(reason) = assert_writeable(&updated_person) {
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

        let proto = cached_person_to_proto(&updated_person);

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
            updated_person.version,
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
                version: updated_person.version,
                offset,
                partition,
            },
        );
        self.cache.put(partition, cache_key, updated_person);
        // The cache carries the version now, so the floor has nothing
        // left to say.
        emitted.resolved();
        counter!("personhog_leader_updates_total", "outcome" => "updated").increment(1);

        Ok(Response::new(UpdatePersonPropertiesResponse {
            person: Some(proto),
            updated: true,
        }))
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
                properties: serde_json::json!({}),
                created_at: 0,
                version: 1,
                is_identified: false,
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
                properties: serde_json::json!({}),
                created_at: 0,
                version: 1,
                is_identified: false,
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
                properties: serde_json::json!({}),
                created_at: 0,
                version: 1,
                is_identified: false,
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
                properties: serde_json::json!({}),
                created_at: 0,
                version: 1,
                is_identified: false,
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
