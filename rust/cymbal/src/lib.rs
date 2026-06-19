pub mod config;
pub mod core;
pub mod modes;
#[cfg(test)]
pub mod test_utils;
pub mod types;

// Compat re-exports: the shared kernel physically lives under `core/`, but much
// of the crate still imports it by the old crate-root paths. Prefer
// `crate::core::*` in new code.
pub use core::sanitize::{
    needs_sanitization, recursively_sanitize_properties, sanitize_source_line, sanitize_string,
};
pub use core::{error, frames, langs, metric_consts, symbolication};

// Compat re-exports: processing-only modules now live under `modes::processing`.
// Prefer `crate::modes::processing::*` in new code.
pub use modes::processing::{
    app_context, assignment_rules, fingerprinting, issue_resolution, posthog_utils, router, server,
    signals, spike_config, stages, suppression_rules, teams, tokenizer,
};
