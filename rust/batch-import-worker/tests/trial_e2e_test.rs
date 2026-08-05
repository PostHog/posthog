//! End-to-end trial run test: the real `TrialJob` against local Postgres and
//! SeaweedFS (docker-compose.dev.yml). A `FolderSource` chunked small enough to
//! split lines at chunk boundaries feeds the production trial parser, pages land
//! in SeaweedFS via the real trial store client, and progress/status flushes go
//! through the lease-guarded Postgres path.
//!
//! Skips when the dev stack isn't running (SeaweedFS unreachable is a hard
//! failure in CI, matching the temp-bucket integration test).

use std::sync::Arc;

use batch_import_worker::config::Config;
use batch_import_worker::context::AppContext;
use batch_import_worker::job::config::{
    FolderSourceConfig, JobConfig, JobSecrets, SinkConfig, SourceConfig,
};
use batch_import_worker::job::model::{JobModel, JobStatus};
use batch_import_worker::parse::content::ContentType;
use batch_import_worker::parse::format::FormatConfig;
use batch_import_worker::trial::TrialJob;
use chrono::Utc;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use object_store::aws::AmazonS3Builder;
use object_store::path::Path;
use object_store::{ObjectStore, ObjectStoreExt};
use serde_json::Value;
use tempfile::TempDir;
use uuid::Uuid;

const SEAWEEDFS_ENDPOINT: &str = "http://localhost:8333";
const TEST_BUCKET: &str = "posthog";
const TEAM_ID: i32 = 1;
// Small enough to split the ~100-byte test lines across chunk boundaries.
const CHUNK_SIZE: usize = 96;
const RECORDS_PER_PAGE: usize = 3;

fn valid_line(n: usize) -> String {
    format!(
        r#"{{"event":"event_{n}","distinct_id":"user_{n}","timestamp":"2024-01-01T00:00:00Z","properties":{{}}}}"#
    )
}

/// 12 lines: 10 valid, one malformed (index 3), one missing distinct_id (index 7).
fn source_lines() -> Vec<String> {
    (0..12)
        .map(|n| match n {
            3 => "{broken json".to_string(),
            7 => r#"{"event":"orphan","properties":{}}"#.to_string(),
            _ => valid_line(n),
        })
        .collect()
}

fn seaweedfs_store() -> Arc<dyn ObjectStore> {
    let store = AmazonS3Builder::new()
        .with_bucket_name(TEST_BUCKET)
        .with_endpoint(SEAWEEDFS_ENDPOINT)
        .with_region("us-east-1")
        .with_allow_http(true)
        .with_virtual_hosted_style_request(false)
        // SeaweedFS dev runs in open-access mode; any credentials are accepted.
        .with_access_key_id("any")
        .with_secret_access_key("any")
        .build()
        .expect("failed to build SeaweedFS object_store");
    Arc::new(store)
}

/// Probe SeaweedFS: unreachable is a silent skip locally but a hard failure in
/// CI, where the dev stack is always booted.
async fn seaweedfs_reachable(store: &Arc<dyn ObjectStore>) -> bool {
    let probe = Path::from("__reachability_probe__");
    let result = tokio::time::timeout(std::time::Duration::from_secs(3), store.head(&probe)).await;
    let reachable = matches!(
        result,
        Ok(Ok(_)) | Ok(Err(object_store::Error::NotFound { .. }))
    );
    if !reachable && std::env::var("CI").is_ok() {
        panic!("SeaweedFS unreachable at {SEAWEEDFS_ENDPOINT} in CI — the dev stack must be up");
    }
    reachable
}

struct TrialRun {
    // Owns the source directory for the duration of the run.
    _dir: TempDir,
    context: Arc<AppContext>,
    store: Arc<dyn ObjectStore>,
    prefix: String,
    job_id: Uuid,
    model: JobModel,
}

