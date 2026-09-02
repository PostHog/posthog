//! Domain layer: the static analysis of a run's pinned conditions, the census over it, and the
//! per-chunk projection derived from it. Depends on `condition`, `ids`, `plan`, `projection`, and
//! `cohort-core`.
//!
//! Two consumers read the same analysis. The scan path narrows each chunk's SELECT through
//! [`ConditionAnalyses::projection`]; the census reports per run what real catalogs look like, which
//! is what says whether the narrowing can pay on a given team's event mix.
//!
//! The census is shaped around the question a later projection pass has to answer, which is
//! per event name rather than per condition. A scan selects columns for a whole event, so one
//! condition on `$pageview` that cannot be narrowed forces full columns for every `$pageview` row,
//! however many of its siblings are narrow. Counting conditions alone would report that event as
//! mostly projectable and overstate what a projection can do — on exactly the fat events where it
//! matters.
//!
//! Being a pure function of the pinned payload is what makes it safe to run per run rather than per
//! chunk: a re-validated run classifies identically, so a chunk retried on another replica cannot
//! disagree with the first attempt.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::Arc;

use cohort_core::filters::TeamFilters;
use cohort_core::hogvm::analysis::{
    analyze_condition_within, AnalysisBudget, ConditionAnalysis, EvaluationClass,
    FullColumnsReason, Projection, ReadPath,
};

use super::condition::PinnedCondition;
use super::ids::ConditionHash;
use super::plan::ActiveConditions;
use super::projection::ChunkProjection;

/// What one condition turned out to need. Ordered so a census renders the same way every time.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum ConditionClass {
    /// Nothing but an event-name equality, which a scan's event filter already decides.
    EventOnly,
    /// Reads a named, narrow set of globals.
    Projectable,
    /// Understood, but reads a whole object, so every column is needed.
    FullColumns,
    /// Not understood, so it falls back to every column.
    Unanalyzable,
}

impl ConditionClass {
    pub const ALL: [Self; 4] = [
        Self::EventOnly,
        Self::Projectable,
        Self::FullColumns,
        Self::Unanalyzable,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::EventOnly => "event_only",
            Self::Projectable => "projectable",
            Self::FullColumns => "full_columns",
            Self::Unanalyzable => "unanalyzable",
        }
    }

    /// Whether this class forces a scan to select every column for its event name.
    const fn is_unprojectable(self) -> bool {
        matches!(self, Self::FullColumns | Self::Unanalyzable)
    }

    fn of(analysis: &ConditionAnalysis) -> Self {
        match (&analysis.evaluation, &analysis.projection) {
            // An event-name equality needs no per-row evaluation, so its projection is irrelevant —
            // except when the projection itself failed, which means the two passes disagree about
            // what the program is. Classifying by the projection there fails wide rather than
            // narrow, which is the direction a wrong answer has to fall.
            (EvaluationClass::EventOnly { .. }, Projection::Reads(_)) => Self::EventOnly,
            // Exhaustive rather than defaulted, like every other reason mapping in this chain. A
            // new `FullColumnsReason` landing in `FullColumns` by default would be reported as an
            // understood outcome: only `Unanalyzable` reaches the reason counter, so the census
            // would describe a brand new failure mode as expected.
            (EvaluationClass::EventOnly { .. }, Projection::FullColumns(reason))
            | (EvaluationClass::General, Projection::FullColumns(reason)) => match reason {
                FullColumnsReason::Unanalyzable(_) => Self::Unanalyzable,
                FullColumnsReason::BarePropertiesRoot
                | FullColumnsReason::BarePersonRoot
                | FullColumnsReason::RepresentationSensitiveCall => Self::FullColumns,
            },
            (EvaluationClass::General, Projection::Reads(_)) => Self::Projectable,
        }
    }
}

/// The label for a pinned condition whose hash the frozen catalog has no bytecode for. Not an
/// analysis outcome: the condition never reached the analyzer.
pub const MISSING_BYTECODE_REASON: &str = "missing_bytecode";

/// How many blocked event names the per-run log line names before it starts counting instead.
/// Sized to hold a large team's whole blocked set, so the cap is a ceiling rather than a routine
/// truncation.
const MAX_RENDERED_BLOCKED_EVENTS: usize = 50;

