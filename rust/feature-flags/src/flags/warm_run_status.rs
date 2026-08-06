//! Run-state reporting for bulk flag-cache warming.
//!
//! The warmer publishes a JSON status blob into the flags Redis so the Django
//! staff API (`products/feature_flags/backend/api/staff_cache.py`) can show
//! live progress of a warm-all run and request cancellation, regardless of
//! where the run was started (staff UI in the future, a jumphost shell today).
//!
//! Interop contract: values are written through the client's default value
//! format (pickle + zstd), which mirrors Django's `flags_dedicated` cache
//! (`django_redis` + `ZstdCompressor`), so Django reads the blob with a plain
//! `caches["flags_dedicated"].get(...)` and vice versa for the cancel key.

use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use common_redis::{Client, CustomRedisError};
use serde::{Deserialize, Serialize};

/// Full Redis keys. django-redis addresses keys as `KEY_PREFIX:VERSION:key`
/// ("posthog:1:" in our config), so the Django-relative keys are
/// `feature_flags/warm_run/status` and `feature_flags/warm_run/cancel`.
pub const WARM_RUN_STATUS_KEY: &str = "posthog:1:feature_flags/warm_run/status";
pub const WARM_RUN_CANCEL_KEY: &str = "posthog:1:feature_flags/warm_run/cancel";

/// Status outlives the run so the staff page can show the last outcome.
const STATUS_TTL_SECONDS: u64 = 7 * 24 * 3600;

/// Minimum interval between status writes; also the cancel-poll cadence.
/// Doubles as the heartbeat period — a running status whose `updated_at` is
/// much older than this means the warmer process died.
pub const REPORT_INTERVAL: Duration = Duration::from_secs(5);

/// A `running` status with a heartbeat older than this is treated as a dead
/// run (the process was killed without writing a final state): the start
/// guard lets a new run overwrite it, and the Django staff API flags it as
/// stale. Keep in sync with WARM_RUN_HEARTBEAT_STALE_SECONDS in
/// `products/feature_flags/backend/api/staff_cache.py`. At a 5s heartbeat,
/// 120s of silence is 24 missed beats — far beyond any Redis blip.
pub const HEARTBEAT_STALE_AFTER_SECONDS: i64 = 120;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WarmRunState {
    Running,
    Completed,
    Cancelled,
}

/// The status blob as stored in Redis. Field names are a contract with the
/// Django staff API serializer — change them in lockstep.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WarmRunStatus {
    pub run_id: String,
    pub state: WarmRunState,
    /// Which team scope the run covers: "all_teams" or "teams_with_flags".
    pub scope: String,
    pub total: usize,
    pub processed: usize,
    pub successful: usize,
    pub failed: usize,
    /// Highest team id handed to a warm task so far. A resume from this cursor
    /// can skip up to `concurrency` teams that were in flight when the process
    /// died; their per-team failures are logged and self-heal on the next
    /// organic invalidation or TTL refresh.
    pub last_team_id: Option<i32>,
    /// Epoch seconds. Serialized as integers (not RFC3339) so the Django
    /// reader never has to parse chrono's nanosecond-precision timestamps.
    #[serde(with = "chrono::serde::ts_seconds")]
    pub started_at: DateTime<Utc>,
    /// Heartbeat: bumped on every status write while running. Epoch seconds.
    #[serde(with = "chrono::serde::ts_seconds")]
    pub updated_at: DateTime<Utc>,
}

/// Read the current status blob, if any. A missing key or an unparseable blob
/// (e.g. written by a newer/older binary) both read as "no run".
pub async fn read_current_status(redis: &Arc<dyn Client + Send + Sync>) -> Option<WarmRunStatus> {
    match redis.get(WARM_RUN_STATUS_KEY.to_string()).await {
        Ok(raw) => match serde_json::from_str::<WarmRunStatus>(&raw) {
            Ok(status) => Some(status),
            Err(e) => {
                tracing::warn!(error = %e, "Ignoring unparseable warm-run status blob");
                None
            }
        },
        Err(CustomRedisError::NotFound) => None,
        Err(e) => {
            tracing::warn!(error = %e, "Failed to read warm-run status");
            None
        }
    }
}

/// True when `status` describes a run that still appears to be alive: state is
/// `running` and the heartbeat is fresher than [`HEARTBEAT_STALE_AFTER_SECONDS`].
pub fn is_active(status: &WarmRunStatus, now: DateTime<Utc>) -> bool {
    status.state == WarmRunState::Running
        && (now - status.updated_at).num_seconds() <= HEARTBEAT_STALE_AFTER_SECONDS
}

