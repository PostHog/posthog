//! Lanes and addresses — where an event publishes, and the one place v0
//! decides it.
//!
//! Each deployment has its own lane set ([`AnalyticsOutputLane`],
//! [`ImportOutputLane`], [`AiLane`], [`SessionReplayLane`]), so an [`Address`]
//! can only name a lane its deployment has an output for. Each kind's `resolve`
//! folds the intent stamped on [`ProcessedEventMetadata`] during processing
//! (restrictions, overflow reasons, the event's kind) through one precedence
//! chain — dlq > custom > historical > overflow > main — and returns an
//! [`AddressDecision`]: the address the event publishes to and the
//! customer-facing [`OrderingGuarantee`] the sink realizes as a partition key.
//! The decision is pure — no counters, no headers, no I/O; side effects are
//! implied by the address and applied by the layer that realizes it.

use crate::api::CaptureError;
use crate::event_restrictions::Pipeline;
use crate::kind::{AiKind, AnalyticsKind, Historical, MainOrHistorical, SnapshotKind};
use crate::ordering::{person_ordering, OrderingGuarantee};
use crate::v0_request::{OverflowReason, ProcessedEventMetadata};

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum OverflowBudget {
    Analytics,
    Ai,
}

pub trait Lane: Copy + std::fmt::Debug + PartialEq + Eq + Send + Sync + 'static {
    fn name(self) -> &'static str;

    fn pipeline(self) -> Pipeline;

    /// Whether a hot key on this lane may give up its partition key.
    fn absorbs_hot_keys(self) -> bool;

    fn writes_persons(self) -> bool;

    /// The lane an overflowing event moves to, and the limiter budget it
    /// overflows from.
    fn overflow(self) -> Option<(Self, OverflowBudget)>;

    fn historical(self) -> Option<Self>;
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum AnalyticsLane {
    Main,
    Overflow,
    Historical,
}

/// No historical lane: the AI divert wins over historical rerouting.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum AiLane {
    Main,
    Overflow,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum SessionReplayLane {
    Main,
    Overflow,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum AnalyticsOutputLane {
    Analytics(AnalyticsLane),
    Ai(AiLane),
    Heatmaps,
    ClientWarnings,
    ErrorTracking,
}

/// capture-import: historical instead of main and overflow, and no AI
/// overflow.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum ImportOutputLane {
    AnalyticsHistorical,
    AiMain,
    Heatmaps,
    ClientWarnings,
    ErrorTracking,
}

impl Lane for AnalyticsOutputLane {
    fn name(self) -> &'static str {
        match self {
            Self::Analytics(AnalyticsLane::Main) => "analytics-main",
            Self::Analytics(AnalyticsLane::Overflow) => "analytics-overflow",
            Self::Analytics(AnalyticsLane::Historical) => "analytics-historical",
            Self::Ai(lane) => lane.name(),
            Self::Heatmaps => "heatmaps-main",
            Self::ClientWarnings => "clientwarnings-main",
            Self::ErrorTracking => "errortracking-main",
        }
    }

    fn pipeline(self) -> Pipeline {
        match self {
            Self::Analytics(_) => Pipeline::Analytics,
            Self::Ai(_) => Pipeline::Ai,
            Self::Heatmaps => Pipeline::Heatmaps,
            Self::ClientWarnings => Pipeline::ClientWarnings,
            Self::ErrorTracking => Pipeline::ErrorTracking,
        }
    }

    fn absorbs_hot_keys(self) -> bool {
        match self {
            Self::Analytics(AnalyticsLane::Main | AnalyticsLane::Overflow) => true,
            Self::Analytics(AnalyticsLane::Historical) => false,
            Self::Ai(lane) => lane.absorbs_hot_keys(),
            Self::Heatmaps | Self::ClientWarnings | Self::ErrorTracking => false,
        }
    }

    fn writes_persons(self) -> bool {
        match self {
            Self::Analytics(_) => true,
            Self::Ai(_) | Self::Heatmaps | Self::ClientWarnings | Self::ErrorTracking => false,
        }
    }

    fn overflow(self) -> Option<(Self, OverflowBudget)> {
        match self {
            Self::Analytics(AnalyticsLane::Main) => Some((
                Self::Analytics(AnalyticsLane::Overflow),
                OverflowBudget::Analytics,
            )),
            Self::Ai(lane) => lane
                .overflow()
                .map(|(overflow, budget)| (Self::Ai(overflow), budget)),
            Self::Analytics(AnalyticsLane::Overflow | AnalyticsLane::Historical)
            | Self::Heatmaps
            | Self::ClientWarnings
            | Self::ErrorTracking => None,
        }
    }

    fn historical(self) -> Option<Self> {
        match self {
            Self::Analytics(AnalyticsLane::Main) => {
                Some(Self::Analytics(AnalyticsLane::Historical))
            }
            Self::Analytics(AnalyticsLane::Overflow | AnalyticsLane::Historical)
            | Self::Ai(_)
            | Self::Heatmaps
            | Self::ClientWarnings
            | Self::ErrorTracking => None,
        }
    }
}

