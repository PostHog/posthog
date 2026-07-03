// Bench-only port of MLHog's v2 byte-scanning scrubber (MLHog repo: prep/labeling/src/). The v2
// walk's traversal mechanics are kept as close to verbatim as possible, but its leaf scrubs and
// routing are wired to this crate's own parity-locked scrubbers (see `leaf`) so the benchmark
// compares architectures (byte-splice walk vs tree walk), not scrub implementations. Compiled only
// under the `mlhog-bench` feature.

pub mod leaf;
pub mod schema;
pub mod v2;

// The v2 walk shares the crate's real per-message context (allow lists + blur memo), so both
// implementations run identical leaf scrubs with identical blur caching.
pub use crate::allow_lists::AllowLists;
pub use crate::context::Ctx;
pub use v2::V2Worker;

// No-op passthrough replacement for MLHog's `timed!` metrics macro (crate::metrics is not ported;
// the `$ctr` counter path is matched but never expanded, so it needs no target to resolve to).
macro_rules! timed {
    ($ctr:path, $e:expr) => {
        $e
    };
}
pub(crate) use timed;
