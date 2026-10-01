//! Domain layer: what each of a run's person conditions needs from a scanned row, decided once from
//! its bytecode. Depends on `person`, `person_relevance`, `projection`, and `cohort-core`.
//!
//! # Why a key check can stand in for the VM
//!
//! `GET_GLOBAL` is the VM's only path into the globals dict and it takes its path from literal
//! strings the compiler pushed, so the analyzer's read set is the whole surface a condition can
//! touch. When every one of those reads is `person.properties.<key>…` or `project.*`, a person whose
//! blob is a JSON object carrying none of those keys resolves every read to `null` — exactly as `{}`
//! does, because `GET_GLOBAL` pushes `Null` for a missing key under a present root. The program then
//! executes the identical instruction sequence, so its outcome on `{}` is its outcome on every such
//! blob, VM errors included.
//!
//! Three shapes stay on the VM. `person.id` and a bare `person.properties` vary per row. A native
//! that reads how a number was spelled, or bytecode the analyzer could not follow, leaves the read
//! set unproven. A root no person-scope globals dict carries (`event`, `properties`, `pdi`) raises
//! `UnknownGlobal` identically on every row and could be shortcut too; it is left to the VM because
//! proving that costs more than the case is worth.
//!
//! # Why the blob must be a JSON object
//!
//! A non-object blob is not "an object missing keys". An array errors where an object yields null
//! (`GET_GLOBAL` coerces the key to a number on an array), and a scalar or a literal `null` yields
//! null without carrying keys at all. Only the object case is answered here; the rest reach the VM.

use std::collections::{BTreeMap, BTreeSet};

use cohort_core::filters::TeamId;
use cohort_core::hogvm::analysis::{
    analyze_condition_within, AnalysisBudget, FullColumnsReason, GlobalRoot, Projection, ReadPath,
    UnanalyzableReason,
};
use cohort_core::hogvm::{
    classify_vm_error, person_scan_globals, CohortEvaluator, ConditionProgram, EvalOutcome,
    VmErrorClass,
};
use serde_json::{Map, Value};
use uuid::Uuid;

use super::person::EvaluatedConditions;
use super::person_relevance::{ConditionIndex, TruthVector};
use super::projection::ProjectedKeys;

/// How many worst-case conditions one person run's analysis may cost, as one budget its conditions
/// share. Mirrors the behavioral census: per-condition ceilings leave `conditions × ceiling`, and a
/// shared budget spent in hash order keeps the classification a pure function of the pinned payload,
/// so a run re-validated on another replica classifies identically.
const ANALYSIS_WORST_CASE_CONDITIONS: usize = 8;

/// What evaluating one condition against one row came to. Mirrors [`EvalOutcome`] minus the
/// unclonable error payload, so a cached verdict and a freshly evaluated one produce the same
/// per-row statistics.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConditionVerdict {
    Matched(bool),
    UnknownFunction,
    VmFailure(VmErrorClass),
}

impl From<EvalOutcome> for ConditionVerdict {
    fn from(outcome: EvalOutcome) -> Self {
        match outcome {
            EvalOutcome::Matched(matched) => Self::Matched(matched),
            EvalOutcome::UnknownFunction(_) => Self::UnknownFunction,
            EvalOutcome::VmError(error) => Self::VmFailure(classify_vm_error(&error)),
        }
    }
}

/// Why a condition has to run on every row.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum AlwaysEvaluateReason {
    /// Reads `person.id`, which differs on every row.
    ReadsPersonId,
    /// Hands a whole `person` or `properties` object somewhere, so which keys decide it is settled
    /// at run time.
    WholeObject,
    /// Calls a native that reads how a number was spelled rather than what it is.
    RepresentationSensitive,
    /// Reads a root the person-scope globals do not carry, so the read set says nothing about the
    /// blob.
    ForeignRoot,
    /// The run's shared analysis budget ran out before this condition. The one reason that says to
    /// raise [`ANALYSIS_WORST_CASE_CONDITIONS`] rather than to accept the wide answer, so it is
    /// named apart from the rest.
    BudgetSpent,
    /// The analyzer lost track of the program.
    Unanalyzable,
}

impl AlwaysEvaluateReason {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ReadsPersonId => "reads_person_id",
            Self::WholeObject => "whole_object",
            Self::RepresentationSensitive => "representation_sensitive",
            Self::ForeignRoot => "foreign_root",
            Self::BudgetSpent => "budget_spent",
            Self::Unanalyzable => "unanalyzable",
        }
    }
}

