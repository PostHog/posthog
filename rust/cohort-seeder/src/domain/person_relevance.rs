//! Domain layer: whether one scanned person's leaf truths can change a participating cohort's
//! membership at all. Depends on `person`'s [`EvaluatedConditions`] and `cohort-core`'s filter
//! trees; reaches nothing outside `domain`.
//!
//! # Why an absent prior is the baseline
//!
//! A person seed reaches membership only through the leaf bits it asserts: the consumer stores
//! `matched ∪ (stored \ evaluated)` and re-walks each cohort's tree over the result. So a person
//! whose truth vector reaches the same verdict as the all-false vector contributes nothing, and
//! emitting them buys a record write and a recompose that ends unchanged.
//!
//! The baseline is the *absent* prior rather than the stored one, which the seeder cannot see. That
//! is the trade the non-matcher skip already makes one level up — a person whose every leaf is
//! false is skipped today, so a stale stored TRUE for them already survives a run. Pruning widens
//! that from all-false vectors to vacuous ones. The healer cadence retracts both, and it prunes
//! nothing.
//!
//! # Scope: the run's own participations
//!
//! The oracle is built from the `TeamFilters` validation assembles out of this run's *active*
//! participations, so "a participating cohort" is literal. The consumer's recompose fan-out is by
//! leaf state key and reaches every cohort on the team holding that leaf, so a person pruned here
//! can still be one a non-participating cohort would have gained from the same seed. That healing
//! was a side effect of seeding everyone, never a promise: a cohort's readiness only ever came from
//! its own run. Stopping it is the point, not an oversight.
//!
//! # Why three-valued logic
//!
//! A run pins only its person conditions. Behavioral leaves, cohort references, and person leaves
//! the run did not pin are `Unknown` here. Kleene's strong three-valued logic (a `False` under AND
//! and a `True` under OR win over an unknown; an unknown wins over everything else) is sound for
//! that: a determinate K3 result holds for *every* substitution of the unknowns, so two
//! determinate, equal results mean the cohort's verdict cannot move whatever the unknowns are. An
//! `Unknown` on either side emits.

use std::collections::HashMap;

use cohort_core::eligibility::{CohortEligibility, ExcludedReason};
use cohort_core::filters::tree::{BoolOp, CohortLeaf, FilterNode};
use cohort_core::filters::TeamFilters;
use cohort_core::seed::MAX_PERSON_SEED_HASHES;

use super::person::EvaluatedConditions;

/// One condition's position in [`EvaluatedConditions`], which is sorted-distinct by hash — so
/// walking indices ascending walks hashes ascending, which is the order a seed's `evaluated` list
/// has to be in.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ConditionIndex(u16);

impl ConditionIndex {
    /// `None` past the wire cap, which validation already refuses — so this is the type restating
    /// that cap rather than a second policy.
    pub fn new(position: usize) -> Option<Self> {
        if position >= MAX_PERSON_SEED_HASHES {
            return None;
        }
        u16::try_from(position).ok().map(Self)
    }

    pub const fn get(self) -> usize {
        self.0 as usize
    }
}

const TRUTH_WORDS: usize = MAX_PERSON_SEED_HASHES / u64::BITS as usize;
// The division above truncates, which would silently shorten the vector rather than fail.
const _: () = assert!(MAX_PERSON_SEED_HASHES.is_multiple_of(u64::BITS as usize));

/// Which of a run's conditions matched TRUE on one scanned person. Every other outcome — matched
/// FALSE, an unknown native, a VM error — reads FALSE here, which is what the consumer reads for a
/// hash absent from `matched`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct TruthVector([u64; TRUTH_WORDS]);

impl TruthVector {
    /// The vector of a person with no stored record: every leaf false.
    pub const ABSENT: Self = Self([0; TRUTH_WORDS]);

    pub fn set(&mut self, index: ConditionIndex) {
        let position = index.get();
        self.0[position / 64] |= 1 << (position % 64);
    }

