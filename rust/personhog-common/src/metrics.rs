//! Histogram bucket ladders shared by the personhog binaries.
//!
//! The exporter's default ladder steps 10 → 50 → 100 ms, which blurs the
//! write path — produce cycles, fence waits, and lock waits all live in
//! 1–50 ms — and pins interpolated quantiles to bucket edges. These
//! ladders give the spans we tune against honest resolution; binaries
//! apply them per metric so coarse, seconds-scale histograms keep the
//! cheap default.

/// Millisecond buckets for write-path spans: produce cycles, fence
/// send/commit waits, lock waits, and per-request server and transport
/// spans.
pub const WRITE_PATH_LATENCY_BUCKETS_MS: &[f64] = &[
    1.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 75.0, 100.0, 250.0, 500.0,
    1000.0, 2000.0, 5000.0,
];

/// Millisecond buckets for partition warms: sub-second once consumer
/// pools are warm, with enough headroom above to see a cold-pool
/// regression rather than collapsing it into +Inf.
pub const WARM_LATENCY_BUCKETS_MS: &[f64] = &[
    50.0, 100.0, 250.0, 500.0, 750.0, 1000.0, 1500.0, 2000.0, 3000.0, 5000.0, 10000.0, 30000.0,
];
