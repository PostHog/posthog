use crate::{
    api::v1::query::Manager, config::Config, group_type_resolver::GroupTypeResolver, types::Update,
};
use health::{HealthHandle, HealthRegistry};
use sqlx::{postgres::PgPoolOptions, PgPool};
use time::Duration;

pub struct AppContext {
    // this points to the original (shared) CLOUD DB instance in prod deployments
    pub pool: PgPool,

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
        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let pool = options.connect(&config.database_url).await?;

        let liveness: HealthRegistry = HealthRegistry::new("liveness");
        let worker_liveness = liveness
            .register("worker".to_string(), Duration::seconds(60))
            .await;

        let group_type_resolver = GroupTypeResolver::new(config);

        Ok(Self {
            pool,
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
        self.group_type_resolver.resolve(updates).await
    }
}