    pub fn get(&self, index: ConditionIndex) -> bool {
        let position = index.get();
        self.0[position / 64] & (1 << (position % 64)) != 0
    }
}

/// Kleene's strong three-valued truth.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Truth3 {
    False,
    True,
    Unknown,
}

impl Truth3 {
    const fn of(value: bool) -> Self {
        if value {
            Self::True
        } else {
            Self::False
        }
    }
}

/// A participation's tree compiled against the run's pinned conditions: a person leaf the run
/// evaluates is [`RelevanceNode::Pinned`], everything else is [`RelevanceNode::Unknown`].
#[derive(Debug)]
enum RelevanceNode {
    /// Empty is `True`, matching the consumer's own `all` fold over an empty group.
    And(Vec<Self>),
    /// Empty is `False`, matching its `any` fold.
    Or(Vec<Self>),
    Pinned {
        index: ConditionIndex,
        negated: bool,
    },
    /// A behavioral leaf, a cohort reference, or a person leaf this run did not pin. Negation is
    /// absent on purpose: `NOT Unknown` is `Unknown`.
    Unknown,
}

impl RelevanceNode {
    /// The three-valued lift of the consumer's `stage2::evaluate_tree`, which this crate cannot
    /// call: `cohort-seeder` does not depend on `cohort-stream-processor`. Four identities have to
    /// agree, and today they do only by inspection — AND is `all` (so an empty group is `True`), OR
    /// is `any` (empty is `False`), a leaf is its bit `^ negated`, and an absent leaf is `false`.
    /// A cohort-reference leaf collapses to [`Self::Unknown`] and drops its negation bit, which is
    /// sound only because `NOT Unknown` is `Unknown`.
    ///
    /// Nothing executes the consumer's function against this one. Closing that needs a test in the
    /// consumer's own crate — see the deferred entry — because the edge has to point that way.
    fn evaluate(&self, truths: &TruthVector) -> Truth3 {
        match self {
            Self::And(children) => children
                .iter()
                .fold(Truth3::True, |acc, child| and3(acc, child.evaluate(truths))),
            Self::Or(children) => children
                .iter()
                .fold(Truth3::False, |acc, child| or3(acc, child.evaluate(truths))),
            Self::Pinned { index, negated } => Truth3::of(truths.get(*index) ^ negated),
            Self::Unknown => Truth3::Unknown,
        }
    }

    fn compile(node: &FilterNode, by_hash: &HashMap<[u8; 16], ConditionIndex>) -> Self {
        match node {
            FilterNode::Group { op, children } => {
                let children = children
                    .iter()
                    .map(|child| Self::compile(child, by_hash))
                    .collect();
                match op {
                    BoolOp::And => Self::And(children),
                    BoolOp::Or => Self::Or(children),
                }
            }
            FilterNode::Leaf(CohortLeaf::PersonProperty(leaf)) => {
                match by_hash.get(&leaf.condition_hash) {
                    Some(index) => Self::Pinned {
                        index: *index,
                        negated: leaf.negated,
                    },
                    None => Self::Unknown,
                }
            }
            FilterNode::Leaf(CohortLeaf::Behavioral(_) | CohortLeaf::CohortRef(_)) => Self::Unknown,
        }
    }
}

const fn and3(left: Truth3, right: Truth3) -> Truth3 {
    match (left, right) {
        (Truth3::False, _) | (_, Truth3::False) => Truth3::False,
        (Truth3::Unknown, _) | (_, Truth3::Unknown) => Truth3::Unknown,
        (Truth3::True, Truth3::True) => Truth3::True,
    }
}

const fn or3(left: Truth3, right: Truth3) -> Truth3 {
    match (left, right) {
        (Truth3::True, _) | (_, Truth3::True) => Truth3::True,
        (Truth3::Unknown, _) | (_, Truth3::Unknown) => Truth3::Unknown,
        (Truth3::False, Truth3::False) => Truth3::False,
    }
}

