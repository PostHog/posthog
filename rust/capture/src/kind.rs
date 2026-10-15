//! What an event is, decided once by the handler that accepts it.
//!
//! Each deployment accepts its own kinds: setup picks the kind type from
//! `CAPTURE_MODE`, and from the handler down the code only sees that type.
//! [`Classify`] turns an event name into a kind, and [`EventKind`] answers what
//! the processing stages ask of it.

use std::convert::Infallible;

use crate::api::CaptureError;
use crate::event_restrictions::Pipeline;
use crate::v0_request::is_ai_event;

pub trait EventKind: Copy + std::fmt::Debug + PartialEq + Eq + Send + Sync + 'static {
    /// The restriction pipeline this event is looked up under. Snapshots have
    /// none here: the recordings endpoint looks them up itself.
    fn pipeline(self) -> Option<Pipeline>;

    fn is_ai(self) -> bool;

    fn is_historical(self) -> bool;

    fn is_session_replay(self) -> bool;

    fn overflow_budget(self) -> Option<OverflowBudget>;

    fn to_historical(self) -> Option<Self>;
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum OverflowBudget {
    Analytics,
    Ai,
}

pub trait Classify: Sized {
    /// `Infallible` for a deployment that accepts every name.
    type Refusal: Refusal;

    fn classify(event_name: &str, historical_migration: bool) -> Result<Self, Self::Refusal>;
}

pub trait Refusal {
    fn into_capture_error(self, event_name: &str) -> CaptureError;
}

impl Refusal for Infallible {
    fn into_capture_error(self, _event_name: &str) -> CaptureError {
        match self {}
    }
}

/// An AI deployment loads only the AI restriction slice, so an event off the
/// AI lane would ingest governed by nothing.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct NonAiEvent;

impl Refusal for NonAiEvent {
    fn into_capture_error(self, event_name: &str) -> CaptureError {
        CaptureError::NonAiEventOnAiLane(event_name.to_string())
    }
}

pub trait AnalyticsVariant:
    Copy + std::fmt::Debug + PartialEq + Eq + Send + Sync + 'static
{
    fn is_historical(self) -> bool;

    fn to_historical(self) -> Option<Self>;
}

/// capture-analytics: live events go to main; `historical_migration` batches
/// and stale events go to historical.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum MainOrHistorical {
    Main,
    Historical,
}

/// capture-import serves only `historical_migration` batches, so every
/// analytics event it accepts is historical.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct Historical;

impl AnalyticsVariant for MainOrHistorical {
    fn is_historical(self) -> bool {
        self == MainOrHistorical::Historical
    }

    fn to_historical(self) -> Option<Self> {
        match self {
            MainOrHistorical::Main => Some(MainOrHistorical::Historical),
            MainOrHistorical::Historical => None,
        }
    }
}

impl AnalyticsVariant for Historical {
    fn is_historical(self) -> bool {
        true
    }

    fn to_historical(self) -> Option<Self> {
        None
    }
}

/// An event accepted on the analytics routes. `$ai_*`, `$exception`,
/// `$$heatmap` and `$$client_ingestion_warning` divert by name; `A` is where
/// everything else goes.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum AnalyticsKind<A> {
    Analytics(A),
    Ai,
    Heatmap,
    ClientWarning,
    Exception,
}

impl<A> AnalyticsKind<A> {
    /// AI events divert on every deployment, winning over historical.
    fn from_event_name(event_name: &str, analytics: A) -> Self {
        match event_name {
            "$$client_ingestion_warning" => Self::ClientWarning,
            "$exception" => Self::Exception,
            "$$heatmap" => Self::Heatmap,
            _ if is_ai_event(event_name) => Self::Ai,
            _ => Self::Analytics(analytics),
        }
    }
}

impl<A: AnalyticsVariant> EventKind for AnalyticsKind<A> {
    fn pipeline(self) -> Option<Pipeline> {
        Some(match self {
            Self::Analytics(_) => Pipeline::Analytics,
            Self::Ai => Pipeline::Ai,
            Self::Heatmap => Pipeline::Heatmaps,
            Self::ClientWarning => Pipeline::ClientWarnings,
            Self::Exception => Pipeline::ErrorTracking,
        })
    }

    fn is_ai(self) -> bool {
        self == Self::Ai
    }

    fn is_historical(self) -> bool {
        matches!(self, Self::Analytics(analytics) if analytics.is_historical())
    }

    fn is_session_replay(self) -> bool {
        false
    }

    fn overflow_budget(self) -> Option<OverflowBudget> {
        match self {
            Self::Analytics(analytics) if !analytics.is_historical() => {
                Some(OverflowBudget::Analytics)
            }
            Self::Ai => Some(OverflowBudget::Ai),
            Self::Analytics(_) | Self::Heatmap | Self::ClientWarning | Self::Exception => None,
        }
    }

    fn to_historical(self) -> Option<Self> {
        match self {
            Self::Analytics(analytics) => analytics.to_historical().map(Self::Analytics),
            Self::Ai | Self::Heatmap | Self::ClientWarning | Self::Exception => None,
        }
    }
}

impl Classify for AnalyticsKind<MainOrHistorical> {
    type Refusal = Infallible;

    fn classify(event_name: &str, historical_migration: bool) -> Result<Self, Infallible> {
        let analytics = if historical_migration {
            MainOrHistorical::Historical
        } else {
            MainOrHistorical::Main
        };
        Ok(Self::from_event_name(event_name, analytics))
    }
}

