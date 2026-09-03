use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use metrics::counter;
use personhog_coordination::authority::AuthorityClock;
use personhog_coordination::error::{Error, Result};
use personhog_coordination::pod::HandoffHandler;
use tracing::{error, info};

use crate::cache::{DirtyIndex, PartitionedCache};
use crate::emitted::EmittedVersions;
use crate::fence::{drop_partition_fences, rebuild_partition_fences, FenceMap};
use crate::fencing::{heal_fence, FenceGuard, FencedChangelogProducers, HealOutcome};
use crate::inflight::InflightTracker;
use crate::warming::{warm_from_kafka, WarmClientPools, WarmingConfig};

const DRAIN_POLL_INTERVAL: Duration = Duration::from_millis(50);

/// Handles partition ownership lifecycle events for a leader pod.
///
/// Drives three phase responses via the `HandoffHandler` trait,
/// matching the four-phase handoff protocol
/// (`Freezing → Draining → Warming → Complete`):
///   - `drain_partition_inflight` (fired in `Draining` for the
///     old owner): fences the partition against new writes, then waits
///     until no in-flight request handlers remain. By the time the
///     coordinator advances to `Draining`, every router has acked freeze
///     and stopped forwarding, so any write arriving after this point is
///     protocol-violating (a router with a stale view) and is rejected.
///     Because the produce path awaits the Kafka delivery future
///     before returning, "no in-flight" implies "every write this
///     pod ever acked is durable in Kafka." The pod then writes
///     `PodDrainedAck` so the coordinator can advance to `Warming`.
///   - `warm_partition` (fired in `Warming` for the new owner):
///     consumes the `personhog_updates` topic for the partition and
///     repopulates the in-memory cache up to the now-stable HWM.
///   - `release_partition` (fired in `Complete` for the old owner):
///     drops the partition's cache (and its write fence) after the
///     routing table has flipped to the new owner.
///   - `resume_partition` (fired when a handoff is cancelled while this
///     pod still owns the partition): lifts the write fence so the
///     still-owning pod serves normally again.
///
/// Reads are never fenced: while writes are frozen the cached state
/// cannot change, so the old owner's cache remains the latest state
/// right up to cutover.
pub struct LeaderHandoffHandler {
    cache: Arc<PartitionedCache>,
    inflight: Arc<InflightTracker>,
    dirty_index: Arc<DirtyIndex>,
    warming: WarmingConfig,
    /// The in-process fence copies, rebuilt from the live marks at every
    /// ownership boundary (see the fence module for the durability model).
    fences: FenceMap,
    /// Pool for the takeover scan — the cache-miss fallback pool. Without
    /// it (dev fixtures) fences are not rebuilt on takeover and only
    /// FencePerson calls fill the map.
    fence_scan_pool: Option<sqlx::PgPool>,
    num_partitions: u32,
    pools: Arc<WarmClientPools>,
    /// Present when broker-enforced epoch fencing is on: acquiring a
    /// partition initializes its transactional producer (fencing every
    /// predecessor), and releasing it drops the producer.
    fenced: Option<Arc<FencedChangelogProducers>>,
    /// Present when lease-gated authority is on. Acquiring a fence takes
    /// the partition's epoch away from whoever holds it, so a pod whose
    /// lease may have lapsed must not do it: the broker grants the epoch
    /// to whoever initializes last, not to whoever the protocol says
    /// owns the partition, so an unchecked acquire lets a zombie waking
    /// inside its lease window fence the legitimate owner.
    authority: Option<Arc<AuthorityClock>>,
    /// Shared with the service, so that giving up a partition also gives
    /// up the version floors held for its persons.
    emitted_versions: Arc<EmittedVersions>,
    /// Partitions whose fence this pod took during the convergence that
    /// is still running.
    ///
    /// A convergence to `Serving` can both warm and resume, in that
    /// order, and warming re-admits writes as its last act. Without this,
    /// the resume that follows re-acquires and bumps the epoch out from
    /// under every write admitted in between — the pod fencing its own
    /// live window.
    freshly_fenced: Arc<dashmap::DashSet<u32>>,
}

