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
//! allocation beyond the label strings, and nothing on the per-message path.

use std::sync::Arc;

use metrics::gauge;
use rdkafka::Statistics;

/// Messages sitting in librdkafka's fetch queue, summed over all partitions.
///
/// With the high-level consumer every partition queue forwards into one shared
/// queue, so the per-partition numbers are an attribution of a shared pool and
/// only their sum is meaningful — hence a single gauge rather than one per
/// partition.
const FETCHQ_MESSAGES: &str = "kafka_consumer_fetchq_messages";

/// Bytes sitting in librdkafka's fetch queue, summed over all partitions.
/// Same shared-pool caveat as [`FETCHQ_MESSAGES`]. This is the memory the
/// client holds on the consumer's behalf, bounded by
/// `queued.max.messages.kbytes`.
const FETCHQ_BYTES: &str = "kafka_consumer_fetchq_bytes";

/// Broker-reported lag in messages for one assigned partition (high watermark
/// minus the next offset to fetch). Partitions librdkafka has no lag for yet
/// report -1 and are skipped.
const PARTITION_LAG: &str = "kafka_consumer_partition_lag";

/// Operations waiting on librdkafka's main reply queue for the application to
/// poll. Sustained growth means the consumer loop is not polling fast enough.
const REPLYQ_OPS: &str = "kafka_consumer_replyq_ops";

/// Average request round-trip time to one broker over the last stats interval.
const BROKER_RTT_AVG_SECONDS: &str = "kafka_consumer_broker_rtt_avg_seconds";

/// Requests awaiting transmission, summed over all brokers.
const BROKER_OUTBUF_REQUESTS: &str = "kafka_consumer_broker_outbuf_requests";

/// Requests sent and awaiting a response, summed over all brokers.
const BROKER_WAITRESP_REQUESTS: &str = "kafka_consumer_broker_waitresp_requests";

/// Rebalances this client has taken part in since it started. A gauge holding a
/// monotonic total: librdkafka reports the running count, not a delta, so read
/// it with `changes()` or `delta()` rather than `rate()`.
const REBALANCE_TOTAL: &str = "kafka_consumer_rebalance_total";

/// Export the gauges described in the module docs from one statistics snapshot.
pub fn export(stats: &Statistics) {
    gauge!(REPLYQ_OPS).set(stats.replyq as f64);

    let mut fetchq_messages: i64 = 0;
    let mut fetchq_bytes: u64 = 0;

    for topic in stats.topics.values() {
        // Cloned once per topic, not once per partition: every partition of a
        // topic shares the label value.
        let topic_label: Arc<str> = Arc::from(topic.topic.as_str());
        for partition in topic.partitions.values() {
            fetchq_messages += partition.fetchq_cnt;
            fetchq_bytes += partition.fetchq_size;

            // -1 means librdkafka has no lag for this partition yet (no fetch
            // has landed, or it is the internal unassigned-partition entry).
            if partition.consumer_lag < 0 {
                continue;
            }
            gauge!(
                PARTITION_LAG,
                "topic" => Arc::clone(&topic_label),
                "partition" => partition.partition.to_string(),
            )
            .set(partition.consumer_lag as f64);
        }
    }

    gauge!(FETCHQ_MESSAGES).set(fetchq_messages as f64);
    gauge!(FETCHQ_BYTES).set(fetchq_bytes as f64);

    let mut outbuf_requests: i64 = 0;
    let mut waitresp_requests: i64 = 0;
    for broker in stats.brokers.values() {
        outbuf_requests += broker.outbuf_cnt;
        waitresp_requests += broker.waitresp_cnt;

        if let Some(rtt) = &broker.rtt {
            gauge!(
                BROKER_RTT_AVG_SECONDS,
                "broker" => broker.nodeid.to_string(),
            )
            .set(rtt.avg as f64 / 1_000_000.0);
        }
    }
    gauge!(BROKER_OUTBUF_REQUESTS).set(outbuf_requests as f64);
    gauge!(BROKER_WAITRESP_REQUESTS).set(waitresp_requests as f64);

    if let Some(cgrp) = &stats.cgrp {
        gauge!(REBALANCE_TOTAL).set(cgrp.rebalance_cnt as f64);
    }
}
