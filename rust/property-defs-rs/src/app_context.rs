use crate::{
    api::v1::query::Manager, config::Config, group_type_resolver::GroupTypeResolver, types::Update,
};
use sqlx::{postgres::PgPoolOptions, PgPool};

pub struct AppContext {
    // this points to the original (shared) CLOUD DB instance in prod deployments
    pub pool: PgPool,

    pub query_manager: Manager,
    pub skip_reads: bool,

    group_type_resolver: GroupTypeResolver,
}

impl AppContext {
    pub async fn new(config: &Config, qmgr: Manager) -> Result<Self, sqlx::Error> {
        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let pool = options.connect(&config.database_url).await?;

        let group_type_resolver = GroupTypeResolver::new(config);

        Ok(Self {
            pool,
            query_manager: qmgr,
            skip_reads: config.skip_reads,
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
