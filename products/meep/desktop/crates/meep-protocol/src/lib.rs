//! Shared wire records for Meep clients and their workspace service.
use serde::{Deserialize, Serialize};
pub mod notifications;
pub mod sessions;

/// A method invocation with optional View authorization and revision context.
#[derive(Clone, Serialize, Deserialize)]
pub struct Rpc {
    /// Method to invoke.
    pub method: String,
    /// Method-specific arguments.
    #[serde(default)]
    pub params: serde_json::Value,
    /// View issuing the request.
    #[serde(default)]
    pub view_id: Option<String>,
    /// Session credential supplied by the caller.
    #[serde(default)]
    pub session_token: Option<String>,
    /// Revision of the calling view.
    #[serde(default)]
    pub view_revision: Option<String>,
}

impl std::fmt::Debug for Rpc {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Rpc")
            .field("method", &self.method)
            .field("view_id", &self.view_id)
            .field("view_revision", &self.view_revision)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rpc_diagnostics_omit_host_and_view_credentials() -> serde_json::Result<()> {
        let rpc: Rpc = serde_json::from_value(
            serde_json::json!({"method":"inspect","params":{"_host_auth":"private-host"},"session_token":"private-view"}),
        )?;
        let diagnostics = format!("{rpc:#?}");
        assert!(diagnostics.contains("inspect"));
        assert!(!diagnostics.contains("private"));
        assert_eq!(
            serde_json::to_value(rpc)?["params"]["_host_auth"],
            "private-host"
        );
        Ok(())
    }
}
