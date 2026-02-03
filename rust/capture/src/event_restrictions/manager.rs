use std::collections::HashMap;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use common_redis::CustomRedisError;
use futures::future::join_all;
use metrics::gauge;
use tokio::sync::RwLock;
use tokio::time::interval;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use crate::config::CaptureMode;

use super::repository::EventRestrictionsRepository;
use super::types::{EventContext, Restriction, RestrictionSet, RestrictionType};

/// Manages restrictions by token.
#[derive(Debug, Clone, Default)]
pub struct RestrictionManager {
    pub restrictions: HashMap<String, Vec<Restriction>>,
}

impl RestrictionManager {
    pub fn new() -> Self {
        Self::default()
    }

    /// Get all restriction types that apply to an event.
    pub fn get_restrictions(&self, token: &str, event: &EventContext) -> RestrictionSet {
        let Some(restrictions) = self.restrictions.get(token) else {
            return RestrictionSet::new();
        };

        let mut result = RestrictionSet::new();
        for r in restrictions {
            if r.matches(event) {
                result.insert(r.restriction_type);
            }
        }
        result
    }

    /// Build a RestrictionManager from repository data for a specific pipeline.
    pub async fn from_repository(
        repository: &dyn EventRestrictionsRepository,
        pipeline: CaptureMode,
    ) -> Result<Self, CustomRedisError> {
        info!(pipeline = %pipeline.as_pipeline_name(), "Fetching event restrictions");

        let mut manager = Self::new();
        let pipeline_str = pipeline.as_pipeline_name();

        // Fetch all restriction types in parallel
        let fetch_futures = RestrictionType::all()
            .into_iter()
            .map(|rt| async move { (rt, repository.get_entries(rt).await) });

        let results = join_all(fetch_futures).await;

        for (restriction_type, result) in results {
            let entries = match result {
                Ok(Some(e)) => e,
                Ok(None) => continue,
                Err(e) => {
                    // Log but continue - we want to be resilient to partial failures
                    warn!(
                        restriction_type = %restriction_type.as_str(),
                        error = %e,
                        "Failed to fetch restriction entries"
                    );
                    continue;
                }
            };

            for entry in entries {
                // Skip if this entry doesn't apply to our pipeline
                if !entry.pipelines.contains(&pipeline_str.to_string()) {
                    continue;
                }

                // Skip old format entries (version must be 2)
                if entry.version != Some(2) {
                    continue;
                }

                let token = entry.token.clone();
                let restriction = entry.into_restriction(restriction_type);
                manager
                    .restrictions
                    .entry(token)
                    .or_default()
                    .push(restriction);
            }
        }

        let total_restrictions: usize = manager.restrictions.values().map(|v| v.len()).sum();
        let total_tokens = manager.restrictions.len();

        info!(
            pipeline = %pipeline_str,
            total_restrictions = total_restrictions,
            total_tokens = total_tokens,
            "Fetched event restrictions"
        );

        Ok(manager)
    }
}

/// Service that manages event restrictions with background refresh and fail-open behavior.
#[derive(Clone)]
pub struct EventRestrictionService {
    manager: Arc<RwLock<RestrictionManager>>,
    last_successful_refresh: Arc<AtomicI64>,
    fail_open_after: Duration,
    pipeline: CaptureMode,
}

impl EventRestrictionService {
    /// Create a new service. Call `start_refresh_task` to begin background updates.
    pub fn new(pipeline: CaptureMode, fail_open_after: Duration) -> Self {
        Self {
            manager: Arc::new(RwLock::new(RestrictionManager::new())),
            last_successful_refresh: Arc::new(AtomicI64::new(0)),
            fail_open_after,
            pipeline,
        }
    }

    /// Returns a future that refreshes restrictions periodically. Caller should spawn this.
    /// The task will run until the cancellation token is triggered.
    pub async fn start_refresh_task(
        &self,
        repository: Arc<dyn EventRestrictionsRepository>,
        refresh_interval: Duration,
        cancel_token: CancellationToken,
    ) {
        let pipeline_str = self.pipeline.as_pipeline_name();
        let mut interval = interval(refresh_interval);

        loop {
            tokio::select! {
                _ = cancel_token.cancelled() => {
                    info!(pipeline = %pipeline_str, "Event restrictions refresh task shutting down");
                    break;
                }
                _ = interval.tick() => {
                    self.refresh_from_repository(&repository).await;
                }
            }
        }
    }