impl TrialRun {
    /// Set up config, context, source dir, and a leased `posthog_batchimport`
    /// row, exactly as a claimed trial job would look. Returns `None` (skip)
    /// when the dev stack or the seed team isn't available.
    async fn create(record_limit: u64) -> Option<Self> {
        let store = seaweedfs_store();
        if !seaweedfs_reachable(&store).await {
            eprintln!("SeaweedFS unreachable at {SEAWEEDFS_ENDPOINT}, skipping test");
            return None;
        }

        let mut config = Config::init_from_env().unwrap();
        config.trial_bucket_name = TEST_BUCKET.to_string();
        config.trial_bucket_endpoint = SEAWEEDFS_ENDPOINT.to_string();
        config.trial_bucket_region = "us-east-1".to_string();
        config.trial_bucket_access_key_id = "any".to_string();
        config.trial_bucket_secret_access_key = "any".to_string();
        config.trial_bucket_force_path_style = true;
        config.trial_bucket_prefix = "trial-e2e-test/".to_string();
        config.trial_records_per_page = RECORDS_PER_PAGE;
        config.trial_chunk_size = CHUNK_SIZE;

        let Ok(context) = AppContext::new(&config).await else {
            eprintln!(
                "Postgres unreachable at {}, skipping test",
                config.database_url
            );
            return None;
        };
        let context = Arc::new(context);

        // The trial parser resolves the team's token; the dev/CI database seeds
        // team 1. Skip (rather than fabricate a team) when it's absent.
        if context.get_token_for_team_id(TEAM_ID).await.is_err() {
            eprintln!("team {TEAM_ID} not found in database, skipping test");
            return None;
        }

        let dir = TempDir::new().unwrap();
        std::fs::write(
            dir.path().join("events.jsonl"),
            source_lines().join("\n") + "\n",
        )
        .unwrap();

        let job_id = Uuid::now_v7();
        let lease_id = format!("trial-e2e-{job_id}");
        let import_config = JobConfig {
            source: SourceConfig::Folder(FolderSourceConfig {
                path: dir.path().to_string_lossy().to_string(),
            }),
            data_format: FormatConfig::JsonLines {
                skip_blanks: true,
                content: ContentType::Captured,
            },
            sink: SinkConfig::TrialS3 { record_limit },
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: false,
        };

        sqlx::query(
            r#"
            INSERT INTO posthog_batchimport
                (id, team_id, created_at, updated_at, status, import_config, secrets, lease_id, leased_until, backoff_attempt)
            VALUES ($1, $2, now(), now(), 'running', $3, '', $4, now() + interval '30 minutes', 0)
            "#,
        )
        .bind(job_id)
        .bind(TEAM_ID)
        .bind(serde_json::to_value(&import_config).unwrap())
        .bind(&lease_id)
        .execute(&context.db)
        .await
        .unwrap();

        let model = JobModel {
            id: job_id,
            team_id: TEAM_ID,
            created_at: Utc::now(),
            updated_at: Utc::now(),
            lease_id: Some(lease_id.clone()),
            leased_until: None,
            status: JobStatus::Running,
            status_message: None,
            display_status_message: None,
            state: None,
            import_config,
            secrets: JobSecrets::empty(),
            backoff_attempt: 0,
            backoff_until: None,
            was_leased: false,
        };

        let prefix = format!("trial-e2e-test/team_{TEAM_ID}/job_{job_id}");
        Some(Self {
            _dir: dir,
            context,
            store,
            prefix,
            job_id,
            model,
        })
    }

