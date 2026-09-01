//! Domain layer: what a chunk's scan has to select, derived from the static read sets of the
//! conditions active on it. Depends on `condition_analysis`'s inputs (`cohort-core`) only.
//!
//! A scan selects columns for a whole chunk, so this is a union: every active condition contributes
//! its demands and the widest one wins. That granularity is why one condition reading a whole
//! `properties` object costs the chunk its narrow scan, however narrow its siblings are.
//!
//! # Fail closed
//!
//! The one failure this module must not have is claiming a column the conditions turn out to need.
//! A row scanned without it evaluates against an empty value and silently drops membership, where a
//! column selected needlessly only costs bytes. So every arm that is not certain widens:
//! [`Projection::FullColumns`], a hash with no analysis, a bare object root, and a path shape this
//! mapping does not recognize all end in the wide answer.
//!
//! # Why the always-kept columns are absent from the types
//!
//! `event`, `timestamp`, `distinct_id`, and `person_id` cannot be rendered empty: the fold reads the
//! timestamp to place the row in its day, the accumulator keys on the person, and the event name
//! selects which conditions run. Leaving them out of [`ColumnPlan`] means no caller can ask for that.

use std::collections::BTreeSet;

use cohort_core::hogvm::analysis::{ConditionAnalysis, GlobalRoot, Projection, ReadPath};

/// What one chunk's scan must select.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ChunkProjection {
    /// Every column, which is what the seeder selected before this existed. The fail-closed arm.
    FullColumns,
    Projected(ColumnPlan),
}

/// The four columns a projection can narrow. The always-kept ones are deliberately absent.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ColumnPlan {
    pub uuid: ScalarColumn,
    pub elements_chain: ScalarColumn,
    pub properties: BlobSource,
    pub person_properties: BlobSource,
}

/// A column that is either selected or rendered as an empty literal. The row decoder lifts `""` to
/// `None`, and the globals builder reads `None` as an absent value without parsing it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScalarColumn {
    Keep,
    Empty,
}

/// How much of a JSON blob column the chunk needs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BlobSource {
    /// The whole column, because some condition reads the object itself rather than named keys.
    Full,
    /// Nothing: no active condition reads under this root.
    Empty,
    Keys(ProjectedKeys),
}

/// A non-empty set of top-level keys, in a stable order so a rendered scan is reproducible.
///
/// Non-empty by construction: an empty key set would render `{}`, which [`BlobSource::Empty`]
/// already expresses more cheaply, and having two spellings of it would let a renderer choose.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProjectedKeys(BTreeSet<String>);

impl ProjectedKeys {
    /// `None` for an empty set, which [`BlobSource::Empty`] expresses instead.
    pub fn new(keys: BTreeSet<String>) -> Option<Self> {
        (!keys.is_empty()).then_some(Self(keys))
    }

    pub fn iter(&self) -> impl ExactSizeIterator<Item = &str> {
        self.0.iter().map(String::as_str)
    }

    /// How many keys the rebuild keeps, always at least one. Named `count` rather than `len`
    /// because the pair `len`/`is_empty` would advertise an emptiness this type cannot have — see
    /// [`ProjectedKeys::new`].
    pub fn count(&self) -> usize {
        self.0.len()
    }
}

impl ColumnPlan {
    /// Every narrowable column selected whole — what the seeder scanned before this existed.
    ///
    /// [`ChunkProjection::FullColumns`] renders through this rather than through a second SQL
    /// literal, so "the wide arm is byte-identical to the old scan" is a property one renderer and
    /// its frozen tests prove, not a claim two strings have to keep agreeing on.
    pub const fn full() -> Self {
        Self {
            uuid: ScalarColumn::Keep,
            elements_chain: ScalarColumn::Keep,
            properties: BlobSource::Full,
            person_properties: BlobSource::Full,
        }
    }
}

impl ChunkProjection {
    /// Derive the union projection from one analysis per active condition, `None` where the frozen
    /// catalog carried no bytecode for that condition's hash.
    ///
    /// Pure and deterministic over the pinned payload, so a chunk retried on another replica — or
    /// scanned twice by the shadow compare — derives the identical projection.
    pub fn derive<'a>(analyses: impl IntoIterator<Item = Option<&'a ConditionAnalysis>>) -> Self {
        let mut demand = Demand::default();
        for analysis in analyses {
            // A condition that never reached the analyzer is a condition whose reads are unknown.
            let Some(analysis) = analysis else {
                return Self::FullColumns;
            };
            match &analysis.projection {
                Projection::FullColumns(_) => return Self::FullColumns,
                Projection::Reads(paths) => {
                    for path in paths {
                        demand.add(path);
                    }
                }
            }
        }
        Self::Projected(demand.into_plan())
    }

    /// The label this chunk's scan is metered under.
    pub const fn outcome(&self) -> &'static str {
        match self {
            Self::FullColumns => "full_columns",
            Self::Projected(_) => "projected",
        }
    }
}