/// How many worst-case conditions one run's census may cost, as one budget its conditions share.
///
/// The analyzer bounds each condition, which leaves `conditions × ceiling` for a run — and nothing
/// caps behavioral conditions per run, so that product is unbounded. Sharing one budget bounds the
/// run instead. Past it the remaining conditions report the budget and fall back to every column,
/// which the census counts under its own reason rather than hiding.
///
/// A budget rather than a deadline because [`ConditionAnalyses::build`] has to stay a pure function
/// of the pinned payload: two replicas re-validating one run must classify it identically, and a
/// wall clock would not.
const CENSUS_WORST_CASE_CONDITIONS: usize = 8;

/// One analysis per unique pinned condition hash.
///
/// Person runs are deliberately absent. Their conditions read the small person-scope globals rather
/// than the event globals this analysis models, so classifying them here would report against the
/// wrong vocabulary.
#[derive(Debug, Default)]
pub struct ConditionAnalyses {
    by_hash: HashMap<ConditionHash, ConditionAnalysis>,
}

impl ConditionAnalyses {
    /// Analyze every unique hash among `conditions` whose bytecode the frozen catalog carries,
    /// under one budget they share — see [`CENSUS_WORST_CASE_CONDITIONS`].
    ///
    /// `conditions` is walked in order, so the budget is spent the same way every time and the
    /// result stays a pure function of the pinned payload.
    pub fn build(conditions: &[PinnedCondition], filters: &TeamFilters) -> Self {
        let mut budget = AnalysisBudget::for_conditions(CENSUS_WORST_CASE_CONDITIONS);
        let mut by_hash = HashMap::new();
        for condition in conditions {
            if by_hash.contains_key(&condition.hash) {
                continue;
            }
            let Some(bytecode) = filters
                .by_condition_to_bytecode
                .get(&condition.hash.as_bytes())
            else {
                continue;
            };
            by_hash.insert(
                condition.hash,
                analyze_condition_within(bytecode.as_slice(), &mut budget),
            );
        }
        Self { by_hash }
    }

    /// What a scan over the conditions active on one chunk has to select.
    ///
    /// Takes the active set rather than the run's whole condition list: a window that has slid past
    /// the chunk's day contributes nothing to that chunk's evaluation, so widening the scan for it
    /// would read columns no condition on that day reads. An active hash with no analysis fails
    /// closed inside [`ChunkProjection::derive`].
    pub fn projection(&self, active: &ActiveConditions) -> ChunkProjection {
        ChunkProjection::derive(active.iter().map(|hash| self.by_hash.get(hash)))
    }

    /// Count the conditions by class, and account for each event name what a projection over it
    /// would have to supply.
    ///
    /// Counted per unique hash and event name, not per pinned condition: the same condition shared
    /// by several cohorts is one piece of work, and counting it twice would overstate the
    /// projectable share.
    ///
    /// The event name is part of the key rather than the hash alone, because the two arrive as
    /// independent fields of the Django payload. Deduplicating on the hash would skip a repeated
    /// hash before it reached its second event name, and that event would then be accounted from
    /// its other conditions alone — projection-eligible on paper while carrying a condition that
    /// needs every column.
    pub fn census(&self, conditions: &[PinnedCondition]) -> ConditionCensus {
        let mut census = ConditionCensus::default();
        let mut seen: BTreeSet<(ConditionHash, &str)> = BTreeSet::new();
        for condition in conditions {
            if !seen.insert((condition.hash, condition.event_name.as_str())) {
                continue;
            }
            let event = census
                .per_event
                .entry(condition.event_name.clone())
                .or_default();
            let Some(analysis) = self.by_hash.get(&condition.hash) else {
                // Unreachable today: `resolve_conditions` drops any hash the frozen catalog has no
                // bytecode for, so every surviving condition has one. Kept because the alternative
                // to a label here is a condition that silently leaves no trace in the census.
                *census
                    .by_class
                    .entry(ConditionClass::Unanalyzable)
                    .or_default() += 1;
                *census
                    .unanalyzable_reasons
                    .entry(UnanalyzableLabel::missing_bytecode())
                    .or_default() += 1;
                event.unprojectable += 1;
                event.blockers.insert(MISSING_BYTECODE_REASON.to_owned());
                continue;
            };
            let class = ConditionClass::of(analysis);
            *census.by_class.entry(class).or_default() += 1;
            match class {
                ConditionClass::EventOnly => event.event_only += 1,
                ConditionClass::Projectable => event.projectable += 1,
                _ => event.unprojectable += 1,
            }
            if let Projection::FullColumns(reason) = &analysis.projection {
                let label = UnanalyzableLabel::of(reason);
                if class.is_unprojectable() {
                    event.blockers.insert(label.render());
                }
                if class == ConditionClass::Unanalyzable {
                    *census.unanalyzable_reasons.entry(label).or_default() += 1;
                }
            }
            if let Projection::Reads(paths) = &analysis.projection {
                event.reads.extend(paths.iter().map(ReadPath::render));
            }
        }
        census
    }
}

