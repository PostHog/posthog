use common_database::Client as DatabaseClient;
use common_redis::Client as RedisClient;
use std::sync::Arc;
use tracing::warn;

pub const DEBOUNCE_TTL_SECONDS: u64 = 3600; // 1 hour, matching Django's debounce window

/// Which API key model a `last_used_at` stamp targets. Personal and project secret keys live in
/// different tables with different id spaces, so each kind gets its own debounce namespace.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApiKeyKind {
    Personal,
    ProjectSecret,
}

impl ApiKeyKind {
    fn table(self) -> &'static str {
        match self {
            ApiKeyKind::Personal => "posthog_personalapikey",
            ApiKeyKind::ProjectSecret => "posthog_projectsecretapikey",
        }
    }

    fn debounce_prefix(self) -> &'static str {
        match self {
            ApiKeyKind::Personal => "posthog:pak_last_used",
            ApiKeyKind::ProjectSecret => "posthog:psak_last_used",
        }
    }
}

/// Returns the Redis debounce key for a given API key.
pub fn debounce_key(kind: ApiKeyKind, key_id: &str) -> String {
    format!("{}:{key_id}", kind.debounce_prefix())
}

/// Debounces and records an API key's last_used_at.
///
/// Uses Redis SET NX EX to gate updates to once per hour per key.
/// When the debounce key is newly set, spawns a background task
/// to update the database and returns its `JoinHandle`.
pub async fn record_api_key_last_used(
    redis: Arc<dyn RedisClient + Send + Sync>,
    pg_writer: Arc<dyn DatabaseClient + Send + Sync>,
    kind: ApiKeyKind,
    key_id: String,
) -> Option<tokio::task::JoinHandle<()>> {
    let key = debounce_key(kind, &key_id);
    match redis
        .set_nx_ex(key, "1".to_string(), DEBOUNCE_TTL_SECONDS)
        .await
    {
        Ok(true) => Some(tokio::spawn(async move {
            update_api_key_last_used_at(pg_writer, kind, key_id).await;
        })),
        Ok(false) => None,
        Err(e) => {
            warn!(
                error = %e,
                ?kind,
                "Redis debounce check failed for API key last_used_at"
            );
            None
        }
    }
}

