use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use common_kafka::config::KafkaConfig;
use metrics::{counter, histogram};
use prost::Message as ProtoMessage;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use tokio::time::timeout;

use personhog_coordination::error::{Error as CoordError, Result as CoordResult};
use personhog_proto::personhog::types::v1::Person;

use crate::cache::{CachedPerson, DirtyIndex, DirtyMark, PartitionedCache, PersonCacheKey};

/// Retry policy for transient warming-metadata failures.
#[derive(Clone, Copy)]
pub struct WarmingRetryPolicy {
    pub max_attempts: u32,
    pub initial_backoff: Duration,
    pub max_backoff: Duration,
}

/// Retry a fallible warming step with exponential backoff. Used for the
/// metadata calls that talk to Kafka brokers (fetch watermarks, committed
/// offsets) so a single transient network blip doesn't cycle the pod.
///
/// The consume loop itself is not retried — it holds partial progress and
/// re-seeking is its own concern; leave to a follow-up if we see flakes.
async fn with_warm_retry<T, F, Fut>(
    stage: &str,
    partition: u32,
    policy: WarmingRetryPolicy,
    mut f: F,
) -> CoordResult<T>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = CoordResult<T>>,
{
    // `max_attempts = 0` would make the loop body never run and the
    // trailing `unreachable!` panic the warming task. Clamp to at least
    // one so a misconfigured env var still produces a single attempt
    // and a real error on failure rather than a panic. `debug_assert`
    // surfaces the misconfiguration during development.
    debug_assert!(
        policy.max_attempts >= 1,
        "warming retry max_attempts must be >= 1; got {}",
        policy.max_attempts,
    );
    let max_attempts = policy.max_attempts.max(1);
    let mut backoff = policy.initial_backoff;
    for attempt in 1..=max_attempts {
        match f().await {
            Ok(v) => return Ok(v),
            Err(e) if attempt == max_attempts => {
                counter!(
                    "personhog_leader_warm_retries_exhausted_total",
                    "stage" => stage.to_string()
                )
                .increment(1);
                return Err(e);
            }
            Err(e) => {
                tracing::warn!(
                    partition,
                    attempt,
                    stage,
                    error = %e,
                    backoff_ms = backoff.as_millis() as u64,
                    "warming step failed, retrying"
                );
                counter!(
                    "personhog_leader_warm_retries_total",
                    "stage" => stage.to_string()
                )
                .increment(1);
                tokio::time::sleep(backoff).await;
                backoff = (backoff * 2).min(policy.max_backoff);
            }
        }
    }
    unreachable!("the last iteration returns either Ok or Err explicitly")
}

/// Configuration for the warming pipeline. Owned by the leader handoff
/// handler and borrowed at each `warm_from_kafka` call.
#[derive(Clone)]
pub struct WarmingConfig {
    pub kafka: KafkaConfig,
    pub topic: String,
    pub pod_name: String,
    /// Writer's consumer group id. We query this group's committed offset
    /// for the partition to find "everything at or after this offset has
    /// not yet been written to PG."
    pub writer_consumer_group: String,
    /// Number of offsets to rewind past the writer's committed offset as a
    /// safety margin. Bounded by Kafka's earliest-available offset.
    pub lookback_offsets: i64,
    /// Timeout for the OffsetFetch metadata call.
    pub committed_offsets_timeout: Duration,
    /// Timeout for the per-partition `fetch_watermarks` call.
    pub fetch_watermarks_timeout: Duration,
    /// Per-message receive timeout during the consume loop.
    pub recv_timeout: Duration,
    /// Retry policy for transient metadata failures.
    pub retry: WarmingRetryPolicy,
}

/// Build a consumer used by warming. Auto-commit and auto-offset-store are
/// disabled so this is safe to instantiate with any group id — including
/// the writer's, where mutating stored offsets would corrupt the writer's
/// durable-progress marker. Two callers reuse it: the warming consume loop
/// (which seeks explicitly per partition) and a short-lived OffsetFetch
/// query against the writer's group (which never subscribes or consumes).
pub(crate) fn make_consumer(
    kafka: &KafkaConfig,
    group_id: &str,
) -> Result<StreamConsumer, rdkafka::error::KafkaError> {
    let mut cfg = ClientConfig::new();
    cfg.set("bootstrap.servers", &kafka.kafka_hosts)
        .set("group.id", group_id)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .set("auto.offset.reset", "earliest");
    if kafka.kafka_tls {
        cfg.set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }
    if !kafka.kafka_client_rack.is_empty() {
        cfg.set("client.rack", &kafka.kafka_client_rack);
    }
    cfg.create()
}

