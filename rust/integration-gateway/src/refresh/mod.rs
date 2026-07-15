pub mod expiry;
pub mod providers;

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use common_metrics::inc;
use common_redis::Client as RedisTrait;
use serde::Deserialize;
use serde_json::Value;
use sqlx::PgPool;
use tracing::warn;

use crate::config::Config;
use crate::crypto::IntegrationDecryptor;
use crate::integrations::model::IntegrationRow;
use crate::integrations::repository;
use crate::metrics_consts;

#[derive(Debug, thiserror::Error)]
enum RefreshError {
    #[error(transparent)]
    Sqlx(#[from] sqlx::Error),
    #[error("http error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("provider returned {0}: {1}")]
    Provider(u16, String),
    #[error("integration has no stored refresh_token")]
    NoRefreshToken,
    #[error("provider response had no access_token")]
    NoAccessToken,
}

/// Standard OAuth2 token-refresh response fields we care about.
#[derive(Deserialize)]
struct TokenResponse {
    access_token: Option<String>,
    expires_in: Option<f64>,
    refresh_token: Option<String>,
}

struct RefreshedTokens {
    access_token: String,
    expires_in: Option<f64>,
    refresh_token: Option<String>,
}

/// Owns just-in-time OAuth token refresh for the kinds listed in `refresh_kinds`. Single-flight per
/// integration via a Redis lock, so only one head refreshes a given row at a time — important for
/// providers that rotate the refresh token. Django's beat MUST exclude these kinds.
pub struct RefreshManager {
    pool: PgPool,
    redis: Arc<dyn RedisTrait + Send + Sync>,
    http: reqwest::Client,
    decryptor: IntegrationDecryptor,
    config: Arc<Config>,
    owned_kinds: HashSet<String>,
}

impl RefreshManager {
    pub fn new(
        pool: PgPool,
        redis: Arc<dyn RedisTrait + Send + Sync>,
        decryptor: IntegrationDecryptor,
        config: Arc<Config>,
    ) -> Self {
        let owned_kinds = config.refresh_kinds_list().into_iter().collect();
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(config.refresh_http_timeout_seconds))
            .build()
            .expect("failed to build reqwest client for token refresh");
        Self {
            pool,
            redis,
            http,
            decryptor,
            config,
            owned_kinds,
        }
    }

    pub fn owns(&self, kind: &str) -> bool {
        self.owned_kinds.contains(kind)
    }

    /// Refresh `row` if its access token is past half-life, returning the (possibly updated) row with
    /// re-encrypted credentials. Fail-open: on any error the input row is returned unchanged, so the
    /// read path still serves the existing token (which is still valid — we refresh proactively at
    /// half-life, so an error just means we serve a valid-but-aging token until the next attempt).
    pub async fn refresh(&self, row: IntegrationRow) -> IntegrationRow {
        if !expiry::access_token_expired(&row.kind, &row.config) {
            return row;
        }

        let provider = match providers::provider_for(&row.kind, &self.config) {
            Some(p) => p,
            None => {
                warn!(kind = %row.kind, id = row.id, "refresh requested but no provider/credentials configured; skipping");
                self.record(&row.kind, "skipped");
                return row;
            }
        };

        let lock_key = format!("integration-gateway:refresh-lock:{}", row.id);
        match self
            .redis
            .set_nx_ex(
                lock_key.clone(),
                "1".to_string(),
                self.config.token_refresh_lock_ttl_seconds,
            )
            .await
        {
            Ok(true) => {}
            Ok(false) => {
                // Another head holds the lock; the current token is still valid (half-life refresh).
                self.record(&row.kind, "locked");
                return row;
            }
            Err(e) => {
                warn!(id = row.id, error = %e, "failed to acquire refresh lock; skipping");
                self.record(&row.kind, "skipped");
                return row;
            }
        }

        let result = self.refresh_locked(&row, &provider).await;
        let _ = self.redis.del(lock_key).await;

        match result {
            Ok(updated) => {
                self.record(&row.kind, "refreshed");
                updated
            }
            Err(e) => {
                warn!(id = row.id, kind = %row.kind, error = %e, "token refresh failed");
                if let Err(mark_err) = repository::mark_refresh_failed(&self.pool, row.id).await {
                    warn!(id = row.id, error = %mark_err, "failed to record refresh error");
                }
                self.record(&row.kind, "failed");
                row
            }
        }
    }