/// What one condition's truth depends on.
#[derive(Debug, Clone, PartialEq, Eq)]
enum RowDependence {
    /// Every read is `person.properties.<key>…` or `project.*`, so a JSON object carrying none of
    /// `keys` reaches `vacuous` without the VM.
    KeyDecidable {
        keys: BTreeSet<String>,
        vacuous: ConditionVerdict,
    },
    AlwaysEvaluate(AlwaysEvaluateReason),
}

/// One [`RowDependence`] per surviving condition, in [`EvaluatedConditions`] order.
#[derive(Debug)]
pub struct PersonConditionAnalyses(Vec<RowDependence>);

impl PersonConditionAnalyses {
    /// Classify every surviving condition and, for the key-decidable ones, record the outcome it
    /// reaches on an empty property bag.
    ///
    /// The budget is shared across the run's conditions and spent in their (hash) order, so the
    /// classification stays a pure function of the pinned payload.
    pub fn build(team_id: TeamId, conditions: &EvaluatedConditions) -> Self {
        let mut budget = AnalysisBudget::for_conditions(ANALYSIS_WORST_CASE_CONDITIONS);
        let mut evaluator = CohortEvaluator::new();
        evaluator.set_globals(person_scan_globals(
            team_id,
            // No key-decidable condition reads `person.id`, so which id stands here cannot reach a
            // recorded outcome.
            Uuid::nil(),
            Value::Object(Map::new()),
        ));

        let dependences = conditions
            .iter()
            .map(|(_, program)| {
                let analysis = analyze_condition_within(program.tokens(), &mut budget);
                match decidable_keys(&analysis.projection) {
                    Ok(keys) => RowDependence::KeyDecidable {
                        keys,
                        vacuous: vacuous_outcome(&mut evaluator, program),
                    },
                    Err(reason) => RowDependence::AlwaysEvaluate(reason),
                }
            })
            .collect();
        Self(dependences)
    }

    /// The outcome `index` reaches on `object` without the VM, or `None` when it needs one.
    pub fn shortcut(
        &self,
        index: ConditionIndex,
        object: Option<&Map<String, Value>>,
    ) -> Option<ConditionVerdict> {
        let RowDependence::KeyDecidable { keys, vacuous } = self.0.get(index.get())? else {
            return None;
        };
        let object = object?;
        keys.iter()
            .all(|key| !object.contains_key(key))
            .then_some(*vacuous)
    }

    /// Every key the run's conditions read, when *all* of them are key-decidable — the precondition
    /// for asking ClickHouse to drop key-less rows. `None` when some condition needs the VM, or when
    /// the union is empty (which [`ProjectedKeys`] cannot express, and which no filter can narrow).
    pub fn keys_if_every_condition_is_key_decidable(&self) -> Option<ProjectedKeys> {
        let mut union = BTreeSet::new();
        for dependence in &self.0 {
            match dependence {
                RowDependence::KeyDecidable { keys, .. } => union.extend(keys.iter().cloned()),
                RowDependence::AlwaysEvaluate(_) => return None,
            }
        }
        ProjectedKeys::new(union)
    }

    /// The truth vector every key-less object blob produces, for the scan filter's precondition.
    ///
    /// `None` when some condition needs the VM, so no such vector exists — and also when some
    /// condition's vacuous verdict is a VM failure rather than an answer. That second case matters
    /// for the same reason the fold refuses to prune an incompletely evaluated row: a condition the
    /// VM never answered is left out of `evaluated`, so the consumer keeps the bit it already
    /// stored for that leaf and composes something this vector does not describe. A run holding one
    /// cannot hand its key test to ClickHouse at all.
    pub fn vacuous_truths(&self) -> Option<TruthVector> {
        let mut truths = TruthVector::ABSENT;
        for (position, dependence) in self.0.iter().enumerate() {
            let RowDependence::KeyDecidable { vacuous, .. } = dependence else {
                return None;
            };
            let ConditionVerdict::Matched(matched) = vacuous else {
                return None;
            };
            if *matched {
                truths.set(
                    ConditionIndex::new(position).expect(
                        "one entry per condition, and validation caps those at the wire cap",
                    ),
                );
            }
        }
        Some(truths)
    }

    /// Counts per class for the per-run log line.
    pub fn census(&self) -> PersonAnalysisCensus {
        let mut census = PersonAnalysisCensus::default();
        for dependence in &self.0 {
            match dependence {
                RowDependence::KeyDecidable { .. } => census.key_decidable += 1,
                RowDependence::AlwaysEvaluate(reason) => {
                    *census.always_evaluate.entry(*reason).or_default() += 1;
                }
            }
        }
        census
    }
}

