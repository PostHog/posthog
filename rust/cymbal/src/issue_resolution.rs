use sqlx::PgPool;
use uuid::Uuid;

use crate::error::Error;

pub struct IssueFingerprintOverride {
    pub id: Uuid,
    pub team_id: i32,
    pub fingerprint: String,
    pub issue_id: Uuid,
    pub version: i64,
}

#[derive(Debug, sqlx::FromRow)]
pub struct Issue {
    pub id: Uuid,
    pub team_id: i32,
    pub fingerprint: String,
}

pub async fn resolve_issue_id(
    pool: &PgPool,
    team_id: i32,
    fingerprint: &str,
) -> Result<Uuid, Error> {
    let existing = load_issue_override(pool, team_id, fingerprint).await?;

    let issue_fingerprint = match existing {
        Some(f) => f,
        None => create_issue(pool, team_id, fingerprint).await?,
    };

    Ok(issue_fingerprint.issue_id)
}

pub async fn load_issue_override<'c, E>(
    executor: E,
    team_id: i32,
    fingerprint: &str,
) -> Result<Option<IssueFingerprintOverride>, Error>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    Ok(sqlx::query_as!(
        IssueFingerprintOverride,
        r#"
            SELECT id, team_id, fingerprint, issue_id, version
            FROM posthog_errortrackingissuefingerprintv2
            WHERE team_id = $1 AND fingerprint = $2
        "#,
        team_id,
        fingerprint
    )
    .fetch_optional(executor)
    .await?)
}

pub async fn create_issue<'c, A>(
    connection: A,
    team_id: i32,
    fingerprint: &str,
) -> Result<IssueFingerprintOverride, Error>
where
    A: sqlx::Acquire<'c, Database = sqlx::Postgres>,
{
    let issue_id = Uuid::now_v7();

    let mut tx = connection.begin().await?;

    sqlx::query!(
        r#"
            INSERT INTO posthog_errortrackingissue (id, team_id)
            VALUES ($1, $2)
        "#,
        issue_id,
        team_id
    )
    .execute(&mut *tx)
    .await?;

    let res = sqlx::query_as!(
        IssueFingerprintOverride,
        r#"
            INSERT INTO posthog_errortrackingissuefingerprintv2 (id, team_id, fingerprint, issue_id, version)
            VALUES ($1, $2, $3, $4, 0)
            ON CONFLICT (team_id, fingerprint) DO UPDATE SET version = posthog_errortrackingissuefingerprintv2.version + 1
            RETURNING id, team_id, fingerprint, issue_id, version
        "#,
        Uuid::now_v7(),
        team_id,
        fingerprint,
        issue_id
    )
    .fetch_one(&mut *tx)
    .await?;

    tx.commit().await?;

    // TODO: write to Kafka

    Ok(res)
}

#[cfg(test)]
mod test {
    use sqlx::PgPool;

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_issue_creation(db: PgPool) {
        let team_id: i32 = 1;
        let fingerprint = "this_is_a_fingerprint".to_string();

        super::resolve_issue_id(&db, team_id, &fingerprint)
            .await
            .unwrap();

        // Verify both records are created in Postgres
        let record = super::load_issue_override(&db, team_id, &fingerprint)
            .await
            .unwrap()
            .unwrap();

        assert_eq!(record.fingerprint, fingerprint);
        assert_eq!(record.version, 0);

        super::resolve_issue_id(&db, team_id, &fingerprint)
            .await
            .unwrap();

        let result = sqlx::query!(
            r#"
                SELECT COUNT(*)
                FROM posthog_errortrackingissue
            "#,
        )
        .fetch_one(&db)
        .await
        .unwrap();

        // Olly: don't understand why I need the Some here
        // I'm just trying to assert that only one record exists
        assert_eq!(result.count, Some(1))
    }
}
