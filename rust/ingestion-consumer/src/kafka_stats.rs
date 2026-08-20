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

use metrics::gauge;
use rdkafka::Statistics;

/// Messages sitting in librdkafka's fetch queue, summed over all partitions.
///
/// With the high-level consumer every partition queue forwards into one shared
/// queue, so per-partition numbers are an attribution of a shared pool and only
/// their sum is meaningful.
const FETCHQ_MESSAGES: &str = "kafka_consumer_fetchq_messages";

/// Bytes sitting in librdkafka's fetch queue, summed over all partitions.
/// Same shared-pool caveat as [`FETCHQ_MESSAGES`]. This is the memory the
/// client holds on the consumer's behalf, bounded by
/// `queued.max.messages.kbytes`.
const FETCHQ_BYTES: &str = "kafka_consumer_fetchq_bytes";

/// Operations waiting on librdkafka's main reply queue for the application to
/// poll. Sustained growth means the consumer loop is not polling fast enough.
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

/// Export the gauges described in the module docs from one statistics snapshot.
pub fn export(stats: &Statistics) {
    gauge!(REPLYQ_OPS).set(stats.replyq as f64);

    let mut fetchq_messages: i64 = 0;
    let mut fetchq_bytes: u64 = 0;
    for topic in stats.topics.values() {
        for partition in topic.partitions.values() {
            fetchq_messages += partition.fetchq_cnt;
            fetchq_bytes += partition.fetchq_size;
        }
    }
    gauge!(FETCHQ_MESSAGES).set(fetchq_messages as f64);
    gauge!(FETCHQ_BYTES).set(fetchq_bytes as f64);

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
