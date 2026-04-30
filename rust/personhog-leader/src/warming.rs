use std::sync::Arc;
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

use crate::cache::{CachedPerson, PartitionedCache, PersonCacheKey};

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
fn make_consumer(
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

/// Query the writer consumer group's committed offset for a partition.
/// Returns `None` if the writer has no commit yet for the partition
/// (typical for a freshly-created topic).
///
/// The OffsetFetch RPC inside `committed_offsets` is synchronous in rdkafka
/// and parks the calling thread for up to `timeout`. We run it on the
/// blocking pool so a slow broker can't stall the tokio runtime.
async fn fetch_writer_committed_offset(
    kafka: &KafkaConfig,
    writer_group: &str,
    topic: &str,
    partition: i32,
    timeout: Duration,
) -> CoordResult<Option<i64>> {
    let kafka = kafka.clone();
    let writer_group = writer_group.to_string();
    let topic = topic.to_string();
    tokio::task::spawn_blocking(move || {
        let consumer = make_consumer(&kafka, &writer_group)
            .map_err(|e| CoordError::invalid_state(format!("create offset query consumer: {e}")))?;
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition(&topic, partition);
        let committed = consumer
            .committed_offsets(tpl, timeout)
            .map_err(|e| CoordError::invalid_state(format!("committed_offsets for group: {e}")))?;
        Ok(committed
            .find_partition(&topic, partition)
            .and_then(|tp| match tp.offset() {
                Offset::Offset(o) => Some(o),
                _ => None,
            }))
    })
    .await
    .map_err(|e| CoordError::invalid_state(format!("offset query join: {e}")))?
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
    cache: &PartitionedCache,
    partition: u32,
) -> CoordResult<()> {
    let start = Instant::now();
    let partition_i32 = i32::try_from(partition).map_err(|_| {
        CoordError::invalid_state(format!("partition {partition} exceeds i32::MAX"))
    })?;

    // Query the writer's committed offset via a separate, short-lived client.
    // This keeps our long-lived warming consumer isolated from the writer's
    // consumer group.
    let committed_offset = with_warm_retry("committed_offset", partition, cfg.retry, || async {
        fetch_writer_committed_offset(
            &cfg.kafka,
            &cfg.writer_consumer_group,
            &cfg.topic,
            partition_i32,
            cfg.committed_offsets_timeout,
        )
        .await
    })
    .await?;

    let warming_group = format!(
        "personhog-leader-warm-{pod}-p{partition}",
        pod = cfg.pod_name
    );
    let consumer = Arc::new(
        make_consumer(&cfg.kafka, &warming_group)
            .map_err(|e| CoordError::invalid_state(format!("create warming consumer: {e}")))?,
    );

    // `fetch_watermarks` is synchronous in rdkafka and may block for the
    // full timeout. Run it on the blocking pool so retries don't park the
    // runtime thread.
    let (low, hwm) = with_warm_retry("fetch_watermarks", partition, cfg.retry, || {
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
    })
    .await?;

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

    let mut assign_tpl = TopicPartitionList::new();
    assign_tpl
        .add_partition_offset(&cfg.topic, partition_i32, Offset::Offset(start_offset))
        .map_err(|e| CoordError::invalid_state(format!("tpl add_partition_offset: {e}")))?;
    consumer
        .assign(&assign_tpl)
        .map_err(|e| CoordError::invalid_state(format!("consumer assign: {e}")))?;

    if hwm <= start_offset {
        // Empty range — install an empty partition cache. Use the
        // atomic install path so this matches the populated path's
        // publication semantics (the partition becomes observable in
        // a single dashmap insert).
        cache.install_warmed_partition(partition, std::iter::empty());
        tracing::info!(partition, hwm, start_offset, "no messages to warm in range");
        return Ok(());
    }

    // Buffer records locally and only commit them to the cache after the
    // entire range warms successfully. Any decode/IO failure mid-range
    // aborts warming with no observable cache mutation, which keeps a
    // partial cache from masking PG fallback reads.
    let mut buffered: Vec<(PersonCacheKey, CachedPerson)> = Vec::new();
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
            let properties = serde_json::from_slice(&person.properties).map_err(|e| {
                CoordError::invalid_state(format!(
                    "warm properties decode failed at offset {offset}: {e}"
                ))
            })?;
            let cached = CachedPerson {
                id: person.id,
                uuid: person.uuid,
                team_id: person.team_id,
                properties,
                created_at: person.created_at,
                version: person.version,
                is_identified: person.is_identified,
            };
            let key = PersonCacheKey {
                team_id: cached.team_id,
                person_id: cached.id,
            };
            buffered.push((key, cached));
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

    // Atomic install: the populated `PersonCache` is built first, then a
    // single `DashMap::insert` publishes it. The previous pattern
    // (`create_partition` + per-record `put` loop) created a window
    // where readers could observe `has_partition == true` while the
    // cache was still being populated, and then fall through to PG —
    // potentially returning stale values for records the writer hasn't
    // yet persisted. Atomicity here removes the dependency on the
    // protocol invariant ("no reads during Warming") for correctness.
    let count = buffered.len() as u64;
    cache.install_warmed_partition(partition, buffered);

    let elapsed = start.elapsed();
    tracing::info!(
        pod = cfg.pod_name,
        partition,
        messages = count,
        hwm,
        start_offset,
        elapsed_ms = elapsed.as_millis() as u64,
        "warmed partition from kafka"
    );
    histogram!("personhog_leader_warm_duration_ms").record(elapsed.as_secs_f64() * 1000.0);
    counter!("personhog_leader_warmed_messages_total").increment(count);

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
