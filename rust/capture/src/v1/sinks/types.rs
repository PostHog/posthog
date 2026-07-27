//! The v1 destination vocabulary. `Destination` is decided during v1
//! processing and bridges onto the shared [`Address`] via [`Destination::as_address`];
//! everything downstream of that bridge is the shared outputs machinery.

use crate::pipeline::{Address, AnalyticsLane, BasicLane, Pipeline};

/// Kafka topic routing for a processed event.
/// `Drop` means the event should not be produced at all.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub enum Destination {
    #[default]
    AnalyticsMain,
    AnalyticsHistorical,
    Overflow,
    Dlq,
    Custom(String),
    Drop,
    ExceptionErrorTracking,
    HeatmapMain,
    ClientIngestionWarning,
}

impl Destination {
    /// Returns true for destinations that flow through the analytics ingestion
    /// pipeline (and are therefore subject to analytics-scoped restrictions,
    /// overflow routing, etc). Mirrors legacy `DataType::is_analytics_pipeline`.
    pub fn is_analytics_pipeline(&self) -> bool {
        matches!(self, Self::AnalyticsMain | Self::AnalyticsHistorical)
    }

    /// Map this v1 destination onto the shared [`Address`] so topic
    /// resolution goes through the one
    /// [`TopicTable`](crate::outputs::topics::TopicTable) instead of a parallel
    /// `topic_for` match. `Drop` has no address and returns `None`. v1 is
    /// analytics-only, so it never produces a replay address.
    pub fn as_address(&self) -> Option<Address> {
        Some(match self {
            Self::AnalyticsMain => Address::Analytics(AnalyticsLane::Main),
            Self::AnalyticsHistorical => Address::Analytics(AnalyticsLane::Historical),
            Self::Overflow => Address::Analytics(AnalyticsLane::Overflow),
            Self::Dlq => Address::Analytics(AnalyticsLane::Dlq),
            Self::ExceptionErrorTracking => Address::ErrorTracking(BasicLane::Main),
            Self::HeatmapMain => Address::Heatmaps(BasicLane::Main),
            Self::ClientIngestionWarning => Address::Warnings(BasicLane::Main),
            Self::Custom(topic) => Address::Custom {
                pipeline: Pipeline::Analytics,
                topic: topic.clone(),
            },
            Self::Drop => return None,
        })
    }

    /// Stable, low-cardinality metric tag. `Custom(_)` collapses to "custom"
    /// so admin-configured topic names never become label values.
    pub fn as_tag(&self) -> &'static str {
        match self {
            Self::AnalyticsMain => "analytics_main",
            Self::AnalyticsHistorical => "analytics_historical",
            Self::Overflow => "overflow",
            Self::Dlq => "dlq",
            Self::Custom(_) => "custom",
            Self::Drop => "drop",
            Self::ExceptionErrorTracking => "exception_error_tracking",
            Self::HeatmapMain => "heatmap_main",
            Self::ClientIngestionWarning => "client_ingestion_warning",
        }
    }
}

#[cfg(test)]
mod destination_tests {
    use super::Destination;
    use crate::pipeline::{Address, AnalyticsLane, BasicLane, Pipeline};

