use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use personhog_coordination::error::{Error, Result};
use personhog_coordination::pod::HandoffHandler;
use tracing::info;

use crate::cache::{DirtyIndex, PartitionedCache};
use crate::emitted::EmittedVersions;
use crate::fencing::{FenceGuard, FencedChangelogProducers};
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
    pools: Arc<WarmClientPools>,
    /// Present when broker-enforced epoch fencing is on: acquiring a
    /// partition initializes its transactional producer (fencing every
    /// predecessor), and releasing it drops the producer.
    fenced: Option<Arc<FencedChangelogProducers>>,
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
    pub fn new(
        cache: Arc<PartitionedCache>,
        inflight: Arc<InflightTracker>,
        dirty_index: Arc<DirtyIndex>,
        warming: WarmingConfig,
        pools: Arc<WarmClientPools>,
        fenced: Option<Arc<FencedChangelogProducers>>,
        emitted_versions: Arc<EmittedVersions>,
    ) -> Self {
        Self {
            cache,
            inflight,
            dirty_index,
            warming,
            pools,
            fenced,
            emitted_versions,
            freshly_fenced: Arc::new(dashmap::DashSet::new()),
        }
    }

    pub fn owns_partition(&self, partition: u32) -> bool {
        self.cache.has_partition(partition)
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
        // window nobody is waiting on. Settling that window here is what
        // makes this drain a boundary: every record this pod put in the
        // partition is committed, and below the cutoff the successor is
        // about to read, before the ack that lets the successor read at
        // all.
        //
        // The successor's `init_transactions` still aborts anything left
        // over — pinned by
        // `a_successors_init_aborts_the_predecessors_open_window` — but
        // as a backstop for the cases this cannot settle rather than as
        // the mechanism the guarantee rests on.
        if let Some(fenced) = &self.fenced {
            fenced
                .settle(partition)
                .await
                .map_err(Error::invalid_state)?;
        }
        info!(partition, "inflight drained; writes fenced");
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        info!(partition, "warming partition cache from kafka");
        // Broker-side fencing before the warm read, not after: acquiring
        // the fence bumps the producer epoch and aborts any in-flight
        // transaction from a predecessor, so every write a stale owner
        // ever committed sits below the watermark the warm is about to
        // read. Fencing after the read would leave a gap where a zombie
        // commits an acked write the warm never sees.
        let fence_guard = if let Some(fenced) = &self.fenced {
            fenced
                .acquire(partition)
                .await
                .map_err(Error::invalid_state)?;
            info!(partition, "changelog fence acquired");
            // From here the fence is held for a warm that has not
            // happened yet. If the warm fails — or never returns,
            // because the attempt was torn down by a lost lease — the
            // guard gives the epoch back rather than leaving this
            // process holding a partition it does not own.
            Some(FenceGuard::new(Arc::clone(fenced), partition))
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
        if self.freshly_fenced.remove(&partition).is_some() {
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
            pools,
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
