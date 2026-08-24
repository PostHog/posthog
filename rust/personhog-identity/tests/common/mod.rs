// Shared by every integration-test binary; each binary compiles its own copy
// and none of them uses every helper.
#![allow(dead_code)]

pub mod sim_leader;

use std::sync::Arc;

use rand::Rng;
use sqlx::postgres::PgPool;

use personhog_identity::config::IdentityTables;
use personhog_identity::storage::postgres::PostgresIdentityStorage;

/// The production table set. Most tests run here; the raw-SQL assertion
/// helpers in the test binaries assume it.
pub fn default_tables() -> IdentityTables {
    IdentityTables::real()
}

/// The validation (shadow) table set — the service's config default.
pub fn tmp_tables() -> IdentityTables {
    IdentityTables::validation()
}

pub struct TestContext {
    pub pool: PgPool,
    pub storage: Arc<PostgresIdentityStorage>,
    pub team_id: i64,
    pub tables: IdentityTables,
}

impl TestContext {
    pub async fn new() -> Self {
        Self::new_with_tables(default_tables()).await
    }

    pub async fn new_with_tables(tables: IdentityTables) -> Self {
        let database_url = std::env::var("DATABASE_URL").unwrap_or_else(|_| {
            "postgres://posthog:posthog@localhost:5432/posthog_persons".to_string()
        });
        let pool = PgPool::connect(&database_url)
            .await
            .expect("Failed to connect to test database");
        let storage = Arc::new(PostgresIdentityStorage::new(pool.clone(), tables.clone()));
        let team_id = rand::thread_rng().gen_range(1_000_000..100_000_000);
        Self {
            pool,
            storage,
            team_id,
            tables,
        }
    }

    /// Inserts a person with a random (non-deterministic) uuid plus a distinct
    /// id row pointing at it. Returns the person id.
    pub async fn insert_person_with_distinct_id(&self, distinct_id: &str) -> i64 {
        let insert_sql = format!(
            r#"
            INSERT INTO {}
                (created_at, properties, properties_last_updated_at, properties_last_operation,
                 team_id, is_identified, uuid, version)
            VALUES (now(), '{{}}'::jsonb, '{{}}'::jsonb, '{{}}'::jsonb, $1, false, gen_random_uuid(), 0)
            RETURNING id
            "#,
            self.tables.person
        );
        let person_id: i64 = sqlx::query_scalar(&insert_sql)
            .bind(self.team_id as i32)
            .fetch_one(&self.pool)
            .await
            .expect("Failed to insert person");

        let pdi_sql = format!(
            r#"
            INSERT INTO {} (distinct_id, person_id, team_id, version)
            VALUES ($1, $2, $3, 0)
            "#,
            self.tables.person_distinct_id
        );
        sqlx::query(&pdi_sql)
            .bind(distinct_id)
            .bind(person_id)
            .bind(self.team_id as i32)
            .execute(&self.pool)
            .await
            .expect("Failed to insert distinct id");

        person_id
    }

    /// An engine over this context's pool, tuned for tests: a short poll
    /// so contention tests run in milliseconds, and a lease long enough
    /// that a live test's op never looks expired to the suite's single
    /// sweep test (in lifecycle_merge_tests), which would otherwise claim
    /// and drive it with the wrong harness. Lease-expiry tests seed
    /// explicit lease_expires_at values instead of waiting this out.
    pub fn engine(&self) -> personhog_identity::lifecycle::engine::Engine {
        personhog_identity::lifecycle::engine::Engine::new(
            self.pool.clone(),
            personhog_identity::lifecycle::engine::EngineConfig {
                lease: std::time::Duration::from_secs(300),
                execute_timeout: std::time::Duration::from_secs(10),
                poll_interval: std::time::Duration::from_millis(25),
                attempt_alert_threshold: 5,
            },
        )
    }

    /// Parks the tmp person sequence in a random high range. Collision
    /// tests insert a real posthog_person row with a tmp person's numeric
    /// id; without this the explicit-id insert could race another test's
    /// sequence-assigned real id.
    pub async fn park_tmp_person_sequence(&self) {
        let base: i64 = rand::thread_rng().gen_range(1_000_000_000_000..2_000_000_000_000);
        sqlx::query("SELECT setval('personhog_person_tmp_id_seq', $1)")
            .bind(base)
            .execute(&self.pool)
            .await
            .expect("park tmp person sequence");
    }