/// Whether a person's seed can move any participating cohort's verdict.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Relevance {
    CanChangeSomeCohort,
    IrrelevantToEveryCohort,
}

/// One cohort's tree beside the verdict it reaches on [`TruthVector::ABSENT`]. The baseline is
/// determinate by construction: a cohort whose baseline is `Unknown` can never be proven
/// irrelevant, so it collapses the oracle to [`RelevanceOracle::AlwaysRelevant`] at build.
#[derive(Debug)]
struct CohortRelevance {
    root: RelevanceNode,
    baseline: bool,
}

/// The run's composable participations, compiled once at validation.
#[derive(Debug)]
pub struct RelevanceOracle(Verdicts);

#[derive(Debug)]
enum Verdicts {
    /// Some composable cohort's verdict is already unknown on the absent vector, so no person can
    /// be proven irrelevant and every scanned person is emitted.
    AlwaysRelevant,
    /// One entry per composable participation. Empty means the run composes nothing, in which case
    /// no seed can change membership — which is the truth, and the per-run log line reports it.
    ByCohort(Vec<CohortRelevance>),
}

impl RelevanceOracle {
    pub fn build(filters: &TeamFilters, conditions: &EvaluatedConditions) -> Self {
        let by_hash: HashMap<[u8; 16], ConditionIndex> = conditions
            .iter()
            .enumerate()
            .filter_map(|(position, (hash, _))| {
                ConditionIndex::new(position).map(|index| (hash.as_bytes(), index))
            })
            .collect();

        Self::from_roots(filters.cohorts.iter().filter_map(|(cohort_id, tree)| {
            let eligibility = filters
                .eligibility
                .get(cohort_id)
                .copied()
                // A parsed cohort always carries an eligibility entry; an absent one composes.
                .unwrap_or(CohortEligibility::Stage2Composable);
            match composability(eligibility) {
                Composability::NeverComposed => None,
                Composability::Composable => Some(RelevanceNode::compile(&tree.root, &by_hash)),
            }
        }))
    }

    /// Pair each root with its absent-vector verdict, collapsing to [`Self::AlwaysRelevant`] as
    /// soon as one of them is indeterminate.
    fn from_roots(roots: impl IntoIterator<Item = RelevanceNode>) -> Self {
        let mut cohorts = Vec::new();
        for root in roots {
            let baseline = match root.evaluate(&TruthVector::ABSENT) {
                Truth3::True => true,
                Truth3::False => false,
                Truth3::Unknown => return Self(Verdicts::AlwaysRelevant),
            };
            cohorts.push(CohortRelevance { root, baseline });
        }
        Self(Verdicts::ByCohort(cohorts))
    }

    /// Judge one person's truths. One walk of each composable participation's tree — the absent
    /// verdict each is compared against was computed at build. A per-chunk memo over distinct
    /// vectors was considered and dropped: hashing the 128-byte key costs about what the walk does
    /// at the tree sizes a person run carries.
    pub fn judge(&self, truths: &TruthVector) -> Relevance {
        let cohorts = match &self.0 {
            Verdicts::AlwaysRelevant => return Relevance::CanChangeSomeCohort,
            Verdicts::ByCohort(cohorts) => cohorts,
        };
        let moved = cohorts
            .iter()
            .any(|cohort| cohort.root.evaluate(truths) != Truth3::of(cohort.baseline));
        match moved {
            true => Relevance::CanChangeSomeCohort,
            false => Relevance::IrrelevantToEveryCohort,
        }
    }

    /// How many participations the oracle walks, or `None` when it proves nothing. For the per-run
    /// log line.
    pub fn composable_cohorts(&self) -> Option<usize> {
        match &self.0 {
            Verdicts::AlwaysRelevant => None,
            Verdicts::ByCohort(cohorts) => Some(cohorts.len()),
        }
    }
}

/// Whether the *consumer* composes a cohort of this class at all.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Composability {
    NeverComposed,
    Composable,
}