/// Updates an API key's last_used_at in the database.
///
/// Includes a WHERE guard as a safety net matching Django's semantics.
pub async fn update_api_key_last_used_at(
    pg_writer: Arc<dyn DatabaseClient + Send + Sync>,
    kind: ApiKeyKind,
    key_id: String,
) {
    let mut conn = match pg_writer.get_connection().await {
        Ok(conn) => conn,
        Err(e) => {
            warn!(key_id, ?kind, error = %e, "Failed to acquire connection for API key last_used_at update");
            return;
        }
    };
    // The table name comes from the enum, never from input.
    let sql = format!(
        "UPDATE {} SET last_used_at = NOW() \
         WHERE id = $1 AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '1 hour')",
        kind.table()
    );
    if let Err(e) = sqlx::query(&sql).bind(&key_id).execute(&mut *conn).await {
        warn!(key_id, ?kind, error = %e, "Failed to update API key last_used_at");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::TestContext;
    use common_redis::MockRedisClient;
    use rstest::rstest;

    async fn create_test_key(ctx: &TestContext, kind: ApiKeyKind) -> String {
        let team = ctx.insert_new_team(None).await.unwrap();
        match kind {
            ApiKeyKind::Personal => {
                let org_id = ctx.get_organization_id_for_team(&team).await.unwrap();
                let email = TestContext::generate_test_email("pak_test");
                let user_id = ctx.create_user(&email, &org_id, team.id).await.unwrap();
                let (pak_id, _) = ctx
                    .create_personal_api_key(user_id, "test", vec!["feature_flag:read"], None, None)
                    .await
                    .unwrap();
                pak_id
            }
            ApiKeyKind::ProjectSecret => {
                ctx.create_project_secret_api_key(team.id, "test", Some(vec!["feature_flag:read"]))
                    .await
                    .unwrap();
                let mut conn = ctx.get_non_persons_connection().await.unwrap();
                let (id,): (String,) =
                    sqlx::query_as("SELECT id FROM posthog_projectsecretapikey WHERE team_id = $1")
                        .bind(team.id)
                        .fetch_one(&mut *conn)
                        .await
                        .unwrap();
                id
            }
        }
    }

    async fn count_where(ctx: &TestContext, kind: ApiKeyKind, key_id: &str, cond: &str) -> i64 {
        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        let sql = format!(
            "SELECT COUNT(*) FROM {} WHERE id = $1 AND {cond}",
            kind.table()
        );
        let count: (i64,) = sqlx::query_as(&sql)
            .bind(key_id)
            .fetch_one(&mut *conn)
            .await
            .unwrap();
        count.0
    }

    #[rstest]
    #[case::personal(ApiKeyKind::Personal)]
    #[case::project_secret(ApiKeyKind::ProjectSecret)]
    #[tokio::test]
    async fn test_updates_last_used_at_for_new_key(#[case] kind: ApiKeyKind) {
        let ctx = TestContext::new(None).await;
        let key_id = create_test_key(&ctx, kind).await;

        update_api_key_last_used_at(ctx.non_persons_writer.clone(), kind, key_id.clone()).await;

        assert_eq!(
            count_where(&ctx, kind, &key_id, "last_used_at IS NOT NULL").await,
            1,
            "last_used_at should be set after update"
        );
    }

    #[rstest]
    #[case::personal(ApiKeyKind::Personal)]
    #[case::project_secret(ApiKeyKind::ProjectSecret)]
    #[tokio::test]
    async fn test_skips_update_when_last_used_at_is_recent(#[case] kind: ApiKeyKind) {
        let ctx = TestContext::new(None).await;
        let key_id = create_test_key(&ctx, kind).await;

        // Set last_used_at to 30 minutes ago (within the 1-hour window)
        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        let sql = format!(
            "UPDATE {} SET last_used_at = NOW() - INTERVAL '30 minutes' WHERE id = $1",
            kind.table()
        );
        sqlx::query(&sql)
            .bind(&key_id)
            .execute(&mut *conn)
            .await
            .unwrap();

        update_api_key_last_used_at(ctx.non_persons_writer.clone(), kind, key_id.clone()).await;

        // Verify last_used_at is still ~30 minutes ago, not updated to NOW()
        assert_eq!(
            count_where(
                &ctx,
                kind,
                &key_id,
                "last_used_at < NOW() - INTERVAL '25 minutes'"
            )
            .await,
            1,
            "last_used_at should not change when within the 1-hour window"
        );
    }

    async fn assert_record_key(
        kind: ApiKeyKind,
        set_nx_ex_result: Result<bool, common_redis::CustomRedisError>,
        expect_last_used_set: bool,
        expect_handle: bool,
    ) {
        let ctx = TestContext::new(None).await;
        let key_id = create_test_key(&ctx, kind).await;
        let key = debounce_key(kind, &key_id);

        let redis: Arc<dyn RedisClient + Send + Sync> =
            Arc::new(MockRedisClient::new().set_nx_ex_ret(&key, set_nx_ex_result));

        let handle =
            record_api_key_last_used(redis, ctx.non_persons_writer.clone(), kind, key_id.clone())
                .await;
        assert_eq!(handle.is_some(), expect_handle);
        if let Some(h) = handle {
            h.await.unwrap();
        }

        let cond = if expect_last_used_set {
            "last_used_at IS NOT NULL"
        } else {
            "last_used_at IS NULL"
        };
        assert_eq!(count_where(&ctx, kind, &key_id, cond).await, 1);
    }

    #[rstest]
    #[case::personal(ApiKeyKind::Personal)]
    #[case::project_secret(ApiKeyKind::ProjectSecret)]
    #[tokio::test]
    async fn test_record_last_used_writes_when_debounce_key_is_new(#[case] kind: ApiKeyKind) {
        assert_record_key(kind, Ok(true), true, true).await;
    }

    #[rstest]
    #[case::personal(ApiKeyKind::Personal)]
    #[case::project_secret(ApiKeyKind::ProjectSecret)]
    #[tokio::test]
    async fn test_record_last_used_skips_write_when_debounce_key_exists(#[case] kind: ApiKeyKind) {
        assert_record_key(kind, Ok(false), false, false).await;
    }

    #[rstest]
    #[case::personal(ApiKeyKind::Personal)]
    #[case::project_secret(ApiKeyKind::ProjectSecret)]
    #[tokio::test]
    async fn test_record_last_used_skips_write_on_redis_error(#[case] kind: ApiKeyKind) {
        assert_record_key(
            kind,
            Err(common_redis::CustomRedisError::Timeout),
            false,
            false,
        )
        .await;
    }

    #[test]
    fn test_debounce_keys_are_namespaced_per_kind() {
        assert_ne!(
            debounce_key(ApiKeyKind::Personal, "abc"),
            debounce_key(ApiKeyKind::ProjectSecret, "abc")
        );
    }
}