/// How a run's conditions classified, rendered into the `person run analyzed` line.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct PersonAnalysisCensus {
    pub key_decidable: u32,
    pub always_evaluate: BTreeMap<AlwaysEvaluateReason, u32>,
}

impl PersonAnalysisCensus {
    /// `reason=count` pairs, ascending, for the log line.
    pub fn render_always_evaluate(&self) -> String {
        self.always_evaluate
            .iter()
            .map(|(reason, count)| format!("{}={count}", reason.as_str()))
            .collect::<Vec<_>>()
            .join(",")
    }
}

/// The top-level `person.properties` keys a projection resolves to, or why it cannot.
fn decidable_keys(projection: &Projection) -> Result<BTreeSet<String>, AlwaysEvaluateReason> {
    let paths = match projection {
        Projection::Reads(paths) => paths,
        Projection::FullColumns(reason) => {
            return Err(match reason {
                FullColumnsReason::BarePropertiesRoot | FullColumnsReason::BarePersonRoot => {
                    AlwaysEvaluateReason::WholeObject
                }
                FullColumnsReason::RepresentationSensitiveCall => {
                    AlwaysEvaluateReason::RepresentationSensitive
                }
                FullColumnsReason::Unanalyzable(
                    UnanalyzableReason::IterationBudget | UnanalyzableReason::StateBudget,
                ) => AlwaysEvaluateReason::BudgetSpent,
                FullColumnsReason::Unanalyzable(_) => AlwaysEvaluateReason::Unanalyzable,
            })
        }
    };
    let mut keys = BTreeSet::new();
    for path in paths {
        keys.extend(decidable_key(path)?);
    }
    Ok(keys)
}

/// The key one read path resolves to: `Some` for `person.properties.<key>…`, `None` for a read whose
/// value is the same on every row of the run.
fn decidable_key(path: &ReadPath) -> Result<Option<String>, AlwaysEvaluateReason> {
    match path.root {
        // `project.id` is the run's own team, identical on every row.
        GlobalRoot::Project => Ok(None),
        GlobalRoot::Person => {
            let mut segments = path.segments.iter().map(String::as_str);
            match (segments.next(), segments.next()) {
                (Some("properties"), Some(key)) => Ok(Some(key.to_owned())),
                // A bare `person.properties` hands the whole bag somewhere.
                (Some("properties"), None) => Err(AlwaysEvaluateReason::WholeObject),
                (Some("id"), _) => Err(AlwaysEvaluateReason::ReadsPersonId),
                // Any other key under `person` resolves to null on every row, but telling that
                // apart from a shape this mapping has not met is not worth the risk.
                _ => Err(AlwaysEvaluateReason::ForeignRoot),
            }
        }
        _ => Err(AlwaysEvaluateReason::ForeignRoot),
    }
}

fn vacuous_outcome(
    evaluator: &mut CohortEvaluator,
    program: &ConditionProgram,
) -> ConditionVerdict {
    evaluator.evaluate_detailed(program).into()
}

#[cfg(test)]
mod tests {
    use cohort_core::hogvm::analysis::analyze_condition;
    use serde_json::json;

    use super::*;

    /// Bytecode as the cohort compiler emits it, taken from `generate_cohort_filter_bytecode` rather
    /// than hand-written, so the classification is tested against the shapes production stores.
    fn compiled(operator: &str) -> Value {
        match operator {
            "is_set" => json!([
                "_H",
                1,
                31,
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                12
            ]),
            "not_icontains" => json!([
                "_H",
                1,
                32,
                "%@posthog.com%",
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                2,
                "toString",
                1,
                20
            ]),
            "exact" => json!([
                "_H",
                1,
                32,
                "a@b.com",
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                11
            ]),
            "in_list" => json!([
                "_H",
                1,
                32,
                "paid",
                32,
                "free",
                44,
                2,
                32,
                "plan",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                21
            ]),
            "not_regex" => json!([
                "_H",
                1,
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                2,
                "toString",
                1,
                32,
                "^a.*",
                2,
                "match",
                2,
                5,
                47,
                3,
                35,
                33,
                1
            ]),
            // `gt`, lowered through `null_safe_comparisons` into an `if`.
            "gt" => json!([
                "_H",
                1,
                32,
                "age",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                2,
                "isNull",
                1,
                33,
                21,
                2,
                "isNull",
                1,
                4,
                2,
                40,
                3,
                30,
                39,
                11,
                33,
                21,
                32,
                "age",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                13
            ]),
            "person_id" => json!(["_H", 1, 32, "x", 32, "id", 32, "person", 1, 2, 11]),
            "bare_person" => json!(["_H", 1, 32, "person", 1, 1, 2, "jsonStringify", 1, 11]),
            "typeof" => json!([
                "_H",
                1,
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                2,
                "typeof",
                1,
                32,
                "string",
                11
            ]),
            "project_only" => json!(["_H", 1, 32, "id", 32, "project", 1, 2, 33, 2, 11]),
            // `person.properties.company.size` — a read two keys deep under `properties`.
            "nested" => json!([
                "_H",
                1,
                32,
                "big",
                32,
                "size",
                32,
                "company",
                32,
                "properties",
                32,
                "person",
                1,
                4,
                11
            ]),
            other => panic!("no fixture for {other}"),
        }
    }

