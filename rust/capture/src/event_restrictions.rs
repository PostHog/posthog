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
}
