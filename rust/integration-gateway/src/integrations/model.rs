use serde::Serialize;
use serde_json::Value;

/// A raw row from `posthog_integration`, with `sensitive_config` still Fernet-encrypted.
#[derive(Debug, Clone)]
pub struct IntegrationRow {
    pub id: i64,
    pub team_id: i64,
    pub kind: String,
    pub config: Value,
    pub sensitive_config: Value,
}

/// A decrypted, cacheable integration. Serializes to exactly the shape the plugin-server's
/// `IntegrationType` expects (`nodejs/src/cdp/types.ts`), so the CDP consumer swap is a drop-in.
#[derive(Debug, Clone, Serialize)]
pub struct DecryptedIntegration {
    pub id: i64,
    pub team_id: i64,
    pub kind: String,
    pub config: Value,
    pub sensitive_config: Value,
}