impl LeaderHandoffHandler {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        cache: Arc<PartitionedCache>,
        inflight: Arc<InflightTracker>,
        dirty_index: Arc<DirtyIndex>,
        warming: WarmingConfig,
        fences: FenceMap,
        fence_scan_pool: Option<sqlx::PgPool>,
        num_partitions: u32,
        pools: Arc<WarmClientPools>,
        fenced: Option<Arc<FencedChangelogProducers>>,
        authority: Option<Arc<AuthorityClock>>,
        emitted_versions: Arc<EmittedVersions>,
    ) -> Self {
        Self {
            cache,
            inflight,
            dirty_index,
            warming,
            fences,
            fence_scan_pool,
            num_partitions,
            pools,
            fenced,
            authority,
            emitted_versions,
            freshly_fenced: Arc::new(dashmap::DashSet::new()),
        }
    }

    pub fn owns_partition(&self, partition: u32) -> bool {
        self.cache.has_partition(partition)
    }

    /// Refuse to take a partition's fence when this pod's own lease may
    /// have lapsed.
    ///
    /// Acquisition is not a private act: `init_transactions` moves the
    /// broker's epoch to this producer and invalidates the previous
    /// holder, whoever that is. A pod that has stopped renewing has no
    /// standing to do that, and doing it anyway is how a waking zombie
    /// takes the partition away from the owner that legitimately holds
    /// it. Failing here leaves the convergence to retry once the lease
    /// is confirmed again, or to end with the session if it is not.
    /// Re-check after a broker round trip that moved the partition's
    /// epoch.
    ///
    /// `check_authority` before `acquire` is a pre-check across an
    /// operation that talks to the broker, so the claim can lapse while
    /// it runs. The epoch bump cannot be undone — `init_transactions`
    /// has already taken it from whoever held it — but this pod can
    /// decline to build on a claim it no longer has: it drops the fence
    /// and fails the convergence rather than serving. The partition's
    /// real owner re-takes the epoch through its own healing
    /// re-acquisition, so a fence stolen this way corrects itself
    /// instead of persisting until the next handoff.
    fn check_authority_after_acquire(&self, partition: u32, phase: &'static str) -> Result<()> {
        let Err(e) = self.check_authority(partition, phase) else {
            return Ok(());
        };
        if let Some(fenced) = &self.fenced {
            fenced.release(partition);
        }
        counter!(
            "personhog_leader_authority_lapsed_mid_acquire_total",
            "phase" => phase
        )
        .increment(1);
        error!(
            partition,
            phase, "authority lapsed while taking the changelog fence; dropping it"
        );
        Err(e)
    }

    fn check_authority(&self, partition: u32, phase: &'static str) -> Result<()> {
        let Some(authority) = &self.authority else {
            return Ok(());
        };
        if authority.is_valid() {
            return Ok(());
        }
        counter!(
            "personhog_leader_authority_lapsed_acquires_total",
            "phase" => phase,
            "reason" => if authority.is_surrendered() { "surrendered" } else { "stale" }
        )
        .increment(1);
        Err(Error::invalid_state(format!(
            "refusing to take the changelog fence for partition {partition}: no confirmed \
             lease renewal in {:?}",
            authority.since_confirmed()
        )))
    }

    /// Stage the mark warming leaves behind. Warming itself needs a
    /// broker, and what these tests pin is the mark's lifetime across the
    /// convergences that follow, not how it comes to exist.
    #[cfg(test)]
    fn mark_freshly_fenced_for_test(&self, partition: u32) {
        self.freshly_fenced.insert(partition);
    }

    /// Whether a resume would take the fence rather than trust an earlier
    /// acquisition — the decision the mark exists to make.
    #[cfg(test)]
    fn would_reacquire_on_resume(&self, partition: u32) -> bool {
        !self.freshly_fenced.contains(&partition)
    }
}

