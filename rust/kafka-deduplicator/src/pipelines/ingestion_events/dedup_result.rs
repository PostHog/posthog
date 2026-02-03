//! Deduplication result types for ingestion events pipeline.

use common_types::RawEvent;

use crate::rocksdb::dedup_metadata::EventSimilarity;

#[derive(strum_macros::Display, Debug, Copy, Clone, PartialEq)]
pub enum DeduplicationResultReason {
    OnlyUuidDifferent,
    SameEvent,
}

#[derive(strum_macros::Display, Debug, Copy, Clone, PartialEq)]
pub enum DeduplicationType {
    Timestamp,
}

#[derive(strum_macros::Display, Debug)]
pub enum DeduplicationResult {
    ConfirmedDuplicate(
        DeduplicationType,
        DeduplicationResultReason,
        EventSimilarity,
        RawEvent, // Original event from metadata
    ), // The reason why it's a confirmed duplicate
    PotentialDuplicate(DeduplicationType, EventSimilarity, RawEvent), // Original event
    New,
    Skipped,
}

impl PartialEq for DeduplicationResult {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (
                DeduplicationResult::ConfirmedDuplicate(
                    deduplication_type,
                    deduplication_reason,
                    _,
                    _,
                ),
                DeduplicationResult::ConfirmedDuplicate(
                    other_deduplication_type,
                    other_deduplication_reason,
                    _,
                    _,
                ),
            ) => {
                deduplication_type == other_deduplication_type
                    && deduplication_reason == other_deduplication_reason
            }
            (
                DeduplicationResult::PotentialDuplicate(deduplication_type, _, _),
                DeduplicationResult::PotentialDuplicate(other_deduplication_type, _, _),
            ) => deduplication_type == other_deduplication_type,
            (DeduplicationResult::New, DeduplicationResult::New) => true,
            (DeduplicationResult::Skipped, DeduplicationResult::Skipped) => true,
            _ => false,
        }
    }
}

impl DeduplicationResult {
    pub fn is_duplicate(&self) -> bool {
        matches!(self, DeduplicationResult::ConfirmedDuplicate(_, _, _, _))
    }

    pub fn get_similarity(&self) -> Option<&EventSimilarity> {
        match self {
            DeduplicationResult::ConfirmedDuplicate(_, _, similarity, _) => Some(similarity),
            DeduplicationResult::PotentialDuplicate(_, similarity, _) => Some(similarity),
            _ => None,
        }
    }

    pub fn get_original_event(&self) -> Option<&RawEvent> {
        match self {
            DeduplicationResult::ConfirmedDuplicate(_, _, _, original) => Some(original),
            DeduplicationResult::PotentialDuplicate(_, _, original) => Some(original),
            _ => None,
        }
    }

    pub fn take_original_event(self) -> Option<RawEvent> {
        match self {
            DeduplicationResult::ConfirmedDuplicate(_, _, _, original) => Some(original),
            DeduplicationResult::PotentialDuplicate(_, _, original) => Some(original),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rocksdb::dedup_metadata::DedupFieldName;

    fn create_test_similarity() -> EventSimilarity {
        EventSimilarity {
            overall_score: 0.9,
            different_field_count: 1,
            different_fields: vec![(
                DedupFieldName::Uuid,
                "uuid1".to_string(),
                "uuid2".to_string(),
            )],
            properties_similarity: 1.0,
            different_property_count: 0,
            different_properties: vec![],
        }
    }

    fn create_test_event() -> RawEvent {
        RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_is_duplicate_returns_true_only_for_confirmed() {
        let confirmed = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::SameEvent,
            create_test_similarity(),
            create_test_event(),
        );
        assert!(confirmed.is_duplicate());

        let potential = DeduplicationResult::PotentialDuplicate(
            DeduplicationType::Timestamp,
            create_test_similarity(),
            create_test_event(),
        );
        assert!(!potential.is_duplicate());

        assert!(!DeduplicationResult::New.is_duplicate());
        assert!(!DeduplicationResult::Skipped.is_duplicate());
    }

    #[test]
    fn test_get_similarity_returns_none_for_new_and_skipped() {
        assert!(DeduplicationResult::New.get_similarity().is_none());
        assert!(DeduplicationResult::Skipped.get_similarity().is_none());
    }

    #[test]
    fn test_get_similarity_returns_some_for_confirmed_duplicate() {
        let confirmed = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::SameEvent,
            create_test_similarity(),
            create_test_event(),
        );
        assert!(confirmed.get_similarity().is_some());
        assert_eq!(confirmed.get_similarity().unwrap().overall_score, 0.9);
    }

    #[test]
    fn test_get_similarity_returns_some_for_potential_duplicate() {
        let potential = DeduplicationResult::PotentialDuplicate(
            DeduplicationType::Timestamp,
            create_test_similarity(),
            create_test_event(),
        );
        assert!(potential.get_similarity().is_some());
    }

    #[test]
    fn test_get_original_event_returns_none_for_new_and_skipped() {
        assert!(DeduplicationResult::New.get_original_event().is_none());
        assert!(DeduplicationResult::Skipped.get_original_event().is_none());
    }

    #[test]
    fn test_get_original_event_returns_some_for_confirmed_duplicate() {
        let confirmed = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::SameEvent,
            create_test_similarity(),
            create_test_event(),
        );
        assert!(confirmed.get_original_event().is_some());
        assert_eq!(confirmed.get_original_event().unwrap().event, "test_event");
    }

