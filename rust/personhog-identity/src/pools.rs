//! The two Postgres pools identity runs on, split by how long a statement
//! holds its connection. Fast: the request path's reads and the lifecycle
//! engine's single-row op bookkeeping, sub-millisecond and never waiting
//! on a person row lock. Heavy: stub creation, distinct id attach, every
//! saga step transaction, and GC, which hold a connection for tens to
//! hundreds of milliseconds and, under lock contention, up to the
//! statement timeout. On one shared pool a burst of heavy statements took
//! every slot the resolves behind them needed.

use std::time::Instant;

use sqlx::pool::PoolConnection;
use sqlx::postgres::PgPool;
use sqlx::{Postgres, Transaction};

use personhog_common::grpc::{current_client_name, current_method_name};

const DB_POOL_ACQUIRE_DURATION: &str = "personhog_identity_db_pool_acquire_duration_ms";

/// Which pool a statement runs on; doubles as the `pool` metric label.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Lane {
    Fast,
    Heavy,
}

impl Lane {
    pub fn label(self) -> &'static str {
        match self {
            Lane::Fast => "fast",
            Lane::Heavy => "heavy",
        }
    }
}

#[derive(Clone)]
pub struct IdentityPools {
    fast: PgPool,
    heavy: PgPool,
}

impl IdentityPools {
    pub fn new(fast: PgPool, heavy: PgPool) -> Self {
        Self { fast, heavy }
    }

    /// One pool behind both lanes, for tests and tooling that run against
    /// a single connection string.
    pub fn shared(pool: PgPool) -> Self {
        Self {
            fast: pool.clone(),
            heavy: pool,
        }
    }

    pub fn fast(&self) -> &PgPool {
        &self.fast
    }

    pub fn heavy(&self) -> &PgPool {
        &self.heavy
    }

    pub fn get(&self, lane: Lane) -> &PgPool {
        match lane {
            Lane::Fast => &self.fast,
            Lane::Heavy => &self.heavy,
        }
    }

    pub async fn acquire(&self, lane: Lane) -> sqlx::Result<PoolConnection<Postgres>> {
        let start = Instant::now();
        let conn = self.get(lane).acquire().await;
        record_acquire(lane, start);
        conn
    }

    pub async fn begin(&self, lane: Lane) -> sqlx::Result<Transaction<'_, Postgres>> {
        let start = Instant::now();
        let tx = self.get(lane).begin().await;
        record_acquire(lane, start);
        tx
    }
}

fn record_acquire(lane: Lane, start: Instant) {
    common_metrics::histogram(
        DB_POOL_ACQUIRE_DURATION,
        &[
            ("pool".to_string(), lane.label().to_string()),
            ("client".to_string(), current_client_name().to_string()),
            ("method".to_string(), current_method_name().to_string()),
        ],
        start.elapsed().as_secs_f64() * 1000.0,
    );
}
