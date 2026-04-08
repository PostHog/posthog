use std::time::Duration;

#[allow(dead_code)]
pub(crate) const DEFAULT_PRODUCE_TIMEOUT: Duration = Duration::from_secs(30);

// Lifecycle Handle configuration for v1 sinks.
//
// Timing chain (worst-case detection of a fully broken sink):
//   1. Last successful heartbeat at t=0
//   2. publish_batch runs for up to produce_timeout (30s), returns with 0 successes -> no heartbeat
//   3. stats callback fires every statistics_interval_ms (10s) but brokers are down -> no heartbeat
//   4. At t=30s liveness_deadline expires
//   5. Next health_poll (within 2s) detects stall, stall_count=1 >= stall_threshold=1
//   6. Global shutdown triggered at ~t=32s
//
// This matches the existing v0 capture setup (setup.rs + main.rs).

/// The handle must receive a report_healthy() call within this window or
/// the health poll considers it stalled. Set equal to produce_timeout so
/// a single full-timeout batch is the minimum detection unit.
#[allow(dead_code)]
pub(crate) const SINK_LIVENESS_DEADLINE: Duration = Duration::from_secs(30);

/// Consecutive stalled health polls before triggering global shutdown.
/// 1 = immediate (first missed deadline triggers shutdown). Matches v0.
#[allow(dead_code)]
pub(crate) const SINK_STALL_THRESHOLD: u32 = 1;
