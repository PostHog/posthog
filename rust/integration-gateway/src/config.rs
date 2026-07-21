use envconfig::Envconfig;

/// Runtime configuration, populated from the environment via `envconfig`.
///
/// Comma-separated secret lists are stored as raw strings and split on demand by the
/// helper methods below (mirroring how `feature-flags` handles `FLAGS_SECRET_KEYS`).
#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3350")]
    pub port: u16,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    /// Primary Fernet keys, comma-separated. Each entry must be exactly 32 bytes.
    /// REQUIRED — the service refuses to start if this yields no usable keys.
    #[envconfig(default = "")]
    pub encryption_salt_keys: String,

    /// Legacy decrypt-only material (values written before the salt-keys rework). Optional.
    #[envconfig(default = "")]
    pub secret_key: String,
    #[envconfig(default = "")]
    pub secret_key_fallbacks: String,
    #[envconfig(default = "0123456789abcdefghijklmnopqrstuvwxyz")]
    pub salt_key: String,

    /// Scoped-JWT verification secret(s) for callers, comma-separated (newest first).
    /// Empty in prod => every request is rejected (fail closed). Do NOT reuse
    /// JWT_SIGNING_KEY / INTERNAL_API_SECRET — this is a dedicated per-purpose secret.
    #[envconfig(default = "")]
    pub integration_gateway_jwt_secret: String,
    #[envconfig(default = "")]
    pub integration_gateway_jwt_secret_fallbacks: String,

    /// In-process decrypted-credential cache. Short TTL is the entire staleness story in v1
    /// (no push invalidation) — safe because Django refreshes tokens well before expiry.
    #[envconfig(default = "30")]
    pub cache_ttl_seconds: u64,
    #[envconfig(default = "50000")]
    pub cache_max_capacity: u64,

    /// Max integration ids accepted in one /fetch request.
    #[envconfig(default = "100")]
    pub max_batch_size: usize,

    // ---- Token refresh (writer) ----
    // Off by default: `refresh_kinds` empty => the gateway never refreshes (pure pass-through) and
    // Django's beat owns all refresh. Enable a kind here AND exclude it from the Django beat
    // (settings.INTEGRATION_GATEWAY_REFRESH_KINDS) so exactly one system refreshes it.
    /// Redis used only for the per-integration refresh single-flight lock.
    #[envconfig(from = "REDIS_URL", default = "redis://localhost:6379/")]
    pub redis_url: String,

    /// TTL (seconds) of the per-integration refresh lock — an upper bound on one refresh attempt.
    #[envconfig(default = "30")]
    pub token_refresh_lock_ttl_seconds: u64,

    /// Integration kinds the gateway refreshes, comma-separated (e.g. "hubspot,salesforce").
    #[envconfig(from = "INTEGRATION_GATEWAY_REFRESH_KINDS", default = "")]
    pub refresh_kinds: String,

    /// Timeout (seconds) for outbound OAuth token-refresh HTTP calls.
    #[envconfig(default = "10")]
    pub refresh_http_timeout_seconds: u64,

    /// Optional override for the OAuth token endpoint used by ALL refreshes. Empty in prod (the
    /// per-provider URLs are used); point at a local mock for e2e testing.
    #[envconfig(default = "")]
    pub refresh_token_url_override: String,

    // Per-provider OAuth client credentials, sourced from the same env vars as
    // posthog/settings/integrations.py so a deployment provisions them once. A kind whose
    // credentials are empty is skipped even if listed in `refresh_kinds`.
    #[envconfig(from = "HUBSPOT_APP_CLIENT_ID", default = "")]
    pub hubspot_client_id: String,
    #[envconfig(from = "HUBSPOT_APP_CLIENT_SECRET", default = "")]
    pub hubspot_client_secret: String,
    #[envconfig(from = "SALESFORCE_CONSUMER_KEY", default = "")]
    pub salesforce_client_id: String,
    #[envconfig(from = "SALESFORCE_CONSUMER_SECRET", default = "")]
    pub salesforce_client_secret: String,
    #[envconfig(from = "GOOGLE_ADS_APP_CLIENT_ID", default = "")]
    pub google_ads_client_id: String,
    #[envconfig(from = "GOOGLE_ADS_APP_CLIENT_SECRET", default = "")]
    pub google_ads_client_secret: String,
    #[envconfig(from = "GOOGLE_ANALYTICS_APP_CLIENT_ID", default = "")]
    pub google_analytics_client_id: String,
    #[envconfig(from = "GOOGLE_ANALYTICS_APP_CLIENT_SECRET", default = "")]
    pub google_analytics_client_secret: String,
    #[envconfig(from = "GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID", default = "")]
    pub google_search_console_client_id: String,
    #[envconfig(from = "GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET", default = "")]
    pub google_search_console_client_secret: String,
    #[envconfig(from = "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY", default = "")]
    pub google_sheets_client_id: String,
    #[envconfig(from = "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET", default = "")]
    pub google_sheets_client_secret: String,
}

fn split_csv(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

impl Config {
    pub fn init() -> Result<Self, envconfig::Error> {
        Self::init_from_env()
    }

    /// Primary Fernet keys (used raw as 32-byte Fernet key material by the decryptor).
    pub fn encryption_salt_keys_list(&self) -> Vec<String> {
        split_csv(&self.encryption_salt_keys)
    }

    /// Legacy secret keys to derive PBKDF2 fallback Fernet keys from (SECRET_KEY + fallbacks).
    pub fn legacy_secret_keys(&self) -> Vec<String> {
        let mut keys = split_csv(&self.secret_key);
        keys.extend(split_csv(&self.secret_key_fallbacks));
        keys
    }

    pub fn salt_keys(&self) -> Vec<String> {
        split_csv(&self.salt_key)
    }

    /// JWT verification secrets, newest first (primary + fallbacks).
    pub fn jwt_secrets(&self) -> Vec<String> {
        let mut keys = split_csv(&self.integration_gateway_jwt_secret);
        keys.extend(split_csv(&self.integration_gateway_jwt_secret_fallbacks));
        keys
    }

    /// Integration kinds the gateway refreshes. Empty => refresh disabled entirely.
    pub fn refresh_kinds_list(&self) -> Vec<String> {
        split_csv(&self.refresh_kinds)
    }
}