/// A reason label pair: the coarse reason, plus the opcode when one is what stopped the analysis.
///
/// Both halves are closed vocabularies — the reason by construction, the opcode because
/// `Operation` is a 57-variant enum — so the pair is safe as a metric dimension. The opcode is
/// carried because "unsupported_op" alone cannot tell one fixable compiler template apart from a
/// program nothing will ever narrow, which is the difference the census exists to report.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct UnanalyzableLabel {
    pub reason: &'static str,
    /// The opcode's variant name, from its `Debug` rendering. `Arc<str>` because the metric layer
    /// clones a label value per emission and the repo's convention is a refcount bump rather than
    /// an allocation.
    pub op: Option<Arc<str>>,
}

impl UnanalyzableLabel {
    fn of(reason: &FullColumnsReason) -> Self {
        Self {
            reason: reason.as_str(),
            op: reason.op().map(|op| Arc::from(format!("{op:?}").as_str())),
        }
    }

    fn missing_bytecode() -> Self {
        Self {
            reason: MISSING_BYTECODE_REASON,
            op: None,
        }
    }

    /// The label as one string, for the log line and the per-event blocker set.
    pub fn render(&self) -> String {
        match &self.op {
            Some(op) => format!("{}:{op}", self.reason),
            None => self.reason.to_owned(),
        }
    }
}

/// What the conditions on one event name would cost a projection over it.
///
/// The counts are per unique condition hash on that event name. `unprojectable` is the one that
/// decides: a scan selects columns for the whole event, so one unprojectable condition forces full
/// columns for every row of it.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct EventCensus {
    pub event_only: u64,
    pub projectable: u64,
    pub unprojectable: u64,
    /// The union of what the narrow conditions on this event name read, rendered dotted.
    pub reads: BTreeSet<String>,
    /// Why the unprojectable ones are, as rendered [`UnanalyzableLabel`]s.
    pub blockers: BTreeSet<String>,
}

impl EventCensus {
    /// Whether a projection over this event name is possible at all.
    pub const fn is_projection_eligible(&self) -> bool {
        self.unprojectable == 0
    }
}

/// The per-run shape report. Every collection is ordered, so two runs over the same catalog log the
/// same text and a census can be compared across replicas.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct ConditionCensus {
    pub by_class: BTreeMap<ConditionClass, u64>,
    pub unanalyzable_reasons: BTreeMap<UnanalyzableLabel, u64>,
    /// One entry per event name any pinned condition references.
    pub per_event: BTreeMap<String, EventCensus>,
}

impl ConditionCensus {
    pub fn total(&self) -> u64 {
        self.by_class.values().sum()
    }

    pub fn count(&self, class: ConditionClass) -> u64 {
        self.by_class.get(&class).copied().unwrap_or(0)
    }

    /// The share of *property-filtered* conditions a projection could narrow.
    ///
    /// Event-only conditions are excluded from both halves rather than counted as wins. They are
    /// the majority of conditions on a real catalog and a small minority of the rows scanned, so
    /// including them produces a high number that says nothing about the work a projection would
    /// save — which is the ranking error this census exists to avoid repeating. Zero when there is
    /// nothing to classify, so an empty run reports no misleading fraction.
    pub fn property_projectable_fraction(&self) -> f64 {
        let projectable = self.count(ConditionClass::Projectable);
        let denominator = projectable
            + self.count(ConditionClass::FullColumns)
            + self.count(ConditionClass::Unanalyzable);
        if denominator == 0 {
            return 0.0;
        }
        projectable as f64 / denominator as f64
    }

