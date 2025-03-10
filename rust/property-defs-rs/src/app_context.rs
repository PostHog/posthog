use health::{HealthHandle, HealthRegistry};
use quick_cache::sync::Cache;
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::borrow::Cow;
use time::Duration;
use tracing::{error, warn};

use crate::{
    api::v1::query::Manager,
    config::Config,
    metrics_consts::{
        CACHE_WARMING_STATE, GROUP_TYPE_CACHE, GROUP_TYPE_READS, UPDATES_CACHE_EVICTION,
        UPDATE_STORED, UPDATE_TRANSACTION_TIME,
    },
    types::{GroupType, Update},
};

// cribbed from this list https://www.postgresql.org/docs/current/errcodes-appendix.html
// while these errors and their causes will differ, none of them should force a single
// point-write to an Update to abort a whole batch write operation
const PG_CONSTRAINT_CODES: [&str; 7] = [
    "23000", "23001", "23502", "23503", "23505", "23515", "23P01",
];

const UPDATE_MAX_ATTEMPTS: u64 = 3;
const UPDATE_RETRY_DELAY_MS: u64 = 50;

pub struct AppContext {
    pub pool: PgPool,
    pub query_manager: Manager,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub cache_warming_delay: Duration,
    pub cache_warming_cutoff: f64,
    pub skip_writes: bool,
    pub skip_reads: bool,
    pub updates_cache: Cache<Update, ()>,
    pub group_type_cache: Cache<String, i32>, // Keyed on group-type name, and team id
}

impl AppContext {
    pub async fn new(config: &Config, qmgr: Manager) -> Result<Self, sqlx::Error> {
        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let pool = options.connect(&config.database_url).await?;

        let liveness: HealthRegistry = HealthRegistry::new("liveness");
        let worker_liveness = liveness
            .register("worker".to_string(), Duration::seconds(60))
            .await;

        let updates_cache = Cache::new(config.cache_capacity);

        let group_type_cache = Cache::new(config.group_type_cache_size);

        Ok(Self {
            pool,
            query_manager: qmgr,
            liveness,
            worker_liveness,
            cache_warming_delay: Duration::milliseconds(config.cache_warming_delay_ms as i64),
            cache_warming_cutoff: 0.9,
            skip_writes: config.skip_writes,
            skip_reads: config.skip_reads,
            updates_cache,
            group_type_cache,
        })
    }

    pub async fn issue(&self, updates: Vec<Update>, cache_consumed: f64) {
        if cache_consumed < self.cache_warming_cutoff {
            metrics::gauge!(CACHE_WARMING_STATE, &[("state", "warming")]).set(cache_consumed);
            let to_sleep = self.cache_warming_delay * (1.0 - cache_consumed) as i32;
            tokio::time::sleep(to_sleep.try_into().unwrap()).await;
        } else {
            metrics::gauge!(CACHE_WARMING_STATE, &[("state", "hot")]).set(1.0);
        }

        // TODO(eli): I didn't bother to change the metric name here but yes, this is no longer a transaction
        let update_batch_time = common_metrics::timing_guard(UPDATE_TRANSACTION_TIME, &[]);
        if !self.skip_writes && !self.skip_reads {
            for update in updates {
                let mut tries: u64 = 1;
                loop {
                    let result = update.issue(&self.pool).await;
                    match result {
                        Ok(_) => {
                            metrics::counter!(UPDATE_STORED, &[("result", "success")],);
                            continue;
                        }

                        Err(sqlx::Error::Database(e))
                            if e.constraint().is_some()
                                || self.is_pg_constraint_error(&e.code()) =>
                        {
                            // If we hit a constraint violation, we just skip the update. We see
                            // this in production for group-type-indexes not being resolved, and it's
                            // not worth aborting the whole batch for.
                            self.remove_from_cache(&update);
                            let tags = [
                                ("result", "constraint_violation".to_string()),
                                ("attempt", AppContext::format_attempt(tries)),
                            ];
                            metrics::counter!(UPDATE_STORED, &tags).increment(1);
                            warn!("Issue update failed on DB constraint: {:?}", e);
                            continue;
                        }

                        Err(e) => {
                            self.remove_from_cache(&update);
                            let tags = [
                                ("result", "error".to_string()),
                                ("attempt", AppContext::format_attempt(tries)),
                            ];
                            metrics::counter!(UPDATE_STORED, &tags).increment(1);
                            error!("Issue update failed on error: {:?}", e);
                        }
                    }

                    if tries < UPDATE_MAX_ATTEMPTS {
                        let jitter = rand::random::<u64>() % 50;
                        let delay: u64 = tries * UPDATE_RETRY_DELAY_MS + jitter;
                        tries += 1;
                        tokio::time::sleep(std::time::Duration::from_millis(delay)).await;
                    } else {
                        error!("Issue update retries exhausted, skipping");
                        break;
                    }
                }
            }
        }
        update_batch_time.fin();
    }

    fn format_attempt(tries: u64) -> String {
        if tries < UPDATE_MAX_ATTEMPTS {
            return tries.to_string();
        }

        "failed".to_string()
    }

    fn remove_from_cache(&self, u: &Update) {
        // Clear the failed update from the cache, so that if
        // we see it again, we'll try again to store it ASAP
        if self.updates_cache.remove(u).is_some() {
            metrics::counter!(UPDATES_CACHE_EVICTION, &[("action", "removed")]).increment(1);
        } else {
            metrics::counter!(UPDATES_CACHE_EVICTION, &[("action", "not_cached")]).increment(1);
        }
    }

    fn is_pg_constraint_error(&self, pg_code: &Option<Cow<'_, str>>) -> bool {
        match pg_code {
            Some(code) => PG_CONSTRAINT_CODES.contains(&code.as_ref()),
            None => false,
        }
    }

    pub async fn resolve_group_types_indexes(
        &self,
        updates: &mut [Update],
    ) -> Result<(), sqlx::Error> {
        if self.skip_reads {
            return Ok(());
        }

        for update in updates {
            // Only property definitions have group types
            let Update::Property(update) = update else {
                continue;
            };
            // If we didn't find a group type, we have nothing to resolve.
            let Some(GroupType::Unresolved(group_name)) = &update.group_type_index else {
                continue;
            };

            let cache_key = format!("{}:{}", update.team_id, group_name);

            let cached = self.group_type_cache.get(&cache_key);
            if let Some(index) = cached {
                metrics::counter!(GROUP_TYPE_CACHE, &[("action", "hit")]).increment(1);
                update.group_type_index =
                    update.group_type_index.take().map(|gti| gti.resolve(index));
                continue;
            }

            metrics::counter!(GROUP_TYPE_READS).increment(1);

            let found = sqlx::query_scalar!(
                    "SELECT group_type_index FROM posthog_grouptypemapping WHERE group_type = $1 AND team_id = $2",
                    group_name,
                    update.team_id
                )
                .fetch_optional(&self.pool)
                .await?;

            if let Some(index) = found {
                metrics::counter!(GROUP_TYPE_CACHE, &[("action", "miss")]).increment(1);
                self.group_type_cache.insert(cache_key, index);
                update.group_type_index =
                    update.group_type_index.take().map(|gti| gti.resolve(index));
            } else {
                metrics::counter!(GROUP_TYPE_CACHE, &[("action", "fail")]).increment(1);
                error!(
                    "Failed to resolve group type index for group name: {} and team id: {}",
                    group_name, update.team_id
                );
                // If we fail to resolve a group type, we just don't write it
                update.group_type_index = None;
            }
        }
        Ok(())
    }
}
