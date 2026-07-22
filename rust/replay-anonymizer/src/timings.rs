//! Phase-timing sink for the snapshot pipeline: contiguous phase boundaries (decompress, scrub)
//! plus accumulated in-scrub op totals (cv de/recompression, image blur).
//!
//! The sink is `Cell`-based and owned by the caller *outside* any `catch_unwind` boundary, so
//! whatever phases completed before a panic are still readable afterwards — the addon reports
//! timings on the failure path too, which is how a panicking payload gets debugged.
//!
//! `last_op` is the in-flight marker: each op sets it on entry and restores `"scrub"` on a clean
//! exit, so after a panic it names the op that was running.

use std::cell::Cell;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;

const UNSET: u64 = u64::MAX;

pub struct PhaseTimings {
    origin: Instant,
    origin_epoch_ms: f64,
    decompress_start_ns: Cell<u64>,
    decompress_end_ns: Cell<u64>,
    scrub_start_ns: Cell<u64>,
    scrub_end_ns: Cell<u64>,
    cv_total_ns: Cell<u64>,
    cv_count: Cell<u32>,
    blur_total_ns: Cell<u64>,
    blur_count: Cell<u32>,
    last_op: Cell<&'static str>,
}

/// Plain serializable view of a [`PhaseTimings`]; field names match the TS `AnonymizeTimings`.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PhaseTimingsSnapshot {
    /// Wall-clock time the task started (when the sink was created), epoch milliseconds.
    pub task_start_epoch_ms: f64,
    /// Phase boundaries as nanosecond offsets from `task_start_epoch_ms`; `None` = never reached.
    pub decompress_start_ns: Option<u64>,
    pub decompress_end_ns: Option<u64>,
    pub scrub_start_ns: Option<u64>,
    pub scrub_end_ns: Option<u64>,
    pub cv_total_ns: u64,
    pub cv_count: u32,
    pub blur_total_ns: u64,
    pub blur_count: u32,
    pub last_op: &'static str,
}

impl PhaseTimings {
    #[allow(clippy::new_without_default)]
    pub fn new() -> Self {
        Self {
            origin: Instant::now(),
            origin_epoch_ms: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_secs_f64() * 1000.0)
                .unwrap_or(0.0),
            decompress_start_ns: Cell::new(UNSET),
            decompress_end_ns: Cell::new(UNSET),
            scrub_start_ns: Cell::new(UNSET),
            scrub_end_ns: Cell::new(UNSET),
            cv_total_ns: Cell::new(0),
            cv_count: Cell::new(0),
            blur_total_ns: Cell::new(0),
            blur_count: Cell::new(0),
            last_op: Cell::new("start"),
        }
    }

    fn now_ns(&self) -> u64 {
        u64::try_from(self.origin.elapsed().as_nanos()).unwrap_or(u64::MAX - 1)
    }

    pub fn decompress_started(&self) {
        self.last_op.set("decompress");
        self.decompress_start_ns.set(self.now_ns());
    }

    pub fn decompress_finished(&self) {
        self.decompress_end_ns.set(self.now_ns());
    }

    pub fn scrub_started(&self) {
        self.last_op.set("scrub");
        self.scrub_start_ns.set(self.now_ns());
    }

    pub fn scrub_finished(&self) {
        self.scrub_end_ns.set(self.now_ns());
    }

    pub fn mark(&self, op: &'static str) {
        self.last_op.set(op);
    }

    /// Time one in-scrub op, accumulating into the `total`/`count` pair named by `op` ("cv" or
    /// "blur"). Restores the `"scrub"` marker only on clean exit — a panic inside `f` leaves
    /// `last_op` naming the op that died.
    pub(crate) fn time_op<T>(&self, op: &'static str, f: impl FnOnce() -> T) -> T {
        let (total, count) = match op {
            "cv" => (&self.cv_total_ns, &self.cv_count),
            _ => (&self.blur_total_ns, &self.blur_count),
        };
        self.last_op.set(op);
        let start = Instant::now();
        let out = f();
        let elapsed = u64::try_from(start.elapsed().as_nanos()).unwrap_or(u64::MAX - 1);
        total.set(total.get().saturating_add(elapsed));
        count.set(count.get().saturating_add(1));
        self.last_op.set("scrub");
        out
    }

    pub fn snapshot(&self) -> PhaseTimingsSnapshot {
        let opt = |c: &Cell<u64>| Some(c.get()).filter(|&v| v != UNSET);
        PhaseTimingsSnapshot {
            task_start_epoch_ms: self.origin_epoch_ms,
            decompress_start_ns: opt(&self.decompress_start_ns),
            decompress_end_ns: opt(&self.decompress_end_ns),
            scrub_start_ns: opt(&self.scrub_start_ns),
            scrub_end_ns: opt(&self.scrub_end_ns),
            cv_total_ns: self.cv_total_ns.get(),
            cv_count: self.cv_count.get(),
            blur_total_ns: self.blur_total_ns.get(),
            blur_count: self.blur_count.get(),
            last_op: self.last_op.get(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::unwind::contain_unwind;

    #[test]
    fn accumulates_ops_and_phase_boundaries() {
        let t = PhaseTimings::new();
        t.decompress_started();
        t.decompress_finished();
        t.scrub_started();
        t.time_op("cv", || {});
        t.time_op("blur", || {});
        t.time_op("blur", || {});
        t.scrub_finished();

        let snap = t.snapshot();
        assert!(snap.decompress_start_ns.unwrap() <= snap.decompress_end_ns.unwrap());
        assert!(snap.scrub_start_ns.unwrap() <= snap.scrub_end_ns.unwrap());
        assert_eq!(snap.cv_count, 1);
        assert_eq!(snap.blur_count, 2);
        assert_eq!(snap.last_op, "scrub");
    }

    #[test]
    fn survives_a_panic_and_names_the_op_in_flight() {
        let t = PhaseTimings::new();
        t.decompress_started();
        t.decompress_finished();
        t.scrub_started();
        t.time_op("cv", || {});
        let result = contain_unwind(
            || -> Result<(), String> {
                t.time_op("blur", || panic!("image decode exploded"));
                Ok(())
            },
            |m| m,
        );
        assert!(result.is_err());

        let snap = t.snapshot();
        assert!(snap.decompress_end_ns.is_some());
        assert!(snap.scrub_start_ns.is_some());
        assert_eq!(snap.scrub_end_ns, None);
        assert_eq!(snap.cv_count, 1);
        assert_eq!(snap.last_op, "blur");
    }
}