    /// The event names a projection could narrow, meaning every condition on them is narrow.
    pub fn projection_eligible_event_names(&self) -> Vec<&str> {
        self.per_event
            .iter()
            .filter(|(_, event)| event.is_projection_eligible())
            .map(|(name, _)| name.as_str())
            .collect()
    }

    /// The event names a projection could not narrow, each with why. This is the list to join
    /// against per-event row volume: an event here costs full columns however many of its
    /// conditions are narrow.
    pub fn blocked_event_names(&self) -> Vec<(&str, &BTreeSet<String>)> {
        self.per_event
            .iter()
            .filter(|(_, event)| !event.is_projection_eligible())
            .map(|(name, event)| (name.as_str(), &event.blockers))
            .collect()
    }

    /// The blocked event names and their reasons as one compact line, for the per-run log.
    ///
    /// Capped at [`MAX_RENDERED_BLOCKED_EVENTS`], with the remainder counted rather than named. The
    /// names are customer-defined and a catalog's event vocabulary has no ceiling, so an uncapped
    /// line is a log entry whose size the operator does not control. The head is what gets acted
    /// on; [`Self::render_all_blocked_events`] is where the elided names are.
    pub fn render_blocked_events(&self) -> String {
        let blocked = self.blocked_event_names();
        let mut rendered =
            render_event_sets(blocked.iter().take(MAX_RENDERED_BLOCKED_EVENTS).copied());
        if let Some(elided) = blocked.len().checked_sub(MAX_RENDERED_BLOCKED_EVENTS) {
            if elided > 0 {
                rendered.push_str(&format!(" (+{elided} more)"));
            }
        }
        rendered
    }

    /// Every blocked event name with its reasons, uncapped, for the per-run debug log.
    ///
    /// This is the list to join against per-event row volume, so a run whose blocked set outgrows
    /// the capped line still has its whole set somewhere. The debug level is what makes the
    /// uncapped size acceptable.
    pub fn render_all_blocked_events(&self) -> String {
        render_event_sets(self.blocked_event_names())
    }

    /// The read sets as one compact line per event name, for the per-run debug log. Events that
    /// read nothing are absent; a blocked one is named by [`Self::render_all_blocked_events`].
    pub fn render_reads(&self) -> String {
        render_event_sets(
            self.per_event
                .iter()
                .filter(|(_, event)| !event.reads.is_empty())
                .map(|(event_name, event)| (event_name.as_str(), &event.reads)),
        )
    }
}

