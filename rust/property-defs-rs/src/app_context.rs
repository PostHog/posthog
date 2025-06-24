use health::{HealthHandle, HealthRegistry};
use quick_cache::sync::Cache;
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::{borrow::Cow, collections::HashMap};
use time::Duration;
use tracing::{error, warn};

use crate::{
    api::v1::query::Manager,
    config::Config,
    metrics_consts::{
        GROUP_TYPE_CACHE, GROUP_TYPE_READS, GROUP_TYPE_RESOLVE_TIME, SINGLE_UPDATE_ISSUE_TIME,
        UPDATES_SKIPPED, UPDATE_TRANSACTION_TIME, V2_ISOLATED_DB_SELECTED,
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
    // this points to the (original, shared) CLOUD PG instance
    // in both property-defs-rs and property-defs-rs-v2 deployments.
    // the v2 deployment will use this pool to access tables that
    // aren't slated to migrate to the isolated PROPDEFS DB in production
    pub pool: PgPool,

    // this is only used by the property-defs-rs-v2 deployments, and
    // only when the enabled_v2 config is set. This maps to the new
    // PROPDEFS isolated PG instances in production, and the local
    // Docker Compose DB in dev/test/CI. This will be *UNSET* in
    // "v1" (property-defs-rs) deployments
    pub propdefs_pool: Option<PgPool>,

    pub query_manager: Manager,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub skip_writes: bool,
    pub skip_reads: bool,
    pub group_type_cache: Cache<String, i32>, // Keyed on group-type name, and team id

    // TEMPORARY: used to gate the process_batch_v2 write path until it becomes the new default
    pub enable_v2: bool,

    // this will gate access to code specifically for use in the new mirror deployment
    // and is INDEPENDENT of enable_v2. The main thing it gates at first is use of
    // the new DB client pointed at the isolated Postgres "propdefs" instances in deploy
    pub enable_mirror: bool,
}

impl AppContext {
    pub async fn new(config: &Config, qmgr: Manager) -> Result<Self, sqlx::Error> {
        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let orig_pool = options.connect(&config.database_url).await?;

        let v2_pool = match config.enable_mirror {
            true => {
                let v2_options = PgPoolOptions::new().max_connections(config.max_pg_connections);
                Some(v2_options.connect(&config.database_propdefs_url).await?)
            }
            _ => None,
        };

        let liveness: HealthRegistry = HealthRegistry::new("liveness");
        let worker_liveness = liveness
            .register("worker".to_string(), Duration::seconds(60))
            .await;

        let group_type_cache = Cache::new(config.group_type_cache_size);

        Ok(Self {
            pool: orig_pool,
            propdefs_pool: v2_pool,
            query_manager: qmgr,
            liveness,
            worker_liveness,
            skip_writes: config.skip_writes,
            skip_reads: config.skip_reads,
            group_type_cache,
            enable_v2: config.enable_v2,
            enable_mirror: config.enable_mirror,
        })
    }

    pub async fn issue(&self, updates: &mut [Update]) -> Result<(), sqlx::Error> {
        let group_type_resolve_time = common_metrics::timing_guard(GROUP_TYPE_RESOLVE_TIME, &[]);
        self.resolve_group_types_indexes(updates).await?;
        group_type_resolve_time.fin();

        let transaction_time = common_metrics::timing_guard(UPDATE_TRANSACTION_TIME, &[]);
        if !self.skip_writes && !self.skip_reads {
            // if enable_mirror is TRUE and we are in the mirror deploy: use propdefs write DB.
            let mut write_pool = &self.pool;
            if self.enable_mirror {
                if let Some(resolved) = &self.propdefs_pool {
                    metrics::counter!(
                        V2_ISOLATED_DB_SELECTED,
                        &[(String::from("processor"), String::from("v1"))]
                    )
                    .increment(1);
                    write_pool = resolved;
                }
            }

            let mut tx = write_pool.begin().await?;

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

        // Collect all unresolved group types that need database lookup
        let mut to_resolve: Vec<(usize, String, i32)> = Vec::new();

        // First pass: check cache and collect uncached items
        for (idx, update) in updates.iter_mut().enumerate() {
            let Update::Property(update) = update else {
                continue;
            };
            let Some(GroupType::Unresolved(group_name)) = &update.group_type_index else {
                continue;
            };

            let cache_key = format!("{}:{}", update.team_id, group_name);

            if let Some(index) = self.group_type_cache.get(&cache_key) {
                metrics::counter!(GROUP_TYPE_CACHE, &[("action", "hit")]).increment(1);
                update.group_type_index =
                    update.group_type_index.take().map(|gti| gti.resolve(index));
            } else {
                to_resolve.push((idx, group_name.clone(), update.team_id));
            }
        }

        // Batch resolve all uncached group types
        if !to_resolve.is_empty() {
            metrics::counter!(GROUP_TYPE_READS).increment(to_resolve.len() as u64);

            let (group_names, team_ids): (Vec<String>, Vec<i32>) = to_resolve
                .iter()
                .map(|(_, name, team_id)| (name.clone(), team_id))
                .unzip();

            let results = sqlx::query!(
                "SELECT group_type, team_id, group_type_index FROM posthog_grouptypemapping
                 WHERE (group_type, team_id) = ANY(SELECT * FROM UNNEST($1::text[], $2::int[]))",
                &group_names,
                &team_ids
            )
            .fetch_all(&self.pool)
            .await?;

            // Create a lookup map for resolved group types
            let mut resolved_map: HashMap<(String, i32), i32> =
                HashMap::with_capacity(results.len());
            for result in results {
                resolved_map.insert((result.group_type, result.team_id), result.group_type_index);
            }

            // Second pass: apply resolved group types to updates
            for (idx, group_name, team_id) in to_resolve {
                let cache_key = format!("{}:{}", team_id, group_name);

                if let Some(&index) = resolved_map.get(&(group_name.clone(), team_id)) {
                    metrics::counter!(GROUP_TYPE_CACHE, &[("action", "miss")]).increment(1);
                    self.group_type_cache.insert(cache_key, index);

                    if let Update::Property(update) = &mut updates[idx] {
                        update.group_type_index =
                            update.group_type_index.take().map(|gti| gti.resolve(index));
                    }
                } else {
                    metrics::counter!(GROUP_TYPE_CACHE, &[("action", "fail")]).increment(1);
                    warn!(
                        "Failed to resolve group type index for group name: {} and team id: {}",
                        group_name, team_id
                    );

                    if let Update::Property(update) = &mut updates[idx] {
                        update.group_type_index = None;
                    }
                }
            }
        }

        Ok(())
    }
}