    fn dependence(operator: &str) -> RowDependence {
        let bytecode = compiled(operator);
        let tokens = bytecode.as_array().expect("fixtures are arrays");
        let analysis = analyze_condition(tokens);
        match decidable_keys(&analysis.projection) {
            Ok(keys) => {
                let program = ConditionProgram::from_stored(tokens).expect("fixtures load");
                let mut evaluator = CohortEvaluator::new();
                evaluator.set_globals(person_scan_globals(
                    TeamId(2),
                    Uuid::nil(),
                    Value::Object(Map::new()),
                ));
                RowDependence::KeyDecidable {
                    keys,
                    vacuous: vacuous_outcome(&mut evaluator, &program),
                }
            }
            Err(reason) => RowDependence::AlwaysEvaluate(reason),
        }
    }

    fn key_decidable(operator: &str) -> (BTreeSet<String>, ConditionVerdict) {
        match dependence(operator) {
            RowDependence::KeyDecidable { keys, vacuous } => (keys, vacuous),
            other => panic!("{operator} classified as {other:?}"),
        }
    }

    fn keys(names: &[&str]) -> BTreeSet<String> {
        names.iter().map(|name| (*name).to_owned()).collect()
    }

    /// The vacuous truths are what the whole optimization turns on: `is_set` is false on a person
    /// with no email and `not_icontains` is *true*, because the VM prints a missing property as the
    /// string "null" before the NOT ILIKE. Reading either the wrong way would prune members.
    #[test]
    fn the_compiled_person_operators_are_key_decidable_with_the_vm_s_own_vacuous_truth() {
        assert_eq!(
            key_decidable("is_set"),
            (keys(&["email"]), ConditionVerdict::Matched(false))
        );
        assert_eq!(
            key_decidable("not_icontains"),
            (keys(&["email"]), ConditionVerdict::Matched(true))
        );
        assert_eq!(
            key_decidable("exact"),
            (keys(&["email"]), ConditionVerdict::Matched(false))
        );
        assert_eq!(
            key_decidable("in_list"),
            (keys(&["plan"]), ConditionVerdict::Matched(false))
        );
        assert_eq!(
            key_decidable("not_regex"),
            (keys(&["email"]), ConditionVerdict::Matched(true))
        );
        assert_eq!(
            key_decidable("gt"),
            (keys(&["age"]), ConditionVerdict::Matched(false))
        );
        // A condition reading only the team reads nothing per row, so it is decidable with no keys.
        assert_eq!(
            key_decidable("project_only"),
            (BTreeSet::new(), ConditionVerdict::Matched(true))
        );
        // A nested read claims its *top-level* key, because that is the only thing
        // `JSONExtractKeys` can see. Claiming `size` instead would render a filter that drops every
        // person carrying `company` while believing it filtered on `size`.
        assert_eq!(
            key_decidable("nested"),
            (keys(&["company"]), ConditionVerdict::Matched(false))
        );
    }

    #[test]
    fn row_varying_and_unprovable_reads_stay_on_the_vm() {
        assert_eq!(
            dependence("person_id"),
            RowDependence::AlwaysEvaluate(AlwaysEvaluateReason::ReadsPersonId)
        );
        assert_eq!(
            dependence("bare_person"),
            RowDependence::AlwaysEvaluate(AlwaysEvaluateReason::WholeObject)
        );
        assert_eq!(
            dependence("typeof"),
            RowDependence::AlwaysEvaluate(AlwaysEvaluateReason::RepresentationSensitive)
        );
    }

