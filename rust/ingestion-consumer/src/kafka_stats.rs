//! Export librdkafka's internal statistics as Prometheus gauges.
//!
//! librdkafka buffers fetched messages in its own queue ahead of the
//! application, sized by `queued.max.messages.kbytes` / `queued.min.messages`.
//! Under a backlog that queue fills to its cap and dominates the process's
//! heap, but nothing in the consumer's own metrics shows it — the batch and lag
//! metrics only describe messages the consumer has already taken delivery of.
//! These gauges make that queue, and the broker connections feeding it, visible.
//!
//! [`export`] is called from the consumer context's `stats` callback, which
//! librdkafka fires on its own thread every `statistics.interval.ms`. It walks
//! the assigned partitions and connected brokers once and emits gauges — no
//! allocation, and nothing on the per-message path.
//!
//! # Every series here is unlabeled, and every one is written every tick
//!
//! The `metrics` facade cannot unregister a series, so a gauge labeled by
//! partition or broker keeps reporting its last value forever once that
//! partition moves to another pod or that broker leaves the cluster.
//! Dashboards and alerts then describe an assignment that no longer exists.
//! Aggregating to one pod-level scalar per statistic removes the failure mode
//! by construction rather than relying on eviction: there is no key that can go
//! away, and a value that stops being true is overwritten on the next tick.
//!
//! This is also why nothing here is skipped conditionally. A gauge that is only
//! written when a value is available is a stale gauge the moment it stops being
//! available, so each one below is written on every invocation, including when
//! the underlying value is absent.
//!
//! # Per-partition queue depths are not additive
//!
//! librdkafka's queue accessors follow queue forwarding, and the high-level
//! consumer forwards every partition queue into one shared queue. A statistic
//! that looks per-partition can therefore be the same shared total repeated
//! once per assigned partition. Aggregate those with a maximum, not a sum — see
//! [`fetch_queue`].

use metrics::gauge;
use rdkafka::{ClientConfig, Statistics};

/// Messages sitting in librdkafka's shared fetch queue. See [`fetch_queue`] for
/// why this is a max across partitions rather than a sum.
const FETCHQ_MESSAGES: &str = "kafka_consumer_fetchq_messages";

/// Bytes sitting in librdkafka's shared fetch queue — the memory the client
/// holds on the consumer's behalf, bounded by `queued.max.messages.kbytes`.
/// Same max-not-sum rule as [`FETCHQ_MESSAGES`].
const FETCHQ_BYTES: &str = "kafka_consumer_fetchq_bytes";

/// Operations waiting for the application to poll.
///
/// Read from the client's main reply queue, which the high-level consumer
/// forwards into the same shared queue the partition fetch queues feed, so this
/// tracks [`FETCHQ_MESSAGES`] rather than counting a separate backlog.
const REPLYQ_OPS: &str = "kafka_consumer_replyq_ops";

/// Slowest average request round-trip time across the connected brokers, over
/// the last statistics interval. `0` means no broker reported any request in
/// the interval, not a zero-latency cluster.
const BROKER_RTT_MAX_SECONDS: &str = "kafka_consumer_broker_rtt_max_seconds";

/// Requests awaiting transmission, summed over all brokers.
const BROKER_OUTBUF_REQUESTS: &str = "kafka_consumer_broker_outbuf_requests";

/// Requests sent and awaiting a response, summed over all brokers.
const BROKER_WAITRESP_REQUESTS: &str = "kafka_consumer_broker_waitresp_requests";

/// Rebalances this client has taken part in since it started. A gauge holding a
/// monotonic total: librdkafka reports the running count, not a delta, so read
/// it with `changes()` or `delta()` rather than `rate()`. Reads `0` until the
/// client joins its consumer group.
const REBALANCE_TOTAL: &str = "kafka_consumer_rebalance_total";

/// Cap on [`FETCHQ_BYTES`], from the resolved `queued.max.messages.kbytes`.
/// A config mirror, set once at startup.
const FETCHQ_BYTES_LIMIT: &str = "kafka_consumer_fetchq_bytes_limit";

/// Cap on [`FETCHQ_MESSAGES`], from the resolved `queued.min.messages`.
/// A config mirror, set once at startup.
const FETCHQ_MESSAGES_LIMIT: &str = "kafka_consumer_fetchq_messages_limit";

/// Cap on `consumer_batch_size`, in messages, from `CONSUMER_BATCH_SIZE`.
/// A config mirror, set once at startup.
const BATCH_SIZE_LIMIT: &str = "consumer_batch_size_limit";

/// Cap on `consumer_batch_size_kb`, from `CONSUMER_BATCH_SIZE_KB`. A config
/// mirror, set once at startup. `0` means the byte bound is off, so a dashboard
/// can tell "unset" from a real cap.
const BATCH_SIZE_KB_LIMIT: &str = "consumer_batch_size_kb_limit";

/// librdkafka's own default for `queued.max.messages.kbytes`.
const DEFAULT_QUEUED_MAX_MESSAGES_KBYTES: f64 = 102_400.0;

/// librdkafka's own default for `queued.min.messages`.
const DEFAULT_QUEUED_MIN_MESSAGES: f64 = 100_000.0;

