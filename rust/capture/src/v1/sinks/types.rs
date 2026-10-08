use uuid::Uuid;

use crate::event_restrictions::Pipeline;
use crate::pipeline::{Address, AiLane, AnalyticsLane, BasicLane, PipelineLane};

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
    AiEvents,
    /// Overflow lane for `AiEvents`. Only produced when the AI overflow
    /// valve (`CAPTURE_OUTPUT_AI_OVERFLOW_TOPIC`) is armed; overflow on the AI lane
    /// lands here, never on the analytics `Overflow` destination.
    AiEventsOverflow,
}

impl Destination {
    /// Returns true for destinations that flow through the analytics ingestion
    /// pipeline (and are therefore subject to analytics-scoped restrictions,
    /// overflow routing, etc). Mirrors legacy `DataType::is_analytics_pipeline`.
    ///
    /// `AiEvents` is false: `$ai_*` events are diverted out of the analytics
    /// pipeline into a dedicated AI lane, just like heatmaps/exceptions.
    pub fn is_analytics_pipeline(&self) -> bool {
        matches!(self, Self::AnalyticsMain | Self::AnalyticsHistorical)
    }

    /// Restriction pipeline this destination is governed by, if any. Mirrors
    /// legacy `DataType::pipeline`: the AI lane (including its overflow arm)
    /// consults ai-scoped restrictions, the analytics lanes consult analytics
    /// ones. `None` destinations flow through unrestricted — either they have
    /// no shared restriction config (heatmaps, ingestion warnings) or they are
    /// themselves restriction/terminal outcomes (Dlq, Custom, Drop).
    pub fn pipeline(&self) -> Option<Pipeline> {
        match self {
            Self::AnalyticsMain | Self::AnalyticsHistorical | Self::Overflow => {
                Some(Pipeline::Analytics)
            }
            Self::AiEvents | Self::AiEventsOverflow => Some(Pipeline::Ai),
            Self::ExceptionErrorTracking => Some(Pipeline::ErrorTracking),
            Self::HeatmapMain | Self::ClientIngestionWarning | Self::Dlq | Self::Custom(_) => None,
            Self::Drop => None,
        }
    }

    /// Whether this lane exists to absorb hot keys, and so may publish without
    /// a partition key to spread load across partitions.
    ///
    /// Everything else keeps its key even when person processing is off,
    /// because its consumers rely on per-distinct-id ordering: historical
    /// backfills, the dlq, admin custom redirects, and the AI main topic.
    /// Matches the lanes legacy `route()` resolves through `person_ordering`.
    ///
    /// Exhaustive on purpose: a new destination has to state which side it is
    /// on rather than silently inheriting "keeps its key".
    pub fn absorbs_hot_keys(&self) -> bool {
        match self {
            Self::AnalyticsMain | Self::Overflow | Self::AiEventsOverflow => true,
            Self::AnalyticsHistorical
            | Self::Dlq
            | Self::Custom(_)
            | Self::ExceptionErrorTracking
            | Self::HeatmapMain
            | Self::ClientIngestionWarning
            | Self::AiEvents => false,
            // Never published, so it never reaches a partition key.
            Self::Drop => false,
        }
    }

    /// Whether this lane's consumer runs person processing with writes. On
    /// such a lane one distinct id must stay on one partition while person
    /// processing is on — spreading it turns a hot key into contended
    /// person-row updates — so a spread decision only takes effect once the
    /// person-processing flag is set. Read-only consumers (the AI lanes,
    /// error tracking) and lanes with no person processing at all (heatmaps,
    /// client warnings) can take keyless records at any time. The dlq and
    /// custom redirects replay into analytics ingestion, so they count as
    /// person-writing.
    ///
    /// Exhaustive for the same reason as [`Self::absorbs_hot_keys`].
    pub fn writes_persons(&self) -> bool {
        match self {
            Self::AnalyticsMain
            | Self::AnalyticsHistorical
            | Self::Overflow
            | Self::Dlq
            | Self::Custom(_) => true,
            Self::AiEvents
            | Self::AiEventsOverflow
            | Self::ExceptionErrorTracking
            | Self::HeatmapMain
            | Self::ClientIngestionWarning => false,
            // Never published, so it never reaches a consumer.
            Self::Drop => false,
        }
    }