/// The accumulating union, before it is frozen into a [`ColumnPlan`]. Separate from the plan so the
/// plan has no half-built state: a `BlobDemand::Keys` that is still empty is representable here and
/// not there.
#[derive(Debug, Default)]
struct Demand {
    uuid: bool,
    elements_chain: bool,
    properties: BlobDemand,
    person_properties: BlobDemand,
}

/// How much of a blob the conditions seen so far need. Ordered by width: `Whole` absorbs `Keys`,
/// which absorbs `Nothing`.
#[derive(Debug, Default)]
enum BlobDemand {
    #[default]
    Nothing,
    Keys(BTreeSet<String>),
    Whole,
}

impl BlobDemand {
    fn widen_to_whole(&mut self) {
        *self = Self::Whole;
    }

    fn add_key(&mut self, key: &str) {
        match self {
            Self::Whole => {}
            Self::Nothing => *self = Self::Keys(BTreeSet::from([key.to_owned()])),
            Self::Keys(keys) => {
                keys.insert(key.to_owned());
            }
        }
    }

    fn freeze(self) -> BlobSource {
        match self {
            Self::Whole => BlobSource::Full,
            Self::Nothing => BlobSource::Empty,
            Self::Keys(keys) => {
                ProjectedKeys::new(keys).map_or(BlobSource::Empty, BlobSource::Keys)
            }
        }
    }
}

impl Demand {
    /// Record what one read path needs. Exhaustive over [`GlobalRoot`], so a root added to the
    /// globals has to decide here rather than fall into a default that might be too narrow.
    fn add(&mut self, path: &ReadPath) {
        match path.root {
            GlobalRoot::Uuid => self.uuid = true,
            // The analyzer records `properties.$elements_chain` as its own path whenever a program
            // reads `elements_chain`, so the fallback the globals builder applies is already
            // covered by the `Properties` arm. Claiming it again here would say the same thing
            // twice.
            GlobalRoot::ElementsChain => self.elements_chain = true,
            GlobalRoot::Properties => match path.segments.first() {
                // A nested path needs its root key's raw value, which carries the whole subtree.
                Some(key) => self.properties.add_key(key),
                // The analyzer reports a bare `properties` as a full-columns reason rather than a
                // read, so this is unreachable; widening keeps it harmless if that ever changes.
                None => self.properties.widen_to_whole(),
            },
            GlobalRoot::Person => self.add_person(&path.segments),
            GlobalRoot::Pdi => match path.segments.first().map(String::as_str) {
                Some("distinct_id" | "person_id") => {}
                Some("person") => self.add_person(&path.segments[1..]),
                _ => self.person_properties.widen_to_whole(),
            },
            // Decided by columns no projection can drop, or by values the globals synthesize the
            // same way for every row: the elements-chain siblings are constants, `$group_n` is
            // null, `group_n` is an empty property bag, and `variables` is an empty object.
            GlobalRoot::Event
            | GlobalRoot::Timestamp
            | GlobalRoot::DistinctId
            | GlobalRoot::ElementsChainHref
            | GlobalRoot::ElementsChainTexts
            | GlobalRoot::ElementsChainIds
            | GlobalRoot::ElementsChainElements
            | GlobalRoot::DollarGroup(_)
            | GlobalRoot::Group(_)
            | GlobalRoot::Variables => {}
            // Absent from the behavioral globals entirely, so a behavioral condition naming it
            // raises however the scan was narrowed, and a person run never reaches a projection.
            // Either way it claims no column.
            GlobalRoot::Project => {}
        }
    }

    /// The `{ id, properties }` object, reached either as `person` or as `pdi.person`.
    fn add_person(&mut self, segments: &[String]) {
        let mut segments = segments.iter().map(String::as_str);
        match (segments.next(), segments.next()) {
            // `person.id` is the resolved person, which the scan always selects.
            (Some("id"), _) => {}
            (Some("properties"), Some(key)) => self.person_properties.add_key(key),
            // A bare `person` or `person.properties` hands a whole object somewhere, and any other
            // key resolves to null on every row — but telling those two apart is exactly the
            // judgement this module does not make.
            _ => self.person_properties.widen_to_whole(),
        }
    }