/// The seeder freezes its catalog with cascade off, so every ref-bearing cohort reads
/// `Excluded(HasCohortRef)` here while the consumer runs with cascade on and composes it. The
/// seeder also holds only the run's own participations, never the referenced cohorts, so
/// `CycleDetected` and `UnresolvedRef` cannot be trusted either. Only the structural exclusions —
/// decided from the tree and the parse flags alone — classify identically in both services.
///
/// Exhaustive rather than defaulted: a new eligibility variant has to decide here rather than
/// silently join the class whose members are pruned away.
const fn composability(eligibility: CohortEligibility) -> Composability {
    match eligibility {
        CohortEligibility::SingleLeaf(_)
        | CohortEligibility::Stage2Composable
        | CohortEligibility::Stage2ComposableRef => Composability::Composable,
        CohortEligibility::Excluded(reason) => match reason {
            ExcludedReason::NotMultiLeaf
            | ExcludedReason::TopLevelNegation
            | ExcludedReason::EmptyGroup
            | ExcludedReason::HasDroppedLeaf => Composability::NeverComposed,
            ExcludedReason::HasCohortRef
            | ExcludedReason::CycleDetected
            | ExcludedReason::UnresolvedRef => Composability::Composable,
        },
    }
}

#[cfg(test)]
mod tests {
    use proptest::prelude::*;

    use super::*;

    fn index(position: usize) -> ConditionIndex {
        ConditionIndex::new(position).expect("test positions are under the cap")
    }

    fn vector(bits: &[bool]) -> TruthVector {
        let mut truths = TruthVector::ABSENT;
        for (position, bit) in bits.iter().enumerate() {
            if *bit {
                truths.set(index(position));
            }
        }
        truths
    }

    fn pinned(position: usize) -> RelevanceNode {
        RelevanceNode::Pinned {
            index: index(position),
            negated: false,
        }
    }

    /// The shape this whole change exists for: `email is_set AND email not_icontains '@posthog.com'`
    /// with the run pinning both leaves. Only a person carrying a non-PostHog address can move it.
    #[test]
    fn an_and_of_a_positive_and_a_vacuously_true_leaf_prunes_everyone_but_its_members() {
        let oracle = RelevanceOracle::from_roots([RelevanceNode::And(vec![pinned(0), pinned(1)])]);

        // No email: is_set false, not_icontains vacuously true.
        assert_eq!(
            oracle.judge(&vector(&[false, true])),
            Relevance::IrrelevantToEveryCohort
        );
        // A @posthog.com address: is_set true, not_icontains false.
        assert_eq!(
            oracle.judge(&vector(&[true, false])),
            Relevance::IrrelevantToEveryCohort
        );
        // A member.
        assert_eq!(
            oracle.judge(&vector(&[true, true])),
            Relevance::CanChangeSomeCohort
        );
    }

    /// The same two leaves under an OR are a whole-team cohort, so the vacuous vector is exactly the
    /// one that must not be pruned.
    #[test]
    fn an_or_carrying_the_vacuous_leaf_never_prunes_the_vacuous_vector() {
        let oracle = RelevanceOracle::from_roots([RelevanceNode::Or(vec![pinned(0), pinned(1)])]);

        assert_eq!(
            oracle.judge(&vector(&[false, true])),
            Relevance::CanChangeSomeCohort
        );
        assert_eq!(
            oracle.judge(&vector(&[false, false])),
            Relevance::IrrelevantToEveryCohort
        );
    }

