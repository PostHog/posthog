use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use common_kafka::config::KafkaConfig;
use metrics::{counter, histogram};
use prost::Message as ProtoMessage;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::Message;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use tokio::time::{sleep, timeout};

use personhog_common::partitioning::partition_for_person;
use personhog_coordination::changelog::WarmSource;
use personhog_coordination::error::{Error as CoordError, Result as CoordResult};
use personhog_proto::personhog::types::v1::Person;

use crate::cache::{CachedPerson, DirtyIndex, DirtyMark, PartitionedCache, PersonCacheKey, Stream};

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
/// The consume loop is not retried and does not need to be: it rides
/// out non-fatal consumer errors in place while librdkafka handles them,
/// bounded by `recv_timeout`. A fatal client state — and a genuine
/// stall — ends it.
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
/// handler and borrowed at each warm.
#[derive(Clone)]
pub struct WarmingConfig {
    pub kafka: KafkaConfig,
    pub pod_name: String,
    /// Writer's consumer group id. We query this group's committed offset
    /// for the partition to find "everything at or after this offset has
    /// not yet been written to PG."
    pub writer_consumer_group: String,
    /// Timeout for the OffsetFetch metadata call.
    pub committed_offsets_timeout: Duration,
    /// Timeout for the per-partition `fetch_watermarks` call.
    pub fetch_watermarks_timeout: Duration,
    /// Per-message receive timeout during the consume loop.
    pub recv_timeout: Duration,
    /// Retry policy for transient metadata failures.
    pub retry: WarmingRetryPolicy,
}