    /// Fetch restrictions from repository and update the local cache.
    async fn refresh_from_repository(&self, repository: &Arc<dyn EventRestrictionsRepository>) {
        let pipeline_str = self.pipeline.as_pipeline_name();

        match RestrictionManager::from_repository(repository.as_ref(), self.pipeline).await {
            Ok(new_manager) => {
                let total_restrictions: usize =
                    new_manager.restrictions.values().map(|v| v.len()).sum();
                let total_tokens = new_manager.restrictions.len();

                let now = self.update(new_manager).await;

                gauge!(
                    "capture_event_restrictions_last_refresh_timestamp",
                    "pipeline" => pipeline_str.to_string()
                )
                .set(now as f64);

                gauge!(
                    "capture_event_restrictions_loaded_count",
                    "pipeline" => pipeline_str.to_string()
                )
                .set(total_restrictions as f64);

                gauge!(
                    "capture_event_restrictions_tokens_count",
                    "pipeline" => pipeline_str.to_string()
                )
                .set(total_tokens as f64);

                gauge!(
                    "capture_event_restrictions_stale",
                    "pipeline" => pipeline_str.to_string()
                )
                .set(0.0);
            }
            Err(e) => {
                error!(
                    pipeline = %pipeline_str,
                    error = %e,
                    "Failed to refresh event restrictions"
                );
            }
        }
    }

    /// Manually update restrictions (useful for testing). Returns the timestamp.
    pub async fn update(&self, new_manager: RestrictionManager) -> i64 {
        let mut guard = self.manager.write().await;
        *guard = new_manager;
        let now = chrono::Utc::now().timestamp();
        self.last_successful_refresh.store(now, Ordering::SeqCst);
        now
    }

    /// Check if the cache is stale (fail-open should be active).
    fn is_stale_at(&self, now_ts: i64) -> bool {
        let last_refresh = self.last_successful_refresh.load(Ordering::SeqCst);
        if last_refresh == 0 {
            return true;
        }

        // Use saturating_sub to handle potential clock skew (if now < last_refresh, age = 0)
        let age_secs = (now_ts as u64).saturating_sub(last_refresh as u64);
        Duration::from_secs(age_secs) > self.fail_open_after
    }