    /// The output address this destination publishes to. `None` for `Drop`,
    /// which is never published.
    pub fn address(&self) -> Option<Address> {
        let lane = |lane| Some(Address::Lane(lane));
        match self {
            Self::AnalyticsMain => lane(PipelineLane::Analytics(AnalyticsLane::Main)),
            Self::AnalyticsHistorical => lane(PipelineLane::Analytics(AnalyticsLane::Historical)),
            Self::Overflow => lane(PipelineLane::Analytics(AnalyticsLane::Overflow)),
            Self::AiEvents => lane(PipelineLane::Ai(AiLane::Main)),
            Self::AiEventsOverflow => lane(PipelineLane::Ai(AiLane::Overflow)),
            Self::ExceptionErrorTracking => lane(PipelineLane::ErrorTracking(BasicLane::Main)),
            Self::HeatmapMain => lane(PipelineLane::Heatmaps(BasicLane::Main)),
            Self::ClientIngestionWarning => lane(PipelineLane::Warnings(BasicLane::Main)),
            Self::Dlq => Some(Address::Dlq),
            Self::Custom(topic) => Some(Address::Custom(topic.clone())),
            Self::Drop => None,
        }
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
            Self::AiEvents => "ai_events",
            Self::AiEventsOverflow => "ai_events_overflow",
        }
    }
}

#[cfg(test)]
mod destination_tests {
    use super::Destination;
    use crate::sinks::registry::Destination as Output;

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
        assert!(!Destination::AiEvents.is_analytics_pipeline());
        assert!(!Destination::AiEventsOverflow.is_analytics_pipeline());
        assert!(!Destination::Overflow.is_analytics_pipeline());
        assert!(!Destination::Dlq.is_analytics_pipeline());
        assert!(!Destination::Drop.is_analytics_pipeline());
        assert!(!Destination::Custom("foo".into()).is_analytics_pipeline());
    }

    /// Each v1 destination publishes to the output that carried its topic
    /// before v1 joined the outputs layer.
    #[rstest::rstest]
    #[case(Destination::AnalyticsMain, Some(Output::AnalyticsMain))]
    #[case(Destination::AnalyticsHistorical, Some(Output::AnalyticsHistorical))]
    #[case(Destination::Overflow, Some(Output::AnalyticsOverflow))]
    #[case(Destination::Dlq, Some(Output::Dlq))]
    #[case(Destination::Custom("admin_topic".into()), Some(Output::Custom("admin_topic".into())))]
    #[case(Destination::ExceptionErrorTracking, Some(Output::ErrorTrackingMain))]
    #[case(Destination::HeatmapMain, Some(Output::HeatmapsMain))]
    #[case(Destination::ClientIngestionWarning, Some(Output::ClientWarningsMain))]
    #[case(Destination::AiEvents, Some(Output::AiMain))]
    #[case(Destination::AiEventsOverflow, Some(Output::AiOverflow))]
    #[case(Destination::Drop, None)]
    fn address_selects_the_destinations_output(
        #[case] destination: Destination,
        #[case] expected: Option<Output>,
    ) {
        let output = destination.address().map(Output::for_address);
        assert_eq!(output, expected);
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
            (Destination::AiEvents, "ai_events"),
            (Destination::AiEventsOverflow, "ai_events_overflow"),
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
// SerializationFailure
// ---------------------------------------------------------------------------

/// An event that failed during the serialize step, before any output saw it.
/// Always fatal: the event is dropped, never retried.
#[derive(Debug, Clone)]
pub struct SerializationFailure {
    uuid: Uuid,
    cause: &'static str,
    detail: String,
}

impl SerializationFailure {
    pub fn from_error(uuid: Uuid, detail: String) -> Self {
        Self {
            uuid,
            cause: "serialization_failed",
            detail,
        }
    }

    pub fn panicked(uuid: Uuid) -> Self {
        Self {
            uuid,
            cause: "serialization_panic",
            detail: "serialization task panicked".to_string(),
        }
    }

    pub fn is_panic(&self) -> bool {
        self.cause == "serialization_panic"
    }

    pub fn uuid(&self) -> Uuid {
        self.uuid
    }

    pub fn cause(&self) -> &'static str {
        self.cause
    }

    pub fn detail_str(&self) -> &str {
        &self.detail
    }
}
