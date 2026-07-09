//! Full-worker lifecycle tests against the real `posthog_batchimport` table:
//! claim, run, pause-with-user-message, resume, complete - the only layer the
//! in-process e2e suites skip. Uses the dev-stack Postgres (localhost:15432,
//! `DATABASE_URL` overrides) and skips when it, the table, or a team row is
//! unavailable.
//!
//! Tests are serialized: `JobModel::claim_next_job` claims *any* claimable job,
//! so concurrent tests would steal each other's rows. For the same reason each
//! test skips if the database already has claimable batch-import jobs (e.g. a
//! developer's real local import) - claiming those would mutate their leases.

use std::sync::{Arc, OnceLock};

use base64::prelude::*;
use batch_import_worker::config::Config;
use batch_import_worker::context::AppContext;
use batch_import_worker::job::config::JobSecrets;
use batch_import_worker::job::model::{JobModel, JobStatus};
use batch_import_worker::job::Job;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

mod common;
use common::mock_export::{Behavior, MockExport, Provider};
use common::{seaweedfs_reachable, seaweedfs_store};

const DEV_DATABASE_URL: &str = "postgres://posthog:posthog@localhost:15432/posthog";
const SEED: u64 = 0x11f3;

static PG_TEST_MUTEX: OnceLock<tokio::sync::Mutex<()>> = OnceLock::new();

/// Restores (or removes) env vars on drop, so a panicking test can't leak
/// staging config into the next test in the same process.
struct EnvGuard {
    saved: Vec<(String, Option<String>)>,
}

impl EnvGuard {
    fn set(vars: &[(&str, &str)]) -> Self {
        let saved = vars
            .iter()
            .map(|(k, _)| (k.to_string(), std::env::var(k).ok()))
            .collect();
        for (k, v) in vars {
            std::env::set_var(k, v);
        }
        Self { saved }
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        for (k, old) in &self.saved {
            match old {
                Some(v) => std::env::set_var(k, v),
                None => std::env::remove_var(k),
            }
        }
    }
}

struct PgHarness {
    context: Arc<AppContext>,
    team_id: i32,
    handle: lifecycle::Handle,
    // Keeps the lifecycle manager's monitor alive for the handle's lifetime.
    _monitor: lifecycle::MonitorGuard,
    inserted: Vec<Uuid>,
}

impl PgHarness {
    /// `None` means skip: Postgres/schema/team unavailable, or the DB already
    /// has claimable jobs this test must not touch.
    async fn try_new() -> Option<Self> {
        if std::env::var("DATABASE_URL").is_err() {
            std::env::set_var("DATABASE_URL", DEV_DATABASE_URL);
        }
        let config = Config::init_from_env().ok()?;
        let Ok(context) = AppContext::new(&config).await else {
            eprintln!("Postgres unreachable, skipping test");
            return None;
        };

        let team_id: i32 =
            match sqlx::query_scalar::<_, i32>("SELECT id FROM posthog_team ORDER BY id LIMIT 1")
                .fetch_optional(&context.db)
                .await
            {
                Ok(Some(id)) => id,
                Ok(None) => {
                    eprintln!("No team in database, skipping test");
                    return None;
                }
                Err(e) => {
                    eprintln!("Schema probe failed ({e}), skipping test");
                    return None;
                }
            };

        let claimable: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM posthog_batchimport \
             WHERE status = 'running' AND (leased_until IS NULL OR leased_until <= now())",
        )
        .fetch_one(&context.db)
        .await
        .ok()?;
        if claimable > 0 {
            eprintln!("Database already has {claimable} claimable batch imports, skipping test");
            return None;
        }

        let token = CancellationToken::new();
        let mut manager = Manager::builder("batch-import-lifecycle-test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_shutdown_token(token)
            .build();
        let handle = manager.register("job", ComponentOptions::new());
        let monitor = manager.monitor_background();

        Some(Self {
            context: Arc::new(context),
            team_id,
            handle,
            _monitor: monitor,
            inserted: Vec::new(),
        })
    }