/// A checkout stack of assign-only Kafka clients sharing one group id.
/// Clients are checked out for the duration of one operation, returned on
/// success, and dropped on error — a client that just failed is never
/// reused, so error hygiene is structural. None of these clients ever
/// joins the group protocol (no subscribe), so the group id is broker
/// bookkeeping, not membership: pooling clients in the writer's group
/// cannot affect the writer's rebalancing.
///
/// The pool exists because client construction is the dominant cost of
/// the operations it serves: a fresh consumer pays connection setup,
/// metadata, and coordinator discovery before its one round-trip. Warms
/// paid that twice per partition; the dirty-index prune paid it every
/// tick.
pub struct ConsumerPool {
    kafka: KafkaConfig,
    group_id: String,
    /// Metric label; also names the pool in logs.
    label: &'static str,
    stack: StdMutex<Vec<StreamConsumer>>,
    created: AtomicU64,
}

impl ConsumerPool {
    pub fn new(kafka: KafkaConfig, group_id: String, label: &'static str) -> Self {
        Self {
            kafka,
            group_id,
            label,
            stack: StdMutex::new(Vec::new()),
            created: AtomicU64::new(0),
        }
    }

    /// Pop a pooled client or create a fresh one.
    pub fn checkout(&self) -> CoordResult<StreamConsumer> {
        if let Some(consumer) = self.stack.lock().unwrap().pop() {
            return Ok(consumer);
        }
        self.created.fetch_add(1, Ordering::Relaxed);
        counter!(
            "personhog_leader_warm_clients_created_total",
            "pool" => self.label
        )
        .increment(1);
        make_consumer(&self.kafka, &self.group_id)
            .map_err(|e| CoordError::invalid_state(format!("create {} client: {e}", self.label)))
    }

    /// Return a client after a successful operation. The assignment is
    /// cleared so the next checkout starts from a clean slate; clearing
    /// an unassigned client is a harmless no-op. A client whose
    /// assignment cannot be cleared is dropped instead of pooled — the
    /// pool's contract is that doubtful clients are never reused — with
    /// the failure logged so a systematic cleanup problem surfaces as a
    /// visible signal rather than silent churn.
    pub fn give_back(&self, consumer: StreamConsumer) {
        if let Err(e) = consumer.unassign() {
            tracing::warn!(
                pool = self.label,
                error = %e,
                "unassign failed; dropping client instead of pooling it"
            );
            return;
        }
        self.stack.lock().unwrap().push(consumer);
    }

    /// Total clients ever created — flat across operations when reuse
    /// works; grows per operation when it does not.
    pub fn created_count(&self) -> u64 {
        self.created.load(Ordering::Relaxed)
    }

    /// Eagerly create `n` clients and open their broker connections
    /// (rdkafka connects lazily, so creation alone leaves cold sockets).
    /// Best-effort: warms cluster in deploy bursts, and a failure here
    /// only means the first operations pay the setup they would have
    /// paid anyway.
    pub async fn warm_up(&self, n: usize) {
        // Hold every connected client outside the pool until the end:
        // returning them as we go would make the next checkout pop the
        // client we just returned, connecting one client n times and
        // leaving the other n-1 slots to be built cold on the hot path.
        let mut connected = Vec::with_capacity(n);
        for _ in 0..n {
            let Ok(consumer) = self.checkout() else {
                break;
            };
            let timeout = Duration::from_secs(5);
            let outcome = tokio::task::spawn_blocking(move || {
                let ok = consumer.fetch_metadata(None, timeout).is_ok();
                (consumer, ok)
            })
            .await;
            match outcome {
                Ok((consumer, true)) => connected.push(consumer),
                _ => break,
            }
        }
        for consumer in connected {
            self.give_back(consumer);
        }
    }
}