/// The topic's partition count from broker metadata, for the boot check.
pub async fn changelog_partition_count(
    kafka: &KafkaConfig,
    topic: &str,
    timeout: Duration,
) -> CoordResult<u32> {
    let consumer = make_consumer(kafka, "personhog-leader-boot")
        .map_err(|e| CoordError::invalid_state(format!("create metadata client: {e}")))?;
    let topic_name = topic.to_string();
    tokio::task::spawn_blocking(move || {
        let metadata = consumer
            .fetch_metadata(Some(&topic_name), timeout)
            .map_err(|e| {
                CoordError::invalid_state(format!("fetch metadata for {topic_name}: {e}"))
            })?;
        let topic_metadata = metadata
            .topics()
            .iter()
            .find(|t| t.name() == topic_name)
            .ok_or_else(|| {
                CoordError::invalid_state(format!(
                    "topic {topic_name} is absent from broker metadata"
                ))
            })?;
        if let Some(error) = topic_metadata.error() {
            return Err(CoordError::invalid_state(format!(
                "topic {topic_name}: {error:?}"
            )));
        }
        u32::try_from(topic_metadata.partitions().len()).map_err(|_| {
            CoordError::invalid_state(format!("topic {topic_name} partition count overflow"))
        })
    })
    .await
    .map_err(|e| CoordError::invalid_state(format!("fetch metadata join: {e}")))?
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
        .set("auto.offset.reset", "earliest")
        // Only committed transactions: with fencing on, aborted windows
        // and zombie leftovers must never reach the cache. Identical
        // behavior on a topic without transactional records.
        .set("isolation.level", "read_committed")
        // A warm learns it reached the end from an empty fetch, held 500ms by default.
        .set("fetch.wait.max.ms", "10");
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
/// success, and dropped when the operation fails — a client whose
/// operation just failed is never reused, so error hygiene is structural.
/// A non-fatal error the operation rode out does not count as failure:
/// the client handled it and completed, and both the consume loop and
/// the give-back verify the client-level fatal state. None of these
/// clients ever joins the group protocol (no subscribe), so the group id
/// is broker bookkeeping, not membership: pooling clients in the
/// writer's group cannot affect the writer's rebalancing.
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
        // The unassign gate below cannot catch a fatal client —
        // librdkafka treats ops on one as successful unassigns — so the
        // contract that a dead client is never pooled is enforced here
        // by construction rather than left to the accident that
        // consumer fatals only arise from group paths these clients
        // never join.
        if let Some((code, reason)) = consumer.client().fatal_error() {
            tracing::warn!(
                pool = self.label,
                code = format!("{code:?}"),
                reason,
                "client in a fatal state; dropping instead of pooling it"
            );
            return;
        }
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
        // Create every client before connecting any: returning them as we
        // go would make the next checkout pop the client we just returned,
        // connecting one client n times and leaving the other n-1 slots to
        // be built cold on the hot path. The connects then run
        // concurrently — a deploy burst needs the pool populated in one
        // connect's time, not n of them in sequence.
        let mut clients = Vec::with_capacity(n);
        for _ in 0..n {
            let Ok(consumer) = self.checkout() else {
                break;
            };
            clients.push(consumer);
        }
        let connects: Vec<_> = clients
            .into_iter()
            .map(|consumer| {
                tokio::task::spawn_blocking(move || {
                    let ok = consumer
                        .fetch_metadata(None, Duration::from_secs(5))
                        .is_ok();
                    (consumer, ok)
                })
            })
            .collect();
        for connect in connects {
            if let Ok((consumer, true)) = connect.await {
                self.give_back(consumer);
            }
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

/// The writer commits an offset only after PG holds every record below it,
/// so a warm replays from the commit, clamped to Kafka's retention.
fn resolve_start_offset(committed: Option<i64>, earliest: i64) -> i64 {
    committed.map_or(earliest, |c| c.max(earliest))
}

/// One warm sub-span sample. The spans share the warm bucket ladder and
/// sum to slightly less than `warm_duration_ms`, whose remainder is the
/// dirty-index seeding and the cache install.
fn record_warm_span(span: &'static str, start: Instant) {
    histogram!("personhog_leader_warm_span_ms", "span" => span)
        .record(start.elapsed().as_secs_f64() * 1000.0);
}

/// Cancellation-safe cleanup for a warm in flight. The coordination loop
/// drops warms on lease loss and shutdown, and a dropped future never
/// reaches code after its await points — so the abort of the unpublished
/// build and the clearing of this partition's seeded dirty marks live in
/// `Drop`, which runs on every exit: error, panic, and cancellation.
/// Disarmed immediately before the publish, when the state stops being
/// residue and becomes the partition's serving truth.
struct WarmCleanup<'a> {
    cache: &'a PartitionedCache,
    dirty_index: &'a DirtyIndex,
    partition: u32,
    armed: bool,
}

impl Drop for WarmCleanup<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.cache.abort_warm_partition(self.partition);
            self.dirty_index.clear_partition(self.partition);
        }
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
/// Together those mean: by the time a warm runs, no producer
/// can append to this partition's Kafka log. The HWM we snapshot here
/// is therefore stable, and we can consume to a known endpoint without
/// racing producers.
async fn warm_source(
    cfg: &WarmingConfig,
    pools: &WarmClientPools,
    cache: &PartitionedCache,
    dirty_index: &DirtyIndex,
    partition: u32,
    source: &WarmSource,
    committed_offset: Option<i64>,
) -> CoordResult<u64> {
    let partition_i32 = i32::try_from(source.partition).map_err(|_| {
        CoordError::invalid_state(format!("partition {} exceeds i32::MAX", source.partition))
    })?;
    let stream = Stream {
        topic: Arc::clone(&source.topic),
        partition: source.partition,
    };

    // Arc because the watermark retry closure needs its own handle for
    // the blocking pool; sole ownership returns once the retries finish.
    // The sub-spans below decompose the warm's wall clock so a slow one
    // is attributable: client construction is lazy, so a cold client's
    // connection cost lands in the metadata span, not the checkout.
    let span_start = Instant::now();
    let consumer = Arc::new(pools.warming.checkout()?);
    record_warm_span("checkout", span_start);

    // `fetch_watermarks` is synchronous in rdkafka and may block for the
    // full timeout, so it runs on the blocking pool.
    let watermarks_fut = with_warm_retry("fetch_watermarks", partition, cfg.retry, || {
        let consumer = Arc::clone(&consumer);
        let topic = Arc::clone(&source.topic);
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
    let span_start = Instant::now();
    // A failed watermark call leaves this consumer doubtful, so the pool's
    // drop-doubtful-clients contract applies: it is not given back.
    let (low, hwm) = watermarks_fut.await?;
    record_warm_span("metadata", span_start);

    let start_offset = resolve_start_offset(committed_offset, low);

    tracing::info!(
        partition,
        topic = %source.topic,
        source_partition = source.partition,
        writer_group = cfg.writer_consumer_group,
        committed = ?committed_offset,
        earliest = low,
        hwm,
        start_offset,
        "computed warming range"
    );

    if hwm <= start_offset {
        tracing::info!(partition, topic = %source.topic, source_partition = source.partition, hwm, start_offset, "no messages to warm in range");
        if let Ok(consumer) = Arc::try_unwrap(consumer) {
            pools.warming.give_back(consumer);
        }
        return Ok(0);
    }

    let span_start = Instant::now();
    let mut assign_tpl = TopicPartitionList::new();
    assign_tpl
        .add_partition_offset(&source.topic, partition_i32, Offset::Offset(start_offset))
        .map_err(|e| CoordError::invalid_state(format!("tpl add_partition_offset: {e}")))?;
    consumer
        .assign(&assign_tpl)
        .map_err(|e| CoordError::invalid_state(format!("consumer assign: {e}")))?;

    let mut consumed: u64 = 0;
    let mut last_offset: i64 = -1;

    // A transactionally-produced range can end in control records
    // (commit/abort markers) that `recv` never delivers, so reaching the
    // HWM is only observable through the fetch position advancing past
    // them. Poll in short slices and consult the position when quiet;
    // `cfg.recv_timeout` still bounds the total quiet time before the
    // warm is declared stalled.
    let poll_slice = Duration::from_millis(100).min(cfg.recv_timeout);
    let mut quiet_since = Instant::now();

    // `return` inside this block exits the block, not the function: a
    // failure propagates through `?` below and the guard cleans up.
    let consume_result: CoordResult<()> = async {
        loop {
        let msg = match timeout(poll_slice, consumer.recv()).await {
            Ok(Ok(m)) => m,
            // A non-fatal consumer error means librdkafka is handling it:
            // a connection blip resolves by reconnecting with the fetch
            // position intact, and the stream never terminates, so the
            // answer is to keep polling — as the fleet's streaming
            // consumers do. The per-event fatal split is not the whole
            // fatality story, so the client-level fatal state (an
            // unrecoverable idempotence or authentication failure) is
            // checked first: it survives even when the event that set it
            // was consumed, and a dead client must not be re-polled while
            // reporting progress.
            //
            // The accepted trade, stated for the record: librdkafka also
            // reports record-skipping through this same non-fatal channel
            // — an unreadable message set is discarded and the fetch
            // position advances past it — and riding one out publishes a
            // cache missing the skipped records. Today that requires
            // broker-side corruption of bytes no consumer could read
            // anyway, or a record format newer than this client, which
            // does not exist. Stop-class errors (an ACL revocation, a
            // deleted topic) also ride, costing the stall budget and a
            // generic stall error instead of an immediate named one; the
            // code survives in the counter label and the warn line.
            Ok(Err(KafkaError::MessageConsumption(code))) => {
                if let Some((fatal_code, reason)) = consumer.client().fatal_error() {
                    return Err(CoordError::invalid_state(format!(
                        "warm consumer entered a fatal state ({fatal_code:?}): {reason}"
                    )));
                }
                // An error is not progress: the stall budget keeps
                // running, so errors arriving faster than the quiet arm
                // can observe still end the warm on time.
                if quiet_since.elapsed() >= cfg.recv_timeout {
                    return Err(CoordError::invalid_state(format!(
                        "warm stalled on repeated consumer errors (last: {code:?}); \
                         consumed {consumed} msgs, last_offset={last_offset}, hwm={hwm}",
                    )));
                }
                counter!(
                    // Debug renders the bare variant ("BrokerTransportFailure");
                    // Display appends librdkafka's prose, which makes a
                    // poor label value.
                    "personhog_leader_warm_transient_errors_total",
                    "code" => format!("{code:?}")
                )
                .increment(1);
                tracing::warn!(
                    partition,
                    error = %code,
                    "non-fatal consumer error during warm; riding it out"
                );
                // A fast-failing recv would otherwise spin this loop hot
                // for the whole stall budget.
                sleep(poll_slice).await;
                continue;
            }
            Ok(Err(e)) => {
                return Err(CoordError::invalid_state(format!("warm recv: {e}")));
            }
            Err(_) => {
                let position_reached = consumer
                    .position()
                    .map_err(|e| CoordError::invalid_state(format!("warm position: {e}")))?
                    .find_partition(&source.topic, partition_i32)
                    .is_some_and(|elem| matches!(elem.offset(), Offset::Offset(p) if p >= hwm));
                if position_reached {
                    break;
                }
                if quiet_since.elapsed() >= cfg.recv_timeout {
                    return Err(CoordError::invalid_state(format!(
                        "warm timeout; consumed {consumed} msgs, last_offset={last_offset}, hwm={hwm}",
                    )));
                }
                continue;
            }
        };
        quiet_since = Instant::now();

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
            // An old partition also holds keys that now belong elsewhere.
            if let Some(keep) = &source.keep {
                if partition_for_person(cached.team_id, cached.id, keep.modulus) != keep.target {
                    if offset + 1 >= hwm {
                        break;
                    }
                    continue;
                }
            }
            consumed += 1;
            // PG may not hold a replayed record yet: mark before insert, so a
            // miss after an eviction recovers from the changelog, not PG.
            dirty_index.mark(
                key.clone(),
                DirtyMark {
                    version: cached.version,
                    offset,
                    partition,
                    stream: stream.clone(),
                    is_deleted: cached.is_deleted,
                },
            );
            cache.warm_put(partition, key, cached);
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
        Ok(())
    }
    .await;
    consume_result?;

    record_warm_span("consume", span_start);

    // Every error path above dropped the consumer: a client that just failed is not pool material.
    if let Ok(consumer) = Arc::try_unwrap(consumer) {
        pools.warming.give_back(consumer);
    }

    Ok(consumed)
}

/// Every source is sealed or fenced, so each replay runs to a known end.
pub async fn warm_from_sources(
    cfg: &WarmingConfig,
    pools: &WarmClientPools,
    cache: &PartitionedCache,
    dirty_index: &DirtyIndex,
    partition: u32,
    sources: &[WarmSource],
) -> CoordResult<()> {
    let start = Instant::now();
    // Every writer position is read before any replay: a live position read
    // after the writer left an old generation would skip records newer than
    // that generation's marked tail.
    let mut committed = Vec::with_capacity(sources.len());
    for source in sources {
        committed.push(
            with_warm_retry("committed_offset", partition, cfg.retry, || async {
                fetch_writer_committed_offset(
                    &pools.offsets,
                    &source.topic,
                    source.partition,
                    cfg.committed_offsets_timeout,
                )
                .await
            })
            .await?,
        );
    }
    // The build is invisible and evicts under the serving budget until the publish.
    cache.begin_warm_partition(partition);
    let mut cleanup = WarmCleanup {
        cache,
        dirty_index,
        partition,
        armed: true,
    };
    let mut consumed = 0u64;
    for (source, committed) in sources.iter().zip(committed) {
        consumed +=
            warm_source(cfg, pools, cache, dirty_index, partition, source, committed).await?;
    }

    let resident_bytes = cache.warm_usage_bytes(partition) as u64;
    // One insert publishes the whole build, and no await sits between the disarm and it.
    cleanup.armed = false;
    cache.publish_warmed_partition(partition);

    let elapsed = start.elapsed();
    tracing::info!(
        pod = cfg.pod_name,
        partition,
        sources = sources.len(),
        messages = consumed,
        resident_bytes,
        elapsed_ms = elapsed.as_millis() as u64,
        "warmed partition from kafka"
    );
    histogram!("personhog_leader_warm_duration_ms").record(elapsed.as_secs_f64() * 1000.0);
    counter!("personhog_leader_warmed_messages_total").increment(consumed);
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

    fn warm_test_person() -> CachedPerson {
        CachedPerson {
            id: 42,
            uuid: "00000000-0000-0000-0000-000000000042".to_string(),
            team_id: 1,
            properties: b"{}".to_vec(),
            created_at: 0,
            version: 1,
            is_identified: false,
            is_deleted: false,
            last_seen_at: None,
        }
    }

    /// The coordination loop cancels a warm by dropping its future, which
    /// never reaches code after an await point — so the cleanup lives in
    /// `WarmCleanup::drop`, and this pins that it runs. A surviving build
    /// pins memory for a partition this pod never serves; a surviving mark
    /// outlives re-acquisition, because the next warm only overwrites
    /// marks past the writer's committed offset by then, and redirects a
    /// later cache miss to a superseded changelog offset.
    #[test]
    fn dropping_an_armed_cleanup_clears_the_build_and_its_marks() {
        let cache = PartitionedCache::new(1 << 20);
        let dirty_index = DirtyIndex::new(1_000);
        let key = PersonCacheKey {
            team_id: 1,
            person_id: 42,
        };

        cache.begin_warm_partition(0);
        {
            let _cleanup = WarmCleanup {
                cache: &cache,
                dirty_index: &dirty_index,
                partition: 0,
                armed: true,
            };
            dirty_index.mark(
                key.clone(),
                DirtyMark {
                    version: 1,
                    offset: 7,
                    partition: 0,
                    stream: Stream {
                        topic: Arc::from("personhog_updates"),
                        partition: 0,
                    },
                    is_deleted: false,
                },
            );
            cache.warm_put(0, key.clone(), warm_test_person());
        }

        assert!(
            dirty_index.get(&key).is_none(),
            "a cancelled warm must clear the marks it seeded"
        );
        assert_eq!(
            cache.usage_bytes(),
            0,
            "a cancelled warm must leave no build in flight"
        );
        assert!(!cache.has_partition(0), "nothing may have published");
    }

    /// The mirror: once the warm publishes, the marks and the cache are
    /// the partition's serving state rather than warm residue, so the
    /// disarmed guard must leave both alone.
    #[test]
    fn dropping_a_disarmed_cleanup_leaves_the_published_partition_alone() {
        let cache = PartitionedCache::new(1 << 20);
        let dirty_index = DirtyIndex::new(1_000);
        let key = PersonCacheKey {
            team_id: 1,
            person_id: 42,
        };

        cache.begin_warm_partition(0);
        {
            let mut cleanup = WarmCleanup {
                cache: &cache,
                dirty_index: &dirty_index,
                partition: 0,
                armed: true,
            };
            dirty_index.mark(
                key.clone(),
                DirtyMark {
                    version: 1,
                    offset: 7,
                    partition: 0,
                    stream: Stream {
                        topic: Arc::from("personhog_updates"),
                        partition: 0,
                    },
                    is_deleted: false,
                },
            );
            cache.warm_put(0, key.clone(), warm_test_person());
            cleanup.armed = false;
            cache.publish_warmed_partition(0);
        }

        assert!(
            dirty_index.get(&key).is_some(),
            "a published partition keeps its marks"
        );
        assert!(cache.has_partition(0), "the partition stays published");
        assert!(matches!(
            cache.get(0, &key),
            crate::cache::CacheLookup::Found(_)
        ));
    }

    #[test]
    fn resolve_starts_at_the_commit_clamped_to_earliest() {
        assert_eq!(resolve_start_offset(Some(500), 0), 500);
        assert_eq!(resolve_start_offset(Some(100), 200), 200);
        assert_eq!(resolve_start_offset(None, 42), 42);
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