    /// Insert a claimable Mixpanel date-range job pointed at `mock`.
    async fn insert_job(&mut self, mock: &MockExport, start_day: &str, days: u32) -> Uuid {
        let start = format!("{start_day}T00:00:00Z");
        let end_date = chrono::NaiveDate::parse_from_str(start_day, "%Y-%m-%d").unwrap()
            + chrono::Duration::days(days as i64);
        let end = format!("{end_date}T00:00:00Z");

        let import_config = serde_json::json!({
            "source": {
                "type": "date_range_export",
                "base_url": mock.export_url(),
                "extractor_type": "plain_gzip",
                "start": start,
                "end": end,
                "start_qp": "from_date",
                "end_qp": "to_date",
                "auth": { "type": "mixpanel_auth", "secret_key_secret": "secret_key" },
                "interval_duration": 86400,
                "date_format": "%Y-%m-%d",
            },
            "data_format": {
                "type": "json_lines",
                "skip_blanks": true,
                "content": {
                    "type": "mixpanel",
                    "skip_no_distinct_id": false,
                    "timestamp_offset_seconds": null,
                },
            },
            "sink": { "type": "noop" },
        });

        // `encrypt` expects already-b64-encoded fernet keys, while `decrypt`
        // (the claim path) encodes the raw configured keys itself - so encode
        // here to produce what the worker will successfully decrypt.
        let keys: Vec<String> = self
            .context
            .encryption_keys
            .iter()
            .map(|k| BASE64_URL_SAFE.encode(k.as_bytes()))
            .collect();
        let secrets = JobSecrets {
            secrets: [(
                "secret_key".to_string(),
                serde_json::Value::String("mock-secret".to_string()),
            )]
            .into_iter()
            .collect(),
        }
        .encrypt(&keys)
        .expect("encrypting job secrets");

        let id = Uuid::now_v7();
        sqlx::query(
            "INSERT INTO posthog_batchimport \
             (id, team_id, created_at, updated_at, status, import_config, secrets, backoff_attempt) \
             VALUES ($1, $2, now(), now(), 'running', $3, $4, 0)",
        )
        .bind(id)
        .bind(self.team_id)
        .bind(&import_config)
        .bind(&secrets)
        .execute(&self.context.db)
        .await
        .expect("inserting batch import row");
        self.inserted.push(id);
        id
    }

    /// Claim the next job (must be `expected`, per the claimable-jobs guard)
    /// and drive `Job::process` until the worker relinquishes it.
    async fn claim_and_run(&self, expected: Uuid) {
        let model = JobModel::claim_next_job(self.context.clone())
            .await
            .expect("claiming job")
            .expect("a claimable job");
        assert_eq!(model.id, expected, "claimed a different job than seeded");

        let mut next = Some(
            Job::new(model, self.context.clone(), self.handle.clone())
                .await
                .expect("job init"),
        );
        while let Some(job) = next {
            next = job.process().await.expect("job process step");
        }
    }

    async fn row(&self, id: Uuid) -> (String, Option<String>, Option<serde_json::Value>) {
        sqlx::query_as::<_, (String, Option<String>, Option<serde_json::Value>)>(
            "SELECT status, display_status_message, state FROM posthog_batchimport WHERE id = $1",
        )
        .bind(id)
        .fetch_one(&self.context.db)
        .await
        .expect("fetching job row")
    }

    async fn cleanup(&self) {
        for id in &self.inserted {
            let _unused = sqlx::query("DELETE FROM posthog_batchimport WHERE id = $1")
                .bind(id)
                .execute(&self.context.db)
                .await;
        }
    }
}

#[tokio::test]
async fn claimed_job_runs_to_completion_and_persists_state() {
    let _lock = PG_TEST_MUTEX
        .get_or_init(|| tokio::sync::Mutex::new(()))
        .lock()
        .await;
    let Some(mut h) = PgHarness::try_new().await else {
        return;
    };

    let mock = MockExport::start(Provider::Mixpanel, SEED, 400).await;
    let id = h.insert_job(&mock, "2022-01-24", 2).await;

    h.claim_and_run(id).await;

    let (status, display, state) = h.row(id).await;
    assert_eq!(status, JobStatus::Completed.to_string());
    assert_eq!(display, None);
    let parts = state.expect("state persisted")["parts"]
        .as_array()
        .expect("parts array")
        .clone();
    assert_eq!(parts.len(), 2);
    for part in &parts {
        let offset = part["current_offset"].as_u64().unwrap();
        let total = part["total_size"].as_u64().expect("total_size persisted");
        assert!(
            offset >= total,
            "part not complete in persisted state: {part}"
        );
    }
    for day in ["2022-01-24", "2022-01-25"] {
        assert_eq!(mock.download_count(day), 1, "day {day}");
    }

    h.cleanup().await;
}