    fn into_plan(self) -> ColumnPlan {
        ColumnPlan {
            uuid: keep_if(self.uuid),
            elements_chain: keep_if(self.elements_chain),
            properties: self.properties.freeze(),
            person_properties: self.person_properties.freeze(),
        }
    }
}

const fn keep_if(needed: bool) -> ScalarColumn {
    if needed {
        ScalarColumn::Keep
    } else {
        ScalarColumn::Empty
    }
}

#[cfg(test)]
mod tests {
    use cohort_core::hogvm::analysis::{
        EvaluationClass, FullColumnsReason, GroupIndex, UnanalyzableReason,
    };

    use super::*;

    fn analysis(projection: Projection) -> ConditionAnalysis {
        ConditionAnalysis {
            evaluation: EvaluationClass::General,
            projection,
        }
    }

    fn reads(paths: impl IntoIterator<Item = ReadPath>) -> ConditionAnalysis {
        analysis(Projection::Reads(paths.into_iter().collect()))
    }

    fn path(root: GlobalRoot, segments: &[&str]) -> ReadPath {
        ReadPath::new(
            root,
            segments
                .iter()
                .map(|segment| (*segment).to_owned())
                .collect(),
        )
    }

    fn plan_of(analyses: &[ConditionAnalysis]) -> ColumnPlan {
        match ChunkProjection::derive(analyses.iter().map(Some)) {
            ChunkProjection::Projected(plan) => plan,
            ChunkProjection::FullColumns => panic!("expected a projected plan"),
        }
    }

    fn keys(source: &BlobSource) -> Vec<&str> {
        match source {
            BlobSource::Keys(keys) => keys.iter().collect(),
            other => panic!("expected key-filtered blob, got {other:?}"),
        }
    }

    /// The empty plan: a condition that reads nothing needs none of the four narrowable columns.
    /// Every one of them rendered empty is what makes an event-only chunk cheap, so this is the
    /// case that pays for the whole change.
    #[test]
    fn a_condition_reading_only_always_kept_globals_needs_no_narrowable_column() {
        let plan = plan_of(&[reads([
            path(GlobalRoot::Event, &[]),
            path(GlobalRoot::Timestamp, &[]),
            path(GlobalRoot::DistinctId, &[]),
            path(GlobalRoot::Person, &["id"]),
            path(GlobalRoot::Pdi, &["person_id"]),
            path(GlobalRoot::Pdi, &["distinct_id"]),
            path(GlobalRoot::Pdi, &["person", "id"]),
        ])]);
        assert_eq!(
            plan,
            ColumnPlan {
                uuid: ScalarColumn::Empty,
                elements_chain: ScalarColumn::Empty,
                properties: BlobSource::Empty,
                person_properties: BlobSource::Empty,
            }
        );
    }

    /// Constants the globals synthesize per row cost nothing: the group bags, the elements-chain
    /// siblings, and `variables` do not come from any column. Widening on them would give back most
    /// of the win on catalogs that use group filters.
    #[test]
    fn synthetic_globals_claim_no_column() {
        let index = GroupIndex::parse(2).expect("2 is a valid group ordinal");
        let plan = plan_of(&[reads([
            path(GlobalRoot::Group(index), &["properties", "tier"]),
            path(GlobalRoot::DollarGroup(index), &[]),
            path(GlobalRoot::Variables, &["x"]),
            path(GlobalRoot::ElementsChainHref, &[]),
            path(GlobalRoot::ElementsChainTexts, &[]),
            path(GlobalRoot::ElementsChainIds, &[]),
            path(GlobalRoot::ElementsChainElements, &[]),
        ])]);
        assert_eq!(plan.properties, BlobSource::Empty);
        assert_eq!(plan.person_properties, BlobSource::Empty);
        assert_eq!(plan.uuid, ScalarColumn::Empty);
        assert_eq!(plan.elements_chain, ScalarColumn::Empty);
    }

    /// A nested path claims its root key, because the raw value of that key carries the subtree.
    /// Claiming the leaf instead would render a `properties` object the condition cannot index into.
    #[test]
    fn a_nested_property_path_claims_its_root_key() {
        let plan = plan_of(&[reads([
            path(GlobalRoot::Properties, &["$set", "plan", "tier"]),
            path(GlobalRoot::Person, &["properties", "company", "size"]),
            path(GlobalRoot::Pdi, &["person", "properties", "email"]),
        ])]);
        assert_eq!(keys(&plan.properties), ["$set"]);
        assert_eq!(keys(&plan.person_properties), ["company", "email"]);
    }

