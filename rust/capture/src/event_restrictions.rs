use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use common_redis::{Client as RedisClient, CustomRedisError};
use metrics::gauge;
use serde::Deserialize;
use tokio::sync::RwLock;
use tokio::time::interval;
use tracing::{error, info, warn};

const REDIS_KEY_PREFIX: &str = "event_ingestion_restriction_dynamic_config";

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
}

/// Ingestion pipeline types
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum IngestionPipeline {
    Analytics,
    SessionRecordings,
    Ai,
}

impl IngestionPipeline {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Analytics => "analytics",
            Self::SessionRecordings => "session_recordings",
            Self::Ai => "ai",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "analytics" => Some(Self::Analytics),
            "session_recordings" => Some(Self::SessionRecordings),
            "ai" => Some(Self::Ai),
            _ => None,
        }
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

    /// Fetch restrictions from Redis for the given pipeline.
    pub async fn fetch_from_redis(
        redis: &Arc<dyn RedisClient + Send + Sync>,
        pipeline: IngestionPipeline,
    ) -> Result<Self, CustomRedisError> {
        info!(pipeline = %pipeline.as_str(), "Fetching event restrictions from Redis");

        let mut manager = Self::new();
        let pipeline_str = pipeline.as_str();

        for restriction_type in [
            RestrictionType::DropEvent,
            RestrictionType::ForceOverflow,
            RestrictionType::RedirectToDlq,
            RestrictionType::SkipPersonProcessing,
        ] {
            let key = format!("{}:{}", REDIS_KEY_PREFIX, restriction_type.redis_key());

            let json_str = match redis.get(key.clone()).await {
                Ok(s) => s,
                Err(CustomRedisError::NotFound) => continue,
                Err(e) => {
                    warn!(key = %key, error = %e, "Failed to fetch restrictions from Redis");
                    continue;
                }
            };

            let entries: Vec<RedisRestrictionEntry> = match serde_json::from_str(&json_str) {
                Ok(e) => e,
                Err(e) => {
                    warn!(key = %key, error = %e, "Failed to parse restrictions from Redis");
                    continue;
                }
            };

            for entry in entries {
                // Skip if this entry doesn't apply to our pipeline
                if !entry.pipelines.contains(&pipeline_str.to_string()) {
                    continue;
                }

                // Skip old format entries (version must be 1)
                if entry.version != Some(1) {
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
            "Fetched event restrictions from Redis"
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
    pipeline: IngestionPipeline,
}

impl EventRestrictionService {
    /// Create a new service. Call `start_refresh_task` to begin background updates.
    pub fn new(pipeline: IngestionPipeline, fail_open_after: Duration) -> Self {
        Self {
            manager: Arc::new(RwLock::new(RestrictionManager::new())),
            last_successful_refresh: Arc::new(AtomicI64::new(0)),
            fail_open_after,
            pipeline,
        }
    }

    /// Returns a future that refreshes restrictions periodically. Caller should spawn this.
    pub async fn start_refresh_task(
        &self,
        redis: Arc<dyn RedisClient + Send + Sync>,
        refresh_interval: Duration,
    ) {
        let manager = self.manager.clone();
        let last_successful_refresh = self.last_successful_refresh.clone();
        let pipeline = self.pipeline;
        let pipeline_str = pipeline.as_str();

        let mut interval = interval(refresh_interval);

        loop {
            interval.tick().await;

            match RestrictionManager::fetch_from_redis(&redis, pipeline).await {
                Ok(new_manager) => {
                    let total_restrictions: usize =
                        new_manager.restrictions.values().map(|v| v.len()).sum();
                    let total_tokens = new_manager.restrictions.len();

                    // Update the manager
                    {
                        let mut guard = manager.write().await;
                        *guard = new_manager;
                    }

                    // Update last successful refresh timestamp
                    let now = chrono::Utc::now().timestamp();
                    last_successful_refresh.store(now, Ordering::SeqCst);

                    // Update metrics
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
                        "Failed to refresh event restrictions from Redis"
                    );
                }
            }
        }
    }

    /// Manually update restrictions (useful for testing).
    pub async fn update(&self, new_manager: RestrictionManager) {
        let mut guard = self.manager.write().await;
        *guard = new_manager;
        self.last_successful_refresh
            .store(chrono::Utc::now().timestamp(), Ordering::SeqCst);
    }

    /// Check if the cache is stale (fail-open should be active).
    fn is_stale(&self) -> bool {
        let last_refresh = self.last_successful_refresh.load(Ordering::SeqCst);
        if last_refresh == 0 {
            return true;
        }

        let now = chrono::Utc::now().timestamp();
        let age = Duration::from_secs((now - last_refresh) as u64);
        age > self.fail_open_after
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
                "pipeline" => self.pipeline.as_str().to_string()
            )
            .set(1.0);
            return HashSet::new();
        }

        let guard = self.manager.read().await;
        guard.get_restrictions(token, event)
    }
}