/// The support-facing surface of a bad-data pause, end to end: the row a
/// customer-facing engineer reads must carry the user-facing parse message
/// with the date-range suffix, and flipping the row back to running (what the
/// resume endpoint does) must let the job finish once the data is fixed.
#[tokio::test]
async fn parse_failure_pauses_with_date_ranged_message_and_resume_completes() {
    let _lock = PG_TEST_MUTEX
        .get_or_init(|| tokio::sync::Mutex::new(()))
        .lock()
        .await;
    let Some(mut h) = PgHarness::try_new().await else {
        return;
    };

    let mock = MockExport::start(Provider::Mixpanel, SEED, 400).await;
    // Corrupt a line deep enough into the day to prove mid-part offsets
    // survive the pause/resume round trip through the DB.
    mock.set_behavior("2022-01-24", Behavior::CorruptLine { line: 300 });
    let id = h.insert_job(&mock, "2022-01-24", 1).await;

    h.claim_and_run(id).await;

    let (status, display, _) = h.row(id).await;
    assert_eq!(status, JobStatus::Paused.to_string());
    let display = display.expect("paused jobs carry a user-facing message");
    assert!(
        display.contains("Invalid JSON syntax"),
        "expected the parse message, got: {display}"
    );
    assert!(
        display.contains("Date range: 2022-01-24"),
        "expected the date-range suffix, got: {display}"
    );

    // The customer fixes their data; support resumes the job. Mirror the
    // resume endpoint exactly (BatchImportViewSet.resume): pausing keeps the
    // worker's lease, so the resume must clear it or no worker can re-claim
    // the row for up to 30 minutes.
    mock.set_behavior("2022-01-24", Behavior::Stable);
    sqlx::query(
        "UPDATE posthog_batchimport \
         SET status = 'running', status_message = 'Resumed by user', \
             lease_id = NULL, leased_until = NULL, \
             backoff_attempt = 0, backoff_until = NULL \
         WHERE id = $1",
    )
    .bind(id)
    .execute(&h.context.db)
    .await
    .unwrap();

    h.claim_and_run(id).await;

    let (status, _, _) = h.row(id).await;
    assert_eq!(status, JobStatus::Completed.to_string());
    assert_eq!(
        mock.download_count("2022-01-24"),
        2,
        "pause + resume is exactly one re-download"
    );

    h.cleanup().await;
}

/// The env-to-backend wiring Phases 1-2 bypass: with `STAGING_BACKEND=
/// temp_bucket` configured through the real `Config`, a claimed job must
/// construct the temp-bucket backend from env and complete through it.
#[tokio::test]
async fn temp_bucket_staging_wired_from_env_config() {
    let _lock = PG_TEST_MUTEX
        .get_or_init(|| tokio::sync::Mutex::new(()))
        .lock()
        .await;

    let store = seaweedfs_store();
    if !seaweedfs_reachable(&store).await {
        eprintln!("SeaweedFS unreachable, skipping test");
        return;
    }

    let _env = EnvGuard::set(&[
        ("STAGING_BACKEND", "temp_bucket"),
        ("TEMP_BUCKET_NAME", common::SEAWEEDFS_BUCKET),
        ("TEMP_BUCKET_ENDPOINT", common::SEAWEEDFS_ENDPOINT),
        ("TEMP_BUCKET_REGION", "us-east-1"),
        ("TEMP_BUCKET_ACCESS_KEY_ID", "any"),
        ("TEMP_BUCKET_SECRET_ACCESS_KEY", "any"),
        ("TEMP_BUCKET_FORCE_PATH_STYLE", "true"),
    ]);
    // Context is built AFTER the env guard so the staging config flows through
    // the real envconfig path.
    let Some(mut h) = PgHarness::try_new().await else {
        return;
    };

    let mock = MockExport::start(Provider::Mixpanel, SEED, 400).await;
    let id = h.insert_job(&mock, "2022-01-24", 1).await;

    h.claim_and_run(id).await;

    let (status, display, _) = h.row(id).await;
    assert_eq!(
        status,
        JobStatus::Completed.to_string(),
        "job through env-configured temp-bucket staging failed: {display:?}"
    );
    assert_eq!(mock.download_count("2022-01-24"), 1);

    h.cleanup().await;
}
