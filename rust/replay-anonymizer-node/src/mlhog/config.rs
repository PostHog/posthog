// Copied verbatim from MLHog prep/labeling/src/config.rs — bench-only.

/// Namespaces the two redaction marks. No tunables.
#[derive(Debug, Default, Clone)]
pub struct Config;

impl Config {
    pub const REDACT_CHAR: char = '*';
    pub const NUMBER_CHAR: char = '#';
}