    /// Every non-`Drop` destination bridges to a shared `Address`, and `Drop`
    /// maps to `None`. This is the seam that lets the v1 stack resolve topics
    /// through the one `TopicTable`.
    #[test]
    fn as_address_bridges_every_destination() {
        assert_eq!(
            Destination::AnalyticsMain.as_address(),
            Some(Address::Analytics(AnalyticsLane::Main))
        );
        assert_eq!(
            Destination::AnalyticsHistorical.as_address(),
            Some(Address::Analytics(AnalyticsLane::Historical))
        );
        assert_eq!(
            Destination::Overflow.as_address(),
            Some(Address::Analytics(AnalyticsLane::Overflow))
        );
        assert_eq!(
            Destination::Dlq.as_address(),
            Some(Address::Analytics(AnalyticsLane::Dlq))
        );
        assert_eq!(
            Destination::ExceptionErrorTracking.as_address(),
            Some(Address::ErrorTracking(BasicLane::Main))
        );
        assert_eq!(
            Destination::HeatmapMain.as_address(),
            Some(Address::Heatmaps(BasicLane::Main))
        );
        assert_eq!(
            Destination::ClientIngestionWarning.as_address(),
            Some(Address::Warnings(BasicLane::Main))
        );
        assert_eq!(
            Destination::Custom("t".to_string()).as_address(),
            Some(Address::Custom {
                pipeline: Pipeline::Analytics,
                topic: "t".to_string(),
            })
        );
        assert_eq!(Destination::Drop.as_address(), None);
    }

    #[test]
    fn is_analytics_pipeline_true_for_main_and_historical() {
        assert!(Destination::AnalyticsMain.is_analytics_pipeline());
        assert!(Destination::AnalyticsHistorical.is_analytics_pipeline());
    }

    #[test]
    fn is_analytics_pipeline_false_for_non_analytics() {
        assert!(!Destination::ExceptionErrorTracking.is_analytics_pipeline());
        assert!(!Destination::HeatmapMain.is_analytics_pipeline());
        assert!(!Destination::ClientIngestionWarning.is_analytics_pipeline());
        assert!(!Destination::Overflow.is_analytics_pipeline());
        assert!(!Destination::Dlq.is_analytics_pipeline());
        assert!(!Destination::Drop.is_analytics_pipeline());
        assert!(!Destination::Custom("foo".into()).is_analytics_pipeline());
    }

    /// Exhaustive: every variant's tag is non-empty, stable, and unique.
    /// Custom(_) collapses to "custom" regardless of the topic name, so two
    /// different Custom values share the same tag (cardinality defense).
    #[test]
    fn as_tag_exhaustive_stable_and_unique() {
        // One representative per variant. If a new variant is added, the
        // as_tag() match becomes non-exhaustive and this file fails to
        // compile, forcing an update here too.
        let expected: &[(Destination, &str)] = &[
            (Destination::AnalyticsMain, "analytics_main"),
            (Destination::AnalyticsHistorical, "analytics_historical"),
            (Destination::Overflow, "overflow"),
            (Destination::Dlq, "dlq"),
            (Destination::Custom("topic_a".into()), "custom"),
            (Destination::Drop, "drop"),
            (
                Destination::ExceptionErrorTracking,
                "exception_error_tracking",
            ),
            (Destination::HeatmapMain, "heatmap_main"),
            (
                Destination::ClientIngestionWarning,
                "client_ingestion_warning",
            ),
        ];

        let mut seen = std::collections::HashSet::new();
        for (dest, tag) in expected {
            assert_eq!(dest.as_tag(), *tag, "tag changed for {dest:?}");
            assert!(!tag.is_empty(), "tag for {dest:?} must be non-empty");
            assert!(seen.insert(*tag), "tag {tag} is not unique across variants");
        }

        // Two different Custom values collapse to the same "custom" tag.
        assert_eq!(Destination::Custom("topic_b".into()).as_tag(), "custom");
        assert_eq!(
            Destination::Custom("topic_a".into()).as_tag(),
            Destination::Custom("topic_b".into()).as_tag()
        );
    }
}

// ---------------------------------------------------------------------------
// Outcome
// ---------------------------------------------------------------------------

/// What happened when a publish attempt resolved.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Success,
    Timeout,
    RetriableError,
    FatalError,
}

impl Outcome {
    pub fn as_tag(&self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::Timeout => "timeout",
            Self::RetriableError => "retriable_error",
            Self::FatalError => "fatal_error",
        }
    }
}

// ---------------------------------------------------------------------------
// SinkResult
// ---------------------------------------------------------------------------
