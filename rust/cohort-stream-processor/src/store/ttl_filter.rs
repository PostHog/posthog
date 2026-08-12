//! Env-gated TTL compaction filter for `cf_person_records`.
//!
//! When `COHORT_PERSON_RECORD_TTL_DAYS` is set (default OFF), a compaction-filter factory is installed
//! on `cf_person_records` only — never on `cf_behavioral`, whose live eviction deadlines are the
//! sweep's contract. Each compaction run gets a fresh filter whose cutoff is frozen at filter creation
//! (`now_ms - ttl`), so every value in that run is judged against one instant.
//!
//! A record whose `last_seen_ms` is strictly older than the cutoff is removed; any value that cannot
//! be positively read as expired (too short, wrong version byte, garbage) is kept.
//!
//! [`PersonRecordTtlFilter::filter`] runs on RocksDB compaction threads across the C FFI boundary,
//! where a panic is undefined behavior, so it must never panic: no unchecked indexing, no unwrap/expect
//! on fallible input. It is also kept free of metrics and logging (no re-entrancy guarantees on the
//! compaction thread); the only observability is a factory-creation `debug!`.

use std::ffi::{CStr, CString};

use rocksdb::compaction_filter::{CompactionFilter, Decision};
use rocksdb::compaction_filter_factory::{CompactionFilterContext, CompactionFilterFactory};
use tracing::debug;

use crate::stage1::person_record::{FORMAT_VERSION, LAST_SEEN_MS_OFFSET};

/// Bump the `_vN` suffix on any change to the filter's semantics so it is visible in the RocksDB LOG.
const FACTORY_NAME: &[u8] = b"cf_person_records_ttl_v1\0";
const FILTER_NAME: &[u8] = b"cf_person_records_ttl_filter_v1\0";

/// Milliseconds per day, the unit `COHORT_PERSON_RECORD_TTL_DAYS` is expressed in.
const MS_PER_DAY: i64 = 86_400_000;

/// The smallest value long enough to carry `last_seen_ms`. Shorter values are always kept.
const MIN_TTL_READABLE_LEN: usize = LAST_SEEN_MS_OFFSET + 8;

/// Factory installed on `cf_person_records` when the TTL is enabled. RocksDB calls [`Self::create`]
/// once per compaction run; the returned filter carries a cutoff frozen at that instant.
pub struct PersonRecordTtlFactory {
    ttl_ms: i64,
    /// The clock, read once per compaction run. Boxed so tests can inject a fixed instant.
    now_ms: Box<dyn Fn() -> i64 + Send>,
}

impl PersonRecordTtlFactory {
    /// A factory that reads the wall clock at each compaction run.
    pub fn new(ttl_days: u32) -> Self {
        Self::with_clock(ttl_days, wall_clock_ms)
    }

    fn with_clock(ttl_days: u32, now_ms: impl Fn() -> i64 + Send + 'static) -> Self {
        Self {
            ttl_ms: ttl_ms_for(ttl_days),
            now_ms: Box::new(now_ms),
        }
    }

    /// The cutoff for a run starting now: records with `last_seen_ms < cutoff` are dropped. Saturating
    /// so an enormous TTL cannot underflow the cutoff.
    fn cutoff(&self) -> i64 {
        (self.now_ms)().saturating_sub(self.ttl_ms)
    }
}

impl CompactionFilterFactory for PersonRecordTtlFactory {
    type Filter = PersonRecordTtlFilter;

    fn create(&mut self, context: CompactionFilterContext) -> Self::Filter {
        let cutoff = self.cutoff();
        // Log here, not in `filter`: this runs once per compaction run, outside the per-key FFI loop.
        debug!(
            cutoff_ms = cutoff,
            is_full_compaction = context.is_full_compaction,
            is_manual_compaction = context.is_manual_compaction,
            "cf_person_records TTL compaction filter created",
        );
        PersonRecordTtlFilter {
            cutoff,
            name: filter_name(),
        }
    }

    fn name(&self) -> &CStr {
        factory_name()
    }
}

/// One compaction run's filter. Holds the frozen cutoff; classifies each value with no allocation,
/// no clock read, and no panic, metric, or log.
pub struct PersonRecordTtlFilter {
    cutoff: i64,
    name: CString,
}

impl CompactionFilter for PersonRecordTtlFilter {
    fn filter(&mut self, _level: u32, _key: &[u8], value: &[u8]) -> Decision {
        match last_seen_ms(value) {
            Some(last_seen_ms) if last_seen_ms < self.cutoff => Decision::Remove,
            // Fresh enough, or unreadable (short / wrong version / garbage): keep it.
            _ => Decision::Keep,
        }
    }

    fn name(&self) -> &CStr {
        self.name.as_c_str()
    }
}

/// Read `last_seen_ms` from a value that is a well-formed v1 person record, else `None`. Panic-free:
/// the length guard makes the fixed-offset slice in-bounds.
fn last_seen_ms(value: &[u8]) -> Option<i64> {
    if value.len() < MIN_TTL_READABLE_LEN || value[0] != FORMAT_VERSION {
        return None;
    }
    let bytes: [u8; 8] = value[LAST_SEEN_MS_OFFSET..LAST_SEEN_MS_OFFSET + 8]
        .try_into()
        .ok()?;
    Some(i64::from_be_bytes(bytes))
}