    /// Seeds this team's rows in the *real* namespace keyed by the given
    /// numeric person id: a posthog_person row plus a mapping row and a
    /// hash-key override referencing it. Validation-set tests plant these
    /// so a leftover hardcoded real table in a saga query would visibly
    /// destroy or move them.
    pub async fn seed_real_namespace_collision(&self, person_id: i64, distinct_id: &str) {
        sqlx::query(
            r#"
            INSERT INTO posthog_person
                (id, created_at, properties, properties_last_updated_at,
                 properties_last_operation, team_id, is_identified, uuid, version)
            VALUES ($1, now(), '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, $2, false,
                    gen_random_uuid(), 0)
            "#,
        )
        .bind(person_id)
        .bind(self.team_id as i32)
        .execute(&self.pool)
        .await
        .expect("insert colliding real person");
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
        .expect("insert colliding real mapping");
        sqlx::query(
            r#"
            INSERT INTO posthog_featureflaghashkeyoverride
                (feature_flag_key, hash_key, person_id, team_id)
            VALUES ('flag', 'real-hash', $1, $2)
            "#,
        )
        .bind(person_id)
        .bind(self.team_id as i32)
        .execute(&self.pool)
        .await
        .expect("insert colliding real override");
    }

    /// Removes this team's rows from the real namespace tables — the
    /// counterpart of [`seed_real_namespace_collision`] for validation-set
    /// tests, whose [`cleanup`](Self::cleanup) only touches the configured
    /// tables.
    pub async fn cleanup_real_namespace(&self) -> Result<(), sqlx::Error> {
        sqlx::query("DELETE FROM posthog_featureflaghashkeyoverride WHERE team_id = $1")
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

    pub async fn cleanup(&self) -> Result<(), sqlx::Error> {
        sqlx::query("DELETE FROM lifecycle_op WHERE team_id = $1")
            .bind(self.team_id as i32)
            .execute(&self.pool)
            .await?;
        sqlx::query(&format!(
            "DELETE FROM {} WHERE team_id = $1",
            self.tables.person_distinct_id
        ))
        .bind(self.team_id as i32)
        .execute(&self.pool)
        .await?;
        sqlx::query(&format!(
            "DELETE FROM {} WHERE team_id = $1",
            self.tables.person
        ))
        .bind(self.team_id as i32)
        .execute(&self.pool)
        .await?;
        Ok(())
    }
}

/// Leader-surface stubs for test binaries whose flows never reach the
/// leader: an accidental call surfaces as a clean unimplemented error
/// instead of a hang or a panic mid-transaction.
pub struct UnusedLeader;

#[async_trait::async_trait]
impl personhog_identity::leader::PropertyWriter for UnusedLeader {
    async fn update_person_properties(
        &self,
        _request: personhog_proto::personhog::types::v1::UpdatePersonPropertiesRequest,
    ) -> Result<personhog_proto::personhog::types::v1::UpdatePersonPropertiesResponse, tonic::Status>
    {
        Err(tonic::Status::unimplemented("not exercised by this test"))
    }
}

#[async_trait::async_trait]
impl personhog_identity::leader::LifecycleLeader for UnusedLeader {
    async fn fence_person(
        &self,
        _request: personhog_proto::personhog::types::v1::FencePersonRequest,
    ) -> Result<personhog_proto::personhog::types::v1::FencePersonResponse, tonic::Status> {
        Err(tonic::Status::unimplemented("not exercised by this test"))
    }

    async fn release_fence(
        &self,
        _request: personhog_proto::personhog::types::v1::ReleaseFenceRequest,
    ) -> Result<personhog_proto::personhog::types::v1::ReleaseFenceResponse, tonic::Status> {
        Err(tonic::Status::unimplemented("not exercised by this test"))
    }

    async fn fold_person_document(
        &self,
        _request: personhog_proto::personhog::types::v1::FoldPersonDocumentRequest,
    ) -> Result<personhog_proto::personhog::types::v1::FoldPersonDocumentResponse, tonic::Status>
    {
        Err(tonic::Status::unimplemented("not exercised by this test"))
    }
}

/// IdentityStorage stub for validation-only test binaries: any call means
/// validation failed to reject first.
pub struct UnusedStorage;

#[async_trait::async_trait]
impl personhog_identity::storage::IdentityStorage for UnusedStorage {
    async fn resolve_distinct_ids(
        &self,
        _keys: &[(i64, String)],
    ) -> personhog_identity::storage::StorageResult<
        std::collections::HashMap<(i64, String), personhog_identity::storage::Person>,
    > {
        panic!("not exercised by this test")
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _team_id: i64,
        _person_ids: &[i64],
        _limit_per_person: Option<i64>,
    ) -> personhog_identity::storage::StorageResult<
        Vec<personhog_identity::storage::DistinctIdMapping>,
    > {
        panic!("not exercised by this test")
    }

