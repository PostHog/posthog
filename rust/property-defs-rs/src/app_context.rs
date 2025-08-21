use health::{HealthHandle, HealthRegistry};
use quick_cache::sync::Cache;
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::collections::HashMap;
use time::Duration;
use tracing::warn;

use crate::{
    api::v1::query::Manager,
    config::Config,
    metrics_consts::{GROUP_TYPE_CACHE, GROUP_TYPE_READS},
    types::{GroupType, Update},
};

pub struct AppContext {
    // this points to the original (shared) CLOUD DB instance in prod deployments.
    // once the persons and groups tables are migrated, this will become the single
    // database used in the service again.
    pub pool: PgPool,

    // if config.dual_writes_enabled is true and this is not None, we will dual write
    // to this pool for every update we issue during the persons and groups migration.
    pub persons_pool: Option<PgPool>,

    // should we dual write to the new and old DBs when updating persons tables?
    pub dual_writes_enabled: bool,

    pub query_manager: Manager,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub skip_writes: bool,
    pub skip_reads: bool,
    pub group_type_cache: Cache<String, i32>, // Keyed on group-type name, and team id
}

impl AppContext {
    pub async fn new(config: &Config, qmgr: Manager) -> Result<Self, sqlx::Error> {
        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let orig_pool = options.connect(&config.database_url).await?;

        // only to be populated and used if DATABASE_PERSONS_URL is set in the deploy env
        // indicating we should read posthog_grouptypemappings from the new persons DB
        let persons_options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let persons_pool: Option<PgPool> = if config.database_persons_url.is_some() {
            Some(
                persons_options
                    .connect(config.database_persons_url.as_ref().unwrap())
                    .await?,
            )
        } else {
            None
        };

        let liveness: HealthRegistry = HealthRegistry::new("liveness");
        let worker_liveness = liveness
            .register("worker".to_string(), Duration::seconds(60))
            .await;

        let group_type_cache = Cache::new(config.group_type_cache_size);

        Ok(Self {
            pool: orig_pool,
            persons_pool,
            dual_writes_enabled: config.dual_writes_enabled,
            query_manager: qmgr,
            liveness,
            worker_liveness,
            skip_writes: config.skip_writes,
            skip_reads: config.skip_reads,
            group_type_cache,
        })
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

        // Batch resolve all uncached group types; for now, alwayds read from
        // the main pool (original cloud DB) until we've completed the persons
        // and groups migration to new DB and this becomes the new DB.
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
                let cache_key = format!("{team_id}:{group_name}");

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
                        "Failed to resolve group type index for group name: {group_name} and team id: {team_id}"
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
