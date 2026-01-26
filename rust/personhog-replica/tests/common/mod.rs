use personhog_replica::storage::{postgres::PostgresStorage, FullStorage};
use rand::Rng;
use sqlx::postgres::PgPool;
use std::sync::Arc;
use uuid::Uuid;

fn random_team_id() -> i64 {
    rand::thread_rng().gen_range(1_000_000..100_000_000)
}

fn random_person_id() -> i64 {
    rand::thread_rng().gen_range(1_000_000..100_000_000)
}

/// Test context that manages database connections and provides test data helpers.
pub struct TestContext {
    pool: PgPool,
    pub storage: Arc<dyn FullStorage>,
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
        let storage = Arc::new(PostgresStorage::new(pool.clone()));
        let team_id = random_team_id();

        Self {
            pool,
            storage,
            team_id,
        }
    }

    pub async fn insert_person(
        &self,
        distinct_id: &str,
        properties: Option<serde_json::Value>,
    ) -> Result<TestPerson, sqlx::Error> {
        let person_id = random_person_id();
        let uuid = Uuid::now_v7();
        let properties = properties.unwrap_or_else(|| serde_json::json!({}));

        sqlx::query(
            r#"INSERT INTO posthog_person
            (id, uuid, team_id, properties, properties_last_updated_at,
             properties_last_operation, created_at, version, is_identified, is_user_id)
            VALUES ($1, $2, $3, $4, '{}', '{}', NOW(), 0, false, NULL)
            ON CONFLICT DO NOTHING"#,
        )
        .bind(person_id)
        .bind(uuid)
        .bind(self.team_id)
        .bind(&properties)
        .execute(&self.pool)
        .await?;

        sqlx::query(
            r#"INSERT INTO posthog_persondistinctid
            (distinct_id, person_id, team_id, version)
            VALUES ($1, $2, $3, 0)
            ON CONFLICT DO NOTHING"#,
        )
        .bind(distinct_id)
        .bind(person_id)
        .bind(self.team_id)
        .execute(&self.pool)
        .await?;

        Ok(TestPerson {
            id: person_id,
            uuid,
        })
    }

    pub async fn insert_group(
        &self,
        group_type_index: i32,
        group_key: &str,
        properties: Option<serde_json::Value>,
    ) -> Result<TestGroup, sqlx::Error> {
        let properties = properties.unwrap_or_else(|| serde_json::json!({}));

        sqlx::query(
            r#"INSERT INTO posthog_group
            (team_id, group_type_index, group_key, group_properties, created_at, version)
            VALUES ($1, $2, $3, $4, NOW(), 0)
            ON CONFLICT DO NOTHING"#,
        )
        .bind(self.team_id)
        .bind(group_type_index)
        .bind(group_key)
        .bind(&properties)
        .execute(&self.pool)
        .await?;

        Ok(TestGroup {
            group_type_index,
            group_key: group_key.to_string(),
        })
    }

    pub async fn insert_group_type_mapping(
        &self,
        group_type: &str,
        group_type_index: i32,
    ) -> Result<(), sqlx::Error> {
        sqlx::query(
            r#"INSERT INTO posthog_grouptypemapping
            (team_id, project_id, group_type, group_type_index, name_singular, name_plural)
            VALUES ($1, $2, $3, $4, NULL, NULL)
            ON CONFLICT DO NOTHING"#,
        )
        .bind(self.team_id)
        .bind(self.team_id)
        .bind(group_type)
        .bind(group_type_index)
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    pub async fn insert_standard_group_type_mappings(&self) -> Result<(), sqlx::Error> {
        let group_types = vec![
            ("project", 0),
            ("organization", 1),
            ("instance", 2),
            ("customer", 3),
            ("team", 4),
        ];

        for (group_type, group_type_index) in group_types {
            self.insert_group_type_mapping(group_type, group_type_index)
                .await?;
        }

        Ok(())
    }

    pub async fn add_person_to_cohort(
        &self,
        person_id: i64,
        cohort_id: i64,
    ) -> Result<(), sqlx::Error> {
        sqlx::query(
            r#"INSERT INTO posthog_cohortpeople
            (person_id, cohort_id, version)
            VALUES ($1, $2, 1)
            ON CONFLICT DO NOTHING"#,
        )
        .bind(person_id)
        .bind(cohort_id)
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    pub async fn insert_hash_key_override(
        &self,
        person_id: i64,
        feature_flag_key: &str,
        hash_key: &str,
    ) -> Result<(), sqlx::Error> {
        sqlx::query(
            r#"INSERT INTO posthog_featureflaghashkeyoverride
            (team_id, person_id, feature_flag_key, hash_key)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT DO NOTHING"#,
        )
        .bind(self.team_id)
        .bind(person_id)
        .bind(feature_flag_key)
        .bind(hash_key)
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    pub async fn add_distinct_id_to_person(
        &self,
        person_id: i64,
        distinct_id: &str,
    ) -> Result<(), sqlx::Error> {
        sqlx::query(
            r#"INSERT INTO posthog_persondistinctid
            (distinct_id, person_id, team_id, version)
            VALUES ($1, $2, $3, 0)
            ON CONFLICT DO NOTHING"#,
        )
        .bind(distinct_id)
        .bind(person_id)
        .bind(self.team_id)
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    pub async fn cleanup(&self) -> Result<(), sqlx::Error> {
        sqlx::query("DELETE FROM posthog_featureflaghashkeyoverride WHERE team_id = $1")
            .bind(self.team_id)
            .execute(&self.pool)
            .await?;

        sqlx::query(
            "DELETE FROM posthog_cohortpeople WHERE person_id IN (SELECT id FROM posthog_person WHERE team_id = $1)",
        )
        .bind(self.team_id)
        .execute(&self.pool)
        .await?;

        sqlx::query("DELETE FROM posthog_persondistinctid WHERE team_id = $1")
            .bind(self.team_id)
            .execute(&self.pool)
            .await?;

        sqlx::query("DELETE FROM posthog_person WHERE team_id = $1")
            .bind(self.team_id)
            .execute(&self.pool)
            .await?;

        sqlx::query("DELETE FROM posthog_group WHERE team_id = $1")
            .bind(self.team_id)
            .execute(&self.pool)
            .await?;

        sqlx::query("DELETE FROM posthog_grouptypemapping WHERE team_id = $1")
            .bind(self.team_id)
            .execute(&self.pool)
            .await?;

        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct TestPerson {
    pub id: i64,
    pub uuid: Uuid,
}

#[derive(Debug, Clone)]
pub struct TestGroup {
    pub group_type_index: i32,
    pub group_key: String,
}