    async fn refresh_locked(
        &self,
        row: &IntegrationRow,
        provider: &providers::Provider,
    ) -> Result<IntegrationRow, RefreshError> {
        // Re-read under the lock: a concurrent head (or Django) may have just rotated the token.
        let fresh = repository::fetch_one(&self.pool, row.id)
            .await?
            .unwrap_or_else(|| row.clone());
        if !expiry::access_token_expired(&fresh.kind, &fresh.config) {
            return Ok(fresh);
        }

        let refresh_token = self.decrypt_refresh_token(&fresh)?;
        let tokens = self.request_refresh(provider, &refresh_token).await?;

        // Some providers omit expires_in on refresh; Django assumes 3600s for Salesforce/Stripe.
        let expires_in = match tokens.expires_in {
            Some(v) => Value::from(v),
            None if fresh.kind == "salesforce" || fresh.kind == "stripe" => Value::from(3600),
            None => Value::Null,
        };

        let mut new_config = fresh.config.clone();
        set_key(&mut new_config, "refreshed_at", Value::from(expiry::now_secs() as i64));
        set_key(&mut new_config, "expires_in", expires_in);

        // Overwrite only the rotated leaves; other (still-encrypted) leaves are left untouched.
        let mut new_sensitive = fresh.sensitive_config.clone();
        set_key(
            &mut new_sensitive,
            "access_token",
            Value::String(self.decryptor.encrypt_leaf(&tokens.access_token)),
        );
        if let Some(rotated) = &tokens.refresh_token {
            set_key(
                &mut new_sensitive,
                "refresh_token",
                Value::String(self.decryptor.encrypt_leaf(rotated)),
            );
        }

        repository::update_after_refresh(&self.pool, fresh.id, &new_config, &new_sensitive).await?;

        Ok(IntegrationRow {
            config: new_config,
            sensitive_config: new_sensitive,
            ..fresh
        })
    }

    fn decrypt_refresh_token(&self, row: &IntegrationRow) -> Result<String, RefreshError> {
        let encrypted = row
            .sensitive_config
            .get("refresh_token")
            .and_then(Value::as_str)
            .ok_or(RefreshError::NoRefreshToken)?;
        self.decryptor
            .decrypt_leaf(encrypted)
            .ok_or(RefreshError::NoRefreshToken)
    }

    async fn request_refresh(
        &self,
        provider: &providers::Provider,
        refresh_token: &str,
    ) -> Result<RefreshedTokens, RefreshError> {
        let response = self
            .http
            .post(&provider.token_url)
            .form(&[
                ("grant_type", "refresh_token"),
                ("refresh_token", refresh_token),
                ("client_id", provider.client_id.as_str()),
                ("client_secret", provider.client_secret.as_str()),
            ])
            .send()
            .await?;

        let status = response.status();
        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(RefreshError::Provider(status.as_u16(), body));
        }

        let parsed: TokenResponse = response.json().await?;
        let access_token = parsed.access_token.ok_or(RefreshError::NoAccessToken)?;
        Ok(RefreshedTokens {
            access_token,
            expires_in: parsed.expires_in,
            refresh_token: parsed.refresh_token,
        })
    }

    fn record(&self, kind: &str, result: &str) {
        inc(
            metrics_consts::REFRESH_TOTAL,
            &[
                ("kind".to_string(), kind.to_string()),
                ("result".to_string(), result.to_string()),
            ],
            1,
        );
    }
}

/// Insert/overwrite a key on a JSON object, coercing a non-object into a fresh object first.
/// `config`/`sensitive_config` are always objects in practice, but stay defensive.
fn set_key(value: &mut Value, key: &str, new: Value) {
    if !value.is_object() {
        *value = Value::Object(serde_json::Map::new());
    }
    if let Value::Object(map) = value {
        map.insert(key.to_string(), new);
    }
}
