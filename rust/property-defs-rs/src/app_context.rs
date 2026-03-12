use health::{HealthHandle, HealthRegistry};
use sqlx::{postgres::PgPoolOptions, PgPool};
use time::Duration;
use tracing::info;

use crate::{
    api::v1::query::Manager, config::Config, group_type_resolver::GroupTypeResolver, types::Update,
};

pub struct AppContext {
    // this points to the original (shared) CLOUD DB instance in prod deployments
    pub pool: PgPool,

    // if populated, this pool will be used to read from the new, isolated
    // persons DB instance in production. call sites will fall back to the
    // std (shared) pool above if this is unset
    pub persons_pool: Option<PgPool>,

    pub query_manager: Manager,
    pub liveness: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub skip_writes: bool,
    pub skip_reads: bool,

    // sentinel flag used to identify the "mirror" deployments (property-defs-rs-v2) in
    // production environments to special case code that only works in those envs. Primary
    // use so far is to condition which database the service writes to. When disabled, it
    // targets the shared PostHog cloud DB. When enabled, it targets the new, isolated
    // property definitions database instace.
    pub enable_mirror: bool,

    group_type_resolver: GroupTypeResolver,
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

        let group_type_resolver = GroupTypeResolver::new(config);

        Ok(Self {
            pool: orig_pool,
            persons_pool,
            query_manager: qmgr,
            liveness,
            worker_liveness,
            skip_writes: config.skip_writes,
            skip_reads: config.skip_reads,
            enable_mirror: config.enable_mirror,
            group_type_resolver,
        })
    }

    pub async fn resolve_group_types_indexes(
        &self,
        updates: &mut [Update],
    ) -> Result<(), anyhow::Error> {
        if self.skip_reads {
            return Ok(());
        }
        self.group_type_resolver
            .resolve(updates, &self.pool, self.persons_pool.as_ref())
            .await
    }
}
