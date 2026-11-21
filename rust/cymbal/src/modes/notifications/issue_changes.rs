use std::time::Duration;

use common_types::format::parse_datetime_assuming_utc;
use sqlx::{Acquire, PgPool};
use tracing::warn;

use crate::{
    core::{config::build_pg_pool, types::notification::IssueSpiking},
    error::UnhandledError,
    issue_resolution::Issue,
    modes::{
        notifications::config::NotificationsConfig,
        processing::issue_changes::{
            load_assignments, record_issue_change_with_id, ExceptionRef, IssueChange, IssueSnapshot,
        },
    },
};

const RECORD_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Clone)]
pub struct SpikeChangeWriter {
    pool: PgPool,
    timeout: Duration,
}

impl SpikeChangeWriter {
    pub fn from_config(config: &NotificationsConfig) -> Result<Option<Self>, UnhandledError> {
        if !config.issue_change_log_enabled {
            return Ok(None);
        }
        let database_url = config
            .database_url
            .as_deref()
            .filter(|url| !url.trim().is_empty())
            .ok_or_else(|| {
                UnhandledError::Other(
                    "DATABASE_URL is required when issue change logging is enabled".to_string(),
                )
            })?;
        Ok(Some(Self {
            pool: build_pg_pool(
                database_url,
                config.max_pg_connections,
                "cymbal_notifications",
            )?,
            timeout: RECORD_TIMEOUT,
        }))
    }