    async fn create_person_stubs(
        &self,
        _stubs: &[personhog_identity::storage::PersonStub],
    ) -> personhog_identity::storage::StorageResult<Vec<personhog_identity::storage::StubOutcome>>
    {
        panic!("not exercised by this test")
    }

    async fn attach_distinct_ids(
        &self,
        _team_id: i64,
        _person_id: i64,
        _distinct_ids: &[String],
    ) -> personhog_identity::storage::StorageResult<
        std::collections::HashMap<String, personhog_identity::storage::AttachOutcome>,
    > {
        panic!("not exercised by this test")
    }
}

/// Wraps the real storage to inject the target-establishment races that
/// cannot be produced deterministically otherwise. Each injection fires
/// once, and the "concurrent winner" side effect is committed through the
/// real storage so the entrance's re-resolution finds what a genuine race
/// would have left behind.
pub struct RacingStorage {
    inner: Arc<PostgresIdentityStorage>,
    /// attach_distinct_ids: map the ids to THIS person instead (the
    /// concurrent winner) and answer AlreadyMapped.
    pub hijack_attach_to: std::sync::Mutex<Option<i64>>,
    /// attach_distinct_ids: attach nothing (the person vanished under a
    /// racing lifecycle op).
    pub vanish_attach: std::sync::Mutex<bool>,
    /// create_person_stubs: commit the stub as a concurrent winner and
    /// answer LostRace.
    pub lose_create_race: std::sync::Mutex<bool>,
}

impl RacingStorage {
    pub fn new(inner: Arc<PostgresIdentityStorage>) -> Self {
        Self {
            inner,
            hijack_attach_to: std::sync::Mutex::new(None),
            vanish_attach: std::sync::Mutex::new(false),
            lose_create_race: std::sync::Mutex::new(false),
        }
    }
}

#[async_trait::async_trait]
impl personhog_identity::storage::IdentityStorage for RacingStorage {
    async fn resolve_distinct_ids(
        &self,
        keys: &[(i64, String)],
    ) -> personhog_identity::storage::StorageResult<
        std::collections::HashMap<(i64, String), personhog_identity::storage::Person>,
    > {
        self.inner.resolve_distinct_ids(keys).await
    }

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
        limit_per_person: Option<i64>,
    ) -> personhog_identity::storage::StorageResult<
        Vec<personhog_identity::storage::DistinctIdMapping>,
    > {
        self.inner
            .get_distinct_ids_for_persons(team_id, person_ids, limit_per_person)
            .await
    }

    async fn create_person_stubs(
        &self,
        stubs: &[personhog_identity::storage::PersonStub],
    ) -> personhog_identity::storage::StorageResult<Vec<personhog_identity::storage::StubOutcome>>
    {
        let lose = std::mem::take(&mut *self.lose_create_race.lock().unwrap());
        if lose {
            self.inner.create_person_stubs(stubs).await?;
            return Ok(stubs
                .iter()
                .map(|_| personhog_identity::storage::StubOutcome::LostRace)
                .collect());
        }
        self.inner.create_person_stubs(stubs).await
    }

    async fn attach_distinct_ids(
        &self,
        team_id: i64,
        person_id: i64,
        distinct_ids: &[String],
    ) -> personhog_identity::storage::StorageResult<
        std::collections::HashMap<String, personhog_identity::storage::AttachOutcome>,
    > {
        let vanish = std::mem::take(&mut *self.vanish_attach.lock().unwrap());
        if vanish {
            return Ok(std::collections::HashMap::new());
        }
        let winner = self.hijack_attach_to.lock().unwrap().take();
        if let Some(winner) = winner {
            self.inner
                .attach_distinct_ids(team_id, winner, distinct_ids)
                .await?;
            return Ok(distinct_ids
                .iter()
                .map(|d| {
                    (
                        d.clone(),
                        personhog_identity::storage::AttachOutcome::AlreadyMapped {
                            person_id: winner,
                        },
                    )
                })
                .collect());
        }
        self.inner
            .attach_distinct_ids(team_id, person_id, distinct_ids)
            .await
    }
}