    /// An unknown leaf beside a false one still folds to a determinate FALSE, which is what lets a
    /// cohort mixing behavioral and person leaves prune at all. Under an OR the baseline itself is
    /// unknown and the oracle stops pruning entirely.
    #[test]
    fn an_unknown_leaf_prunes_under_an_and_and_blocks_under_an_or() {
        let mixed = RelevanceOracle::from_roots([RelevanceNode::And(vec![
            RelevanceNode::Unknown,
            pinned(0),
            pinned(1),
        ])]);
        assert_eq!(
            mixed.judge(&vector(&[false, true])),
            Relevance::IrrelevantToEveryCohort
        );
        assert_eq!(
            mixed.judge(&vector(&[true, true])),
            Relevance::CanChangeSomeCohort,
            "the person arm now carries the composition, so the seed has to reach the consumer"
        );

        let unknown_baseline = RelevanceOracle::from_roots([RelevanceNode::Or(vec![
            RelevanceNode::Unknown,
            pinned(0),
        ])]);
        assert_eq!(
            unknown_baseline.composable_cohorts(),
            None,
            "an indeterminate baseline collapses the oracle"
        );
        assert_eq!(
            unknown_baseline.judge(&vector(&[false])),
            Relevance::CanChangeSomeCohort
        );
    }

    /// A negated person leaf reads `bit ^ negated`, the consumer's own rule, so an absent prior
    /// makes it TRUE and a matching person makes it FALSE.
    #[test]
    fn a_negated_pinned_leaf_inverts_the_bit() {
        let oracle = RelevanceOracle::from_roots([RelevanceNode::And(vec![
            pinned(0),
            RelevanceNode::Pinned {
                index: index(1),
                negated: true,
            },
        ])]);

        assert_eq!(
            oracle.judge(&vector(&[true, false])),
            Relevance::CanChangeSomeCohort
        );
        assert_eq!(
            oracle.judge(&vector(&[true, true])),
            Relevance::IrrelevantToEveryCohort
        );
    }

    /// The fold accumulators, which every group uses and the empty group exposes directly: AND
    /// starts at TRUE and OR at FALSE, matching the consumer's `all`/`any`. Flipping either would
    /// invert every group in the oracle.
    ///
    /// Note this is not a test about `EmptyGroup` cohorts. Those classify as
    /// `Excluded(EmptyGroup)`, which `composability` calls never-composed, so `build` never compiles
    /// one and the empty arms are unreachable through it.
    #[test]
    fn the_group_fold_accumulators_match_the_consumers() {
        assert_eq!(
            RelevanceNode::And(Vec::new()).evaluate(&TruthVector::ABSENT),
            Truth3::True
        );
        assert_eq!(
            RelevanceNode::Or(Vec::new()).evaluate(&TruthVector::ABSENT),
            Truth3::False
        );
    }

    /// A run composing nothing prunes everyone, which is correct — no participation registers
    /// membership — and is why the per-run log line reports the count.
    #[test]
    fn an_oracle_with_no_composable_cohort_prunes_every_vector() {
        let empty = RelevanceOracle::from_roots([]);
        assert_eq!(empty.composable_cohorts(), Some(0));
        assert_eq!(
            empty.judge(&vector(&[true, true])),
            Relevance::IrrelevantToEveryCohort
        );
    }