/// `ttl_days` as milliseconds, saturating so a pathological day count cannot overflow `i64`.
fn ttl_ms_for(ttl_days: u32) -> i64 {
    (ttl_days as i64).saturating_mul(MS_PER_DAY)
}

fn wall_clock_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

fn factory_name() -> &'static CStr {
    CStr::from_bytes_with_nul(FACTORY_NAME).expect("factory name is a valid C string literal")
}

fn filter_name() -> CString {
    CStr::from_bytes_with_nul(FILTER_NAME)
        .expect("filter name is a valid C string literal")
        .to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::stage1::person_record::{PersonRecord, Stamp};

    fn record_with_last_seen(last_seen_ms: i64) -> Vec<u8> {
        let mut record = PersonRecord::absent();
        record.last_seen_ms = last_seen_ms;
        record.stamp = Stamp::new(last_seen_ms, 0);
        record.encode()
    }

    /// A factory whose "now" is fixed, so a run's cutoff is deterministic.
    fn factory_at(now_ms: i64, ttl_days: u32) -> PersonRecordTtlFactory {
        PersonRecordTtlFactory::with_clock(ttl_days, move || now_ms)
    }

    #[test]
    fn expired_record_is_removed_and_fresh_is_kept() {
        // now = day 40, TTL = 30d → cutoff = day 10.
        let mut filter = factory_at(40 * MS_PER_DAY, 30).create(context());

        let ancient = record_with_last_seen(5 * MS_PER_DAY); // < cutoff
        let fresh = record_with_last_seen(35 * MS_PER_DAY); // > cutoff
        assert!(matches!(filter.filter(0, b"k", &ancient), Decision::Remove));
        assert!(matches!(filter.filter(0, b"k", &fresh), Decision::Keep));
    }

    #[test]
    fn a_record_exactly_at_the_cutoff_is_kept() {
        // Strictly-older is the drop rule: `last_seen_ms == cutoff` must survive.
        let mut filter = factory_at(40 * MS_PER_DAY, 30).create(context()); // cutoff = day 10
        let at_cutoff = record_with_last_seen(10 * MS_PER_DAY);
        assert!(matches!(filter.filter(0, b"k", &at_cutoff), Decision::Keep));
    }

    #[test]
    fn malformed_values_are_always_kept() {
        let mut filter = factory_at(40 * MS_PER_DAY, 30).create(context()); // cutoff = day 10
        for value in [
            [].as_slice(),
            &[FORMAT_VERSION], // version only
            // One byte short of the 10-byte minimum (`last_seen_ms` spans bytes 2..10) — the
            // tightest truncation the length guard must reject.
            &[FORMAT_VERSION, 0, 0, 0, 0, 0, 0, 0, 0],
            &[0xFF; 32], // wrong version byte, plenty long
        ] {
            assert!(
                matches!(filter.filter(0, b"k", value), Decision::Keep),
                "malformed value {value:?} must be kept",
            );
        }
    }

    #[test]
    fn last_seen_ms_reads_only_well_formed_v1_records() {
        let encoded = record_with_last_seen(1_234_567_890);
        assert_eq!(last_seen_ms(&encoded), Some(1_234_567_890));
        assert_eq!(last_seen_ms(&[]), None);
        assert_eq!(last_seen_ms(&[FORMAT_VERSION, 0, 0]), None, "too short");
        let mut wrong_version = encoded.clone();
        wrong_version[0] = FORMAT_VERSION + 1;
        assert_eq!(last_seen_ms(&wrong_version), None, "version guard");
    }

    #[test]
    fn cutoff_does_not_underflow_for_a_small_now_and_a_large_ttl() {
        // A wrap would flip the cutoff positive and classify nothing as expired.
        let mut factory = factory_at(0, 30);
        factory.ttl_ms = i64::MAX;
        assert_eq!(factory.cutoff(), 0i64.saturating_sub(i64::MAX));
        assert!(factory.cutoff() < 0);
    }

    #[test]
    fn ttl_ms_for_maps_days_to_millis_without_overflow_for_any_u32() {
        assert_eq!(ttl_ms_for(30), 30 * MS_PER_DAY);
        // Every `u32` day count fits in `i64` millis, so the saturating multiply never saturates here.
        assert_eq!(ttl_ms_for(u32::MAX), u32::MAX as i64 * MS_PER_DAY);
    }

    #[test]
    fn names_are_valid_nul_terminated_c_strings() {
        assert_eq!(factory_name().to_bytes(), b"cf_person_records_ttl_v1");
        assert_eq!(
            filter_name().as_c_str().to_bytes(),
            b"cf_person_records_ttl_filter_v1",
        );
    }

    fn context() -> CompactionFilterContext {
        CompactionFilterContext {
            is_full_compaction: true,
            is_manual_compaction: true,
        }
    }
}
