use std::collections::HashMap;

use dashmap::DashMap;
use sqlx::PgPool;

/// Resolves capture tokens to team ids against the app database read replica.
/// Tokens are effectively immutable, so hits and misses are cached for the
/// process lifetime. With no pool configured, every token resolves to `None`.
pub struct TeamResolver {
    pool: Option<PgPool>,
    cache: DashMap<String, Option<i32>>,
}

impl TeamResolver {
    pub fn new(pool: Option<PgPool>) -> Self {
        Self {
            pool,
            cache: DashMap::new(),
        }
    }

    pub async fn resolve(&self, tokens: &[String]) -> HashMap<String, Option<i32>> {
        let mut resolved: HashMap<String, Option<i32>> = HashMap::new();
        let mut misses: Vec<String> = Vec::new();
        for token in tokens {
            match self.cache.get(token) {
                Some(entry) => {
                    resolved.insert(token.clone(), *entry.value());
                }
                None => misses.push(token.clone()),
            }
        }

        let Some(pool) = &self.pool else {
            for token in misses {
                resolved.insert(token, None);
            }
            return resolved;
        };

        if !misses.is_empty() {
            match sqlx::query_as::<_, (i32, String)>(
                "SELECT id, api_token FROM posthog_team WHERE api_token = ANY($1)",
            )
            .bind(&misses)
            .fetch_all(pool)
            .await
            {
                Ok(rows) => {
                    let found: HashMap<String, i32> =
                        rows.into_iter().map(|(id, token)| (token, id)).collect();
                    for token in misses {
                        let team_id = found.get(&token).copied();
                        self.cache.insert(token.clone(), team_id);
                        resolved.insert(token, team_id);
                    }
                }
                Err(e) => {
                    // Team resolution is best-effort enrichment; the analysis
                    // is still useful without it.
                    tracing::warn!(error = %e, "token -> team resolution failed");
                    for token in misses {
                        resolved.insert(token, None);
                    }
                }
            }
        }

        resolved
    }
}
