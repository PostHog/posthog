use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize, sqlx::FromRow)]
pub struct Team {
    pub id: i32,
    pub name: String,
    pub api_token: String,
}

// We use query_as functions here rather than macros to avoid having to wrangle sqlx... TODO, be better
// about that.
impl Team {
    pub async fn by_token<'c, E>(executor: E, token: &str) -> Result<Option<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as::<_, Self>(
            r#"
            SELECT id, name, api_token
            FROM teams
            WHERE api_token = $1
            "#,
        )
        .bind(token)
        .fetch_optional(executor)
        .await
    }

    pub async fn by_id<'c, E>(executor: E, id: i32) -> Result<Option<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as::<_, Self>(
            r#"
            SELECT id, name, api_token
            FROM teams
            WHERE id = $1
            "#,
        )
        .bind(id)
        .fetch_optional(executor)
        .await
    }

    pub async fn bulk_by_tokens<'c, E>(
        executor: E,
        tokens: &[&str],
    ) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query_as::<_, Self>(
            r#"
            SELECT id, name, api_token
            FROM teams
            WHERE api_token = ANY($1)
            "#,
        )
        .bind(tokens)
        .fetch_all(executor)
        .await
    }
}