/// The two client pools the warm path and the dirty-index prune share.
/// Separate pools because a client's group id is fixed at construction:
/// offset queries must carry the writer's group id to OffsetFetch its
/// committed offsets, while warming consumers carry their own.
pub struct WarmClientPools {
    pub offsets: ConsumerPool,
    pub warming: ConsumerPool,
}

impl WarmClientPools {
    pub fn new(kafka: &KafkaConfig, pod_name: &str, writer_group: &str) -> Self {
        Self {
            offsets: ConsumerPool::new(kafka.clone(), writer_group.to_string(), "offsets"),
            warming: ConsumerPool::new(
                kafka.clone(),
                format!("personhog-leader-warm-{pod_name}"),
                "warming",
            ),
        }
    }
}

/// Query the writer consumer group's committed offset for a partition.
/// Returns `None` if the writer has no commit yet for the partition
/// (typical for a freshly-created topic).
async fn fetch_writer_committed_offset(
    pool: &ConsumerPool,
    topic: &str,
    partition: u32,
    timeout: Duration,
) -> CoordResult<Option<i64>> {
    let offsets = fetch_writer_committed_offsets(pool, topic, &[partition], timeout).await?;
    Ok(offsets.get(&partition).copied())
}

/// Query the writer consumer group's committed offsets for many partitions
/// in one OffsetFetch round-trip, with one short-lived consumer for the
/// whole batch. Partitions without a commit are absent from the result.
/// The batch shape suits the dirty-index prune loop, which polls every
/// owned partition on a cadence — per-partition consumers would be
/// constant churn.
///
/// The OffsetFetch RPC inside `committed_offsets` is synchronous in rdkafka
/// and parks the calling thread for up to `timeout`. We run it on the
/// blocking pool so a slow broker can't stall the tokio runtime.
pub async fn fetch_writer_committed_offsets(
    pool: &ConsumerPool,
    topic: &str,
    partitions: &[u32],
    timeout: Duration,
) -> CoordResult<HashMap<u32, i64>> {
    if partitions.is_empty() {
        return Ok(HashMap::new());
    }
    let consumer = pool.checkout()?;
    let topic = topic.to_string();
    let partitions = partitions.to_vec();
    let (consumer, result) = tokio::task::spawn_blocking(move || {
        let mut tpl = TopicPartitionList::new();
        for partition in &partitions {
            tpl.add_partition(&topic, *partition as i32);
        }
        let result = consumer
            .committed_offsets(tpl, timeout)
            .map_err(|e| CoordError::invalid_state(format!("committed_offsets for group: {e}")))
            .map(|committed| {
                let mut offsets = HashMap::new();
                for partition in partitions {
                    if let Some(Offset::Offset(offset)) = committed
                        .find_partition(&topic, partition as i32)
                        .map(|tp| tp.offset())
                    {
                        offsets.insert(partition, offset);
                    }
                }
                offsets
            });
        (consumer, result)
    })
    .await
    .map_err(|e| CoordError::invalid_state(format!("offset query join: {e}")))?;
    if result.is_ok() {
        pool.give_back(consumer);
    }
    result
}

/// Decide where to start consuming for a partition.
///
/// The writer's committed offset is the authoritative "everything up to
/// here is durable in PG" marker. Messages at or after it need to be warmed
/// into the leader's cache — otherwise a cache miss for a key in that
/// range would fall through to PG and return a stale value (PG hasn't seen
/// the update yet).
///
/// We rewind an extra `lookback` offsets as a safety margin against races
/// between the writer's commit and our read of it, and clamp to the
/// earliest available offset so we don't seek past Kafka's retention.
fn resolve_start_offset(committed: Option<i64>, earliest: i64, lookback: i64) -> i64 {
    let lookback = lookback.max(0);
    match committed {
        Some(c) => (c - lookback).max(earliest),
        None => earliest,
    }
}

