// Shared by every integration-test binary; each binary compiles its own copy
// and none of them uses every helper.
#![allow(dead_code)]

use std::sync::Arc;

use rand::Rng;
use sqlx::postgres::PgPool;

use personhog_identity::storage::postgres::PostgresIdentityStorage;

pub struct TestContext {
    pub pool: PgPool,
    pub storage: Arc<PostgresIdentityStorage>,
    pub team_id: i64,
}

impl TestContext {
    pub async fn new() -> Self {
        let database_url = std::env::var("DATABASE_URL").unwrap_or_else(|_| {
            "postgres://posthog:posthog@localhost:5432/posthog_persons".to_string()
        });
        let pool = PgPool::connect(&database_url)
            .await
            .expect("Failed to connect to test database");
        let storage = Arc::new(PostgresIdentityStorage::new(pool.clone()));
        let team_id = rand::thread_rng().gen_range(1_000_000..100_000_000);
        Self {
            pool,
            storage,
            team_id,
        }
    }

    /// Inserts a person with a random (non-deterministic) uuid plus a distinct
    /// id row pointing at it. Returns the person id.
    pub async fn insert_person_with_distinct_id(&self, distinct_id: &str) -> i64 {
        let person_id: i64 = sqlx::query_scalar(
            r#"
            INSERT INTO posthog_person
                (created_at, properties, properties_last_updated_at, properties_last_operation,
                 team_id, is_identified, uuid, version)
            VALUES (now(), '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, $1, false, gen_random_uuid(), 0)
            RETURNING id
            "#,
        )
        .bind(self.team_id as i32)
        .fetch_one(&self.pool)
        .await
        .expect("Failed to insert person");

        sqlx::query(
            r#"
            INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
            VALUES ($1, $2, $3, 0)
            "#,
        )
        .bind(distinct_id)
        .bind(person_id)
        .bind(self.team_id as i32)
        .execute(&self.pool)
        .await
        .expect("Failed to insert distinct id");

        person_id
    }

    /// An engine over this context's pool, tuned for tests: short lease and
    /// poll so lease-contention tests run in milliseconds.
    pub fn engine(&self) -> personhog_identity::lifecycle::engine::Engine {
        personhog_identity::lifecycle::engine::Engine::new(
            self.pool.clone(),
            personhog_identity::lifecycle::engine::EngineConfig {
                lease: std::time::Duration::from_secs(5),
                execute_timeout: std::time::Duration::from_secs(10),
                poll_interval: std::time::Duration::from_millis(25),
                attempt_alert_threshold: 5,
            },
        )
    }

    pub async fn cleanup(&self) -> Result<(), sqlx::Error> {
        sqlx::query("DELETE FROM lifecycle_op WHERE team_id = $1")
            .bind(self.team_id as i32)
            .execute(&self.pool)
            .await?;
        sqlx::query("DELETE FROM posthog_persondistinctid WHERE team_id = $1")
            .bind(self.team_id as i32)
            .execute(&self.pool)
            .await?;
        sqlx::query("DELETE FROM posthog_person WHERE team_id = $1")
            .bind(self.team_id as i32)
            .execute(&self.pool)
            .await?;
        Ok(())
    }
}
