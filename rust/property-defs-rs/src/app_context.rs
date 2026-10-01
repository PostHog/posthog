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

    // Reader pool for the read-before-write filter; None when the feature is off.
    // No writer guard: these connections only ever read.
    pub read_pool: Option<PgPool>,

    pub query_manager: Manager,
    pub skip_reads: bool,

    group_type_resolver: GroupTypeResolver,
}

impl AppContext {
    pub async fn new(config: &Config, qmgr: Manager) -> Result<Self, sqlx::Error> {
        let pool = build_write_pool(config).await?;

        let read_pool = if config.read_before_write_enabled {
            let read_url = if config.database_read_url.is_empty() {
                &config.database_url
            } else {
                &config.database_read_url
            };
            Some(read_pool_options(config).connect_lazy(read_url)?)
        } else {
            None
        };

        let group_type_resolver = GroupTypeResolver::new(config);

        Ok(Self {
            pool,
            read_pool,
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

/// Options for the read-before-write pool. The client drops a probe at
/// `read_before_write_timeout_ms`, but Postgres keeps running it, so the same budget is set as
/// the server-side `statement_timeout` to cancel the abandoned query on the reader too.
fn read_pool_options(config: &Config) -> PgPoolOptions {
    let statement_timeout_ms = config.read_before_write_timeout_ms;
    PgPoolOptions::new()
        .max_connections(config.max_pg_connections)
        .max_lifetime(jittered_max_lifetime(config.pg_max_lifetime_secs))
        .after_connect(move |conn, _meta| {
            Box::pin(async move {
                // SET takes no bind parameters; the value is a u64, so format! is safe.
                sqlx::query(&format!("SET statement_timeout = {statement_timeout_ms}"))
                    .execute(conn)
                    .await?;
                Ok(())
            })
        })
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

    #[sqlx::test(migrations = false)]
    async fn read_pool_cancels_probes_that_outlive_the_budget(db: PgPool) {
        let mut config = Config::init_with_defaults().unwrap();
        config.read_before_write_timeout_ms = 100;
        let read_pool = read_pool_options(&config)
            .connect_with((*db.connect_options()).clone())
            .await
            .unwrap();

        let err = sqlx::query("SELECT pg_sleep(5)")
            .execute(&read_pool)
            .await
            .unwrap_err();

        let code = err.as_database_error().and_then(|e| e.code());
        assert_eq!(code.as_deref(), Some("57014"), "{err}");
    }

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
