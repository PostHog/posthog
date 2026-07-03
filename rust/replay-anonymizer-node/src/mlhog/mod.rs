// Bench-only port of MLHog's v2 byte-scanning scrubber (MLHog repo: prep/labeling/src/). This
// umbrella module is new; the submodules are copied as close to verbatim as possible — see each
// file's header for its MLHog source path. Compiled only under the `mlhog-bench` feature.

pub mod config;
pub mod context;
pub mod dict;
pub mod schema;
pub mod scrub;
pub mod v2;

pub use context::Ctx;
pub use dict::AllowLists;
pub use v2::V2Worker;

// No-op passthrough replacement for MLHog's `timed!` metrics macro (crate::metrics is not ported;
// the `$ctr` counter path is matched but never expanded, so it needs no target to resolve to).
macro_rules! timed {
    ($ctr:path, $e:expr) => {
        $e
    };
}
pub(crate) use timed;
