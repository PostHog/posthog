use common_database::Client as DatabaseClient;
use common_redis::Client as RedisClient;
use std::sync::Arc;
use tracing::warn;

pub const DEBOUNCE_TTL_SECONDS: u64 = 3600; // 1 hour, matching Django's debounce window

/// Returns the Redis debounce key for a given PAK ID.
pub fn debounce_key(pak_id: &str) -> String {
    format!("posthog:pak_last_used:{pak_id}")
}

/// Debounces and records PAK last_used_at.
///
/// Uses Redis SET NX EX to gate updates to once per hour per PAK.
/// When the debounce key is newly set, spawns a background task
/// to update the database and returns its `JoinHandle`.
pub async fn record_pak_last_used(
    redis: Arc<dyn RedisClient + Send + Sync>,
    pg_writer: Arc<dyn DatabaseClient + Send + Sync>,
    pak_id: String,
) -> Option<tokio::task::JoinHandle<()>> {
    let key = debounce_key(&pak_id);
    match redis
        .set_nx_ex(key, "1".to_string(), DEBOUNCE_TTL_SECONDS)
        .await
    {
        Ok(true) => Some(tokio::spawn(async move {
            update_pak_last_used_at(pg_writer, pak_id).await;
        })),
        Ok(false) => None,
        Err(e) => {
            warn!(
                error = %e,
                "Redis debounce check failed for PAK last_used_at"
            );
            None
        }
    }
}

/// Updates PAK last_used_at in the database.
///
/// Includes a WHERE guard as a safety net matching Django's semantics.
pub async fn update_pak_last_used_at(
    pg_writer: Arc<dyn DatabaseClient + Send + Sync>,
    pak_id: String,
) {
    let mut conn = match pg_writer.get_connection().await {
        Ok(conn) => conn,
        Err(e) => {
            warn!(pak_id, error = %e, "Failed to acquire connection for PAK last_used_at update");
            return;
        }
    };
    if let Err(e) = sqlx::query(
        "UPDATE posthog_personalapikey SET last_used_at = NOW() \
         WHERE id = $1 AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '1 hour')",
    )
    .bind(&pak_id)
    .execute(&mut *conn)
    .await
    {
        warn!(pak_id, error = %e, "Failed to update PAK last_used_at");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::test_utils::TestContext;
    use common_redis::MockRedisClient;

    async fn create_test_pak(ctx: &TestContext) -> String {
        let team = ctx.insert_new_team(None).await.unwrap();
        let org_id = ctx.get_organization_id_for_team(&team).await.unwrap();
        let email = TestContext::generate_test_email("pak_test");
        let user_id = ctx.create_user(&email, &org_id, team.id).await.unwrap();
        let (pak_id, _) = ctx
            .create_personal_api_key(user_id, "test", vec!["feature_flag:read"], None, None)
            .await
            .unwrap();
        pak_id
    }

    #[tokio::test]
    async fn test_updates_last_used_at_for_new_pak() {
        let ctx = TestContext::new(None).await;
        let pak_id = create_test_pak(&ctx).await;

        update_pak_last_used_at(ctx.non_persons_writer.clone(), pak_id.clone()).await;

        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        let count: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM posthog_personalapikey WHERE id = $1 AND last_used_at IS NOT NULL",
        )
        .bind(&pak_id)
        .fetch_one(&mut *conn)
        .await
        .unwrap();
        assert_eq!(count.0, 1, "last_used_at should be set after update");
    }

    #[tokio::test]
    async fn test_skips_update_when_last_used_at_is_recent() {
        let ctx = TestContext::new(None).await;
        let pak_id = create_test_pak(&ctx).await;

        // Set last_used_at to 30 minutes ago (within the 1-hour window)
        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        sqlx::query(
            "UPDATE posthog_personalapikey SET last_used_at = NOW() - INTERVAL '30 minutes' WHERE id = $1",
        )
        .bind(&pak_id)
        .execute(&mut *conn)
        .await
        .unwrap();

        update_pak_last_used_at(ctx.non_persons_writer.clone(), pak_id.clone()).await;

        // Verify last_used_at is still ~30 minutes ago, not updated to NOW()
        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        let count: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM posthog_personalapikey \
             WHERE id = $1 AND last_used_at < NOW() - INTERVAL '25 minutes'",
        )
        .bind(&pak_id)
        .fetch_one(&mut *conn)
        .await
        .unwrap();
        assert_eq!(
            count.0, 1,
            "last_used_at should not change when within the 1-hour window"
        );
    }

    async fn assert_record_pak(
        set_nx_ex_result: Result<bool, common_redis::CustomRedisError>,
        expect_last_used_set: bool,
        expect_handle: bool,
    ) {
        let ctx = TestContext::new(None).await;
        let pak_id = create_test_pak(&ctx).await;
        let key = debounce_key(&pak_id);

        let redis: Arc<dyn RedisClient + Send + Sync> =
            Arc::new(MockRedisClient::new().set_nx_ex_ret(&key, set_nx_ex_result));

        let handle =
            record_pak_last_used(redis, ctx.non_persons_writer.clone(), pak_id.clone()).await;
        assert_eq!(handle.is_some(), expect_handle);
        if let Some(h) = handle {
            h.await.unwrap();
        }

        let mut conn = ctx.get_non_persons_connection().await.unwrap();
        let count: (i64,) = sqlx::query_as(if expect_last_used_set {
            "SELECT COUNT(*) FROM posthog_personalapikey WHERE id = $1 AND last_used_at IS NOT NULL"
        } else {
            "SELECT COUNT(*) FROM posthog_personalapikey WHERE id = $1 AND last_used_at IS NULL"
        })
        .bind(&pak_id)
        .fetch_one(&mut *conn)
        .await
        .unwrap();
        assert_eq!(count.0, 1);
    }

    #[tokio::test]
    async fn test_record_pak_last_used_writes_when_debounce_key_is_new() {
        assert_record_pak(Ok(true), true, true).await;
    }

    #[tokio::test]
    async fn test_record_pak_last_used_skips_write_when_debounce_key_exists() {
        assert_record_pak(Ok(false), false, false).await;
    }

    #[tokio::test]
    async fn test_record_pak_last_used_skips_write_on_redis_error() {
        assert_record_pak(Err(common_redis::CustomRedisError::Timeout), false, false).await;
    }
}