#[async_trait]
impl HandoffHandler for LeaderHandoffHandler {
    async fn prepare_acquire(&self, partition: u32) {
        // Spawned: the convergence must not wait on a broker connect,
        // and `preconnect` is single-flight per partition, so repeated
        // convergences through the drain window cost one spawn each and
        // one client total. A parked connection the acquire never
        // consumes is discarded on release or by the periodic sweep —
        // a cancelled inbound handoff leaves no convergence behind, so
        // the sweep is the only path that reaches its leftovers.
        if let Some(fenced) = &self.fenced {
            let fenced = Arc::clone(fenced);
            tokio::spawn(async move { fenced.preconnect(partition).await });
        }
    }

    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        info!(partition, "fencing writes and draining inflight handlers");
        // Fence before waiting: fencing only after the wait would leave a
        // window between the inflight count reaching zero and the
        // DrainedAck where a late write could advance the Kafka HWM past
        // the point warming snapshots.
        self.inflight.fence(partition);
        // From here the partition is moving, so a fence taken by an
        // earlier convergence stops counting as fresh: the incoming owner
        // can take the epoch before the handoff is cancelled, and a
        // resume that skipped its re-acquire on the strength of that
        // stale mark would re-admit writes onto a producer the broker has
        // already moved past.
        self.freshly_fenced.remove(&partition);
        self.inflight
            .wait_until_empty(partition, DRAIN_POLL_INTERVAL)
            .await;
        // A request cancelled mid-produce takes its handler — and the
        // count above — with it, leaving the record it enqueued in a
        // window nobody is waiting on. Committing that window here lands
        // the cancelled write below the cutoff the successor is about to
        // read, rather than leaving it to be aborted by whichever side
        // acts first.
        //
        // Best-effort by construction, and the drain proceeds either way:
        // the successor's `init_transactions` aborts whatever is left,
        // exactly as it did before this wait existed — pinned by
        // `a_successors_init_aborts_the_predecessors_open_window`.
        if let Some(fenced) = &self.fenced {
            fenced.settle(partition).await;
        }
        info!(partition, "inflight drained; writes fenced");
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        // The takeover scan: rebuild the partition's lifecycle fences from
        // the live marks BEFORE warming — the partition becomes servable
        // the moment `warm_from_kafka` installs it in the cache, and a
        // fenced person must never be writable in that gap. A mark
        // committed after this read arrives as a FencePerson call to this
        // (now current) owner, so the two sources cover every mark; a
        // fence installed for a partition that is not yet serving is
        // harmless.
        if let Some(pool) = &self.fence_scan_pool {
            let installed =
                rebuild_partition_fences(pool, &self.fences, partition, self.num_partitions)
                    .await
                    .map_err(|e| personhog_coordination::error::Error::HandoffFailed {
                        partition,
                        reason: format!("fence takeover scan failed: {e}"),
                    })?;
            if installed > 0 {
                info!(
                    partition,
                    installed, "rebuilt lifecycle fences from live marks"
                );
            }
        }
        info!(partition, "warming partition cache from kafka");
        self.check_authority(partition, "warm")?;
        // Broker-side fencing before the warm read, not after: acquiring
        // the fence bumps the producer epoch and aborts any in-flight
        // transaction from a predecessor, so every write a stale owner
        // ever committed sits below the watermark the warm is about to
        // read. Fencing after the read would leave a gap where a zombie
        // commits an acked write the warm never sees.
        // Deliberately re-acquired even when this pod already holds a
        // fence from a convergence torn down before it could record the
        // warm. Skipping would spare the writes that warm admitted, but
        // it leaves this pod's own uncommitted records between the read
        // and the high watermark, and the warm below then waits for
        // records it can never read. Re-acquiring aborts that window,
        // which is what lets the read complete; the admitted writes fail
        // as fenced and their versions stay spent.
        let fence_guard = if let Some(fenced) = &self.fenced {
            fenced
                .acquire(partition)
                .await
                .map_err(Error::invalid_state)?;
            self.check_authority_after_acquire(partition, "warm")?;
            info!(partition, "changelog fence acquired");
            // From here the fence is held for a warm that has not
            // happened yet. If the warm fails — or never returns,
            // because the attempt was torn down by a lost lease — the
            // guard gives the epoch back rather than leaving this
            // process holding a partition it does not own.
            Some(FenceGuard::new(Arc::clone(fenced), partition, "warm"))
        } else {
            None
        };
        warm_from_kafka(
            &self.warming,
            &self.pools,
            &self.cache,
            &self.dirty_index,
            partition,
        )
        .await?;
        // This pod may still carry a fence from a previous ownership of
        // the partition (a drain whose handoff never completed); taking
        // ownership through a fresh warm re-admits writes.
        self.inflight.unfence(partition);
        if let Some(guard) = fence_guard {
            guard.keep();
            self.freshly_fenced.insert(partition);
        }
        info!(partition, "partition warmed");
        Ok(())
    }

    /// The partition is meant to be served, so make sure this pod can
    /// actually write to it. A fence lost to a broker rejection or a
    /// failed abort has no other way back — convergence sees the
    /// partition warmed and unfenced and would otherwise do nothing.
    ///
    /// A heal that cannot acquire is reported through the
    /// partition-labeled failure counter and the error log, not by
    /// failing the run. Failing the run would escalate through the
    /// convergence budgets to process death — trading one partition's
    /// writes for every partition's reads — while the reconcile tick
    /// already retries this every pass. A heal that succeeds counts as
    /// applied work, so a repairing pod's budgets reset like any other
    /// progress.
    async fn verify_serving(&self, partition: u32) -> Result<bool> {
        let Some(fenced) = &self.fenced else {
            return Ok(false);
        };
        match heal_fence(fenced, &self.inflight, self.authority.as_deref(), partition).await {
            Ok(HealOutcome::Healed) => {
                // The epoch just moved. Mark it like every other
                // acquisition site, so the resume step of this same
                // convergence trusts this fence instead of bumping
                // the epoch out from under the writes it re-admits.
                self.freshly_fenced.insert(partition);
                Ok(true)
            }
            Ok(_) | Err(_) => Ok(false),
        }
    }

    // CONSTRAINT: synchronous local work only. The shutdown fence's
    // certified teardown sum (`validate_lease_timescales`) counts these
    // releases as free; making this await an external system requires
    // growing SHUTDOWN_FENCE_BOUND.
    async fn release_partition(&self, partition: u32) -> Result<()> {
        info!(partition, "releasing partition");
        if let Some(fenced) = &self.fenced {
            fenced.release(partition);
        }
        self.inflight.unfence(partition);
        self.cache.drop_partition(partition);
        // The new owner's warming rebuilds its own marks; stale marks here
        // would only pin memory for a partition this pod no longer serves.
        self.dirty_index.clear_partition(partition);
        // Same for the lifecycle fences: the new owner's takeover scan
        // rebuilds its own.
        drop_partition_fences(&self.fences, partition, self.num_partitions);
        // The incoming owner derives versions from the changelog, which
        // is the authority these floors stood in for; carrying them would
        // only constrain a partition this pod no longer serves.
        self.emitted_versions.clear_partition(partition);
        self.freshly_fenced.remove(&partition);
        info!(partition, "partition released");
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        info!(partition, "handoff cancelled; re-admitting writes");
        self.check_authority(partition, "resume")?;
        // The cancelled handoff's target may have gotten as far as
        // acquiring the changelog fence, which leaves this pod's producer
        // epoch-stale — every write would fail as fenced until the next
        // handoff. Re-acquiring bumps the epoch back to this pod before
        // writes are re-admitted. (No acked write can predate this: the
        // target never serves before the assignment flips.)
        //
        // Unless this convergence already took the fence on its way here.
        // Warming re-admits writes as its last act, so acquiring again
        // would bump the epoch out from under everything admitted since —
        // the pod fencing its own live window, and handing the successor
        // of a genuinely moved partition an epoch nobody asked for.
        if self.freshly_fenced.contains(&partition) {
            info!(
                partition,
                "fence already taken by this convergence; not re-acquiring on resume"
            );
            self.inflight.unfence(partition);
            return Ok(());
        }
        if let Some(fenced) = &self.fenced {
            fenced
                .acquire(partition)
                .await
                .map_err(Error::invalid_state)?;
            self.check_authority_after_acquire(partition, "resume")?;
            // Mark it the same way warming does. A convergence torn down
            // between here and the point `apply` records the resume
            // retries with the partition still listed as fenced, and
            // without this mark that retry would acquire again — this
            // time bumping the epoch out from under the writes the line
            // below is about to admit.
            self.freshly_fenced.insert(partition);
            info!(partition, "changelog fence re-acquired on resume");
        }
        self.inflight.unfence(partition);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::warming::WarmingRetryPolicy;
    use common_kafka::config::KafkaConfig;

    /// `warm_partition` is exercised end-to-end in
    /// `tests/warming_integration.rs` against a mock Kafka cluster
    /// because it now consumes from a real broker. These unit tests
    /// cover the parts of `LeaderHandoffHandler` that don't require
    /// Kafka: drain semantics, release semantics, and `owns_partition`.
    fn handler() -> LeaderHandoffHandler {
        let kafka = KafkaConfig {
            kafka_producer_linger_ms: 0,
            kafka_producer_queue_mib: 50,
            kafka_message_timeout_ms: 5000,
            kafka_compression_codec: "none".to_string(),
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_producer_queue_messages: 1000,
            kafka_client_rack: String::new(),
            kafka_client_id: String::new(),
            kafka_producer_batch_size: None,
            kafka_producer_batch_num_messages: None,
            kafka_producer_enable_idempotence: None,
            kafka_producer_max_in_flight_requests_per_connection: None,
            kafka_producer_topic_metadata_refresh_interval_ms: None,
            kafka_producer_message_max_bytes: None,
            kafka_producer_sticky_partitioning_linger_ms: None,
            kafka_producer_partitioner: None,
            kafka_producer_acks: None,
            kafka_producer_retries: None,
        };
        let pools = Arc::new(WarmClientPools::new(&kafka, "test", "personhog-writer"));
        LeaderHandoffHandler::new(
            Arc::new(PartitionedCache::new(1 << 20)),
            Arc::new(InflightTracker::new()),
            Arc::new(DirtyIndex::new(1_000_000)),
            WarmingConfig {
                kafka,
                topic: "personhog_updates".to_string(),
                pod_name: "test".to_string(),
                writer_consumer_group: "personhog-writer".to_string(),
                lookback_offsets: 0,
                committed_offsets_timeout: Duration::from_secs(5),
                fetch_watermarks_timeout: Duration::from_secs(5),
                recv_timeout: Duration::from_secs(10),
                retry: WarmingRetryPolicy {
                    max_attempts: 3,
                    initial_backoff: Duration::from_millis(500),
                    max_backoff: Duration::from_secs(5),
                },
            },
            Arc::new(dashmap::DashMap::new()),
            None,
            4,
            pools,
            None,
            None,
            Arc::new(EmittedVersions::new(1_000_000)),
        )
    }

    #[tokio::test]
    async fn release_partition_drops_cache_entry() {
        let handler = handler();
        // Simulate a successful prior warm by creating the partition
        // directly. We can't call `warm_partition` here because it
        // would try to talk to Kafka.
        handler.cache.create_partition(42);
        assert!(handler.owns_partition(42));

        handler.release_partition(42).await.unwrap();
        assert!(!handler.owns_partition(42));
    }

    /// The incoming owner derives versions from the changelog, which is
    /// the authority these floors stand in for. Carrying one across a
    /// release would constrain a partition this pod no longer serves.
    #[tokio::test]
    async fn releasing_a_partition_forgets_the_versions_it_emitted() {
        let handler = handler();
        handler.cache.create_partition(3);
        let key = crate::cache::PersonCacheKey {
            team_id: 1,
            person_id: 7,
        };
        handler.emitted_versions.raise_for_test(3, key.clone(), 900);

        handler.release_partition(3).await.unwrap();

        assert_eq!(
            handler.emitted_versions.floor_for(3, &key, 5),
            5,
            "a departed owner's floor must not survive the release"
        );
    }

    #[tokio::test]
    async fn release_partition_is_idempotent_for_unknown_partition() {
        let handler = handler();
        // Releasing a partition that was never warmed must be a no-op,
        // not an error. The pod's watch loop can deliver Complete events
        // for partitions this pod never owned (e.g., during a rapid
        // assignment churn) and we shouldn't fail the protocol.
        handler.release_partition(99).await.unwrap();
        assert!(!handler.owns_partition(99));
    }

    #[tokio::test]
    async fn owns_partition_reflects_cache_state_across_lifecycle() {
        let handler = handler();
        assert!(!handler.owns_partition(1));
        handler.cache.create_partition(1);
        assert!(handler.owns_partition(1));
        handler.cache.create_partition(2);
        handler.cache.create_partition(3);
        assert!(handler.owns_partition(2));
        assert!(handler.owns_partition(3));

        handler.release_partition(2).await.unwrap();
        assert!(handler.owns_partition(1));
        assert!(!handler.owns_partition(2));
        assert!(handler.owns_partition(3));
    }

    #[tokio::test]
    async fn drain_partition_inflight_returns_immediately_when_empty() {
        let handler = handler();
        // No request handlers in flight → drain returns immediately.
        // The protocol relies on this for partitions that never
        // received traffic between Freezing and the actual drain call.
        handler.drain_partition_inflight(7).await.unwrap();
    }

    /// A fence taken while warming only licenses skipping the re-acquire
    /// for the convergence that took it. Once a handoff drains the
    /// partition it is moving, and the incoming owner can take the epoch
    /// before the handoff is cancelled — so a resume that still trusted
    /// that mark would re-admit writes onto a producer the broker has
    /// moved past, which is exactly what the re-acquire exists to stop.
    #[tokio::test]
    async fn a_handoff_drain_retires_an_earlier_convergences_fence() {
        let handler = handler();
        handler.mark_freshly_fenced_for_test(7);
        assert!(
            !handler.would_reacquire_on_resume(7),
            "the convergence that just warmed holds a current fence"
        );

        handler.drain_partition_inflight(7).await.unwrap();

        assert!(
            handler.would_reacquire_on_resume(7),
            "a resume after a handoff drain must take the fence again"
        );
    }

    /// The mark is per partition: draining one must not force an unrelated
    /// partition's resume to bump its own epoch out from under live writes.
    #[tokio::test]
    async fn a_drain_retires_only_its_own_partitions_fence() {
        let handler = handler();
        handler.mark_freshly_fenced_for_test(7);
        handler.mark_freshly_fenced_for_test(8);

        handler.drain_partition_inflight(7).await.unwrap();

        assert!(!handler.would_reacquire_on_resume(8));
    }
}