/// Publishes run state to Redis with throttled writes and polls for
/// cancellation. All Redis failures are best-effort: a status blip must never
/// sink a multi-hour warm run, so errors log a warning and the run continues.
pub struct WarmRunReporter {
    redis: Arc<dyn Client + Send + Sync>,
    status: WarmRunStatus,
    last_write: Instant,
}

impl WarmRunReporter {
    pub fn new(
        redis: Arc<dyn Client + Send + Sync>,
        run_id: String,
        scope: String,
        total: usize,
    ) -> Self {
        let now = Utc::now();
        Self {
            redis,
            status: WarmRunStatus {
                run_id,
                state: WarmRunState::Running,
                scope,
                total,
                processed: 0,
                successful: 0,
                failed: 0,
                last_team_id: None,
                started_at: now,
                updated_at: now,
            },
            last_write: Instant::now(),
        }
    }

    pub fn run_id(&self) -> &str {
        &self.status.run_id
    }

    /// Publish the initial `running` status.
    pub async fn start(&mut self) {
        self.write().await;
    }

    /// Update in-memory counters. Cheap and sync — call freely from the warm
    /// loop; the Redis write happens in [`Self::maybe_report`].
    pub fn record(
        &mut self,
        processed: usize,
        successful: usize,
        failed: usize,
        last_team_id: Option<i32>,
    ) {
        self.status.processed = processed;
        self.status.successful = successful;
        self.status.failed = failed;
        if last_team_id.is_some() {
            self.status.last_team_id = last_team_id;
        }
    }

    /// If the report interval has elapsed, write the current status and poll
    /// the cancel key. Returns true when cancellation was requested for this
    /// run — the caller should stop dispatching new teams.
    pub async fn maybe_report(&mut self) -> bool {
        if self.last_write.elapsed() < REPORT_INTERVAL {
            return false;
        }
        self.write().await;
        self.cancel_requested().await
    }

    /// Publish the terminal state.
    pub async fn finish(&mut self, state: WarmRunState) {
        self.status.state = state;
        self.write().await;
    }

    /// True when the cancel key holds this run's id. Values left over from
    /// cancelling an earlier run don't match and are ignored.
    pub async fn cancel_requested(&self) -> bool {
        match self.redis.get(WARM_RUN_CANCEL_KEY.to_string()).await {
            Ok(value) => value == self.status.run_id,
            Err(CustomRedisError::NotFound) => false,
            Err(e) => {
                tracing::warn!(error = %e, "Failed to poll warm-run cancel key");
                false
            }
        }
    }