/// `name=[value,value] name=[value]` — the shape both per-event log lines render in.
fn render_event_sets<'a>(
    events: impl IntoIterator<Item = (&'a str, &'a BTreeSet<String>)>,
) -> String {
    events
        .into_iter()
        .map(|(event_name, values)| {
            format!(
                "{event_name}=[{}]",
                values.iter().cloned().collect::<Vec<_>>().join(",")
            )
        })
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use cohort_core::filters::{CohortId, TeamFiltersBuilder, TeamId};
    use serde_json::json;

    use super::*;
    use crate::domain::{BlobSource, Lookback};

    fn hash(value: &str) -> ConditionHash {
        ConditionHash::parse(value).expect("test hashes are 16 ASCII bytes")
    }

    fn condition(hash_value: &str, event_name: &str) -> PinnedCondition {
        PinnedCondition {
            cohort_id: CohortId(1),
            hash: hash(hash_value),
            event_name: event_name.to_owned(),
            lookback: Lookback::SlidingDays(7),
        }
    }

    /// Build a frozen catalog holding one behavioral leaf per `(hash, event, bytecode)` triple.
    fn filters(leaves: &[(&str, &str, serde_json::Value)]) -> TeamFilters {
        let values = leaves
            .iter()
            .map(|(hash_value, event_name, bytecode)| {
                json!({
                    "type": "behavioral",
                    "value": "performed_event",
                    "key": event_name,
                    "conditionHash": hash_value,
                    "time_value": 7,
                    "time_interval": "day",
                    "bytecode": bytecode,
                })
            })
            .collect::<Vec<_>>();
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(2),
                &json!({ "properties": { "type": "AND", "values": values } }),
            )
            .expect("the test catalog parses");
        builder.freeze(chrono_tz::UTC)
    }

    fn event_equality(event_name: &str) -> serde_json::Value {
        json!(["_H", 1, 32, event_name, 32, "event", 1, 1, 11])
    }

    /// `properties.plan == 'paid' AND event == 'purchase'`, in the compiler's emission order.
    fn property_condition() -> serde_json::Value {
        json!([
            "_H",
            1,
            32,
            "paid",
            32,
            "plan",
            32,
            "properties",
            1,
            2,
            11,
            32,
            "purchase",
            32,
            "event",
            1,
            1,
            11,
            3,
            2
        ])
    }

    /// A bare `properties` root: understood, but every column is needed.
    fn bare_properties() -> serde_json::Value {
        json!(["_H", 1, 32, "properties", 1, 1, 35])
    }

    /// A `CALLABLE`, which introduces a frame the model refuses.
    fn unanalyzable() -> serde_json::Value {
        json!(["_H", 1, 52, "f", 0, 0, 0])
    }

    #[test]
    fn each_bytecode_shape_lands_in_its_class_with_its_read_set() {
        let conditions = [
            condition("eventonly0000000", "purchase"),
            condition("projectable00000", "signup"),
            condition("fullcolumns00000", "checkout"),
            condition("unanalyzable0000", "refund"),
        ];
        let catalog = filters(&[
            ("eventonly0000000", "purchase", event_equality("purchase")),
            ("projectable00000", "signup", property_condition()),
            ("fullcolumns00000", "checkout", bare_properties()),
            ("unanalyzable0000", "refund", unanalyzable()),
        ]);

        let census = ConditionAnalyses::build(&conditions, &catalog).census(&conditions);
        assert_eq!(census.count(ConditionClass::EventOnly), 1);
        assert_eq!(census.count(ConditionClass::Projectable), 1);
        assert_eq!(census.count(ConditionClass::FullColumns), 1);
        assert_eq!(census.count(ConditionClass::Unanalyzable), 1);
        assert_eq!(census.total(), 4);
        // One projectable against one bare-root and one refused: the event-only condition is not a
        // property filter and takes no part in the ratio.
        assert_eq!(census.property_projectable_fraction(), 1.0 / 3.0);
        assert_eq!(
            census.unanalyzable_reasons,
            BTreeMap::from([(
                UnanalyzableLabel {
                    reason: "unsupported_op",
                    op: Some(Arc::from("Callable")),
                },
                1
            )])
        );
        assert_eq!(
            census.projection_eligible_event_names(),
            ["purchase", "signup"]
        );
        assert_eq!(
            census.render_blocked_events(),
            "checkout=[bare_properties_root] refund=[unsupported_op:Callable]"
        );
        // The event-only condition is still a narrow read, so its `event` read is reported too.
        assert_eq!(
            census.render_reads(),
            "purchase=[event] signup=[event,properties.plan]"
        );
    }

    /// One narrow and one wide condition on the same event name. A scan selects columns for the
    /// whole event, so that event is not projection-eligible however narrow its other condition is.
    /// Counting conditions alone would report it as half projectable and overstate the win on
    /// exactly the busy events that carry several conditions.
    #[test]
    fn an_event_name_with_one_wide_condition_is_not_projection_eligible() {
        let conditions = [
            condition("narrow0000000000", "$pageview"),
            condition("wide000000000000", "$pageview"),
        ];
        let catalog = filters(&[
            ("narrow0000000000", "$pageview", property_condition()),
            ("wide000000000000", "$pageview", bare_properties()),
        ]);

        let census = ConditionAnalyses::build(&conditions, &catalog).census(&conditions);
        assert_eq!(census.count(ConditionClass::Projectable), 1);
        assert_eq!(census.count(ConditionClass::FullColumns), 1);
        let event = &census.per_event["$pageview"];
        assert_eq!(event.projectable, 1);
        assert_eq!(event.unprojectable, 1);
        assert!(!event.is_projection_eligible());
        assert_eq!(census.projection_eligible_event_names(), Vec::<&str>::new());
        assert_eq!(
            census.blocked_event_names(),
            [(
                "$pageview",
                &BTreeSet::from(["bare_properties_root".to_owned()])
            )]
        );
    }

    /// The opcode that stopped the analysis is carried alongside the coarse reason. Without it,
    /// every branch, frame, and heap write reads as one "unsupported_op" bucket, and the census
    /// cannot say whether the blocked conditions are one fixable compiler template or many.
    #[test]
    fn an_unsupported_opcode_is_reported_with_the_opcode() {
        let conditions = [
            condition("callable00000000", "a"),
            condition("incohort00000000", "b"),
        ];
        let catalog = filters(&[
            ("callable00000000", "a", unanalyzable()),
            // `IN_COHORT` reads membership state that is not in the globals dict at all.
            ("incohort00000000", "b", json!(["_H", 1, 29, 29, 27])),
        ]);

        let census = ConditionAnalyses::build(&conditions, &catalog).census(&conditions);
        assert_eq!(
            census.unanalyzable_reasons,
            BTreeMap::from([
                (
                    UnanalyzableLabel {
                        reason: "unsupported_op",
                        op: Some(Arc::from("Callable")),
                    },
                    1
                ),
                (
                    UnanalyzableLabel {
                        reason: "unsupported_op",
                        op: Some(Arc::from("InCohort")),
                    },
                    1
                ),
            ])
        );
        assert_eq!(
            census.render_blocked_events(),
            "a=[unsupported_op:Callable] b=[unsupported_op:InCohort]"
        );
    }

    /// A hash the frozen catalog carries no bytecode for never reached the analyzer, so it is
    /// counted under its own reason rather than blamed on the analysis.
    #[test]
    fn a_condition_without_bytecode_is_counted_as_missing_rather_than_analyzed() {
        let conditions = [condition("nobytecode000000", "purchase")];
        let census = ConditionAnalyses::build(&conditions, &filters(&[])).census(&conditions);
        assert_eq!(census.count(ConditionClass::Unanalyzable), 1);
        assert_eq!(
            census.unanalyzable_reasons,
            BTreeMap::from([(UnanalyzableLabel::missing_bytecode(), 1)])
        );
        assert!(!census.per_event["purchase"].is_projection_eligible());
    }

    /// One condition shared by several cohorts is one piece of work. Counting it per pinned entry
    /// would overstate the projectable share on exactly the catalogs where sharing is common.
    #[test]
    fn a_hash_shared_across_cohorts_is_counted_once() {
        let shared = "shared0000000000";
        let mut first = condition(shared, "purchase");
        first.cohort_id = CohortId(1);
        let mut second = condition(shared, "purchase");
        second.cohort_id = CohortId(2);
        let conditions = [first, second];
        let catalog = filters(&[(shared, "purchase", event_equality("purchase"))]);

        let census = ConditionAnalyses::build(&conditions, &catalog).census(&conditions);
        assert_eq!(census.total(), 1);
        assert_eq!(census.count(ConditionClass::EventOnly), 1);
        assert_eq!(census.per_event["purchase"].event_only, 1);
    }

    /// The same hash under two event names has to account against both. The hash and the event name
    /// are independent fields of the Django payload, so nothing structural pairs them; a census that
    /// skipped the repeat would leave the second event with no row, and an event whose only other
    /// conditions are narrow would then read as projection-eligible while carrying a wide one.
    #[test]
    fn a_hash_reused_under_two_event_names_accounts_against_both() {
        let shared = "shared0000000000";
        let conditions = [condition(shared, "purchase"), condition(shared, "signup")];
        let catalog = filters(&[(shared, "purchase", bare_properties())]);

        let census = ConditionAnalyses::build(&conditions, &catalog).census(&conditions);
        assert_eq!(
            census.blocked_event_names(),
            [
                (
                    "purchase",
                    &BTreeSet::from(["bare_properties_root".to_owned()])
                ),
                (
                    "signup",
                    &BTreeSet::from(["bare_properties_root".to_owned()])
                ),
            ]
        );
    }

    /// Past the cap the info line counts the rest instead of naming them, and the uncapped
    /// renderer still names every one. An event blocked only by a wide condition reads nothing, so
    /// it is absent from the read dump; without the uncapped list it would appear in no output at
    /// all, and the blocked set is the census's whole deliverable.
    #[test]
    fn blocked_events_past_the_cap_are_counted_in_the_info_line_and_named_in_full() {
        let over_cap = MAX_RENDERED_BLOCKED_EVENTS + 3;
        // Zero-padded so the rendered order matches the generated one.
        let hashes = (0..over_cap)
            .map(|index| format!("wide{index:012}"))
            .collect::<Vec<_>>();
        let names = (0..over_cap)
            .map(|index| format!("event_{index:03}"))
            .collect::<Vec<_>>();
        let conditions = hashes
            .iter()
            .zip(&names)
            .map(|(hash, name)| condition(hash, name))
            .collect::<Vec<_>>();
        let leaves = hashes
            .iter()
            .zip(&names)
            .map(|(hash, name)| (hash.as_str(), name.as_str(), bare_properties()))
            .collect::<Vec<_>>();
        let catalog = filters(&leaves);

        let census = ConditionAnalyses::build(&conditions, &catalog).census(&conditions);
        assert_eq!(census.blocked_event_names().len(), over_cap);

        let capped = census.render_blocked_events();
        assert!(capped.ends_with(" (+3 more)"), "{capped}");
        assert!(!capped.contains(&names[over_cap - 1]), "{capped}");

        let full = census.render_all_blocked_events();
        for name in &names {
            assert!(full.contains(name), "{name} is named nowhere");
        }
        assert!(!full.contains("more)"), "the uncapped line does not elide");
        // Nothing narrow was found, so the read dump cannot carry these names either.
        assert_eq!(census.render_reads(), "");
    }

    /// A chunk's projection is derived from the conditions active on its day, not from the run's
    /// whole list. A window that has slid past the day cannot affect its evaluation, so the wide
    /// read of a condition outside it must not cost that chunk its narrow scan.
    #[test]
    fn a_chunks_projection_ignores_conditions_that_are_not_active_on_it() {
        let conditions = [
            condition("narrow0000000000", "signup"),
            condition("wide000000000000", "checkout"),
        ];
        let catalog = filters(&[
            ("narrow0000000000", "signup", property_condition()),
            ("wide000000000000", "checkout", bare_properties()),
        ]);
        let analyses = ConditionAnalyses::build(&conditions, &catalog);

        let narrow_only = ActiveConditions::new([hash("narrow0000000000")]);
        let ChunkProjection::Projected(plan) = analyses.projection(&narrow_only) else {
            panic!("the narrow condition alone must project");
        };
        match &plan.properties {
            BlobSource::Keys(keys) => assert_eq!(keys.iter().collect::<Vec<_>>(), ["plan"]),
            other => panic!("expected key-filtered properties, got {other:?}"),
        }

        let both = ActiveConditions::new([hash("narrow0000000000"), hash("wide000000000000")]);
        assert_eq!(analyses.projection(&both), ChunkProjection::FullColumns);
    }

    /// An active hash the frozen catalog carried no bytecode for never reached the analyzer, so its
    /// reads are unknown and the chunk has to take every column.
    #[test]
    fn an_active_hash_without_an_analysis_projects_full_columns() {
        let conditions = [condition("nobytecode000000", "purchase")];
        let analyses = ConditionAnalyses::build(&conditions, &filters(&[]));
        let active = ActiveConditions::new([hash("nobytecode000000")]);
        assert_eq!(analyses.projection(&active), ChunkProjection::FullColumns);
    }

    #[test]
    fn a_run_with_no_conditions_reports_an_empty_census() {
        let census = ConditionAnalyses::default().census(&[]);
        assert_eq!(census, ConditionCensus::default());
        assert_eq!(census.total(), 0);
        assert_eq!(census.property_projectable_fraction(), 0.0);
        assert_eq!(census.render_reads(), "");
        assert_eq!(census.render_blocked_events(), "");
    }
}
