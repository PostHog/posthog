use std::collections::HashMap;
use std::sync::Arc;

use sqlx::PgPool;

use super::model::DecryptedIntegration;
use super::repository;
use crate::cache::CredentialCache;
use crate::crypto::{decrypt_sensitive_config, IntegrationDecryptor};
use crate::refresh::RefreshManager;

/// Loads, decrypts, caches, and team-scopes integrations. When a `RefreshManager` is present and
/// owns a row's kind, an expired token is refreshed just-in-time on the DB-load path before it's
/// decrypted and cached (so the cache never holds a stale pre-refresh token).
pub struct IntegrationService {
    pool: PgPool,
    decryptor: IntegrationDecryptor,
    cache: CredentialCache,
    refresh: Option<Arc<RefreshManager>>,
}

/// Outcome of a batch fetch, so the handler can emit an accurate audit line.
pub struct FetchOutcome {
    pub resolved: HashMap<i64, Arc<DecryptedIntegration>>,
    pub cache_hits: usize,
    pub db_loaded: usize,
}

impl IntegrationService {
    pub fn new(
        pool: PgPool,
        decryptor: IntegrationDecryptor,
        cache: CredentialCache,
        refresh: Option<Arc<RefreshManager>>,
    ) -> Self {
        Self {
            pool,
            decryptor,
            cache,
            refresh,
        }
    }

    /// Return the decrypted integrations for `ids` that exist AND belong to `team_id`.
    ///
    /// Ids that are missing, or that belong to another team, are simply absent from the result
    /// (the handler renders them as `null`) — a wrong-team id is indistinguishable from a
    /// non-existent one, so existence can't be probed across teams. This mirrors the CDP's inline
    /// `integration.team_id === hogFunction.team_id` check and batch-exports' `team_id=` filter.
    pub async fn get_for_team(
        &self,
        team_id: i64,
        ids: &[i64],
    ) -> Result<FetchOutcome, sqlx::Error> {
        let mut resolved: HashMap<i64, Arc<DecryptedIntegration>> = HashMap::new();
        let mut misses: Vec<i64> = Vec::new();
        let mut cache_hits = 0usize;

        for &id in ids {
            match self.cache.get(&id).await {
                Some(hit) => {
                    cache_hits += 1;
                    resolved.insert(id, hit);
                }
                None => misses.push(id),
            }
        }

        let mut db_loaded = 0usize;
        if !misses.is_empty() {
            let rows = repository::fetch_by_ids(&self.pool, &misses).await?;
            db_loaded = rows.len();
            for row in rows {
                // Just-in-time refresh for owned kinds before decrypt/cache, so a stale token is
                // never cached. No-op (returns the row unchanged) when refresh is disabled, the kind
                // isn't owned, the token is still fresh, or the refresh fails (fail-open).
                let row = match &self.refresh {
                    Some(manager) if manager.owns(&row.kind) => manager.refresh(row).await,
                    _ => row,
                };
                let decrypted = Arc::new(DecryptedIntegration {
                    id: row.id,
                    team_id: row.team_id,
                    kind: row.kind,
                    config: row.config,
                    sensitive_config: decrypt_sensitive_config(
                        &self.decryptor,
                        &row.sensitive_config,
                    ),
                });
                self.cache.insert(row.id, decrypted.clone()).await;
                resolved.insert(row.id, decrypted);
            }
        }

        // Team-scope isolation: drop anything not owned by the caller's team.
        resolved.retain(|_, v| v.team_id == team_id);

        Ok(FetchOutcome {
            resolved,
            cache_hits,
            db_loaded,
        })
    }
}
