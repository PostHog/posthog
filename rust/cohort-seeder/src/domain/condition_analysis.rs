//! Domain layer: the static analysis of a run's pinned conditions, and the census over it.
//! Depends on `condition`, `ids`, and `cohort-core`.
//!
//! The analysis runs once per run, at validation time, over the pinned payload alone. Nothing in
//! the scan path consumes it yet: it is published as counters and one log line per run, so the
//! shape of real catalogs is known before anything is built on it.
//!
//! Being a pure function of the pinned payload is what makes it safe to run per run rather than per
//! chunk: a re-validated run classifies identically, so a chunk retried on another replica cannot
//! disagree with the first attempt.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::Arc;

use cohort_core::filters::TeamFilters;
use cohort_core::hogvm::analysis::{
    analyze_condition, ConditionAnalysis, EvaluationClass, Projection, ReadPath,
};

use super::condition::PinnedCondition;
use super::ids::ConditionHash;

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

    fn of(analysis: &ConditionAnalysis) -> Self {
        match (&analysis.evaluation, &analysis.projection) {
            (EvaluationClass::EventOnly { .. }, _) => Self::EventOnly,
            (EvaluationClass::General, Projection::Reads(_)) => Self::Projectable,
            (EvaluationClass::General, Projection::FullColumns(reason)) => match reason {
                cohort_core::hogvm::analysis::FullColumnsReason::Unanalyzable(_) => {
                    Self::Unanalyzable
                }
                _ => Self::FullColumns,
            },
        }
    }
}

/// The label for a pinned condition whose hash the frozen catalog has no bytecode for. Not an
/// analysis outcome: the condition never reached the analyzer.
pub const MISSING_BYTECODE_REASON: &str = "missing_bytecode";

/// One analysis per unique pinned condition hash.
///
/// Person runs are deliberately absent. Their conditions read the small person-scope globals rather
/// than the event globals this analysis models, so classifying them here would report against the
/// wrong vocabulary.
#[derive(Debug, Default)]
pub struct ConditionAnalyses {
    by_hash: HashMap<ConditionHash, Arc<ConditionAnalysis>>,
}

impl ConditionAnalyses {
    /// Analyze every unique hash among `conditions` whose bytecode the frozen catalog carries.
    pub fn build(conditions: &[PinnedCondition], filters: &TeamFilters) -> Self {
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
                Arc::new(analyze_condition(bytecode.as_slice())),
            );
        }
        Self { by_hash }
    }

    pub fn get(&self, hash: ConditionHash) -> Option<&Arc<ConditionAnalysis>> {
        self.by_hash.get(&hash)
    }

    /// Count the conditions by class and collect what the projectable ones read, per event name.
    ///
    /// Counted per unique hash, not per pinned condition: the same condition shared by several
    /// cohorts is one piece of work, and counting it twice would overstate the projectable share.
    pub fn census(&self, conditions: &[PinnedCondition]) -> ConditionCensus {
        let mut census = ConditionCensus::default();
        let mut seen = BTreeSet::new();
        for condition in conditions {
            if !seen.insert(condition.hash) {
                continue;
            }
            let Some(analysis) = self.by_hash.get(&condition.hash) else {
                *census
                    .by_class
                    .entry(ConditionClass::Unanalyzable)
                    .or_default() += 1;
                *census
                    .unanalyzable_reasons
                    .entry(MISSING_BYTECODE_REASON)
                    .or_default() += 1;
                continue;
            };
            let class = ConditionClass::of(analysis);
            *census.by_class.entry(class).or_default() += 1;
            if let Projection::FullColumns(reason) = &analysis.projection {
                if class == ConditionClass::Unanalyzable {
                    *census
                        .unanalyzable_reasons
                        .entry(reason.as_str())
                        .or_default() += 1;
                }
            }
            if let Projection::Reads(paths) = &analysis.projection {
                census
                    .reads_by_event_name
                    .entry(condition.event_name.clone())
                    .or_default()
                    .extend(paths.iter().map(ReadPath::render));
            }
        }
        census
    }
}

/// The per-run shape report. Every collection is ordered, so two runs over the same catalog log the
/// same text and a census can be compared across replicas.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct ConditionCensus {
    pub by_class: BTreeMap<ConditionClass, u64>,
    /// Keyed by [`cohort_core::hogvm::analysis::UnanalyzableReason::as_str`], plus
    /// [`MISSING_BYTECODE_REASON`].
    pub unanalyzable_reasons: BTreeMap<&'static str, u64>,
    /// The union of what the projectable conditions on each event name read, rendered dotted.
    pub reads_by_event_name: BTreeMap<String, BTreeSet<String>>,
}

impl ConditionCensus {
    pub fn total(&self) -> u64 {
        self.by_class.values().sum()
    }

    pub fn count(&self, class: ConditionClass) -> u64 {
        self.by_class.get(&class).copied().unwrap_or(0)
    }

    /// The share of conditions a later projection pass could narrow. Zero when there is nothing to
    /// classify, so an empty run reports no misleading fraction.
    pub fn projectable_fraction(&self) -> f64 {
        let total = self.total();
        if total == 0 {
            return 0.0;
        }
        let narrow =
            self.count(ConditionClass::EventOnly) + self.count(ConditionClass::Projectable);
        narrow as f64 / total as f64
    }

    /// The read sets as one compact line per event name, for the per-run log.
    pub fn render_reads(&self) -> String {
        self.reads_by_event_name
            .iter()
            .map(|(event_name, paths)| {
                format!(
                    "{event_name}=[{}]",
                    paths.iter().cloned().collect::<Vec<_>>().join(",")
                )
            })
            .collect::<Vec<_>>()
            .join(" ")
    }
}

#[cfg(test)]
mod tests {
    use cohort_core::filters::{CohortId, TeamFiltersBuilder, TeamId};
    use serde_json::json;

    use super::*;
    use crate::domain::Lookback;

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
            // A bare `properties` root: understood, but every column is needed.
            (
                "fullcolumns00000",
                "checkout",
                json!(["_H", 1, 32, "properties", 1, 1, 35]),
            ),
            // A branch, which the linear model refuses.
            (
                "unanalyzable0000",
                "refund",
                json!(["_H", 1, 29, 40, 2, 30]),
            ),
        ]);

        let census = ConditionAnalyses::build(&conditions, &catalog).census(&conditions);
        assert_eq!(census.count(ConditionClass::EventOnly), 1);
        assert_eq!(census.count(ConditionClass::Projectable), 1);
        assert_eq!(census.count(ConditionClass::FullColumns), 1);
        assert_eq!(census.count(ConditionClass::Unanalyzable), 1);
        assert_eq!(census.total(), 4);
        assert_eq!(census.projectable_fraction(), 0.5);
        assert_eq!(
            census.unanalyzable_reasons,
            BTreeMap::from([("unsupported_op", 1)])
        );
        // The event-only condition is still a narrow read, so its `event` read is reported too.
        // The two conditions that fell back to every column contribute nothing.
        assert_eq!(
            census.render_reads(),
            "purchase=[event] signup=[event,properties.plan]"
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
            BTreeMap::from([(MISSING_BYTECODE_REASON, 1)])
        );
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
    }

    #[test]
    fn a_run_with_no_conditions_reports_an_empty_census() {
        let census = ConditionAnalyses::default().census(&[]);
        assert_eq!(census, ConditionCensus::default());
        assert_eq!(census.total(), 0);
        assert_eq!(census.projectable_fraction(), 0.0);
        assert_eq!(census.render_reads(), "");
    }
}