/// Export the gauges described in the module docs from one statistics snapshot.
pub fn export(stats: &Statistics) {
    gauge!(REPLYQ_OPS).set(stats.replyq as f64);

    let fetchq = fetch_queue(stats);
    gauge!(FETCHQ_MESSAGES).set(fetchq.messages as f64);
    gauge!(FETCHQ_BYTES).set(fetchq.bytes as f64);

    let mut outbuf_requests: i64 = 0;
    let mut waitresp_requests: i64 = 0;
    let mut rtt_max_micros: i64 = 0;
    for broker in stats.brokers.values() {
        outbuf_requests += broker.outbuf_cnt;
        waitresp_requests += broker.waitresp_cnt;
        // A broker with no request in the interval has no window at all, so it
        // contributes nothing to the max rather than a misleading zero.
        if let Some(rtt) = &broker.rtt {
            rtt_max_micros = rtt_max_micros.max(rtt.avg);
        }
    }
    gauge!(BROKER_OUTBUF_REQUESTS).set(outbuf_requests as f64);
    gauge!(BROKER_WAITRESP_REQUESTS).set(waitresp_requests as f64);
    gauge!(BROKER_RTT_MAX_SECONDS).set(rtt_max_micros as f64 / 1_000_000.0);

    // Written even before the group is joined, so the series never goes stale.
    let rebalance_count = stats.cgrp.as_ref().map_or(0, |cgrp| cgrp.rebalance_cnt);
    gauge!(REBALANCE_TOTAL).set(rebalance_count as f64);
}

/// Depth of the one queue librdkafka holds fetched messages in.
struct FetchQueue {
    messages: i64,
    bytes: u64,
}

/// Read the shared fetch queue's depth from a statistics snapshot.
///
/// Takes the maximum across partitions, never the sum. librdkafka fills each
/// partition's `fetchq_cnt` and `fetchq_size` from that partition's queue
/// handle, and those accessors follow queue forwarding. The high-level consumer
/// forwards every partition queue into a single shared queue, so each assigned
/// partition reports the whole shared queue rather than a disjoint slice of it.
/// Summing therefore multiplies the real depth by the assigned partition count,
/// and can report more memory than the process has. A partition that is not
/// forwarding yet reports its own empty queue, which the maximum ignores.
fn fetch_queue(stats: &Statistics) -> FetchQueue {
    let mut messages = 0i64;
    let mut bytes = 0u64;
    for topic in stats.topics.values() {
        for partition in topic.partitions.values() {
            messages = messages.max(partition.fetchq_cnt);
            bytes = bytes.max(partition.fetchq_size);
        }
    }
    FetchQueue { messages, bytes }
}

/// Publish the configured caps that bound the live gauges above.
///
/// Config mirrors, set once at startup because none of them change while the
/// process runs. They exist so a dashboard can compute utilization against the
/// cap per deployment, rather than hardcoding limits that differ per lane.
///
/// The librdkafka caps come from the built [`ClientConfig`], not from the typed
/// settings that seeded it. The generic `KAFKA_CONSUMER_*` passthrough can
/// override any property, so only the built config states what the client
/// actually runs with.
pub fn export_limits(client_config: &ClientConfig, batch_size: usize, batch_size_kb: usize) {
    let queued_max_kbytes = property(
        client_config,
        "queued.max.messages.kbytes",
        DEFAULT_QUEUED_MAX_MESSAGES_KBYTES,
    );
    gauge!(FETCHQ_BYTES_LIMIT).set(queued_max_kbytes * 1024.0);
    gauge!(FETCHQ_MESSAGES_LIMIT).set(property(
        client_config,
        "queued.min.messages",
        DEFAULT_QUEUED_MIN_MESSAGES,
    ));
    gauge!(BATCH_SIZE_LIMIT).set(batch_size as f64);
    gauge!(BATCH_SIZE_KB_LIMIT).set(batch_size_kb as f64);
}

/// Read a numeric librdkafka property from the built config, falling back to
/// librdkafka's own default when the key is unset. A value librdkafka would
/// reject also falls back here, and fails the client creation that follows.
fn property(client_config: &ClientConfig, key: &str, default: f64) -> f64 {
    client_config
        .get(key)
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use rdkafka::statistics::{Partition, Topic};

    use super::*;

    fn partition(id: i32, fetchq_cnt: i64, fetchq_size: u64) -> Partition {
        Partition {
            partition: id,
            fetchq_cnt,
            fetchq_size,
            ..Default::default()
        }
    }

    fn statistics(partitions: Vec<Partition>) -> Statistics {
        let partitions = partitions.into_iter().map(|p| (p.partition, p)).collect();
        Statistics {
            topics: HashMap::from([(
                "t".to_string(),
                Topic {
                    partitions,
                    ..Default::default()
                },
            )]),
            ..Default::default()
        }
    }

    /// Every forwarding partition reports the whole shared queue, so the depth
    /// is one partition's figure — not the total across them.
    #[test]
    fn fetch_queue_does_not_multiply_shared_queue_by_partition_count() {
        let mut partitions: Vec<Partition> = (0..6).map(|id| partition(id, 100, 1_000)).collect();
        // Assigned but not fetching yet: reports its own still-empty queue.
        partitions.push(partition(6, 0, 0));

        let fetchq = fetch_queue(&statistics(partitions));

        assert_eq!(fetchq.messages, 100);
        assert_eq!(fetchq.bytes, 1_000);
    }
}