    async fn run_job(&self) {
        let mut manager = Manager::builder("trial-e2e-test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .build();
        let handle = manager.register("job", ComponentOptions::new());

        let job = TrialJob::new(self.model.clone(), self.context.clone(), handle)
            .await
            .unwrap();
        job.run().await.unwrap();
    }

    async fn db_status_and_state(&self) -> (String, Value) {
        let row: (String, Value) =
            sqlx::query_as("SELECT status, state FROM posthog_batchimport WHERE id = $1")
                .bind(self.job_id)
                .fetch_one(&self.context.db)
                .await
                .unwrap();
        row
    }

    async fn read_object(&self, rel: &str) -> Vec<u8> {
        self.store
            .get(&Path::from(format!("{}/{rel}", self.prefix)))
            .await
            .unwrap()
            .bytes()
            .await
            .unwrap()
            .to_vec()
    }

    async fn read_all_page_lines(&self, pages: u64) -> Vec<Value> {
        let mut lines = vec![];
        for page in 0..pages {
            let bytes = self.read_object(&format!("pages/{page:05}.jsonl")).await;
            for line in String::from_utf8(bytes).unwrap().lines() {
                lines.push(serde_json::from_str(line).unwrap());
            }
        }
        lines
    }

    /// Best-effort teardown: the row is deleted; objects are left under the
    /// uniquely-named job prefix.
    async fn cleanup(&self) {
        sqlx::query("DELETE FROM posthog_batchimport WHERE id = $1")
            .bind(self.job_id)
            .execute(&self.context.db)
            .await
            .ok();
    }
}

#[tokio::test]
async fn trial_job_pairs_every_source_line_and_completes() {
    let Some(run) = TrialRun::create(100).await else {
        return;
    };
    run.run_job().await;

    let (status, state) = run.db_status_and_state().await;
    assert_eq!(status, "completed");

    // Progress persisted through the lease-guarded flush path
    let trial = &state["trial"];
    assert_eq!(trial["records_emitted"], 12);
    assert_eq!(trial["summary"]["dropped_records"], 2);
    assert_eq!(trial["summary"]["output_events"], 10);
    let pages = trial["pages_written"].as_u64().unwrap();

    // Every source line becomes exactly one record despite lines being split
    // across ~96-byte chunks, and bad lines don't abort the run.
    let lines = run.read_all_page_lines(pages).await;
    assert_eq!(lines.len(), 12);
    for (i, line) in lines.iter().enumerate() {
        assert_eq!(
            line["seq"].as_u64(),
            Some(i as u64),
            "seq must be continuous"
        );
    }

    // The two planted failures carry their reasons and original source
    assert!(lines[3]["error"].as_str().is_some());
    assert_eq!(
        lines[3]["source"],
        Value::String("{broken json".to_string())
    );
    assert_eq!(lines[7]["error"], "No distinct_id found");
    assert_eq!(lines[7]["source"]["event"], "orphan");

    // A valid record pairs its source with the transformed output
    assert_eq!(lines[0]["source"]["event"], "event_0");
    assert_eq!(lines[0]["outputs"][0]["event"], "event_0");
    assert_eq!(lines[0]["outputs"][0]["distinct_id"], "user_0");
    assert_eq!(
        lines[0]["outputs"][0]["payload"]["properties"]["$import_job_id"],
        run.job_id.to_string()
    );

    // Summary is readable and consistent with the pages
    let summary: Value = serde_json::from_slice(&run.read_object("summary.json").await).unwrap();
    assert_eq!(summary["records"], 12);
    assert_eq!(summary["pages"], pages);
    assert_eq!(summary["error_counts"]["No distinct_id found"], 1);

    run.cleanup().await;
}

#[tokio::test]
async fn trial_job_stops_at_the_record_limit() {
    let Some(run) = TrialRun::create(4).await else {
        return;
    };
    run.run_job().await;

    let (status, state) = run.db_status_and_state().await;
    assert_eq!(status, "completed");
    assert_eq!(state["trial"]["records_emitted"], 4);

    let pages = state["trial"]["pages_written"].as_u64().unwrap();
    let lines = run.read_all_page_lines(pages).await;
    assert_eq!(lines.len(), 4);
    assert_eq!(lines.last().unwrap()["seq"], 3);

    run.cleanup().await;
}