/// Redis entry format (version 1)
#[derive(Debug, Clone, Deserialize)]
struct RedisRestrictionEntry {
    version: Option<i32>,
    token: String,
    #[serde(default)]
    pipelines: Vec<String>,
    #[serde(default)]
    distinct_ids: Vec<String>,
    #[serde(default)]
    session_ids: Vec<String>,
    #[serde(default)]
    event_names: Vec<String>,
    #[serde(default)]
    event_uuids: Vec<String>,
}

impl RedisRestrictionEntry {
    fn into_restriction(self, restriction_type: RestrictionType) -> Restriction {
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

impl Restriction {
    pub fn matches(&self, event: &EventContext) -> bool {
        match &self.scope {
            RestrictionScope::AllEvents => true,
            RestrictionScope::Filtered(filters) => filters.matches(event),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
        assert_eq!(
            RestrictionType::from_redis_key("unknown_type"),
            None
        );
    }

    #[test]
    fn test_ingestion_pipeline_from_str() {
        assert_eq!(
            IngestionPipeline::from_str("analytics"),
            Some(IngestionPipeline::Analytics)
        );
        assert_eq!(
            IngestionPipeline::from_str("session_recordings"),
            Some(IngestionPipeline::SessionRecordings)
        );
        assert_eq!(
            IngestionPipeline::from_str("ai"),
            Some(IngestionPipeline::Ai)
        );
        assert_eq!(IngestionPipeline::from_str("unknown"), None);
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
    fn test_restriction_manager_get_restrictions() {
        let mut manager = RestrictionManager::new();
        manager.restrictions.insert(
            "token1".to_string(),
            vec![
                Restriction {
                    restriction_type: RestrictionType::DropEvent,
                    scope: RestrictionScope::AllEvents,
                },
                Restriction {
                    restriction_type: RestrictionType::ForceOverflow,
                    scope: RestrictionScope::Filtered({
                        let mut f = RestrictionFilters::default();
                        f.event_names.insert("$pageview".to_string());
                        f
                    }),
                },
            ],
        );

        let event = EventContext {
            event_name: Some("$pageview".to_string()),
            ..Default::default()
        };

        let restrictions = manager.get_restrictions("token1", &event);
        assert!(restrictions.contains(&RestrictionType::DropEvent));
        assert!(restrictions.contains(&RestrictionType::ForceOverflow));

        let event_other = EventContext {
            event_name: Some("$identify".to_string()),
            ..Default::default()
        };
        let restrictions_other = manager.get_restrictions("token1", &event_other);
        assert!(restrictions_other.contains(&RestrictionType::DropEvent));
        assert!(!restrictions_other.contains(&RestrictionType::ForceOverflow));

        // unknown token
        let restrictions_unknown = manager.get_restrictions("unknown", &event);
        assert!(restrictions_unknown.is_empty());
    }

    #[test]
    fn test_redis_entry_parsing() {
        let json = r#"[
            {
                "version": 1,
                "token": "token1",
                "pipelines": ["analytics"],
                "distinct_ids": ["user1", "user2"],
                "event_names": ["$pageview"]
            },
            {
                "version": 1,
                "token": "token2",
                "pipelines": ["analytics", "session_recordings"]
            }
        ]"#;

        let entries: Vec<RedisRestrictionEntry> = serde_json::from_str(json).unwrap();
        assert_eq!(entries.len(), 2);

        let entry1 = &entries[0];
        assert_eq!(entry1.token, "token1");
        assert_eq!(entry1.distinct_ids, vec!["user1", "user2"]);
        assert_eq!(entry1.event_names, vec!["$pageview"]);
        assert!(entry1.session_ids.is_empty());

        let restriction1 = entries[0].clone().into_restriction(RestrictionType::DropEvent);
        assert!(matches!(restriction1.scope, RestrictionScope::Filtered(_)));

        let entry2 = &entries[1];
        assert_eq!(entry2.token, "token2");
        assert!(entry2.distinct_ids.is_empty());

        let restriction2 = entries[1].clone().into_restriction(RestrictionType::DropEvent);
        assert!(matches!(restriction2.scope, RestrictionScope::AllEvents));
    }

    #[test]
    fn test_redis_entry_skips_old_version() {
        let json = r#"[
            {
                "token": "token1",
                "pipelines": ["analytics"]
            }
        ]"#;

        let entries: Vec<RedisRestrictionEntry> = serde_json::from_str(json).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].version, None);
    }
}