    /// Get restrictions for an event. Returns empty set if fail-open is active.
    pub async fn get_restrictions(&self, token: &str, event: &EventContext<'_>) -> RestrictionSet {
        if self.is_stale_at(event.now_ts) {
            gauge!(
                "capture_event_restrictions_stale",
                "pipeline" => self.pipeline.as_pipeline_name().to_string()
            )
            .set(1.0);
            return RestrictionSet::new();
        }

        let guard = self.manager.read().await;
        guard.get_restrictions(token, event)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event_restrictions::repository::testing::MockRestrictionsRepository;
    use crate::event_restrictions::repository::RestrictionEntry;
    use crate::event_restrictions::types::RestrictionScope;
    use common_redis::CustomRedisError;

    fn make_entry(token: &str, pipelines: Vec<&str>) -> RestrictionEntry {
        RestrictionEntry {
            version: Some(2),
            token: token.to_string(),
            pipelines: pipelines.into_iter().map(|s| s.to_string()).collect(),
            distinct_ids: vec![],
            session_ids: vec![],
            event_names: vec![],
            event_uuids: vec![],
        }
    }

    fn make_entry_with_filters(
        token: &str,
        pipelines: Vec<&str>,
        distinct_ids: Vec<&str>,
        event_names: Vec<&str>,
    ) -> RestrictionEntry {
        RestrictionEntry {
            version: Some(2),
            token: token.to_string(),
            pipelines: pipelines.into_iter().map(|s| s.to_string()).collect(),
            distinct_ids: distinct_ids.into_iter().map(|s| s.to_string()).collect(),
            session_ids: vec![],
            event_names: event_names.into_iter().map(|s| s.to_string()).collect(),
            event_uuids: vec![],
        }
    }

    #[tokio::test]
    async fn test_manager_applies_all_restriction_types() {
        let repo = MockRestrictionsRepository::new();

        // Set up one entry for each restriction type
        repo.set_entries(
            RestrictionType::DropEvent,
            Some(vec![make_entry("token_drop", vec!["analytics"])]),
        )
        .await;
        repo.set_entries(
            RestrictionType::ForceOverflow,
            Some(vec![make_entry("token_overflow", vec!["analytics"])]),
        )
        .await;
        repo.set_entries(
            RestrictionType::RedirectToDlq,
            Some(vec![make_entry("token_dlq", vec!["analytics"])]),
        )
        .await;
        repo.set_entries(
            RestrictionType::SkipPersonProcessing,
            Some(vec![make_entry("token_skip", vec!["analytics"])]),
        )
        .await;

        let manager = RestrictionManager::from_repository(&repo, CaptureMode::Events)
            .await
            .unwrap();

        let event = EventContext::default();

        // Each token should have exactly its restriction type
        let drop_restrictions = manager.get_restrictions("token_drop", &event);
        assert_eq!(drop_restrictions.len(), 1);
        assert!(drop_restrictions.contains(RestrictionType::DropEvent));

        let overflow_restrictions = manager.get_restrictions("token_overflow", &event);
        assert_eq!(overflow_restrictions.len(), 1);
        assert!(overflow_restrictions.contains(RestrictionType::ForceOverflow));

        let dlq_restrictions = manager.get_restrictions("token_dlq", &event);
        assert_eq!(dlq_restrictions.len(), 1);
        assert!(dlq_restrictions.contains(RestrictionType::RedirectToDlq));

        let skip_restrictions = manager.get_restrictions("token_skip", &event);
        assert_eq!(skip_restrictions.len(), 1);
        assert!(skip_restrictions.contains(RestrictionType::SkipPersonProcessing));

        // Unknown token should have no restrictions
        let unknown = manager.get_restrictions("unknown_token", &event);
        assert!(unknown.is_empty());
    }

    #[tokio::test]
    async fn test_manager_applies_filters_correctly() {
        let repo = MockRestrictionsRepository::new();

        repo.set_entries(
            RestrictionType::DropEvent,
            Some(vec![make_entry_with_filters(
                "token1",
                vec!["analytics"],
                vec!["user1", "user2"],
                vec!["$pageview"],
            )]),
        )
        .await;

        let manager = RestrictionManager::from_repository(&repo, CaptureMode::Events)
            .await
            .unwrap();

        // Should match when both distinct_id and event_name match
        let event_match = EventContext {
            distinct_id: Some("user1"),
            event_name: Some("$pageview"),
            ..Default::default()
        };
        let restrictions = manager.get_restrictions("token1", &event_match);
        assert!(restrictions.contains(RestrictionType::DropEvent));

        // Should NOT match when event_name doesn't match (AND logic)
        let event_wrong_name = EventContext {
            distinct_id: Some("user1"),
            event_name: Some("$identify"),
            ..Default::default()
        };
        let restrictions = manager.get_restrictions("token1", &event_wrong_name);
        assert!(restrictions.is_empty());

        // Should NOT match when distinct_id doesn't match
        let event_wrong_user = EventContext {
            distinct_id: Some("user3"),
            event_name: Some("$pageview"),
            ..Default::default()
        };
        let restrictions = manager.get_restrictions("token1", &event_wrong_user);
        assert!(restrictions.is_empty());
    }

    #[tokio::test]
    async fn test_manager_filters_by_pipeline() {
        let repo = MockRestrictionsRepository::new();

        repo.set_entries(
            RestrictionType::DropEvent,
            Some(vec![
                make_entry("token_analytics", vec!["analytics"]),
                make_entry("token_recordings", vec!["session_recordings"]),
                make_entry("token_both", vec!["analytics", "session_recordings"]),
            ]),
        )
        .await;

        // Fetch for analytics pipeline
        let manager = RestrictionManager::from_repository(&repo, CaptureMode::Events)
            .await
            .unwrap();

        let event = EventContext::default();

        // analytics token should be present
        assert!(!manager
            .get_restrictions("token_analytics", &event)
            .is_empty());

        // recordings token should NOT be present
        assert!(manager
            .get_restrictions("token_recordings", &event)
            .is_empty());

        // both token should be present
        assert!(!manager.get_restrictions("token_both", &event).is_empty());
    }

    #[tokio::test]
    async fn test_manager_skips_old_version() {
        let repo = MockRestrictionsRepository::new();

        let mut old_entry = make_entry("token_old", vec!["analytics"]);
        old_entry.version = Some(1); // Old version

        let new_entry = make_entry("token_new", vec!["analytics"]);

        repo.set_entries(RestrictionType::DropEvent, Some(vec![old_entry, new_entry]))
            .await;

        let manager = RestrictionManager::from_repository(&repo, CaptureMode::Events)
            .await
            .unwrap();

        let event = EventContext::default();

        // Old version should be skipped
        assert!(manager.get_restrictions("token_old", &event).is_empty());

        // New version should be present
        assert!(!manager.get_restrictions("token_new", &event).is_empty());
    }

    #[tokio::test]
    async fn test_manager_handles_repository_errors_gracefully() {
        let repo = MockRestrictionsRepository::new();

        // One type returns an error
        repo.set_error(RestrictionType::DropEvent, CustomRedisError::Timeout)
            .await;

        // Another type returns valid data
        repo.set_entries(
            RestrictionType::ForceOverflow,
            Some(vec![make_entry("token1", vec!["analytics"])]),
        )
        .await;

        // Should still succeed and return the valid data
        let manager = RestrictionManager::from_repository(&repo, CaptureMode::Events)
            .await
            .unwrap();

        let event = EventContext::default();
        let restrictions = manager.get_restrictions("token1", &event);
        assert!(restrictions.contains(RestrictionType::ForceOverflow));
    }

    #[tokio::test]
    async fn test_manager_handles_empty_repository() {
        let repo = MockRestrictionsRepository::new();
        // Don't set any entries

        let manager = RestrictionManager::from_repository(&repo, CaptureMode::Events)
            .await
            .unwrap();

        assert!(manager.restrictions.is_empty());
    }

    #[tokio::test]
    async fn test_manager_multiple_restrictions_same_token() {
        let repo = MockRestrictionsRepository::new();

        // Same token has multiple restriction types
        repo.set_entries(
            RestrictionType::ForceOverflow,
            Some(vec![make_entry("token1", vec!["analytics"])]),
        )
        .await;
        repo.set_entries(
            RestrictionType::SkipPersonProcessing,
            Some(vec![make_entry("token1", vec!["analytics"])]),
        )
        .await;

        let manager = RestrictionManager::from_repository(&repo, CaptureMode::Events)
            .await
            .unwrap();

        let restrictions = manager.get_restrictions("token1", &EventContext::default());
        assert_eq!(restrictions.len(), 2);
        assert!(restrictions.contains(RestrictionType::ForceOverflow));
        assert!(restrictions.contains(RestrictionType::SkipPersonProcessing));
    }

    // ========================================================================
    // EventRestrictionService tests
    // ========================================================================

    fn event_ctx_now() -> EventContext<'static> {
        EventContext {
            now_ts: chrono::Utc::now().timestamp(),
            ..Default::default()
        }
    }