    /// Only the structural exclusions are decided the same way in both services; the seeder freezes
    /// with cascade off, so a ref-bearing cohort it calls excluded is one the consumer composes.
    #[test]
    fn only_structurally_excluded_cohorts_count_as_never_composed() {
        use cohort_core::LeafStateKey;

        for eligibility in [
            CohortEligibility::Excluded(ExcludedReason::NotMultiLeaf),
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation),
            CohortEligibility::Excluded(ExcludedReason::EmptyGroup),
            CohortEligibility::Excluded(ExcludedReason::HasDroppedLeaf),
        ] {
            assert_eq!(composability(eligibility), Composability::NeverComposed);
        }
        for eligibility in [
            CohortEligibility::SingleLeaf(LeafStateKey([0; 16])),
            CohortEligibility::Stage2Composable,
            CohortEligibility::Stage2ComposableRef,
            CohortEligibility::Excluded(ExcludedReason::HasCohortRef),
            CohortEligibility::Excluded(ExcludedReason::CycleDetected),
            CohortEligibility::Excluded(ExcludedReason::UnresolvedRef),
        ] {
            assert_eq!(composability(eligibility), Composability::Composable);
        }
    }

    /// The bit positions must not alias across the 64-bit word boundary, which a `1 << position`
    /// written without the word split would do silently past index 63.
    #[test]
    fn truth_vector_bits_are_independent_across_word_boundaries() {
        const POSITIONS: [usize; 7] = [0, 1, 63, 64, 65, 127, MAX_PERSON_SEED_HASHES - 1];
        for position in POSITIONS {
            let mut truths = TruthVector::ABSENT;
            truths.set(index(position));
            for other in POSITIONS {
                assert_eq!(
                    truths.get(index(other)),
                    other == position,
                    "setting {position} answered {other}"
                );
            }
        }
        assert_eq!(ConditionIndex::new(MAX_PERSON_SEED_HASHES), None);
    }

    /// The two-valued evaluation the consumer performs once the unknowns are filled in. Both
    /// branches of every group are evaluated so the unknown cursor advances identically whatever the
    /// truths are — a short-circuiting walk would hand the two sides different fillings.
    fn evaluate_completed(
        node: &RelevanceNode,
        truths: TruthVector,
        filling: &[bool],
        cursor: &mut usize,
    ) -> bool {
        match node {
            RelevanceNode::And(children) => children.iter().fold(true, |acc, child| {
                acc & evaluate_completed(child, truths, filling, cursor)
            }),
            RelevanceNode::Or(children) => children.iter().fold(false, |acc, child| {
                acc | evaluate_completed(child, truths, filling, cursor)
            }),
            RelevanceNode::Pinned { index, negated } => truths.get(*index) ^ negated,
            RelevanceNode::Unknown => {
                let bit = filling[*cursor % filling.len()];
                *cursor += 1;
                bit
            }
        }
    }

    const PROPTEST_LEAVES: usize = 4;

    fn arb_node(depth: u32) -> impl Strategy<Value = RelevanceNode> {
        let leaf = (0..PROPTEST_LEAVES, any::<bool>(), any::<bool>()).prop_map(
            |(position, negated, unknown)| match unknown {
                true => RelevanceNode::Unknown,
                false => RelevanceNode::Pinned {
                    index: index(position),
                    negated,
                },
            },
        );
        leaf.prop_recursive(depth, 16, 3, |inner| {
            prop_oneof![
                prop::collection::vec(inner.clone(), 0..3).prop_map(RelevanceNode::And),
                prop::collection::vec(inner, 0..3).prop_map(RelevanceNode::Or),
            ]
        })
    }

    proptest! {
        /// The soundness law the pruning rests on: when the oracle calls a vector irrelevant, the
        /// cohort's *two-valued* verdict at that vector equals its verdict at the absent vector, for
        /// every filling of the unknown leaves. A wrong K3 rule (`NOT Unknown = False`, an AND that
        /// loses a `False` to an `Unknown`, an OR identity slip) breaks this.
        #[test]
        fn an_irrelevant_vector_cannot_move_a_cohort_under_any_completion(
            root in arb_node(3),
            bits in prop::collection::vec(any::<bool>(), PROPTEST_LEAVES),
            fillings in prop::collection::vec(
                prop::collection::vec(any::<bool>(), 1..16),
                1..8,
            ),
        ) {
            let truths = vector(&bits);
            let oracle = RelevanceOracle::from_roots([root]);
            // An unknown baseline never prunes, so there is nothing to falsify.
            let Verdicts::ByCohort(cohorts) = &oracle.0 else { return Ok(()); };
            prop_assume!(oracle.judge(&truths) == Relevance::IrrelevantToEveryCohort);

            for cohort in cohorts {
                for filling in &fillings {
                    let at_truths =
                        evaluate_completed(&cohort.root, truths, filling, &mut 0);
                    let at_absent =
                        evaluate_completed(&cohort.root, TruthVector::ABSENT, filling, &mut 0);
                    prop_assert_eq!(
                        at_truths,
                        at_absent,
                        "pruned a vector that moves the cohort under filling {:?}",
                        filling
                    );
                }
            }
        }
    }
}
