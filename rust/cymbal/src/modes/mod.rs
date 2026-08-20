//! Run modes for the cymbal binary. The active mode is selected at boot via
//! the `CYMBAL_MODE` env var; each mode owns its own server stack and (nested)
//! config. Adding a mode is one submodule, one [`CymbalMode`] variant, one
//! nested config field on [`crate::modes::processing::ProcessingConfig`], and one match arm in
//! `main.rs`.

use std::str::FromStr;

pub mod notifications;
pub mod processing;
pub mod resolution;

/// Which server stack the cymbal binary runs. Parsed from `CYMBAL_MODE`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum CymbalMode {
    /// Error-tracking HTTP `/process` pipeline (the default).
    #[default]
    Processing,
    /// `cymbal.resolution.v1` gRPC symbol-resolution service.
    Resolution,
    /// Consumes the error-tracking ingestion notifications topic and logs it.
    Notifications,
}

impl FromStr for CymbalMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_ascii_lowercase().as_str() {
            "processing" => Ok(Self::Processing),
            "resolution" => Ok(Self::Resolution),
            "notifications" => Ok(Self::Notifications),
            other => Err(format!(
                "unknown CYMBAL_MODE '{other}', expected 'processing', 'resolution', or 'notifications'"
            )),
        }
    }
}