/// Populate the cache from Kafka for a single partition.
///
/// Invariants at call time (enforced by the handoff protocol). The
/// coordinator only advances to `Warming` once two predecessor phases
/// have closed:
///
///   * `Freezing → Draining`: every router has acked freeze and stopped
///     forwarding to the old owner.
///   * `Draining → Warming`: the old owner has drained its in-flight
///     request handlers and written `PodDrainedAck`. Because the leader's
///     produce path awaits the Kafka delivery future before returning,
///     "no in-flight" implies "every acked write is durable in Kafka."
///
/// Together those mean: by the time `warm_from_kafka` runs, no producer
/// can append to this partition's Kafka log. The HWM we snapshot here
/// is therefore stable, and we can consume to a known endpoint without
/// racing producers.
pub async fn warm_from_kafka(
    cfg: &WarmingConfig,
    pools: &WarmClientPools,
    cache: &PartitionedCache,
    dirty_index: &DirtyIndex,
    partition: u32,
) -> CoordResult<()> {
    let start = Instant::now();
    let partition_i32 = i32::try_from(partition).map_err(|_| {
        CoordError::invalid_state(format!("partition {partition} exceeds i32::MAX"))
    })?;

    // Arc because the watermark retry closure needs its own handle for
    // the blocking pool; sole ownership returns once the retries finish.
    let consumer = Arc::new(pools.warming.checkout()?);

    // The two offset queries are independent — the writer's committed
    // position comes from the offsets pool, the watermarks from this
    // consumer — so they run concurrently; each keeps its own retry
    // policy. The committed query uses a separate, short-lived client to
    // keep the long-lived warming consumer isolated from the writer's
    // consumer group. `fetch_watermarks` is synchronous in rdkafka and
    // may block for the full timeout, so it runs on the blocking pool.
    let committed_fut = with_warm_retry("committed_offset", partition, cfg.retry, || async {
        fetch_writer_committed_offset(
            &pools.offsets,
            &cfg.topic,
            partition,
            cfg.committed_offsets_timeout,
        )
        .await
    });
    let watermarks_fut = with_warm_retry("fetch_watermarks", partition, cfg.retry, || {
        let consumer = Arc::clone(&consumer);
        let topic = cfg.topic.clone();
        let timeout = cfg.fetch_watermarks_timeout;
        async move {
            tokio::task::spawn_blocking(move || {
                consumer
                    .fetch_watermarks(&topic, partition_i32, timeout)
                    .map_err(|e| CoordError::invalid_state(format!("fetch watermarks: {e}")))
            })
            .await
            .map_err(|e| CoordError::invalid_state(format!("fetch_watermarks join: {e}")))?
        }
    });
    let (committed_res, watermarks_res) = tokio::join!(committed_fut, watermarks_fut);
    let (low, hwm) = match watermarks_res {
        Ok(marks) => marks,
        // The watermark call failed on this consumer, so the pool's
        // drop-doubtful-clients contract applies: fall through without
        // giving it back.
        Err(e) => return Err(e),
    };
    let committed_offset = match committed_res {
        Ok(offset) => offset,
        Err(e) => {
            // The committed-offset query runs on the offsets pool's
            // client; this consumer did nothing and is sound. Returning
            // it keeps reconcile-driven warm retries from rebuilding a
            // Kafka client per attempt.
            if let Ok(consumer) = Arc::try_unwrap(consumer) {
                pools.warming.give_back(consumer);
            }
            return Err(e);
        }
    };

    let start_offset = resolve_start_offset(committed_offset, low, cfg.lookback_offsets);

    tracing::info!(
        partition,
        writer_group = cfg.writer_consumer_group,
        committed = ?committed_offset,
        earliest = low,
        hwm,
        lookback = cfg.lookback_offsets,
        start_offset,
        "computed warming range"
    );

    if hwm <= start_offset {
        // Empty range — install an empty partition cache. Use the
        // atomic install path so this matches the populated path's
        // publication semantics (the partition becomes observable in
        // a single dashmap insert). The consumer never got assigned, so
        // it goes straight back to the pool.
        cache.install_warmed_partition(partition, std::iter::empty());
        tracing::info!(partition, hwm, start_offset, "no messages to warm in range");
        if let Ok(consumer) = Arc::try_unwrap(consumer) {
            pools.warming.give_back(consumer);
        }
        return Ok(());
    }

    let mut assign_tpl = TopicPartitionList::new();
    assign_tpl
        .add_partition_offset(&cfg.topic, partition_i32, Offset::Offset(start_offset))
        .map_err(|e| CoordError::invalid_state(format!("tpl add_partition_offset: {e}")))?;
    consumer
        .assign(&assign_tpl)
        .map_err(|e| CoordError::invalid_state(format!("consumer assign: {e}")))?;

    // Buffer records locally and only commit them to the cache after the
    // entire range warms successfully. Any decode/IO failure mid-range
    // aborts warming with no observable cache mutation, which keeps a
    // partial cache from masking PG fallback reads.
    let mut buffered: Vec<(PersonCacheKey, CachedPerson, i64)> = Vec::new();
    let mut last_offset: i64 = -1;

    loop {
        let msg = match timeout(cfg.recv_timeout, consumer.recv()).await {
            Ok(Ok(m)) => m,
            Ok(Err(e)) => {
                return Err(CoordError::invalid_state(format!("warm recv: {e}")));
            }
            Err(_) => {
                return Err(CoordError::invalid_state(format!(
                    "warm timeout; consumed {count} msgs, last_offset={last_offset}, hwm={hwm}",
                    count = buffered.len()
                )));
            }
        };

        let offset = msg.offset();
        last_offset = offset;

        if let Some(payload) = msg.payload() {
            let person = <Person as ProtoMessage>::decode(payload).map_err(|e| {
                CoordError::invalid_state(format!("warm decode failed at offset {offset}: {e}"))
            })?;
            let cached = CachedPerson::try_from(person).map_err(|e| {
                CoordError::invalid_state(format!(
                    "warm properties decode failed at offset {offset}: {e}"
                ))
            })?;
            let key = PersonCacheKey {
                team_id: cached.team_id,
                person_id: cached.id,
            };
            buffered.push((key, cached, offset));
        } else {
            // The writer never produces null-payload (tombstone) records
            // to `personhog_updates` today. If one ever appears it would
            // semantically represent a deletion, but the warming pipeline
            // has no concept of evictions — so we silently skip and
            // surface the occurrence via metrics + logs so an operator
            // notices if this assumption ever stops holding.
            counter!("personhog_leader_warm_tombstones_skipped_total").increment(1);
            tracing::warn!(
                partition,
                offset,
                "skipped null-payload (tombstone) record; the writer is not expected to produce these"
            );
        }

        // HWM is exclusive — it's one past the last offset present.
        if offset + 1 >= hwm {
            break;
        }
    }

    // Records at or above the writer's committed offset are not yet in PG:
    // seed the dirty index so that, if the cache later evicts them, a miss
    // recovers from the changelog instead of trusting a stale PG row. With
    // no committed offset the writer has applied nothing, so every record
    // is marked. Seeding happens before the install publishes the
    // partition, so no request can observe the cache without the marks.
    let mut seeded = 0u64;
    for (key, cached, offset) in &buffered {
        if committed_offset.is_none_or(|committed| *offset >= committed) {
            dirty_index.mark(
                key.clone(),
                DirtyMark {
                    version: cached.version,
                    offset: *offset,
                    partition,
                },
            );
            seeded += 1;
        }
    }

    // Atomic install: the populated `PersonCache` is built first, then a
    // single `DashMap::insert` publishes it. The previous pattern
    // (`create_partition` + per-record `put` loop) created a window
    // where readers could observe `has_partition == true` while the
    // cache was still being populated, and then fall through to PG —
    // potentially returning stale values for records the writer hasn't
    // yet persisted. Atomicity here removes the dependency on the
    // protocol invariant ("no reads during Warming") for correctness.
    let count = buffered.len() as u64;
    cache.install_warmed_partition(
        partition,
        buffered.into_iter().map(|(key, cached, _)| (key, cached)),
    );

    let elapsed = start.elapsed();
    tracing::info!(
        pod = cfg.pod_name,
        partition,
        messages = count,
        dirty_seeded = seeded,
        hwm,
        start_offset,
        elapsed_ms = elapsed.as_millis() as u64,
        "warmed partition from kafka"
    );
    histogram!("personhog_leader_warm_duration_ms").record(elapsed.as_secs_f64() * 1000.0);
    counter!("personhog_leader_warmed_messages_total").increment(count);

    // Every error path above dropped the consumer instead of returning
    // it — a client that just failed is not pool material. Failing to
    // unwrap the Arc would only mean the same disposition.
    if let Ok(consumer) = Arc::try_unwrap(consumer) {
        pools.warming.give_back(consumer);
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;

    const TEST_RETRY_POLICY: WarmingRetryPolicy = WarmingRetryPolicy {
        max_attempts: 3,
        initial_backoff: Duration::from_millis(500),
        max_backoff: Duration::from_secs(5),
    };

    #[test]
    fn resolve_uses_committed_minus_lookback() {
        assert_eq!(resolve_start_offset(Some(500), 0, 100), 400);
    }

    #[test]
    fn resolve_clamps_to_earliest() {
        // Lookback would take us to 50, but earliest is 200.
        assert_eq!(resolve_start_offset(Some(100), 200, 50), 200);
    }

    #[test]
    fn resolve_falls_back_to_earliest_when_no_commit() {
        assert_eq!(resolve_start_offset(None, 42, 100), 42);
    }

    #[test]
    fn resolve_treats_negative_lookback_as_zero() {
        assert_eq!(resolve_start_offset(Some(500), 0, -10), 500);
    }

    #[test]
    fn resolve_handles_zero_lookback() {
        assert_eq!(resolve_start_offset(Some(500), 0, 0), 500);
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn retry_succeeds_on_second_attempt() {
        use std::sync::atomic::{AtomicU32, Ordering};
        let attempts = Arc::new(AtomicU32::new(0));
        let a = Arc::clone(&attempts);
        let result: CoordResult<&'static str> =
            with_warm_retry("test", 0, TEST_RETRY_POLICY, || {
                let a = Arc::clone(&a);
                async move {
                    let n = a.fetch_add(1, Ordering::AcqRel) + 1;
                    if n == 1 {
                        Err(CoordError::invalid_state("first fails".to_string()))
                    } else {
                        Ok("second succeeds")
                    }
                }
            })
            .await;
        assert_eq!(result.unwrap(), "second succeeds");
        assert_eq!(attempts.load(Ordering::Acquire), 2);
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn retry_exhausts_and_returns_last_error() {
        use std::sync::atomic::{AtomicU32, Ordering};
        let attempts = Arc::new(AtomicU32::new(0));
        let a = Arc::clone(&attempts);
        let result: CoordResult<()> = with_warm_retry("test", 0, TEST_RETRY_POLICY, || {
            let a = Arc::clone(&a);
            async move {
                a.fetch_add(1, Ordering::AcqRel);
                Err(CoordError::invalid_state("always fails".to_string()))
            }
        })
        .await;
        assert!(result.is_err());
        assert_eq!(
            attempts.load(Ordering::Acquire),
            TEST_RETRY_POLICY.max_attempts
        );
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn retry_returns_immediately_on_success() {
        use std::sync::atomic::{AtomicU32, Ordering};
        let attempts = Arc::new(AtomicU32::new(0));
        let a = Arc::clone(&attempts);
        let result: CoordResult<()> = with_warm_retry("test", 0, TEST_RETRY_POLICY, || {
            let a = Arc::clone(&a);
            async move {
                a.fetch_add(1, Ordering::AcqRel);
                Ok(())
            }
        })
        .await;
        assert!(result.is_ok());
        assert_eq!(attempts.load(Ordering::Acquire), 1);
    }

    /// `max_attempts = 0` is meaningless (would mean "never try") but
    /// could arrive via a misconfigured env var. Clamp to 1 instead of
    /// panicking via the trailing `unreachable!`. Build in release mode
    /// to skip the `debug_assert` and exercise the runtime clamp.
    #[tokio::test(flavor = "current_thread", start_paused = true)]
    #[cfg(not(debug_assertions))]
    async fn retry_clamps_zero_max_attempts_to_one() {
        use std::sync::atomic::{AtomicU32, Ordering};
        let attempts = Arc::new(AtomicU32::new(0));
        let a = Arc::clone(&attempts);
        let zero_policy = WarmingRetryPolicy {
            max_attempts: 0,
            initial_backoff: Duration::from_millis(1),
            max_backoff: Duration::from_millis(1),
        };
        let result: CoordResult<()> = with_warm_retry("test", 0, zero_policy, || {
            let a = Arc::clone(&a);
            async move {
                a.fetch_add(1, Ordering::AcqRel);
                Err(CoordError::invalid_state("always fails".to_string()))
            }
        })
        .await;
        assert!(result.is_err(), "must produce an Err, not panic");
        assert_eq!(
            attempts.load(Ordering::Acquire),
            1,
            "clamped to a single attempt"
        );
    }
}
