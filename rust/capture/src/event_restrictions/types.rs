use std::collections::HashSet;

use metrics::counter;

use crate::config::CaptureMode;

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

    /// Bit position for this restriction type (0-3).
    const fn bit_pos(self) -> u8 {
        match self {
            Self::DropEvent => 0,
            Self::ForceOverflow => 1,
            Self::RedirectToDlq => 2,
            Self::SkipPersonProcessing => 3,
        }
    }
}

/// A compact set of restriction types using a bitfield.
/// Avoids heap allocation - just a u8 on the stack.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct RestrictionSet(u8);

impl RestrictionSet {
    /// Create an empty set.
    pub const fn new() -> Self {
        Self(0)
    }

    /// Insert a restriction type into the set.
    pub fn insert(&mut self, t: RestrictionType) {
        self.0 |= 1 << t.bit_pos();
    }

    /// Check if the set contains a restriction type.
    pub const fn contains(self, t: RestrictionType) -> bool {
        (self.0 & (1 << t.bit_pos())) != 0
    }

    /// Check if the set is empty.
    pub const fn is_empty(self) -> bool {
        self.0 == 0
    }

    /// Count the number of restrictions in the set.
    pub const fn len(self) -> usize {
        self.0.count_ones() as usize
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
    pub fn from_restrictions(restrictions: RestrictionSet, pipeline: CaptureMode) -> Self {
        let mut result = Self::default();
        let pipeline_str = pipeline.as_pipeline_name();

        for restriction_type in RestrictionType::all() {
            if restrictions.contains(restriction_type) {
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
        self.matches_field(&self.distinct_ids, event.distinct_id)
            && self.matches_field(&self.session_ids, event.session_id)
            && self.matches_field(&self.event_names, event.event_name)
            && self.matches_field(&self.event_uuids, event.event_uuid)
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
/// Uses references to avoid cloning strings for every event.
#[derive(Debug, Clone, Copy, Default)]
pub struct EventContext<'a> {
    pub distinct_id: Option<&'a str>,
    pub session_id: Option<&'a str>,
    pub event_name: Option<&'a str>,
    pub event_uuid: Option<&'a str>,
    /// Pre-computed timestamp to avoid syscalls per event. Use `chrono::Utc::now().timestamp()`.
    pub now_ts: i64,
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
            distinct_id: Some("user1"),
            event_name: Some("$pageview"),
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
            distinct_id: Some("user1"),
            ..Default::default()
        };
        assert!(filters.matches(&event_match));

        let event_no_match = EventContext {
            distinct_id: Some("user3"),
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
            distinct_id: Some("user1"),
            event_name: Some("$pageview"),
            ..Default::default()
        };
        assert!(filters.matches(&event_both));

        // only distinct_id matches
        let event_wrong_event = EventContext {
            distinct_id: Some("user1"),
            event_name: Some("$identify"),
            ..Default::default()
        };
        assert!(!filters.matches(&event_wrong_event));

        // only event_name matches
        let event_wrong_user = EventContext {
            distinct_id: Some("user2"),
            event_name: Some("$pageview"),
            ..Default::default()
        };
        assert!(!filters.matches(&event_wrong_user));
    }

    #[test]
    fn test_restriction_set_new_is_empty() {
        let set = RestrictionSet::new();
        assert!(set.is_empty());
        assert_eq!(set.len(), 0);
    }

    #[test]
    fn test_restriction_set_insert_and_contains() {
        let mut set = RestrictionSet::new();

        set.insert(RestrictionType::DropEvent);
        assert!(set.contains(RestrictionType::DropEvent));
        assert!(!set.contains(RestrictionType::ForceOverflow));
        assert!(!set.contains(RestrictionType::RedirectToDlq));
        assert!(!set.contains(RestrictionType::SkipPersonProcessing));
        assert_eq!(set.len(), 1);
        assert!(!set.is_empty());
    }

    #[test]
    fn test_restriction_set_multiple_inserts() {
        let mut set = RestrictionSet::new();

        set.insert(RestrictionType::DropEvent);
        set.insert(RestrictionType::ForceOverflow);
        set.insert(RestrictionType::RedirectToDlq);

        assert!(set.contains(RestrictionType::DropEvent));
        assert!(set.contains(RestrictionType::ForceOverflow));
        assert!(set.contains(RestrictionType::RedirectToDlq));
        assert!(!set.contains(RestrictionType::SkipPersonProcessing));
        assert_eq!(set.len(), 3);
    }

    #[test]
    fn test_restriction_set_all_types() {
        let mut set = RestrictionSet::new();

        for t in RestrictionType::all() {
            set.insert(t);
        }

        assert_eq!(set.len(), 4);
        for t in RestrictionType::all() {
            assert!(set.contains(t));
        }
    }

    #[test]
    fn test_restriction_set_insert_idempotent() {
        let mut set = RestrictionSet::new();

        set.insert(RestrictionType::DropEvent);
        set.insert(RestrictionType::DropEvent);
        set.insert(RestrictionType::DropEvent);

        assert_eq!(set.len(), 1);
        assert!(set.contains(RestrictionType::DropEvent));
    }

    #[test]
    fn test_restriction_set_default() {
        let set = RestrictionSet::default();
        assert!(set.is_empty());
        assert_eq!(set.len(), 0);
    }

    #[test]
    fn test_restriction_set_copy() {
        let mut set1 = RestrictionSet::new();
        set1.insert(RestrictionType::DropEvent);

        let set2 = set1; // Copy
        assert!(set2.contains(RestrictionType::DropEvent));

        // set1 is still valid (Copy, not Move)
        assert!(set1.contains(RestrictionType::DropEvent));
    }
}