    #[test]
    fn test_get_original_event_returns_some_for_potential_duplicate() {
        let potential = DeduplicationResult::PotentialDuplicate(
            DeduplicationType::Timestamp,
            create_test_similarity(),
            create_test_event(),
        );
        assert!(potential.get_original_event().is_some());
    }

    #[test]
    fn test_take_original_event_moves_ownership() {
        let confirmed = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::SameEvent,
            create_test_similarity(),
            create_test_event(),
        );

        let taken = confirmed.take_original_event();
        assert!(taken.is_some());
        assert_eq!(taken.unwrap().event, "test_event");
    }

    #[test]
    fn test_take_original_event_returns_none_for_new_and_skipped() {
        assert!(DeduplicationResult::New.take_original_event().is_none());
        assert!(DeduplicationResult::Skipped.take_original_event().is_none());
    }

    #[test]
    fn test_partial_eq_same_type_and_reason_are_equal() {
        // Same type and reason should be equal even with different similarity/event
        let result1 = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::SameEvent,
            create_test_similarity(),
            create_test_event(),
        );
        let result2 = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::SameEvent,
            EventSimilarity {
                overall_score: 0.5, // Different score
                different_field_count: 5,
                different_fields: vec![],
                properties_similarity: 0.5,
                different_property_count: 10,
                different_properties: vec![],
            },
            RawEvent {
                event: "different_event".to_string(),
                ..Default::default()
            },
        );
        assert_eq!(result1, result2);
    }

    #[test]
    fn test_partial_eq_different_reason_not_equal() {
        let result1 = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::SameEvent,
            create_test_similarity(),
            create_test_event(),
        );
        let result2 = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::OnlyUuidDifferent,
            create_test_similarity(),
            create_test_event(),
        );
        assert_ne!(result1, result2);
    }

    #[test]
    fn test_partial_eq_potential_duplicates_same_type_are_equal() {
        let potential1 = DeduplicationResult::PotentialDuplicate(
            DeduplicationType::Timestamp,
            create_test_similarity(),
            create_test_event(),
        );
        let potential2 = DeduplicationResult::PotentialDuplicate(
            DeduplicationType::Timestamp,
            EventSimilarity {
                overall_score: 0.1,
                different_field_count: 10,
                different_fields: vec![],
                properties_similarity: 0.0,
                different_property_count: 100,
                different_properties: vec![],
            },
            RawEvent {
                event: "other".to_string(),
                ..Default::default()
            },
        );
        assert_eq!(potential1, potential2);
    }

    #[test]
    fn test_partial_eq_different_variants_not_equal() {
        let confirmed = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::SameEvent,
            create_test_similarity(),
            create_test_event(),
        );
        let potential = DeduplicationResult::PotentialDuplicate(
            DeduplicationType::Timestamp,
            create_test_similarity(),
            create_test_event(),
        );

        assert_ne!(confirmed, potential);
        assert_ne!(confirmed, DeduplicationResult::New);
        assert_ne!(confirmed, DeduplicationResult::Skipped);
        assert_ne!(potential, DeduplicationResult::New);
        assert_ne!(DeduplicationResult::New, DeduplicationResult::Skipped);
    }

    #[test]
    fn test_new_and_skipped_equal_to_themselves() {
        assert_eq!(DeduplicationResult::New, DeduplicationResult::New);
        assert_eq!(DeduplicationResult::Skipped, DeduplicationResult::Skipped);
    }
}
