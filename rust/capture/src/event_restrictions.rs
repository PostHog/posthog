use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use common_redis::CustomRedisError;
use metrics::{counter, gauge};
use tokio::sync::RwLock;
use tokio::time::interval;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use crate::config::CaptureMode;
use crate::event_restrictions_repository::{EventRestrictionsRepository, RestrictionEntry};

// Re-export for external use
pub use crate::event_restrictions_repository::{RedisRestrictionsRepository};

/// Restriction types that can be applied to events in capture.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RestrictionType {
    DropEvent,
    ForceOverflow,
    RedirectToDlq,
    SkipPersonProcessing,
}

impl RestrictionType {
    pub fn from_redis_key(value: &str) -> Option<Self> {
        match value {
            "drop_event_from_ingestion" => Some(Self::DropEvent),
            "force_overflow_from_ingestion" => Some(Self::ForceOverflow),
            "redirect_to_dlq" => Some(Self::RedirectToDlq),
            "skip_person_processing" => Some(Self::SkipPersonProcessing),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::DropEvent => "drop_event",
            Self::ForceOverflow => "force_overflow",
            Self::RedirectToDlq => "redirect_to_dlq",
            Self::SkipPersonProcessing => "skip_person_processing",
        }
    }

    pub fn redis_key(&self) -> &'static str {
        match self {
            Self::DropEvent => "drop_event_from_ingestion",
            Self::ForceOverflow => "force_overflow_from_ingestion",
            Self::RedirectToDlq => "redirect_to_dlq",
            Self::SkipPersonProcessing => "skip_person_processing",
        }
    }

    pub fn all() -> [Self; 4] {
        [
            Self::DropEvent,
            Self::ForceOverflow,
            Self::SkipPersonProcessing,
            Self::RedirectToDlq,
        ]
    }
}

/// Result of applying restrictions to an event.
/// Contains flags indicating what actions to take.
#[derive(Debug, Default)]
pub struct AppliedRestrictions {
    pub should_drop: bool,
    pub force_overflow: bool,
    pub skip_person_processing: bool,
    pub redirect_to_dlq: bool,
}

impl AppliedRestrictions {
    /// Apply restrictions and emit metrics.
    pub fn from_restrictions(
        restrictions: &HashSet<RestrictionType>,
        pipeline: CaptureMode,
    ) -> Self {
        let mut result = Self::default();
        let pipeline_str = pipeline.as_pipeline_name();

        for restriction_type in RestrictionType::all() {
            if restrictions.contains(&restriction_type) {
                counter!(
                    "capture_event_restrictions_applied",
                    "restriction_type" => restriction_type.as_str(),
                    "pipeline" => pipeline_str
                )
                .increment(1);

                match restriction_type {
                    RestrictionType::DropEvent => result.should_drop = true,
                    RestrictionType::ForceOverflow => result.force_overflow = true,
                    RestrictionType::SkipPersonProcessing => result.skip_person_processing = true,
                    RestrictionType::RedirectToDlq => result.redirect_to_dlq = true,
                }
            }
        }

        result
    }
}

/// Filters for a restriction. AND logic between types, OR logic within each type.
/// Empty set means "no filter on this field" (matches all).
#[derive(Debug, Clone, Default)]
pub struct RestrictionFilters {
    pub distinct_ids: HashSet<String>,
    pub session_ids: HashSet<String>,
    pub event_names: HashSet<String>,
    pub event_uuids: HashSet<String>,
}

impl RestrictionFilters {
    /// Check if an event matches these filters.
    /// AND logic between filter types, OR logic within each type.
    /// Empty filter = matches all for that field.
    pub fn matches(&self, event: &EventContext) -> bool {
        self.matches_field(&self.distinct_ids, event.distinct_id.as_deref())
            && self.matches_field(&self.session_ids, event.session_id.as_deref())
            && self.matches_field(&self.event_names, event.event_name.as_deref())
            && self.matches_field(&self.event_uuids, event.event_uuid.as_deref())
    }