    /// The shortcut must fire only on an object missing *every* key, and never on a non-object: an
    /// array makes `GET_GLOBAL` coerce a string key to a number and error where `{}` yields null.
    #[test]
    fn the_shortcut_fires_only_on_an_object_missing_every_key() {
        let analyses = PersonConditionAnalyses(vec![RowDependence::KeyDecidable {
            keys: keys(&["email", "plan"]),
            vacuous: ConditionVerdict::Matched(true),
        }]);
        let index = ConditionIndex::new(0).unwrap();
        let object = |text: &str| match serde_json::from_str::<Value>(text).unwrap() {
            Value::Object(map) => Some(map),
            _ => None,
        };

        for missing in [
            r#"{}"#,
            r#"{"other":1}"#,
            r#"{"Email":"x"}"#,
            r#"{"a":{"email":1}}"#,
        ] {
            assert_eq!(
                analyses.shortcut(index, object(missing).as_ref()),
                Some(ConditionVerdict::Matched(true)),
                "{missing} carries none of the keys"
            );
        }
        for present in [
            r#"{"email":null}"#,
            r#"{"plan":"paid"}"#,
            r#"{"email":"a"}"#,
        ] {
            assert_eq!(
                analyses.shortcut(index, object(present).as_ref()),
                None,
                "{present} carries a key, so the VM decides it"
            );
        }
        assert_eq!(analyses.shortcut(index, None), None, "a non-object blob");
    }

    #[test]
    fn a_condition_needing_the_vm_withdraws_the_scan_filter_and_the_vacuous_vector() {
        let mixed = PersonConditionAnalyses(vec![
            RowDependence::KeyDecidable {
                keys: keys(&["email"]),
                vacuous: ConditionVerdict::Matched(true),
            },
            RowDependence::AlwaysEvaluate(AlwaysEvaluateReason::ReadsPersonId),
        ]);
        assert_eq!(mixed.keys_if_every_condition_is_key_decidable(), None);
        assert_eq!(mixed.vacuous_truths(), None);

        let decidable = PersonConditionAnalyses(vec![
            RowDependence::KeyDecidable {
                keys: keys(&["email"]),
                vacuous: ConditionVerdict::Matched(false),
            },
            RowDependence::KeyDecidable {
                keys: keys(&["plan"]),
                vacuous: ConditionVerdict::Matched(true),
            },
        ]);
        let scan_keys = decidable
            .keys_if_every_condition_is_key_decidable()
            .expect("both conditions are key-decidable");
        assert_eq!(scan_keys.iter().collect::<Vec<_>>(), ["email", "plan"]);

        let truths = decidable.vacuous_truths().expect("both are key-decidable");
        assert!(!truths.get(ConditionIndex::new(0).unwrap()));
        assert!(truths.get(ConditionIndex::new(1).unwrap()));
    }

    /// An empty key union cannot be expressed as a scan filter, so the run scans wide and prunes
    /// per row instead of rendering `hasAny(keys, [])`, which drops every object.
    #[test]
    fn a_condition_reading_no_keys_renders_no_scan_filter() {
        let analyses = PersonConditionAnalyses(vec![RowDependence::KeyDecidable {
            keys: BTreeSet::new(),
            vacuous: ConditionVerdict::Matched(true),
        }]);
        assert_eq!(analyses.keys_if_every_condition_is_key_decidable(), None);
    }

    /// The exactness claim, run through the real VM: for a key-decidable condition, any object blob
    /// lacking its keys evaluates to the cached outcome, and a blob carrying one is sent to the VM.
    #[test]
    fn the_cached_vacuous_outcome_matches_the_vm_on_every_key_less_object() {
        for operator in [
            "is_set",
            "not_icontains",
            "exact",
            "in_list",
            "not_regex",
            "gt",
        ] {
            let bytecode = compiled(operator);
            let tokens = bytecode.as_array().unwrap();
            let program = ConditionProgram::from_stored(tokens).unwrap();
            let (keys, vacuous) = key_decidable(operator);

            for blob in [
                json!({}),
                json!({ "unrelated": 1 }),
                json!({ "Email": "a@b.com", "PLAN": "paid", "AGE": 99 }),
                json!({ "nested": { "email": "a@b.com" } }),
                json!({ "emai": "a@b.com", "emails": ["a@b.com"] }),
            ] {
                let map = blob.as_object().unwrap();
                assert!(
                    keys.iter().all(|key| !map.contains_key(key)),
                    "{blob} was meant to carry none of {keys:?}"
                );
                let mut evaluator = CohortEvaluator::new();
                evaluator.set_globals(person_scan_globals(
                    TeamId(2),
                    Uuid::from_u128(7),
                    blob.clone(),
                ));
                assert_eq!(
                    vacuous_outcome(&mut evaluator, &program),
                    vacuous,
                    "{operator} on {blob} diverged from its cached vacuous outcome"
                );
            }
        }
    }
}