impl Lane for ImportOutputLane {
    fn name(self) -> &'static str {
        match self {
            Self::AnalyticsHistorical => "analytics-historical",
            Self::AiMain => "ai-main",
            Self::Heatmaps => "heatmaps-main",
            Self::ClientWarnings => "clientwarnings-main",
            Self::ErrorTracking => "errortracking-main",
        }
    }

    fn pipeline(self) -> Pipeline {
        match self {
            Self::AnalyticsHistorical => Pipeline::Analytics,
            Self::AiMain => Pipeline::Ai,
            Self::Heatmaps => Pipeline::Heatmaps,
            Self::ClientWarnings => Pipeline::ClientWarnings,
            Self::ErrorTracking => Pipeline::ErrorTracking,
        }
    }

    fn absorbs_hot_keys(self) -> bool {
        false
    }

    fn writes_persons(self) -> bool {
        match self {
            Self::AnalyticsHistorical => true,
            Self::AiMain | Self::Heatmaps | Self::ClientWarnings | Self::ErrorTracking => false,
        }
    }

    fn overflow(self) -> Option<(Self, OverflowBudget)> {
        None
    }

    fn historical(self) -> Option<Self> {
        None
    }
}

impl Lane for AiLane {
    fn name(self) -> &'static str {
        match self {
            Self::Main => "ai-main",
            Self::Overflow => "ai-overflow",
        }
    }

    fn pipeline(self) -> Pipeline {
        Pipeline::Ai
    }

    fn absorbs_hot_keys(self) -> bool {
        match self {
            Self::Main => false,
            Self::Overflow => true,
        }
    }

    fn writes_persons(self) -> bool {
        false
    }

    fn overflow(self) -> Option<(Self, OverflowBudget)> {
        match self {
            Self::Main => Some((Self::Overflow, OverflowBudget::Ai)),
            Self::Overflow => None,
        }
    }

    fn historical(self) -> Option<Self> {
        None
    }
}

impl Lane for SessionReplayLane {
    fn name(self) -> &'static str {
        match self {
            Self::Main => "sessionreplay-main",
            Self::Overflow => "sessionreplay-overflow",
        }
    }

    fn pipeline(self) -> Pipeline {
        Pipeline::SessionRecordings
    }

    fn absorbs_hot_keys(self) -> bool {
        false
    }

    fn writes_persons(self) -> bool {
        false
    }

    // Replay overflows by session, through the replay limiter `resolve`
    // reads, never through a per-key budget.
    fn overflow(self) -> Option<(Self, OverflowBudget)> {
        None
    }

    fn historical(self) -> Option<Self> {
        None
    }
}

/// Where an event publishes: a lane of its deployment, or an admin redirect outside
/// the lane model. A redirect carries no lane: every pipeline shares one dlq
/// output, and a custom redirect names its own topic.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Address<L> {
    Lane(L),
    Dlq,
    Custom(String),
}

