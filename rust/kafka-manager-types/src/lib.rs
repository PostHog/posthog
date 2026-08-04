//! Wire types for the kafka-manager telemetry channel.
//!
//! Shared by producers of health reports (capture) and the kafka-manager
//! service. Reports flow one way — client to manager — and carry the produce
//! health signals a Kafka circuit breaker needs: delivery outcome counts,
//! producer queue pressure, and broker connectivity. The manager never sends
//! anything back on this channel; clients must keep working identically when
//! it is absent.

use serde::{Deserialize, Serialize};

/// One reporting interval's view of a single pod's produce health.
///
/// Counters are cumulative since process start, not per-interval deltas: the
/// manager computes rates from consecutive reports, which makes the channel
/// tolerant to lost or duplicated reports and makes pod restarts detectable
/// (a counter going backwards).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthReport {
    /// Pod identity, unique within a deployment (Kubernetes pod name).
    pub pod: String,
    /// Logical group the pod belongs to (e.g. `capture`, `capture-replay`).
    /// Fleet aggregation happens per deployment.
    pub deployment: String,
    /// Cumulative delivery outcome counts since process start.
    pub delivery: DeliveryCounts,
    /// Latest librdkafka statistics snapshot, if one has been observed yet
    /// (the stats callback fires on an interval, so the first report after
    /// boot may not carry one).
    pub producer: Option<ProducerStats>,
}

/// Cumulative delivery report outcomes, classified the way a breaker needs
/// them: successes, retriable transport failures, local timeouts, and the
/// permanent per-message errors that must never count toward tripping.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeliveryCounts {
    /// Broker acknowledged the write.
    pub ok: u64,
    /// Broker or transport returned a retriable produce error.
    pub broker_error: u64,
    /// Message expired in the producer before the broker acked it
    /// (librdkafka `message.timeout.ms` including retries).
    pub timed_out: u64,
    /// Rejected as too large — permanent, excluded from breaker error ratios.
    pub too_large: u64,
    /// Ack future dropped before completion (batch fail-fast aborted the
    /// wait); outcome unknown, message may or may not have been delivered.
    pub abandoned: u64,
    /// Rejected synchronously at enqueue time (queue full, unknown topic).
    pub enqueue_error: u64,
}

impl DeliveryCounts {
    /// Attempts with a known terminal outcome.
    pub fn total(&self) -> u64 {
        self.ok + self.broker_error + self.timed_out + self.too_large + self.enqueue_error
    }

    /// Outcomes a breaker should count as failures. `too_large` is excluded
    /// (permanent per-message error, not cluster health) and `abandoned` is
    /// excluded (unknown outcome).
    pub fn failures(&self) -> u64 {
        self.broker_error + self.timed_out + self.enqueue_error
    }
}

/// Producer-level pressure and connectivity from the librdkafka statistics
/// callback.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct ProducerStats {
    /// Messages currently buffered in the producer queue.
    pub queue_depth: u64,
    /// Producer queue capacity (`queue.buffering.max.messages`). The fill
    /// ratio `queue_depth / queue_capacity` is the leading indicator of a
    /// produce stall.
    pub queue_capacity: u64,
    pub brokers_up: u32,
    pub brokers_total: u32,
    pub brokers: Vec<BrokerStats>,
}

/// Per-broker connectivity and error counters (cumulative).
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct BrokerStats {
    pub id: String,
    pub up: bool,
    /// Producer-observed round-trip p99 in microseconds. Under `acks=all`
    /// this includes follower replication, making it an early ISR-lag signal.
    pub rtt_p99_us: i64,
    pub tx_errors: u64,
    pub request_timeouts: u64,
}
