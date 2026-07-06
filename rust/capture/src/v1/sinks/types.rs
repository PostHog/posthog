use std::borrow::Cow;
use std::collections::HashMap;
use std::fmt;

use common_types::CapturedEventHeaders;
use uuid::Uuid;

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
        }
    }
}

#[cfg(test)]
mod destination_tests {
    use super::Destination;

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
            (Destination::AiEvents, "ai_events"),
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

/// Backend-agnostic trait for introspecting per-event publish results.
pub trait SinkResult: Send + Sync {
    /// Correlation key -- the originating event's UUID.
    fn key(&self) -> Uuid;

    fn outcome(&self) -> Outcome;

    /// Stable, low-cardinality tag for metrics. None on success.
    fn cause(&self) -> Option<&'static str>;

    /// Rich human-readable error detail for logging. None on success.
    fn detail(&self) -> Option<Cow<'_, str>>;

    /// Time between batch enqueue and this event's ack completion.
    /// None if the event never entered the ack path (immediate error).
    fn elapsed(&self) -> Option<std::time::Duration>;
}

// ---------------------------------------------------------------------------
// PreparedEvent
// ---------------------------------------------------------------------------

/// Storage-agnostic, fully-owned output of the serialize step. Produced by
/// [`serialize_batch`](super::prepare::serialize_batch) and consumed by any
/// [`Sink`](super::sink::Sink). Owns its payload (`Bytes`) so it can be cloned
/// across multiple sinks (dual-write) without re-encoding and moved into
/// spawned tasks. The Sink resolves `destination` to a concrete backend target
/// and applies its own routing policy (e.g. nulling `partition_key`).
#[derive(Debug, Clone)]
pub struct PreparedEvent {
    pub uuid: Uuid,
    pub destination: Destination,
    pub payload: bytes::Bytes,
    pub headers: CapturedEventHeaders,
    /// Raw key; the Sink decides whether to use or null it per routing policy.
    pub partition_key: String,
}

// ---------------------------------------------------------------------------
// SerializationFailure
// ---------------------------------------------------------------------------

/// `SinkResult` for an event that failed during the serialize step (before any
/// sink saw it). Always fatal (non-retriable) and has no ack latency.
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

    pub fn detail_str(&self) -> &str {
        &self.detail
    }
}

impl SinkResult for SerializationFailure {
    fn key(&self) -> Uuid {
        self.uuid
    }

    fn outcome(&self) -> Outcome {
        Outcome::FatalError
    }

    fn cause(&self) -> Option<&'static str> {
        Some(self.cause)
    }

    fn detail(&self) -> Option<Cow<'_, str>> {
        Some(Cow::Borrowed(&self.detail))
    }

    fn elapsed(&self) -> Option<std::time::Duration> {
        None
    }
}

// ---------------------------------------------------------------------------
// BatchSummary
// ---------------------------------------------------------------------------

/// Aggregated stats for a batch of publish results.
pub struct BatchSummary {
    pub total: usize,
    pub succeeded: usize,
    pub retriable: usize,
    pub fatal: usize,
    pub timed_out: usize,
    /// Counts keyed by cause tag (e.g. "queue_full", "timeout").
    pub errors: HashMap<&'static str, usize>,
}

impl BatchSummary {
    pub fn from_results(results: &[Box<dyn SinkResult>]) -> Self {
        let mut succeeded = 0usize;
        let mut retriable = 0usize;
        let mut fatal = 0usize;
        let mut timed_out = 0usize;
        let mut errors: HashMap<&'static str, usize> = HashMap::new();

        for r in results {
            match r.outcome() {
                Outcome::Success => succeeded += 1,
                Outcome::Timeout => {
                    timed_out += 1;
                    if let Some(tag) = r.cause() {
                        *errors.entry(tag).or_default() += 1;
                    }
                }
                Outcome::RetriableError => {
                    retriable += 1;
                    if let Some(tag) = r.cause() {
                        *errors.entry(tag).or_default() += 1;
                    }
                }
                Outcome::FatalError => {
                    fatal += 1;
                    if let Some(tag) = r.cause() {
                        *errors.entry(tag).or_default() += 1;
                    }
                }
            }
        }

        Self {
            total: results.len(),
            succeeded,
            retriable,
            fatal,
            timed_out,
            errors,
        }
    }

    pub fn all_ok(&self) -> bool {
        self.retriable == 0 && self.fatal == 0 && self.timed_out == 0
    }
}

impl fmt::Display for BatchSummary {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{} total, {} ok, {} retriable, {} fatal, {} timed_out",
            self.total, self.succeeded, self.retriable, self.fatal, self.timed_out
        )?;
        if !self.errors.is_empty() {
            let mut pairs: Vec<_> = self.errors.iter().collect();
            pairs.sort_by_key(|(_, count)| std::cmp::Reverse(**count));
            write!(f, " (")?;
            for (i, (tag, count)) in pairs.iter().enumerate() {
                if i > 0 {
                    write!(f, ", ")?;
                }
                write!(f, "{}={}", tag, count)?;
            }
            write!(f, ")")?;
        }
        Ok(())
    }
}