impl<L: Lane> Address<L> {
    /// `Custom` collapses to "custom" so admin topic names never leak into
    /// labels or error messages.
    pub fn name(&self) -> &'static str {
        match self {
            Address::Lane(lane) => lane.name(),
            Address::Dlq => "dlq",
            Address::Custom(_) => "custom",
        }
    }

    pub fn pipeline(&self) -> Option<Pipeline> {
        match self {
            Address::Lane(lane) => Some(lane.pipeline()),
            Address::Dlq | Address::Custom(_) => None,
        }
    }

    pub fn absorbs_hot_keys(&self) -> bool {
        match self {
            Address::Lane(lane) => lane.absorbs_hot_keys(),
            Address::Dlq | Address::Custom(_) => false,
        }
    }

    pub fn writes_persons(&self) -> bool {
        match self {
            Address::Lane(lane) => lane.writes_persons(),
            Address::Dlq | Address::Custom(_) => true,
        }
    }
}

/// The pure routing decision for a single event: which address, and which
/// ordering guarantee. Depends only on [`ProcessedEventMetadata`] (stamped
/// upstream by the pipeline) and whether the deployment has an AI overflow
/// lane — the one piece of deployment config that changes a routing decision
/// rather than a topic name. Side effects are not part of the decision: the dlq header set and
/// the reroute counters follow from the address, and the person-processing
/// header follows from
/// [`ProcessedEventMetadata::person_processing_disabled`] — the stamped flag,
/// or a `ForceLimited` reason, which implies the skip on its own.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AddressDecision<L> {
    pub address: Address<L>,
    pub ordering: OrderingGuarantee,
}

impl<L> AddressDecision<L> {
    fn lane(lane: L, ordering: OrderingGuarantee) -> Self {
        Self {
            address: Address::Lane(lane),
            ordering,
        }
    }
}

/// DLQ and custom-topic redirects take priority over every lane decision, and
/// both key on the event key.
fn redirect<K, L>(metadata: &ProcessedEventMetadata<K>) -> Option<AddressDecision<L>> {
    let address = if metadata.redirect_to_dlq {
        Address::Dlq
    } else {
        Address::Custom(metadata.redirect_to_topic.clone()?)
    };
    Some(AddressDecision {
        address,
        ordering: OrderingGuarantee::PerDistinctId,
    })
}

/// A restriction's `force_overflow` takes priority over a stamped
/// `overflow_reason`.
fn analytics_main<K>(metadata: &ProcessedEventMetadata<K>) -> (AnalyticsLane, OrderingGuarantee) {
    if metadata.force_overflow {
        return (
            AnalyticsLane::Overflow,
            person_ordering(metadata.person_processing_disabled()),
        );
    }
    match &metadata.overflow_reason {
        Some(OverflowReason::ForceLimited) => (AnalyticsLane::Overflow, OrderingGuarantee::None),
        // The person flag alone decides the key here, in both directions. A
        // burst keeps its key while person processing is on — the overflow
        // consumer updates persons keyed on distinct id, so spreading one
        // distinct id across partitions turns a hot key into contended
        // person-row updates — which makes the locality preference irrelevant
        // on this lane. And a key whose person processing is already off (the
        // global rate limiter stamps its verdict before the overflow limiter
        // overwrites the reason) must not get its partition back.
        Some(OverflowReason::RateLimited { .. }) => (
            AnalyticsLane::Overflow,
            person_ordering(metadata.person_processing_disabled()),
        ),
        // ReplayLimited is stamped only by the recordings pipeline, so an
        // analytics event cannot carry it — the shared OverflowReason enum
        // forces the arm, which treats the impossible stamp as unstamped.
        Some(OverflowReason::ReplayLimited) | None => (
            AnalyticsLane::Main,
            person_ordering(metadata.person_processing_disabled()),
        ),
    }
}