    /// The union across conditions is what a chunk actually needs, deduplicated and ordered.
    #[test]
    fn separate_conditions_union_their_keys() {
        let plan = plan_of(&[
            reads([path(GlobalRoot::Properties, &["plan"])]),
            reads([path(GlobalRoot::Properties, &["utm_source"])]),
            reads([path(GlobalRoot::Properties, &["plan"])]),
        ]);
        assert_eq!(keys(&plan.properties), ["plan", "utm_source"]);
    }

    /// `person.properties` and `pdi.person` name whole objects whose keys are chosen at runtime, so
    /// the column has to arrive intact — and a narrow sibling must not talk it back down.
    #[test]
    fn a_whole_object_read_widens_its_blob_and_survives_narrow_siblings() {
        for whole in [
            path(GlobalRoot::Person, &["properties"]),
            path(GlobalRoot::Pdi, &["person"]),
        ] {
            let plan = plan_of(&[
                reads([whole.clone()]),
                reads([path(GlobalRoot::Person, &["properties", "email"])]),
            ]);
            assert_eq!(plan.person_properties, BlobSource::Full, "{whole:?}");
            // Only the person blob widens: the event's own properties are untouched by it.
            assert_eq!(plan.properties, BlobSource::Empty, "{whole:?}");
        }
    }

    /// A key under `person` that is neither `id` nor `properties` resolves to null on every row, so
    /// a narrow answer would even be correct. It still widens: telling those two cases apart is a
    /// judgement this mapping does not make, and the safe direction is the wide one.
    #[test]
    fn an_unrecognized_person_key_widens_rather_than_guesses() {
        for unrecognized in [
            path(GlobalRoot::Person, &["created_at"]),
            path(GlobalRoot::Pdi, &["person", "created_at"]),
            path(GlobalRoot::Pdi, &["team_id"]),
        ] {
            let plan = plan_of(&[reads([unrecognized.clone()])]);
            assert_eq!(
                plan.person_properties,
                BlobSource::Full,
                "{unrecognized:?} did not widen"
            );
        }
    }

    /// An `elements_chain` read arrives from the analyzer with its `properties.$elements_chain`
    /// fallback alongside, and both halves have to reach the scan: the globals builder reads the
    /// property only when the column is empty, so projecting one without the other would evaluate
    /// the condition against a chain that is not the row's.
    #[test]
    fn an_elements_chain_read_keeps_both_the_column_and_its_property_fallback() {
        let plan = plan_of(&[reads([
            path(GlobalRoot::ElementsChain, &[]),
            path(GlobalRoot::Properties, &["$elements_chain"]),
        ])]);
        assert_eq!(plan.elements_chain, ScalarColumn::Keep);
        assert_eq!(keys(&plan.properties), ["$elements_chain"]);
    }

    /// Every way a condition can escape the analysis takes the whole chunk wide, whatever its
    /// siblings found. A narrow scan built next to one of these would drop rows.
    #[test]
    fn any_unnarrowable_condition_takes_the_whole_chunk_wide() {
        let narrow = reads([path(GlobalRoot::Properties, &["plan"])]);
        for reason in [
            FullColumnsReason::BarePropertiesRoot,
            FullColumnsReason::BarePersonRoot,
            FullColumnsReason::Unanalyzable(UnanalyzableReason::DynamicGlobalPath),
        ] {
            let wide = analysis(Projection::FullColumns(reason.clone()));
            assert_eq!(
                ChunkProjection::derive([Some(&narrow), Some(&wide)]),
                ChunkProjection::FullColumns,
                "{reason:?}"
            );
        }
        // A hash the frozen catalog carried no bytecode for never reached the analyzer at all.
        assert_eq!(
            ChunkProjection::derive([Some(&narrow), None]),
            ChunkProjection::FullColumns
        );
    }

    /// No active conditions means no reads, which is the empty plan rather than the wide one.
    #[test]
    fn no_conditions_projects_every_narrowable_column_away() {
        assert_eq!(
            ChunkProjection::derive([]),
            ChunkProjection::Projected(ColumnPlan {
                uuid: ScalarColumn::Empty,
                elements_chain: ScalarColumn::Empty,
                properties: BlobSource::Empty,
                person_properties: BlobSource::Empty,
            })
        );
    }

    #[test]
    fn the_metric_outcome_names_which_arm_was_taken() {
        assert_eq!(ChunkProjection::FullColumns.outcome(), "full_columns");
        assert_eq!(ChunkProjection::derive([]).outcome(), "projected");
    }
}