    pub async fn record(&self, notification: &IssueSpiking) -> Result<(), UnhandledError> {
        let Some(change_id) = notification.change_id.filter(|id| !id.is_nil()) else {
            return Ok(());
        };
        let Ok(timestamp) = parse_datetime_assuming_utc(&notification.event_timestamp) else {
            warn!(
                notification_id = %notification.meta.notification_id,
                "Skipping spiking change with an unparseable event timestamp"
            );
            return Ok(());
        };
        let deadline = tokio::time::Instant::now() + self.timeout;
        let timeout_error =
            || UnhandledError::Other("Spiking change recording timed out".to_string());
        let mut connection = tokio::time::timeout_at(deadline, self.pool.acquire())
            .await
            .map_err(|_| timeout_error())??;
        let result = tokio::time::timeout_at(deadline, async {
            let mut txn = connection.begin().await?;
            // Read a coherent snapshot without taking write locks on ingestion's issue rows.
            sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                .execute(&mut *txn)
                .await?;
            sqlx::query(
                "SELECT set_config('statement_timeout', $1, true), set_config('idle_in_transaction_session_timeout', $1, true)",
            )
            .bind(format!("{}ms", self.timeout.as_millis()))
            .execute(&mut *txn)
            .await?;
            let Some(issue) = Issue::load(
                &mut *txn,
                notification.meta.team_id,
                notification.issue.issue_id,
            )
            .await?
            else {
                txn.rollback().await?;
                return Ok(());
            };
            let assignments = load_assignments(&mut *txn, &[issue.id]).await?;
            let snapshot =
                IssueSnapshot::load(&mut txn, &issue, assignments.get(&issue.id)).await?;
            record_issue_change_with_id(
                &mut *txn,
                change_id,
                &issue,
                &IssueChange::Spiking {
                    computed_baseline: notification.computed_baseline,
                    current_bucket_value: notification.current_bucket_value as i64,
                },
                &snapshot,
                &ExceptionRef {
                    uuid: notification.event_uuid,
                    timestamp,
                },
            )
            .await?;
            txn.commit().await?;
            Ok(())
        })
        .await;
        match result {
            Ok(result) => result,
            Err(_) => {
                // Closing the socket cancels database work left running at the client deadline.
                connection.close_on_drop();
                Err(timeout_error())
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use chrono::Utc;
    use envconfig::Envconfig;
    use serde_json::json;
    use uuid::Uuid;

    use super::*;
    use crate::core::types::notification::{
        IssueNotificationContext, IssueSnapshot as NotificationSnapshot, NotificationMeta,
    };

    async fn notification(db: &PgPool) -> IssueSpiking {
        let issue = Issue::insert_new(1, "TypeError".to_string(), String::new(), None, db)
            .await
            .unwrap();
        IssueSpiking {
            change_id: Some(Uuid::now_v7()),
            meta: NotificationMeta {
                notification_id: Uuid::now_v7(),
                team_id: issue.team_id,
            },
            issue: IssueNotificationContext {
                issue_id: issue.id,
                issue: NotificationSnapshot {
                    name: issue.name,
                    description: issue.description,
                    status: "active".to_string(),
                    severity: None,
                    created_at: issue.created_at,
                },
                event_properties: serde_json::from_value(json!({
                    "$exception_list": [{"type": "TypeError", "value": "Example error"}],
                    "$exception_fingerprint": "test-fingerprint",
                    "$exception_fingerprint_record": [{"type": "manual"}],
                    "$exception_issue_id": issue.id,
                    "$exception_handled": false,
                    "$exception_types": ["TypeError"],
                    "$exception_values": ["Example error"],
                    "$exception_sources": [],
                    "$exception_functions": []
                }))
                .unwrap(),
            },
            event_uuid: Uuid::now_v7(),
            event_timestamp: "2020-02-03T04:05:06Z".to_string(),
            computed_baseline: 12.5,
            current_bucket_value: 140.0,
            assignee: None,
        }
    }

    #[test]
    fn database_is_required_only_when_recording_is_enabled() {
        let mut vars = std::collections::HashMap::from([
            (
                "KAFKA_CONSUMER_AUTO_COMMIT".to_string(),
                "false".to_string(),
            ),
            (
                "KAFKA_CONSUMER_TOPIC".to_string(),
                "test-notifications".to_string(),
            ),
            (
                "KAFKA_CONSUMER_GROUP".to_string(),
                "test-notifications".to_string(),
            ),
            (
                "ERROR_TRACKING_NOTIFICATIONS_RATE_LIMIT_REDIS_URL".to_string(),
                "redis://localhost:6379".to_string(),
            ),
        ]);
        let config = NotificationsConfig::init_from_hashmap(&vars).unwrap();
        assert!(SpikeChangeWriter::from_config(&config).unwrap().is_none());
        vars.insert(
            "ERROR_TRACKING_ISSUE_CHANGE_LOG_ENABLED".to_string(),
            "true".to_string(),
        );
        let config = NotificationsConfig::init_from_hashmap(&vars).unwrap();
        assert!(
            matches!(SpikeChangeWriter::from_config(&config), Err(UnhandledError::Other(message)) if message.contains("DATABASE_URL"))
        );
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn records_current_snapshot_once_across_notification_replays(db: PgPool) {
        let mut notification = notification(&db).await;
        let writer = SpikeChangeWriter {
            pool: db.clone(),
            timeout: Duration::from_secs(10),
        };
        sqlx::query("INSERT INTO posthog_errortrackingissueassignment (id, issue_id, user_id, created_at) VALUES ($1, $2, 42, NOW())")
            .bind(Uuid::now_v7()).bind(notification.issue.issue_id).execute(&db).await.unwrap();
        sqlx::query("INSERT INTO posthog_errortrackingissuefingerprintv2 (id, team_id, issue_id, fingerprint, version, first_seen) VALUES ($1, 1, $2, 'old-fingerprint', 2, $3)")
            .bind(Uuid::now_v7())
            .bind(notification.issue.issue_id)
            .bind("2019-01-02T03:04:05Z".parse::<chrono::DateTime<Utc>>().unwrap())
            .execute(&db).await.unwrap();

        let mut wrong_team = notification.clone();
        wrong_team.meta.team_id = 2;
        writer.record(&wrong_team).await.unwrap();
        let before: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM posthog_errortrackingissuechange")
                .fetch_one(&db)
                .await
                .unwrap();
        assert_eq!(before, 0);

        writer.record(&notification).await.unwrap();
        notification.event_uuid = Uuid::now_v7();
        notification.meta.notification_id = Uuid::now_v7();
        writer.record(&notification).await.unwrap();
        let rows: Vec<(Uuid, String, serde_json::Value, serde_json::Value, String)> =
            sqlx::query_as(
                "SELECT id, kind, data, snapshot, actor_type FROM posthog_errortrackingissuechange",
            )
            .fetch_all(&db)
            .await
            .unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].0, notification.change_id.unwrap());
        assert_eq!(rows[0].1, "spiking");
        assert_eq!(
            rows[0].2,
            json!({"computed_baseline": 12.5, "current_bucket_value": 140})
        );
        assert_eq!(rows[0].3["first_seen"], "2019-01-02T03:04:05+00:00");
        assert_eq!(rows[0].3["assignee"], json!({"type": "user", "id": "42"}));
        assert_eq!(rows[0].4, "ingestion");
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn a_failed_write_can_retry_from_the_same_notification(db: PgPool) {
        let notification = notification(&db).await;
        let writer = SpikeChangeWriter {
            pool: db.clone(),
            timeout: Duration::from_secs(10),
        };
        sqlx::query("ALTER TABLE posthog_errortrackingissuechange ADD CONSTRAINT reject_spikes CHECK (kind != 'spiking')")
            .execute(&db).await.unwrap();
        assert!(writer.record(&notification).await.is_err());
        sqlx::query("ALTER TABLE posthog_errortrackingissuechange DROP CONSTRAINT reject_spikes")
            .execute(&db)
            .await
            .unwrap();
        writer.record(&notification).await.unwrap();
        let row: (f64, i64, Uuid) = sqlx::query_as(
            "SELECT (data->>'computed_baseline')::double precision, (data->>'current_bucket_value')::bigint, event_uuid FROM posthog_errortrackingissuechange",
        ).fetch_one(&db).await.unwrap();
        assert_eq!(row, (12.5, 140, notification.event_uuid));
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn a_deadline_releases_blocked_database_work_and_bounds_pool_wait(db: PgPool) {
        let notification = notification(&db).await;
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .connect_with((*db.connect_options()).clone())
            .await
            .unwrap();
        let writer = SpikeChangeWriter {
            pool: pool.clone(),
            timeout: Duration::from_millis(100),
        };
        let mut blocker = db.begin().await.unwrap();
        sqlx::query("LOCK TABLE posthog_errortrackingissuechange IN ACCESS EXCLUSIVE MODE")
            .execute(&mut *blocker)
            .await
            .unwrap();
        assert!(
            tokio::time::timeout(Duration::from_secs(2), writer.record(&notification))
                .await
                .unwrap()
                .is_err()
        );
        let lease = tokio::time::timeout(Duration::from_secs(5), pool.acquire())
            .await
            .unwrap()
            .unwrap();
        assert!(
            tokio::time::timeout(Duration::from_secs(2), writer.record(&notification))
                .await
                .unwrap()
                .is_err()
        );
        drop(lease);
        blocker.rollback().await.unwrap();
        let writer = SpikeChangeWriter {
            pool: pool.clone(),
            timeout: Duration::from_secs(10),
        };
        writer.record(&notification).await.unwrap();
        let row: Uuid = sqlx::query_scalar("SELECT id FROM posthog_errortrackingissuechange")
            .fetch_one(&db)
            .await
            .unwrap();
        assert_eq!(row, notification.change_id.unwrap());
        pool.close().await;
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn legacy_and_invalid_notifications_do_not_block_the_partition(db: PgPool) {
        let mut notification = notification(&db).await;
        let mut legacy = notification.clone();
        legacy.change_id = None;
        let writer = SpikeChangeWriter {
            pool: db.clone(),
            timeout: Duration::from_secs(10),
        };
        writer.record(&legacy).await.unwrap();
        notification.event_timestamp = "not a timestamp".to_string();
        writer.record(&notification).await.unwrap();
        let count: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM posthog_errortrackingissuechange")
                .fetch_one(&db)
                .await
                .unwrap();
        assert_eq!(count, 0);
    }
}
