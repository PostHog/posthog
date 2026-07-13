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
}
