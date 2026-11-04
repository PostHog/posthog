//! Mirror of `products/ai_observability/shared/crosslang/ai_event_limits.json`, in decimal bytes.
//! Edit that file first, then these constants. The parity test in
//! `tests/ai_event_limits_parity.rs` fails when they differ.

pub const AI_MAX_EVENT_BYTES_DEFAULT: u64 = 8_388_608;
pub const AI_MAX_EVENT_BYTES_OVERRIDES: [u64; 2] = [24_000_000, 48_000_000];
pub const AI_MAX_EVENT_BYTES_CEILING: u64 = 48_000_000;
