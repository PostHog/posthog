use std::{sync::Arc, time::Duration};

use common_database::{install_writer_guard, WriterGuard, WriterGuardConfig};
use rand::Rng;
use sqlx::{postgres::PgPoolOptions, PgPool};

use crate::{
    api::v1::query::Manager, config::Config, group_type_resolver::GroupTypeResolver, types::Update,
};

pub struct AppContext {
    // this points to the original (shared) CLOUD DB instance in prod deployments
    pub pool: PgPool,

    pub query_manager: Manager,
    pub skip_reads: bool,

    group_type_resolver: GroupTypeResolver,
}

impl AppContext {
    pub async fn new(config: &Config, qmgr: Manager) -> Result<Self, sqlx::Error> {
        let pool = build_write_pool(config).await?;

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

/// Builds the definition-write pool. Every connection here writes, so the writer guard keeps
/// the pool off a demoted Aurora reader, which a liveness ping cannot detect. The guard replaces
/// that ping rather than adding to it.
async fn build_write_pool(config: &Config) -> Result<PgPool, sqlx::Error> {
    let guard = WriterGuard::new(WriterGuardConfig {
        pool_name: Some(Arc::from("propdefs_write")),
        ..Default::default()
    });

    let options = PgPoolOptions::new()
        .max_connections(config.max_pg_connections)
        .max_lifetime(jittered_max_lifetime(config.pg_max_lifetime_secs));

    install_writer_guard(options, &guard)
        .connect(&config.database_url)
        .await
}

/// Spreads connection expiry across pods. sqlx compares age against `max_lifetime` exactly, so
/// without jitter every pod reconnects in lockstep. Drawn once per process.
fn jittered_max_lifetime(base_secs: u64) -> Duration {
    let spread = base_secs / 5;
    let jitter = if spread == 0 {
        0
    } else {
        rand::thread_rng().gen_range(0..=spread)
    };
    Duration::from_secs(base_secs + jitter)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jitter_stays_within_a_fifth_above_the_base() {
        for _ in 0..1000 {
            let got = jittered_max_lifetime(300);
            assert!(
                got >= Duration::from_secs(300) && got <= Duration::from_secs(360),
                "{got:?} outside 300..=360s"
            );
        }
    }

    #[test]
    fn tiny_lifetimes_do_not_panic_on_an_empty_jitter_range() {
        // spread == 0, which an exclusive range would panic on.
        assert_eq!(jittered_max_lifetime(4), Duration::from_secs(4));
        assert_eq!(jittered_max_lifetime(0), Duration::from_secs(0));
    }
}