    fn matches_field(&self, filter: &HashSet<String>, value: Option<&str>) -> bool {
        if filter.is_empty() {
            return true; // no filter = matches all
        }
        match value {
            Some(v) => filter.contains(v),
            None => false, // filter set but no value = no match
        }
    }
}

/// Event data for matching against restrictions.
#[derive(Debug, Clone, Default)]
pub struct EventContext {
    pub distinct_id: Option<String>,
    pub session_id: Option<String>,
    pub event_name: Option<String>,
    pub event_uuid: Option<String>,
}

/// What events a restriction applies to.
#[derive(Debug, Clone)]
pub enum RestrictionScope {
    /// Applies to all events for this token
    AllEvents,
    /// Applies only to events matching the filters
    Filtered(RestrictionFilters),
}

/// A single restriction rule.
#[derive(Debug, Clone)]
pub struct Restriction {
    pub restriction_type: RestrictionType,
    pub scope: RestrictionScope,
}

impl Restriction {
    pub fn matches(&self, event: &EventContext) -> bool {
        match &self.scope {
            RestrictionScope::AllEvents => true,
            RestrictionScope::Filtered(filters) => filters.matches(event),
        }
    }
}

impl RestrictionEntry {
    pub fn into_restriction(self, restriction_type: RestrictionType) -> Restriction {
        let has_filters = !self.distinct_ids.is_empty()
            || !self.session_ids.is_empty()
            || !self.event_names.is_empty()
            || !self.event_uuids.is_empty();

        let scope = if has_filters {
            RestrictionScope::Filtered(RestrictionFilters {
                distinct_ids: self.distinct_ids.into_iter().collect(),
                session_ids: self.session_ids.into_iter().collect(),
                event_names: self.event_names.into_iter().collect(),
                event_uuids: self.event_uuids.into_iter().collect(),
            })
        } else {
            RestrictionScope::AllEvents
        };

        Restriction {
            restriction_type,
            scope,
        }
    }
}

