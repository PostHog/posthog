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
        CACHE_WARMING_STATE, GROUP_TYPE_CACHE, GROUP_TYPE_READS, GROUP_TYPE_RESOLVE_TIME,
        SINGLE_UPDATE_ISSUE_TIME, UPDATES_SKIPPED, UPDATE_TRANSACTION_TIME,
    },
    types::{GroupType, Update},
};

// cribbed from this list https://www.postgresql.org/docs/current/errcodes-appendix.html
// while these errors and their causes will differ, none of them should force a single
// point-write to an Update to abort a whole batch write operation
const PG_CONSTRAINT_CODES: [&str; 7] = [
    "23000", "23001", "23502", "23503", "23505", "23515", "23P01",
];

pub struct AppContext {
    pub pool: PgPool,
    pub query_manager: Manager,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub cache_warming_delay: Duration,
    pub cache_warming_cutoff: f64,
    pub skip_writes: bool,
    pub skip_reads: bool,
    pub group_type_cache: Cache<String, i32>, // Keyed on group-type name, and team id
    pub enable_v2: bool,
}

impl AppContext {
    pub async fn new(config: &Config, qmgr: Manager) -> Result<Self, sqlx::Error> {
        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let pool = options.connect(&config.database_url).await?;

        let liveness: HealthRegistry = HealthRegistry::new("liveness");
        let worker_liveness = liveness
            .register("worker".to_string(), Duration::seconds(60))
            .await;

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
            group_type_cache,
            enable_v2: config.enable_v2,
        })
    }

    pub async fn issue(
        &self,
        updates: &mut [Update],
        cache_consumed: f64,
    ) -> Result<(), sqlx::Error> {
        if cache_consumed < self.cache_warming_cutoff {
            metrics::gauge!(CACHE_WARMING_STATE, &[("state", "warming")]).set(cache_consumed);
            let to_sleep = self.cache_warming_delay * (1.0 - cache_consumed);
            tokio::time::sleep(to_sleep.try_into().unwrap()).await;
        } else {
            metrics::gauge!(CACHE_WARMING_STATE, &[("state", "hot")]).set(1.0);
        }

        let group_type_resolve_time = common_metrics::timing_guard(GROUP_TYPE_RESOLVE_TIME, &[]);
        self.resolve_group_types_indexes(updates).await?;
        group_type_resolve_time.fin();

        let transaction_time = common_metrics::timing_guard(UPDATE_TRANSACTION_TIME, &[]);
        if !self.skip_writes && !self.skip_reads {
            let mut tx = self.pool.begin().await?;

            for update in updates {
                let issue_time = common_metrics::timing_guard(SINGLE_UPDATE_ISSUE_TIME, &[]);
                match update.issue(&mut *tx).await {
                    Ok(_) => issue_time.label("outcome", "success"),
                    Err(sqlx::Error::Database(e))
                        if e.constraint().is_some() || self.is_pg_constraint_error(&e.code()) =>
                    {
                        // If we hit a constraint violation, we just skip the update. We see
                        // this in production for group-type-indexes not being resolved, and it's
                        // not worth aborting the whole batch for.
                        metrics::counter!(UPDATES_SKIPPED, &[("reason", "constraint_violation")])
                            .increment(1);
                        warn!("Failed to issue update: {:?}", e);
                        issue_time.label("outcome", "skipped")
                        // for now, we can leave the failed write in the parent Update cache, since these won't
                        // be helped by additional retries. an hour w/o write attempts is a good thing for these
                    }
                    Err(e) => {
                        // TODO(eli): move retry behavior (and cache removal) here and out of parent batch?
                        // depends on what kind of errors we see landing here now that it's instrumented,
                        // and we're (hopefully) catching the frequent constraint errors above
                        metrics::counter!(UPDATES_SKIPPED, &[("reason", "unhandled_fail")])
                            .increment(1);
                        error!(
                            "Unhandled issue update error, bubbling up to batch: {:?}",
                            e
                        );
                        tx.rollback().await?;
                        issue_time.label("outcome", "abort");
                        return Err(e);
                    }
                }
                .fin();
            }
            tx.commit().await?;
        }
        transaction_time.fin();

        Ok(())
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
                warn!(
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