    async fn write(&mut self) {
        self.status.updated_at = Utc::now();
        self.last_write = Instant::now();
        let payload = match serde_json::to_string(&self.status) {
            Ok(payload) => payload,
            Err(e) => {
                tracing::warn!(error = %e, "Failed to serialize warm-run status");
                return;
            }
        };
        if let Err(e) = self
            .redis
            .setex(WARM_RUN_STATUS_KEY.to_string(), payload, STATUS_TTL_SECONDS)
            .await
        {
            tracing::warn!(error = %e, "Failed to write warm-run status");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::{MockRedisClient, MockRedisValue};

    fn reporter_with(redis: MockRedisClient) -> WarmRunReporter {
        WarmRunReporter::new(
            Arc::new(redis),
            "run-abc".to_string(),
            "teams_with_flags".to_string(),
            100,
        )
    }

    fn written_status(redis: &MockRedisClient) -> WarmRunStatus {
        let calls = redis.get_calls();
        let write = calls
            .iter()
            .rev()
            .find(|c| c.op == "setex" && c.key == WARM_RUN_STATUS_KEY)
            .expect("expected a setex on the status key");
        match &write.value {
            MockRedisValue::StringWithTTL(payload, ttl) => {
                assert_eq!(*ttl, STATUS_TTL_SECONDS);
                serde_json::from_str(payload).expect("status payload must be valid JSON")
            }
            other => panic!("expected StringWithTTL, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn start_publishes_running_status() {
        let mut redis = MockRedisClient::new();
        redis.set_ret(WARM_RUN_STATUS_KEY, Ok(()));
        let redis = redis;

        let mut reporter = reporter_with(redis.clone());
        reporter.start().await;

        let status = written_status(&redis);
        assert_eq!(status.state, WarmRunState::Running);
        assert_eq!(status.run_id, "run-abc");
        assert_eq!(status.total, 100);
        assert_eq!(status.processed, 0);
    }

    #[tokio::test]
    async fn maybe_report_throttles_within_interval() {
        let redis = MockRedisClient::new();
        let mut reporter = reporter_with(redis.clone());
        // last_write is now, so the interval has not elapsed.
        let cancelled = reporter.maybe_report().await;
        assert!(!cancelled);
        assert!(
            redis.get_calls().is_empty(),
            "no Redis traffic expected inside the report interval"
        );
    }

    #[tokio::test]
    async fn maybe_report_writes_and_polls_after_interval() {
        let mut redis = MockRedisClient::new();
        redis.set_ret(WARM_RUN_STATUS_KEY, Ok(()));
        let redis = redis;

        let mut reporter = reporter_with(redis.clone());
        reporter.record(50, 48, 2, Some(4321));
        reporter.last_write = Instant::now() - REPORT_INTERVAL;

        let cancelled = reporter.maybe_report().await;
        assert!(!cancelled, "no cancel key set, so not cancelled");

        let status = written_status(&redis);
        assert_eq!(status.processed, 50);
        assert_eq!(status.successful, 48);
        assert_eq!(status.failed, 2);
        assert_eq!(status.last_team_id, Some(4321));
    }

    #[tokio::test]
    async fn cancel_only_honored_for_matching_run_id() {
        let mut redis = MockRedisClient::new();
        redis.get_ret(WARM_RUN_CANCEL_KEY, Ok("some-older-run".to_string()));
        let reporter = reporter_with(redis);
        assert!(!reporter.cancel_requested().await);

        let mut redis = MockRedisClient::new();
        redis.get_ret(WARM_RUN_CANCEL_KEY, Ok("run-abc".to_string()));
        let reporter = reporter_with(redis);
        assert!(reporter.cancel_requested().await);
    }

    #[tokio::test]
    async fn cancel_absent_key_reads_as_not_cancelled() {
        let reporter = reporter_with(MockRedisClient::new());
        assert!(!reporter.cancel_requested().await);
    }

    #[tokio::test]
    async fn finish_publishes_terminal_state() {
        let mut redis = MockRedisClient::new();
        redis.set_ret(WARM_RUN_STATUS_KEY, Ok(()));
        let redis = redis;

        let mut reporter = reporter_with(redis.clone());
        reporter.record(100, 97, 3, Some(9999));
        reporter.finish(WarmRunState::Completed).await;

        let status = written_status(&redis);
        assert_eq!(status.state, WarmRunState::Completed);
        assert_eq!(status.processed, 100);
    }

    /// The JSON field names and state values are a contract with the Django
    /// staff API — lock them down so a rename can't silently break the UI.
    #[test]
    fn status_json_shape_is_stable() {
        let status = WarmRunStatus {
            run_id: "r".to_string(),
            state: WarmRunState::Running,
            scope: "all_teams".to_string(),
            total: 1,
            processed: 0,
            successful: 0,
            failed: 0,
            last_team_id: None,
            started_at: Utc::now(),
            updated_at: Utc::now(),
        };
        let value: serde_json::Value =
            serde_json::from_str(&serde_json::to_string(&status).unwrap()).unwrap();
        for field in [
            "run_id",
            "state",
            "scope",
            "total",
            "processed",
            "successful",
            "failed",
            "last_team_id",
            "started_at",
            "updated_at",
        ] {
            assert!(value.get(field).is_some(), "missing field {field}");
        }
        assert_eq!(value["state"], "running");
        assert!(
            value["started_at"].is_i64() && value["updated_at"].is_i64(),
            "timestamps must serialize as epoch seconds for the Django reader"
        );
        assert_eq!(
            serde_json::to_value(WarmRunState::Cancelled).unwrap(),
            "cancelled"
        );
        assert_eq!(
            serde_json::to_value(WarmRunState::Completed).unwrap(),
            "completed"
        );
    }

    #[test]
    fn is_active_requires_running_state_and_fresh_heartbeat() {
        let now = Utc::now();
        let mut status = WarmRunStatus {
            run_id: "r".to_string(),
            state: WarmRunState::Running,
            scope: "all_teams".to_string(),
            total: 1,
            processed: 0,
            successful: 0,
            failed: 0,
            last_team_id: None,
            started_at: now,
            updated_at: now,
        };
        assert!(is_active(&status, now));

        status.updated_at = now - chrono::Duration::seconds(HEARTBEAT_STALE_AFTER_SECONDS);
        assert!(
            is_active(&status, now),
            "heartbeat exactly at the threshold matches the Django reader's `> stale` check"
        );

        status.updated_at = now - chrono::Duration::seconds(HEARTBEAT_STALE_AFTER_SECONDS + 1);
        assert!(!is_active(&status, now), "stale heartbeat is not active");

        status.updated_at = now;
        status.state = WarmRunState::Completed;
        assert!(!is_active(&status, now), "terminal state is not active");
    }
}