/// The AI lanes route overflow like analytics, except that a burst may spread
/// while person processing is on — the AI consumer reads persons without
/// writing them, so keyless person-on records cause no person-update
/// contention there. The default route keeps the event key regardless of
/// skip_person_processing.
fn ai<K>(metadata: &ProcessedEventMetadata<K>) -> (AiLane, OrderingGuarantee) {
    if metadata.force_overflow {
        return (
            AiLane::Overflow,
            person_ordering(metadata.person_processing_disabled()),
        );
    }
    match &metadata.overflow_reason {
        Some(OverflowReason::ForceLimited) => (AiLane::Overflow, OrderingGuarantee::None),
        Some(OverflowReason::RateLimited {
            preserve_locality: true,
        }) => (
            AiLane::Overflow,
            // Same precedence as the analytics overflow lane above.
            person_ordering(metadata.person_processing_disabled()),
        ),
        Some(OverflowReason::RateLimited {
            preserve_locality: false,
        }) => (AiLane::Overflow, OrderingGuarantee::None),
        // ReplayLimited cannot be stamped on the AI lane either; treated as
        // unstamped, as above.
        Some(OverflowReason::ReplayLimited) | None => {
            (AiLane::Main, OrderingGuarantee::PerDistinctId)
        }
    }
}

pub(crate) fn resolve_analytics(
    metadata: &ProcessedEventMetadata<AnalyticsKind<MainOrHistorical>>,
) -> AddressDecision<AnalyticsOutputLane> {
    if let Some(decision) = redirect(metadata) {
        return decision;
    }
    match metadata.kind {
        AnalyticsKind::Analytics(MainOrHistorical::Main) => {
            let (lane, ordering) = analytics_main(metadata);
            AddressDecision::lane(AnalyticsOutputLane::Analytics(lane), ordering)
        }
        // Historical events never overflow — force_overflow and
        // overflow_reason are deliberately ignored here.
        AnalyticsKind::Analytics(MainOrHistorical::Historical) => AddressDecision::lane(
            AnalyticsOutputLane::Analytics(AnalyticsLane::Historical),
            OrderingGuarantee::PerDistinctId,
        ),
        AnalyticsKind::Ai => {
            let (lane, ordering) = ai(metadata);
            AddressDecision::lane(AnalyticsOutputLane::Ai(lane), ordering)
        }
        // A ForceOverflow restriction can stamp `force_overflow` on these
        // events. They have no overflow lane, so the stamp is ignored.
        AnalyticsKind::ClientWarning => AddressDecision::lane(
            AnalyticsOutputLane::ClientWarnings,
            OrderingGuarantee::PerDistinctId,
        ),
        AnalyticsKind::Heatmap => AddressDecision::lane(
            AnalyticsOutputLane::Heatmaps,
            OrderingGuarantee::PerDistinctId,
        ),
        AnalyticsKind::Exception => AddressDecision::lane(
            AnalyticsOutputLane::ErrorTracking,
            OrderingGuarantee::PerDistinctId,
        ),
    }
}

/// Import has no overflow lane, so every overflow stamp is ignored.
pub(crate) fn resolve_import(
    metadata: &ProcessedEventMetadata<AnalyticsKind<Historical>>,
) -> AddressDecision<ImportOutputLane> {
    if let Some(decision) = redirect(metadata) {
        return decision;
    }
    let lane = match metadata.kind {
        AnalyticsKind::Analytics(Historical) => ImportOutputLane::AnalyticsHistorical,
        AnalyticsKind::Ai => ImportOutputLane::AiMain,
        AnalyticsKind::ClientWarning => ImportOutputLane::ClientWarnings,
        AnalyticsKind::Heatmap => ImportOutputLane::Heatmaps,
        AnalyticsKind::Exception => ImportOutputLane::ErrorTracking,
    };
    AddressDecision::lane(lane, OrderingGuarantee::PerDistinctId)
}

pub(crate) fn resolve_ai(metadata: &ProcessedEventMetadata<AiKind>) -> AddressDecision<AiLane> {
    if let Some(decision) = redirect(metadata) {
        return decision;
    }
    let (lane, ordering) = ai(metadata);
    AddressDecision::lane(lane, ordering)
}