    #[tokio::test]
    async fn test_service_is_stale_when_never_refreshed() {
        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        // last_successful_refresh is 0, so should be stale (fail-open)
        let restrictions = service.get_restrictions("token", &event_ctx_now()).await;
        assert!(restrictions.is_empty());
    }

    #[tokio::test]
    async fn test_service_returns_restrictions_after_update() {
        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));

        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "token1".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        let restrictions = service.get_restrictions("token1", &event_ctx_now()).await;
        assert!(restrictions.contains(RestrictionType::DropEvent));
    }

    #[tokio::test]
    async fn test_service_fail_open_after_timeout() {
        let service = EventRestrictionService::new(
            CaptureMode::Events,
            Duration::from_secs(1), // 1 second timeout
        );

        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "token1".to_string(),
            vec![Restriction {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::AllEvents,
            }],
        );
        service.update(manager).await;

        // Immediately after update, should return restrictions
        let restrictions = service.get_restrictions("token1", &event_ctx_now()).await;
        assert!(restrictions.contains(RestrictionType::DropEvent));

        // Manually set last_successful_refresh to 10 seconds ago
        let old_timestamp = chrono::Utc::now().timestamp() - 10;
        service
            .last_successful_refresh
            .store(old_timestamp, Ordering::SeqCst);

        // Now should be stale (fail-open)
        let restrictions_after = service.get_restrictions("token1", &event_ctx_now()).await;
        assert!(restrictions_after.is_empty());
    }
}
