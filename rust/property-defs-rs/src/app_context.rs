use health::{HealthHandle, HealthRegistry};
use quick_cache::sync::Cache;
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::collections::HashMap;
use time::Duration;
use tracing::{info, warn};

use crate::{
    api::v1::query::Manager,
    config::Config,
    metrics_consts::{GROUP_TYPE_CACHE, GROUP_TYPE_READS},
    types::{GroupType, Update},
};

pub struct AppContext {
    // this points to the original (shared) CLOUD DB instance in prod deployments
    pub pool: PgPool,

    // when true, the service will point group type mappings resolution
    // to the new persons DB. if false, falls back to std cloud DB pool.
    pub read_groups_from_persons_db: bool,

    // if populated, this pool will be used to read from the new, isolated
    // persons DB instance in production. call sites will fall back to the
    // std (shared) pool above if this is unset
    pub persons_pool: Option<PgPool>,

    pub query_manager: Manager,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub skip_writes: bool,
    pub skip_reads: bool,
    pub group_type_cache: Cache<String, i32>, // Keyed on group-type name, and team id

    // sentinel flag used to identify the "mirror" deployments (property-defs-rs-v2) in
    // production environments to special case code that only works in those envs. Primary
    // use so far is to condition which database the service writes to. When disabled, it
    // targets the shared PostHog cloud DB. When enabled, it targets the new, isolated
    // property definitions database instace.
    pub enable_mirror: bool,
}

impl AppContext {
    pub async fn new(config: &Config, qmgr: Manager) -> Result<Self, sqlx::Error> {
        // This is where writes to propdefs tables will be routed. Since we're not
        // migrating these tables, this pool will always be used on the write path.
        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let orig_pool = options.connect(&config.database_url).await?;

        // this pool is only created if DATABASE_PERSONS_URL is set in the deploy env.
        // if the read_groups_from_persons_db flag is set, we will use this pool to
        // read posthog_grouptypemappings from the new persons DB. Otherwise, we
        // fall back to the std. cloud DB pool above.
        let persons_options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let persons_pool: Option<PgPool> =
            if config.read_groups_from_persons_db && !config.database_persons_url.is_empty() {
                info!("Creating persons DB connection pool (read_groups_from_persons_db=true)");
                let pool = persons_options
                    .connect(&config.database_persons_url)
                    .await?;
                info!("Successfully created persons DB connection pool");
                Some(pool)
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
            read_groups_from_persons_db: config.read_groups_from_persons_db,
            persons_pool,
            query_manager: qmgr,
            liveness,
            worker_liveness,
            skip_writes: config.skip_writes,
            skip_reads: config.skip_reads,
            group_type_cache,
            enable_mirror: config.enable_mirror,
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

        // Batch resolve all uncached group types
        if !to_resolve.is_empty() {
            let tag_value = if self.read_groups_from_persons_db {
                "persons"
            } else {
                "cloud"
            };
            metrics::counter!(GROUP_TYPE_READS, &[("src_db", tag_value)])
                .increment(to_resolve.len() as u64);

            let (group_names, team_ids): (Vec<String>, Vec<i32>) = to_resolve
                .iter()
                .map(|(_, name, team_id)| (name.clone(), team_id))
                .unzip();

            let resolved_pool = if self.read_groups_from_persons_db && self.persons_pool.is_some() {
                self.persons_pool.as_ref().unwrap()
            } else {
                &self.pool
            };

            let results = sqlx::query!(
                "SELECT group_type, team_id, group_type_index FROM posthog_grouptypemapping
                 WHERE (group_type, team_id) = ANY(SELECT * FROM UNNEST($1::text[], $2::int[]))",
                &group_names,
                &team_ids
            )
            .fetch_all(resolved_pool)
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