// ============================================================================
// Restriction Manager
// ============================================================================

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
    pub fn get_restrictions(&self, token: &str, event: &EventContext) -> HashSet<RestrictionType> {
        let Some(restrictions) = self.restrictions.get(token) else {
            return HashSet::new();
        };

        restrictions
            .iter()
            .filter(|r| r.matches(event))
            .map(|r| r.restriction_type)
            .collect()
    }

    /// Build a RestrictionManager from repository data for a specific pipeline.
    pub async fn from_repository(
        repository: &dyn EventRestrictionsRepository,
        pipeline: CaptureMode,
    ) -> Result<Self, CustomRedisError> {
        info!(pipeline = %pipeline.as_pipeline_name(), "Fetching event restrictions");

        let mut manager = Self::new();
        let pipeline_str = pipeline.as_pipeline_name();

        for restriction_type in RestrictionType::all() {
            let entries = match repository.get_entries(restriction_type).await {
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

// ============================================================================
// Event Restriction Service
// ============================================================================

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
    fn is_stale(&self) -> bool {
        let last_refresh = self.last_successful_refresh.load(Ordering::SeqCst);
        if last_refresh == 0 {
            return true;
        }

        let now = chrono::Utc::now().timestamp();
        // Use saturating_sub to handle potential clock skew (if now < last_refresh, age = 0)
        let age_secs = (now as u64).saturating_sub(last_refresh as u64);
        Duration::from_secs(age_secs) > self.fail_open_after
    }

    /// Get restrictions for an event. Returns empty set if fail-open is active.
    pub async fn get_restrictions(
        &self,
        token: &str,
        event: &EventContext,
    ) -> HashSet<RestrictionType> {
        if self.is_stale() {
            gauge!(
                "capture_event_restrictions_stale",
                "pipeline" => self.pipeline.as_pipeline_name().to_string()
            )
            .set(1.0);
            return HashSet::new();
        }

        let guard = self.manager.read().await;
        guard.get_restrictions(token, event)
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event_restrictions_repository::testing::MockRestrictionsRepository;

    #[test]
    fn test_restriction_type_from_redis_key() {
        assert_eq!(
            RestrictionType::from_redis_key("drop_event_from_ingestion"),
            Some(RestrictionType::DropEvent)
        );
        assert_eq!(
            RestrictionType::from_redis_key("force_overflow_from_ingestion"),
            Some(RestrictionType::ForceOverflow)
        );
        assert_eq!(
            RestrictionType::from_redis_key("redirect_to_dlq"),
            Some(RestrictionType::RedirectToDlq)
        );
        assert_eq!(
            RestrictionType::from_redis_key("skip_person_processing"),
            Some(RestrictionType::SkipPersonProcessing)
        );
        assert_eq!(RestrictionType::from_redis_key("unknown_type"), None);
    }

    #[test]
    fn test_ingestion_pipeline_parse() {
        assert_eq!(
            CaptureMode::parse_pipeline_name("analytics"),
            Some(CaptureMode::Events)
        );
        assert_eq!(
            CaptureMode::parse_pipeline_name("session_recordings"),
            Some(CaptureMode::Recordings)
        );
        assert_eq!(
            CaptureMode::parse_pipeline_name("ai"),
            Some(CaptureMode::Ai)
        );
        assert_eq!(CaptureMode::parse_pipeline_name("unknown"), None);
    }

    #[test]
    fn test_restriction_scope_all_events() {
        let restriction = Restriction {
            restriction_type: RestrictionType::DropEvent,
            scope: RestrictionScope::AllEvents,
        };
        let event = EventContext::default();
        assert!(restriction.matches(&event));
    }

    #[test]
    fn test_restriction_filters_empty_matches_all() {
        let filters = RestrictionFilters::default();
        let event = EventContext {
            distinct_id: Some("user1".to_string()),
            event_name: Some("$pageview".to_string()),
            ..Default::default()
        };
        assert!(filters.matches(&event));
    }

    #[test]
    fn test_restriction_filters_distinct_id_match() {
        let mut filters = RestrictionFilters::default();
        filters.distinct_ids.insert("user1".to_string());
        filters.distinct_ids.insert("user2".to_string());

        let event_match = EventContext {
            distinct_id: Some("user1".to_string()),
            ..Default::default()
        };
        assert!(filters.matches(&event_match));

        let event_no_match = EventContext {
            distinct_id: Some("user3".to_string()),
            ..Default::default()
        };
        assert!(!filters.matches(&event_no_match));
    }

    #[test]
    fn test_restriction_filters_and_logic() {
        let mut filters = RestrictionFilters::default();
        filters.distinct_ids.insert("user1".to_string());
        filters.event_names.insert("$pageview".to_string());

        // both match
        let event_both = EventContext {
            distinct_id: Some("user1".to_string()),
            event_name: Some("$pageview".to_string()),
            ..Default::default()
        };
        assert!(filters.matches(&event_both));

        // only distinct_id matches
        let event_wrong_event = EventContext {
            distinct_id: Some("user1".to_string()),
            event_name: Some("$identify".to_string()),
            ..Default::default()
        };
        assert!(!filters.matches(&event_wrong_event));

        // only event_name matches
        let event_wrong_user = EventContext {
            distinct_id: Some("user2".to_string()),
            event_name: Some("$pageview".to_string()),
            ..Default::default()
        };
        assert!(!filters.matches(&event_wrong_user));
    }

    #[test]
    fn test_restriction_entry_parsing() {
        let json = r#"[
            {
                "version": 2,
                "token": "token1",
                "pipelines": ["analytics"],
                "distinct_ids": ["user1", "user2"],
                "event_names": ["$pageview"]
            },
            {
                "version": 2,
                "token": "token2",
                "pipelines": ["analytics", "session_recordings"]
            }
        ]"#;

        let entries: Vec<RestrictionEntry> = serde_json::from_str(json).unwrap();
        assert_eq!(entries.len(), 2);

        let entry1 = &entries[0];
        assert_eq!(entry1.token, "token1");
        assert_eq!(entry1.distinct_ids, vec!["user1", "user2"]);
        assert_eq!(entry1.event_names, vec!["$pageview"]);
        assert!(entry1.session_ids.is_empty());

        let restriction1 = entries[0]
            .clone()
            .into_restriction(RestrictionType::DropEvent);
        assert!(matches!(restriction1.scope, RestrictionScope::Filtered(_)));

        let entry2 = &entries[1];
        assert_eq!(entry2.token, "token2");
        assert!(entry2.distinct_ids.is_empty());

        let restriction2 = entries[1]
            .clone()
            .into_restriction(RestrictionType::DropEvent);
        assert!(matches!(restriction2.scope, RestrictionScope::AllEvents));
    }

    // ========================================================================
    // RestrictionManager tests using MockRestrictionsRepository
    // ========================================================================

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
        assert!(drop_restrictions.contains(&RestrictionType::DropEvent));

        let overflow_restrictions = manager.get_restrictions("token_overflow", &event);
        assert_eq!(overflow_restrictions.len(), 1);
        assert!(overflow_restrictions.contains(&RestrictionType::ForceOverflow));

        let dlq_restrictions = manager.get_restrictions("token_dlq", &event);
        assert_eq!(dlq_restrictions.len(), 1);
        assert!(dlq_restrictions.contains(&RestrictionType::RedirectToDlq));

        let skip_restrictions = manager.get_restrictions("token_skip", &event);
        assert_eq!(skip_restrictions.len(), 1);
        assert!(skip_restrictions.contains(&RestrictionType::SkipPersonProcessing));

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
            distinct_id: Some("user1".to_string()),
            event_name: Some("$pageview".to_string()),
            ..Default::default()
        };
        let restrictions = manager.get_restrictions("token1", &event_match);
        assert!(restrictions.contains(&RestrictionType::DropEvent));

        // Should NOT match when event_name doesn't match (AND logic)
        let event_wrong_name = EventContext {
            distinct_id: Some("user1".to_string()),
            event_name: Some("$identify".to_string()),
            ..Default::default()
        };
        let restrictions = manager.get_restrictions("token1", &event_wrong_name);
        assert!(restrictions.is_empty());

        // Should NOT match when distinct_id doesn't match
        let event_wrong_user = EventContext {
            distinct_id: Some("user3".to_string()),
            event_name: Some("$pageview".to_string()),
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

        repo.set_entries(
            RestrictionType::DropEvent,
            Some(vec![old_entry, new_entry]),
        )
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
        assert!(restrictions.contains(&RestrictionType::ForceOverflow));
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
        assert!(restrictions.contains(&RestrictionType::ForceOverflow));
        assert!(restrictions.contains(&RestrictionType::SkipPersonProcessing));
    }

    // ========================================================================
    // EventRestrictionService tests
    // ========================================================================

    #[tokio::test]
    async fn test_service_is_stale_when_never_refreshed() {
        let service = EventRestrictionService::new(CaptureMode::Events, Duration::from_secs(300));
        // last_successful_refresh is 0, so should be stale (fail-open)
        let restrictions = service
            .get_restrictions("token", &EventContext::default())
            .await;
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

        let event = EventContext::default();
        let restrictions = service.get_restrictions("token1", &event).await;
        assert!(restrictions.contains(&RestrictionType::DropEvent));
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
        let restrictions = service
            .get_restrictions("token1", &EventContext::default())
            .await;
        assert!(restrictions.contains(&RestrictionType::DropEvent));

        // Manually set last_successful_refresh to 10 seconds ago
        let old_timestamp = chrono::Utc::now().timestamp() - 10;
        service
            .last_successful_refresh
            .store(old_timestamp, Ordering::SeqCst);

        // Now should be stale (fail-open)
        let restrictions_after = service
            .get_restrictions("token1", &EventContext::default())
            .await;
        assert!(restrictions_after.is_empty());
    }
}