impl Classify for AnalyticsKind<Historical> {
    type Refusal = Infallible;

    fn classify(event_name: &str, _historical_migration: bool) -> Result<Self, Infallible> {
        Ok(Self::from_event_name(event_name, Historical))
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct AiKind;

impl EventKind for AiKind {
    fn pipeline(self) -> Option<Pipeline> {
        Some(Pipeline::Ai)
    }

    fn is_ai(self) -> bool {
        true
    }

    fn is_historical(self) -> bool {
        false
    }

    fn is_session_replay(self) -> bool {
        false
    }

    fn overflow_budget(self) -> Option<OverflowBudget> {
        Some(OverflowBudget::Ai)
    }

    fn to_historical(self) -> Option<Self> {
        None
    }
}

impl Classify for AiKind {
    type Refusal = NonAiEvent;

    fn classify(event_name: &str, _historical_migration: bool) -> Result<Self, NonAiEvent> {
        if is_ai_event(event_name) {
            Ok(AiKind)
        } else {
            Err(NonAiEvent)
        }
    }
}

/// capture-replay builds every event it accepts as a snapshot: the handler
/// reads `$snapshot_data` and names the record `$snapshot_items` whatever the
/// client sent, so it needs no [`Classify`].
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct SnapshotKind;

impl EventKind for SnapshotKind {
    fn pipeline(self) -> Option<Pipeline> {
        None
    }

    fn is_ai(self) -> bool {
        false
    }

    fn is_historical(self) -> bool {
        false
    }

    fn is_session_replay(self) -> bool {
        true
    }

    fn overflow_budget(self) -> Option<OverflowBudget> {
        None
    }

    fn to_historical(self) -> Option<Self> {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MAIN: AnalyticsKind<MainOrHistorical> = AnalyticsKind::Analytics(MainOrHistorical::Main);
    const HISTORICAL: AnalyticsKind<MainOrHistorical> =
        AnalyticsKind::Analytics(MainOrHistorical::Historical);

    /// Mirrors v1's `destination_for_event_name` mapping tests: the
    /// dedicated-name lanes always win, an AI name diverts on every deployment
    /// (beating historical), and everything else falls through to
    /// main/historical per the batch flag.
    #[rstest::rstest]
    // Dedicated-name lanes are unaffected by the historical flag.
    #[case("$exception", false, AnalyticsKind::Exception)]
    #[case("$exception", true, AnalyticsKind::Exception)]
    #[case("$$heatmap", false, AnalyticsKind::Heatmap)]
    #[case("$$heatmap", true, AnalyticsKind::Heatmap)]
    #[case("$$client_ingestion_warning", false, AnalyticsKind::ClientWarning)]
    #[case("$$client_ingestion_warning", true, AnalyticsKind::ClientWarning)]
    // Non-AI events keep the main/historical split.
    #[case("$pageview", false, MAIN)]
    #[case("custom_event", false, MAIN)]
    #[case("$pageview", true, HISTORICAL)]
    // Names that only look like the prefix never divert.
    #[case("ai_generation", false, MAIN)]
    #[case("$AI_generation", false, MAIN)]
    #[case("$ai", false, MAIN)]
    // Every `$ai_` name diverts, and wins over historical.
    #[case("$ai_generation", false, AnalyticsKind::Ai)]
    #[case("$ai_span", false, AnalyticsKind::Ai)]
    #[case("$ai_trace", false, AnalyticsKind::Ai)]
    #[case("$ai_generation_summary", false, AnalyticsKind::Ai)]
    #[case("$ai_generation", true, AnalyticsKind::Ai)]
    #[case("$ai_call", false, AnalyticsKind::Ai)]
    #[case("$ai_generation_enriched", false, AnalyticsKind::Ai)]
    #[case("$ai_model_failover", false, AnalyticsKind::Ai)]
    #[case("$ai_model_failover", true, AnalyticsKind::Ai)]
    #[case("$ai_", false, AnalyticsKind::Ai)]
    fn from_event_name_mapping(
        #[case] event_name: &str,
        #[case] historical_migration: bool,
        #[case] expected: AnalyticsKind<MainOrHistorical>,
    ) {
        assert_eq!(
            AnalyticsKind::<MainOrHistorical>::classify(event_name, historical_migration),
            Ok(expected)
        );
    }

    /// Import reroutes every analytics event to historical, whatever the batch
    /// flag says; the name-based diverts still win.
    #[rstest::rstest]
    #[case("$pageview", AnalyticsKind::Analytics(Historical))]
    #[case("$ai_generation", AnalyticsKind::Ai)]
    #[case("$exception", AnalyticsKind::Exception)]
    fn import_classifies_analytics_events_as_historical(
        #[case] event_name: &str,
        #[case] expected: AnalyticsKind<Historical>,
    ) {
        for historical_migration in [false, true] {
            assert_eq!(
                AnalyticsKind::<Historical>::classify(event_name, historical_migration),
                Ok(expected)
            );
        }
    }

    #[rstest::rstest]
    #[case("$ai_generation", Ok(AiKind))]
    #[case("$pageview", Err(NonAiEvent))]
    #[case("$exception", Err(NonAiEvent))]
    #[case("$$heatmap", Err(NonAiEvent))]
    fn ai_deployment_refuses_non_ai_events(
        #[case] event_name: &str,
        #[case] expected: Result<AiKind, NonAiEvent>,
    ) {
        assert_eq!(AiKind::classify(event_name, false), expected);
    }
}
