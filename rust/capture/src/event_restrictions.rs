use std::collections::{HashMap, HashSet};

/// Restriction types that can be applied to events in capture.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RestrictionType {
    DropEvent,
    ForceOverflow,
    RedirectToDlq,
}

impl RestrictionType {
    pub fn from_redis_key(value: &str) -> Option<Self> {
        match value {
            "drop_event_from_ingestion" => Some(Self::DropEvent),
            "force_overflow_from_ingestion" => Some(Self::ForceOverflow),
            "redirect_to_dlq" => Some(Self::RedirectToDlq),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::DropEvent => "drop_event",
            Self::ForceOverflow => "force_overflow",
            Self::RedirectToDlq => "redirect_to_dlq",
        }
    }

    pub fn redis_key(&self) -> &'static str {
        match self {
            Self::DropEvent => "drop_event_from_ingestion",
            Self::ForceOverflow => "force_overflow_from_ingestion",
            Self::RedirectToDlq => "redirect_to_dlq",
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
}
