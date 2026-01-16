use rand::{distributions::Alphanumeric, Rng};
use sqlx::postgres::PgPool;
use std::sync::Arc;
use uuid::Uuid;

use crate::storage::{postgres::PostgresStorage, PersonStorage};

/// Test configuration
pub struct TestConfig {
    /// URL for the persons database (contains person, group, cohort tables)
    pub database_url: String,
}

impl Default for TestConfig {
    fn default() -> Self {
        Self {
            // The persons database - separate from the main posthog database
            // Schema is created by rust/persons_migrations/
            database_url: "postgres://posthog:posthog@localhost:5432/posthog_persons".to_string(),
        }
    }
}

/// Generate a random string with a given prefix
pub fn random_string(prefix: &str, length: usize) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(Alphanumeric)
        .take(length)
        .map(char::from)
        .collect();
    format!("{prefix}{suffix}")
}

/// Generate a random team ID in a range that won't conflict with real data
pub fn random_team_id() -> i64 {
    rand::thread_rng().gen_range(1_000_000..100_000_000)
}

/// Generate a random person ID
pub fn random_person_id() -> i64 {
    rand::thread_rng().gen_range(1_000_000..100_000_000)
}

/// Test context that manages database connections and provides test data helpers
pub struct TestContext {
    pool: Arc<PgPool>,
    pub storage: Arc<dyn PersonStorage>,
    /// Team ID used for this test context (for cleanup)
    pub team_id: i64,
}

impl TestContext {
    /// Create a new test context with the default test database and a random team ID
    pub async fn new() -> Self {
        Self::with_config(TestConfig::default(), None).await
    }

    /// Create a new test context with a specific team ID
    pub async fn with_team_id(team_id: i64) -> Self {
        Self::with_config(TestConfig::default(), Some(team_id)).await
    }

    /// Create a new test context with custom configuration
    pub async fn with_config(config: TestConfig, team_id: Option<i64>) -> Self {
        let pool = PgPool::connect(&config.database_url)
            .await
            .expect("Failed to connect to test database");
        let pool = Arc::new(pool);
        let storage = Arc::new(PostgresStorage::new(pool.clone()));
        let team_id = team_id.unwrap_or_else(random_team_id);

        Self {
            pool,
            storage,
            team_id,
        }
    }

    /// Get direct access to the database pool for custom queries
    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    /// Insert a test person
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
        .execute(&*self.pool)
        .await?;

        // Insert distinct ID mapping
        sqlx::query(
            r#"INSERT INTO posthog_persondistinctid
            (distinct_id, person_id, team_id, version)
            VALUES ($1, $2, $3, 0)
            ON CONFLICT DO NOTHING"#,
        )
        .bind(distinct_id)
        .bind(person_id)
        .bind(self.team_id)
        .execute(&*self.pool)
        .await?;

        Ok(TestPerson {
            id: person_id,
            uuid,
            team_id: self.team_id,
            distinct_id: distinct_id.to_string(),
            properties,
        })
    }

    /// Insert a test group
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
        .execute(&*self.pool)
        .await?;

        Ok(TestGroup {
            team_id: self.team_id,
            group_type_index,
            group_key: group_key.to_string(),
            properties,
        })
    }

    /// Insert a group type mapping
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
        .bind(self.team_id) // project_id = team_id
        .bind(group_type)
        .bind(group_type_index)
        .execute(&*self.pool)
        .await?;

        Ok(())
    }

    /// Insert standard group type mappings
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

    /// Add a person to a cohort (cohort_id can be any value - no FK constraint in persons db)
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
        .execute(&*self.pool)
        .await?;

        Ok(())
    }

    /// Clean up all test data for this context's team_id
    pub async fn cleanup(&self) -> Result<(), sqlx::Error> {
        // Delete in reverse dependency order
        // Note: We clean up cohortpeople by person_id since cohort definitions
        // live in the main database, not the persons database
        sqlx::query(
            "DELETE FROM posthog_cohortpeople WHERE person_id IN (SELECT id FROM posthog_person WHERE team_id = $1)",
        )
        .bind(self.team_id)
        .execute(&*self.pool)
        .await?;

        sqlx::query("DELETE FROM posthog_persondistinctid WHERE team_id = $1")
            .bind(self.team_id)
            .execute(&*self.pool)
            .await?;

        sqlx::query("DELETE FROM posthog_person WHERE team_id = $1")
            .bind(self.team_id)
            .execute(&*self.pool)
            .await?;

        sqlx::query("DELETE FROM posthog_group WHERE team_id = $1")
            .bind(self.team_id)
            .execute(&*self.pool)
            .await?;

        sqlx::query("DELETE FROM posthog_grouptypemapping WHERE team_id = $1")
            .bind(self.team_id)
            .execute(&*self.pool)
            .await?;

        Ok(())
    }
}

/// Test person data
#[derive(Debug, Clone)]
pub struct TestPerson {
    pub id: i64,
    pub uuid: Uuid,
    pub team_id: i64,
    pub distinct_id: String,
    pub properties: serde_json::Value,
}

/// Test group data
#[derive(Debug, Clone)]
pub struct TestGroup {
    pub team_id: i64,
    pub group_type_index: i32,
    pub group_key: String,
    pub properties: serde_json::Value,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_context_creation() {
        // This test verifies we can connect to the test database
        // If we get here without panicking, the connection worked
        let ctx = TestContext::new().await;
        // Verify pool is accessible
        let _ = ctx.pool();
    }
}
