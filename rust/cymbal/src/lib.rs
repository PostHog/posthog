pub mod app_context;
pub mod assignment_rules;
pub mod config;
pub mod core;
pub mod fingerprinting;
pub mod issue_resolution;
pub mod modes;
pub mod posthog_utils;
pub mod router;
pub mod server;
pub mod signals;
pub mod spike_config;
pub mod stages;
pub mod suppression_rules;
pub mod teams;
#[cfg(test)]
pub mod test_utils;
pub mod tokenizer;
pub mod types;

// Compat re-exports: these modules physically live under `core/` now, but much
// of the crate still imports them by their old crate-root paths. Prefer
// `crate::core::*` in new code.
pub use core::sanitize::{
    needs_sanitization, recursively_sanitize_properties, sanitize_source_line, sanitize_string,
};
pub use core::{error, frames, langs, metric_consts, symbolication};