/// A replay event with no session id is rejected here, so every returned
/// decision is realizable by the sink.
pub(crate) fn resolve_session_replay(
    metadata: &ProcessedEventMetadata<SnapshotKind>,
) -> Result<AddressDecision<SessionReplayLane>, CaptureError> {
    if let Some(decision) = redirect(metadata) {
        return Ok(decision);
    }
    // Partition key is always session_id for replay to keep per-session
    // ordering on the overflow lane; a missing id makes the decision
    // unrealizable, so it is rejected as part of the decision.
    if metadata.session_id.is_none() {
        return Err(CaptureError::MissingSessionId);
    }
    let lane = if metadata.force_overflow
        || matches!(
            metadata.overflow_reason,
            Some(OverflowReason::ReplayLimited)
        ) {
        SessionReplayLane::Overflow
    } else {
        SessionReplayLane::Main
    };
    Ok(AddressDecision::lane(lane, OrderingGuarantee::PerSession))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    const MAIN: AnalyticsKind<MainOrHistorical> = AnalyticsKind::Analytics(MainOrHistorical::Main);
    const HISTORICAL: AnalyticsKind<MainOrHistorical> =
        AnalyticsKind::Analytics(MainOrHistorical::Historical);

    fn meta<K>(kind: K) -> ProcessedEventMetadata<K> {
        ProcessedEventMetadata {
            kind,
            session_id: Some("session123".to_string()),
            computed_timestamp: None,
            event_name: "test_event".to_string(),
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            skip_heatmap_processing: false,
            overflow_reason: None,
            distinct_id_truncated_from: None,
        }
    }

    fn lane<L>(lane: L) -> Address<L> {
        Address::Lane(lane)
    }

    fn resolve(
        m: &ProcessedEventMetadata<AnalyticsKind<MainOrHistorical>>,
    ) -> Result<AddressDecision<AnalyticsOutputLane>, CaptureError> {
        Ok(resolve_analytics(m))
    }

    #[test]
    fn dlq_wins_over_custom_topic_and_datatype() {
        // redirect_to_dlq set alongside redirect_to_topic and an overflow
        // reason: DLQ still wins, keyed on the event key, with the DLQ effect.
        let mut m = meta(MAIN);
        m.redirect_to_dlq = true;
        m.redirect_to_topic = Some("custom".to_string());
        m.force_overflow = true;
        assert_eq!(
            resolve(&m).unwrap(),
            AddressDecision {
                address: Address::Dlq,
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );
    }

    #[test]
    fn custom_topic_wins_over_datatype() {
        // Custom-topic redirect beats per-datatype/overflow routing (but not DLQ).
        let mut m = meta(MAIN);
        m.redirect_to_topic = Some("my_topic".to_string());
        m.force_overflow = true;
        assert_eq!(
            resolve(&m).unwrap(),
            AddressDecision {
                address: Address::Custom("my_topic".to_string()),
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );
    }

    #[rstest]
    #[case(MAIN, AnalyticsOutputLane::Analytics(AnalyticsLane::Main))]
    #[case(HISTORICAL, AnalyticsOutputLane::Analytics(AnalyticsLane::Historical))]
    #[case(AnalyticsKind::ClientWarning, AnalyticsOutputLane::ClientWarnings)]
    #[case(AnalyticsKind::Heatmap, AnalyticsOutputLane::Heatmaps)]
    #[case(AnalyticsKind::Exception, AnalyticsOutputLane::ErrorTracking)]
    #[case(AnalyticsKind::Ai, AnalyticsOutputLane::Ai(AiLane::Main))]
    fn per_kind_addresses(
        #[case] kind: AnalyticsKind<MainOrHistorical>,
        #[case] expected_lane: AnalyticsOutputLane,
    ) {
        let d = resolve(&meta(kind)).unwrap();
        assert_eq!(d.address, lane(expected_lane), "wrong address for {kind:?}");
    }

    #[rstest]
    #[case(AnalyticsKind::ClientWarning, AnalyticsOutputLane::ClientWarnings)]
    #[case(AnalyticsKind::Heatmap, AnalyticsOutputLane::Heatmaps)]
    #[case(AnalyticsKind::Exception, AnalyticsOutputLane::ErrorTracking)]
    #[case(HISTORICAL, AnalyticsOutputLane::Analytics(AnalyticsLane::Historical))]
    fn lanes_without_overflow_ignore_overflow_intent(
        #[case] kind: AnalyticsKind<MainOrHistorical>,
        #[case] main: AnalyticsOutputLane,
    ) {
        let mut m = meta(kind);
        m.force_overflow = true;
        m.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&m).unwrap(),
            AddressDecision {
                address: lane(main),
                ordering: OrderingGuarantee::PerDistinctId,
            },
            "overflow intent must not move {kind:?} off its lane"
        );
    }

    /// Import has no overflow lane, so overflow intent changes neither the
    /// lane nor the key.
    #[rstest]
    #[case(
        AnalyticsKind::Analytics(Historical),
        ImportOutputLane::AnalyticsHistorical
    )]
    #[case(AnalyticsKind::Ai, ImportOutputLane::AiMain)]
    #[case(AnalyticsKind::ClientWarning, ImportOutputLane::ClientWarnings)]
    #[case(AnalyticsKind::Heatmap, ImportOutputLane::Heatmaps)]
    #[case(AnalyticsKind::Exception, ImportOutputLane::ErrorTracking)]
    fn import_ignores_overflow_intent(
        #[case] kind: AnalyticsKind<Historical>,
        #[case] expected: ImportOutputLane,
    ) {
        let mut m = meta(kind);
        m.force_overflow = true;
        m.skip_person_processing = true;
        m.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve_import(&m),
            AddressDecision {
                address: lane(expected),
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );
    }

    #[test]
    fn analytics_main_overflow_ordering() {
        // force_overflow -> overflow lane; key policy follows skip_person.
        let mut m = meta(MAIN);
        m.force_overflow = true;
        assert_eq!(
            resolve(&m).unwrap().ordering,
            OrderingGuarantee::PerDistinctId
        );
        m.skip_person_processing = true;
        assert_eq!(resolve(&m).unwrap().ordering, OrderingGuarantee::None);
        assert_eq!(
            resolve(&m).unwrap().address,
            lane(AnalyticsOutputLane::Analytics(AnalyticsLane::Overflow))
        );
    }

    #[test]
    fn analytics_main_overflow_reason_precedence() {
        let base = meta(MAIN);

        let mut force_limited = base.clone();
        force_limited.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&force_limited).unwrap(),
            AddressDecision {
                address: lane(AnalyticsOutputLane::Analytics(AnalyticsLane::Overflow)),
                ordering: OrderingGuarantee::None,
            }
        );

        let mut preserve = base.clone();
        preserve.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: true,
        });
        assert_eq!(
            resolve(&preserve).unwrap().ordering,
            OrderingGuarantee::PerDistinctId
        );
        assert_eq!(
            resolve(&preserve).unwrap().address,
            lane(AnalyticsOutputLane::Analytics(AnalyticsLane::Overflow))
        );

        // The locality preference is irrelevant on the analytics lane: a
        // person-on burst keeps its key either way, because the overflow
        // consumer writes persons keyed on distinct id.
        let mut no_preserve = base.clone();
        no_preserve.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: false,
        });
        assert_eq!(
            resolve(&no_preserve).unwrap().ordering,
            OrderingGuarantee::PerDistinctId
        );
        assert_eq!(
            resolve(&no_preserve).unwrap().address,
            lane(AnalyticsOutputLane::Analytics(AnalyticsLane::Overflow))
        );
        no_preserve.skip_person_processing = true;
        assert_eq!(
            resolve(&no_preserve).unwrap().ordering,
            OrderingGuarantee::None
        );

        // ReplayLimited cannot be stamped on analytics events (only the
        // recordings pipeline produces it); the impossible combination is
        // treated as unstamped.
        let mut replay = base;
        replay.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(
            resolve(&replay).unwrap().address,
            lane(AnalyticsOutputLane::Analytics(AnalyticsLane::Main))
        );
    }

    /// The global rate limiter stamps `skip_person_processing` before the
    /// overflow limiter runs, and the overflow limiter overwrites the reason it
    /// stamped. Without this precedence a key the rate limiter declared too hot
    /// would go back to hashing onto a single overflow partition whenever the
    /// limiter preserves locality.
    #[rstest]
    #[case::analytics(MAIN, AnalyticsOutputLane::Analytics(AnalyticsLane::Overflow))]
    #[case::ai(AnalyticsKind::Ai, AnalyticsOutputLane::Ai(AiLane::Overflow))]
    fn person_processing_off_outranks_preserve_locality(
        #[case] kind: AnalyticsKind<MainOrHistorical>,
        #[case] overflow: AnalyticsOutputLane,
    ) {
        let mut m = meta(kind);
        m.overflow_reason = Some(OverflowReason::RateLimited {
            preserve_locality: true,
        });

        assert_eq!(
            resolve(&m).unwrap().ordering,
            OrderingGuarantee::PerDistinctId,
            "locality is preserved while person processing is on"
        );

        m.skip_person_processing = true;
        assert_eq!(
            resolve(&m).unwrap(),
            AddressDecision {
                address: lane(overflow),
                ordering: OrderingGuarantee::None,
            }
        );
    }

    #[test]
    fn ai_events_overflow_mirrors_analytics_main() {
        let mut m = meta(AnalyticsKind::Ai);
        m.force_overflow = true;
        assert_eq!(
            resolve(&m).unwrap().address,
            lane(AnalyticsOutputLane::Ai(AiLane::Overflow))
        );
        assert_eq!(
            resolve(&m).unwrap().ordering,
            OrderingGuarantee::PerDistinctId
        );
        m.skip_person_processing = true;
        assert_eq!(resolve(&m).unwrap().ordering, OrderingGuarantee::None);

        let mut force_limited = meta(AnalyticsKind::Ai);
        force_limited.overflow_reason = Some(OverflowReason::ForceLimited);
        assert_eq!(
            resolve(&force_limited).unwrap(),
            AddressDecision {
                address: lane(AnalyticsOutputLane::Ai(AiLane::Overflow)),
                ordering: OrderingGuarantee::None,
            }
        );
    }

    #[test]
    fn ai_events_default_route_keeps_event_key() {
        // skip_person_processing must not null the key on the AI default
        // route: v1 only nulls keys for Main/Overflow-shaped destinations.
        let mut m = meta(AnalyticsKind::Ai);
        m.skip_person_processing = true;
        assert_eq!(
            resolve(&m).unwrap(),
            AddressDecision {
                address: lane(AnalyticsOutputLane::Ai(AiLane::Main)),
                ordering: OrderingGuarantee::PerDistinctId,
            }
        );
    }

    #[test]
    fn snapshot_routing_keeps_per_session_ordering() {
        let mut m = meta(SnapshotKind);
        assert_eq!(
            resolve_session_replay(&m).unwrap(),
            AddressDecision {
                address: lane(SessionReplayLane::Main),
                ordering: OrderingGuarantee::PerSession,
            }
        );

        m.force_overflow = true;
        assert_eq!(
            resolve_session_replay(&m).unwrap().address,
            lane(SessionReplayLane::Overflow)
        );
        assert_eq!(
            resolve_session_replay(&m).unwrap().ordering,
            OrderingGuarantee::PerSession
        );

        m.force_overflow = false;
        m.overflow_reason = Some(OverflowReason::ReplayLimited);
        assert_eq!(
            resolve_session_replay(&m).unwrap().address,
            lane(SessionReplayLane::Overflow)
        );
    }

    /// A replay event with no session id has no realizable address — the
    /// decision itself rejects, rather than handing the sink a `PerSession`
    /// guarantee it cannot key.
    #[test]
    fn snapshot_without_session_id_is_rejected() {
        let mut m = meta(SnapshotKind);
        m.session_id = None;
        assert!(matches!(
            resolve_session_replay(&m),
            Err(CaptureError::MissingSessionId)
        ));

        // A dlq redirect keys on the event key, so it stays realizable
        // without a session id.
        m.redirect_to_dlq = true;
        assert_eq!(resolve_session_replay(&m).unwrap().address, Address::Dlq);
    }
}
