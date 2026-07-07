//! SanitizerCoverage edge bitmap for the parser-parity grind.
//!
//! Only compiled when the crate is built with `--features coverage`. Implements
//! the two `__sanitizer_cov_trace_pc_*` callbacks LLVM's
//! `-sanitizer-coverage-trace-pc-guard` instrumentation pass emits, maintains a
//! fixed-size atomic bitmap of hit edges, and exposes snapshot / reset to
//! Python via PyO3. The Python-side PBT
//! (`posthog/hogql/test/test_parser_pbt.py`) calls `cov_reset()` before each
//! parse, takes a `cov_snapshot()` afterwards, and feeds
//! `popcount(snapshot & ~seen)` to Hypothesis `target("rust_edges", ...)` for
//! coverage-guided steering of the example generator. See the corresponding
//! README section in `rust/hogql/parser/README.md` for the build dance.
//!
//! Bitmap sizing: parser binaries have at most a few thousand basic blocks, so
//! a 64KiB bitmap with mask-wrap on guard IDs leaves comfortable headroom
//! without paying for a large per-snapshot copy.

use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::sync::atomic::{AtomicU32, AtomicU8, Ordering};

/// Power of two so `(id) & (BITMAP_SIZE - 1)` is the index. 64KiB.
pub const BITMAP_SIZE: usize = 1 << 16;

/// One byte per edge; 0 = not hit since last reset, 1 = hit. `AtomicU8` because
/// the trace callbacks may run from any thread that ends up parsing; `Relaxed`
/// is sufficient because we only need eventual per-parse visibility, not strict
/// cross-thread ordering.
static COVERAGE: [AtomicU8; BITMAP_SIZE] = [const { AtomicU8::new(0) }; BITMAP_SIZE];

/// Monotonic counter handed out at init time so each LLVM guard slot gets a
/// unique non-zero ID. Wraps via modulo so an oversize binary aliases edges
/// rather than overflowing; aliased edges still produce a useful steering
/// signal, just with slightly diluted novelty.
static NEXT_GUARD: AtomicU32 = AtomicU32::new(1);

/// Called by the runtime once per loaded image with the guard region for this
/// image's instrumented basic blocks. We assign each guard a unique non-zero ID
/// so `__sanitizer_cov_trace_pc_guard` can mask it directly to a bitmap index.
/// LLVM treats a zero guard as "edge disabled"; we never emit one.
///
/// # Safety
/// LLVM guarantees that `start <= stop` and that both pointers refer to a
/// valid contiguous `u32` array owned by the loaded image; we only write
/// within that range and don't keep the pointers past this call.
#[no_mangle]
pub unsafe extern "C" fn __sanitizer_cov_trace_pc_guard_init(start: *mut u32, stop: *mut u32) {
    let mut p = start;
    while p < stop {
        let next = NEXT_GUARD.fetch_add(1, Ordering::Relaxed);
        // 1..=BITMAP_SIZE-1 so the value is always non-zero (zero = disabled).
        let nonzero = (next % (BITMAP_SIZE as u32 - 1)) + 1;
        *p = nonzero;
        p = p.add(1);
    }
}

/// Hot-path callback fired on every instrumented basic block entry. Pull the
/// edge ID out of the guard slot, mask into the bitmap, OR-in the hit bit.
///
/// # Safety
/// LLVM passes a pointer to a `u32` slot in the guard region initialized by
/// `__sanitizer_cov_trace_pc_guard_init`. A single read.
#[no_mangle]
pub unsafe extern "C" fn __sanitizer_cov_trace_pc_guard(guard: *mut u32) {
    let g = *guard;
    if g == 0 {
        return;
    }
    let idx = (g as usize) & (BITMAP_SIZE - 1);
    COVERAGE[idx].fetch_or(1, Ordering::Relaxed);
}

/// Return the current bitmap as a fresh Python `bytes`. The Python diagnostic
/// reads this with `numpy.frombuffer` and computes the novelty count for the
/// `target()` call. A 64KiB copy per example is well inside the per-example
/// budget (microseconds vs the millisecond per-parse cost).
#[pyfunction]
pub fn cov_snapshot(py: Python<'_>) -> PyObject {
    let mut buf = [0u8; BITMAP_SIZE];
    for (i, cell) in COVERAGE.iter().enumerate() {
        buf[i] = cell.load(Ordering::Relaxed);
    }
    PyBytes::new_bound(py, &buf).into()
}

/// Zero the bitmap. The diagnostic calls this before each example so the
/// subsequent `cov_snapshot()` reflects only that example's edges.
#[pyfunction]
pub fn cov_reset() {
    for cell in COVERAGE.iter() {
        cell.store(0, Ordering::Relaxed);
    }
}
