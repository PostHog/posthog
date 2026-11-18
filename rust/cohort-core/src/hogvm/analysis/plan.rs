//! Which globals a set of conditions can name, so a builder materializes only those.
//!
//! Omitting a root is sound because `GET_GLOBAL` is the VM's only path into the globals dict and
//! [`super::Projection`] names every root a condition's `GET_GLOBAL`s can reach.
//!
//! Omitting one a condition does read is loud rather than silent: the VM raises
//! `VmError::UnknownGlobal` for an absent root, and pushes null only for a missing key under a
//! present one. A stub value under every root would turn the same bug into a wrong answer.

use std::fmt;

use super::{GlobalRoot, Projection};

const _: () = assert!(GlobalRoot::COUNT as u32 <= u32::BITS);

/// What a globals builder has to materialize for a set of conditions: every root any of them can
/// name, as a bitset over [`GlobalRoot`] ordinals. Unioned over an event-name bucket, because one
/// globals dict serves the whole bucket.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct GlobalsPlan(u32);

impl GlobalsPlan {
    /// Reads nothing. The identity of [`GlobalsPlan::union`].
    pub const NONE: Self = Self(0);
    /// Reads everything. The ordinals are dense over `0..COUNT`, so every root is the mask of their
    /// bits.
    pub const FULL: Self = Self(((1u64 << GlobalRoot::COUNT) - 1) as u32);

    /// An `elements_chain` read needs `properties` too, for the `$elements_chain` fallback. No arm
    /// here handles that because the analysis already records the fallback as its own path.
    pub fn of(projection: &Projection) -> Self {
        match projection {
            Projection::FullColumns(_) => Self::FULL,
            Projection::Reads(paths) => paths
                .iter()
                .fold(Self::NONE, |plan, path| plan.with(path.root)),
        }
    }

    pub fn union(self, other: Self) -> Self {
        Self(self.0 | other.0)
    }

    pub fn reads(self, root: GlobalRoot) -> bool {
        self.0 & Self::bit(root) != 0
    }

    /// Whether `self` claims every root `other` does, which is what makes a narrowed
    /// [`GlobalsBuild`] safe.
    pub fn covers(self, other: Self) -> bool {
        self.0 & other.0 == other.0
    }

    fn with(self, root: GlobalRoot) -> Self {
        Self(self.0 | Self::bit(root))
    }

    fn bit(root: GlobalRoot) -> u32 {
        1u32 << root.ordinal()
    }

    /// Ordinal order, which is what makes [`fmt::Debug`] stable.
    fn roots(self) -> impl Iterator<Item = GlobalRoot> {
        GlobalRoot::all().filter(move |&root| self.reads(root))
    }
}

impl FromIterator<GlobalsPlan> for GlobalsPlan {
    fn from_iter<I: IntoIterator<Item = GlobalsPlan>>(plans: I) -> Self {
        plans.into_iter().fold(Self::NONE, Self::union)
    }
}

/// Root names rather than a bit pattern, so a failing assertion is readable.
impl fmt::Debug for GlobalsPlan {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_set()
            .entries(self.roots().map(|root| root.as_str()))
            .finish()
    }
}

/// The two plans one behavioral globals build runs under.
///
/// `materialize` is the plan of the conditions that will run against the dict — one event-name
/// bucket's, under the fan-out gate. `parse` is every root the team's behavioral conditions can
/// read, and it alone decides which of the event's JSON payloads are parsed at all.
///
/// `parse` has to be the wider one. Whether an event's payloads are malformed must not depend on
/// which bucket the event landed in, or the fan-out gate would become a correctness switch: a
/// bucket that parses nothing would evaluate an event that the ungated sweep drops for a payload
/// neither of them reads.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct GlobalsBuild {
    materialize: GlobalsPlan,
    parse: GlobalsPlan,
}

impl GlobalsBuild {
    /// A build narrowed to `materialize`, parsing whatever `parse` covers.
    pub fn narrowed(materialize: GlobalsPlan, parse: GlobalsPlan) -> Self {
        debug_assert!(
            parse.covers(materialize),
            "a build cannot materialize {materialize:?} out of a parse of {parse:?}",
        );
        Self { materialize, parse }
    }

    /// One plan for both, for a caller that evaluates every condition it planned for.
    pub fn whole(plan: GlobalsPlan) -> Self {
        Self {
            materialize: plan,
            parse: plan,
        }
    }

    pub(crate) fn materialize(self) -> GlobalsPlan {
        self.materialize
    }

    /// Whether the `properties` payload has to be parsed. An `elements_chain` read reaches
    /// `properties.$elements_chain` as a fallback, which the analysis records as its own
    /// `properties` path; naming the root here too keeps the builder from depending on that.
    pub(crate) fn parses_properties(self) -> bool {
        self.parse.reads(GlobalRoot::Properties) || self.parse.reads(GlobalRoot::ElementsChain)
    }

    /// Whether the `person_properties` payload has to be parsed: `person` carries it, and `pdi`
    /// carries `person`.
    pub(crate) fn parses_person_properties(self) -> bool {
        self.parse.reads(GlobalRoot::Person) || self.parse.reads(GlobalRoot::Pdi)
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::super::{FullColumnsReason, GroupIndex, ReadPath, UnanalyzableReason};
    use super::*;

    fn reads(paths: [ReadPath; 2]) -> Projection {
        Projection::Reads(BTreeSet::from(paths))
    }

    fn path(root: GlobalRoot, segments: &[&str]) -> ReadPath {
        ReadPath::new(root, segments.iter().map(|s| (*s).to_owned()).collect())
    }

    #[test]
    fn a_full_plan_holds_every_root_and_an_empty_one_holds_none() {
        let all: Vec<GlobalRoot> = GlobalRoot::all().collect();
        assert_eq!(all.len(), GlobalRoot::COUNT as usize);
        for root in &all {
            assert!(GlobalsPlan::FULL.reads(*root), "FULL is missing {root:?}");
            assert!(!GlobalsPlan::NONE.reads(*root), "NONE holds {root:?}");
            assert_eq!(
                GlobalsPlan::NONE.with(*root).roots().collect::<Vec<_>>(),
                vec![*root],
            );
        }
        assert_eq!(GlobalsPlan::NONE.roots().count(), 0);
        assert!(
            all.windows(2)
                .all(|pair| pair[0].ordinal() < pair[1].ordinal()),
            "iteration is not in ordinal order, so a Debug rendering would reorder unpredictably",
        );
    }

    #[test]
    fn a_plan_claims_the_read_sets_roots_and_widens_on_full_columns() {
        let narrowed = GlobalsPlan::of(&reads([
            path(GlobalRoot::Pdi, &["person", "properties", "plan"]),
            path(GlobalRoot::Event, &[]),
        ]));
        assert!(narrowed.reads(GlobalRoot::Pdi));
        assert!(narrowed.reads(GlobalRoot::Event));
        assert!(!narrowed.reads(GlobalRoot::Person));
        assert!(!narrowed.reads(GlobalRoot::Properties));

        for reason in [
            FullColumnsReason::BarePersonRoot,
            FullColumnsReason::BarePropertiesRoot,
            FullColumnsReason::RepresentationSensitiveCall,
            FullColumnsReason::Unanalyzable(UnanalyzableReason::DynamicGlobalPath),
        ] {
            assert_eq!(
                GlobalsPlan::of(&Projection::FullColumns(reason.clone())),
                GlobalsPlan::FULL,
                "{reason:?} did not widen to every root",
            );
        }

        assert_eq!(
            GlobalsPlan::of(&Projection::Reads(BTreeSet::new())),
            GlobalsPlan::NONE,
        );
    }

    #[test]
    fn a_union_of_plans_is_the_union_of_their_roots() {
        let event = GlobalsPlan::of(&reads([
            path(GlobalRoot::Event, &[]),
            path(
                GlobalRoot::Group(GroupIndex::parse(3).unwrap()),
                &["properties"],
            ),
        ]));
        let person = GlobalsPlan::of(&reads([
            path(GlobalRoot::Person, &["properties", "plan"]),
            path(GlobalRoot::Timestamp, &[]),
        ]));

        let union = event.union(person);
        for root in [
            GlobalRoot::Event,
            GlobalRoot::Group(GroupIndex::parse(3).unwrap()),
            GlobalRoot::Person,
            GlobalRoot::Timestamp,
        ] {
            assert!(union.reads(root), "the union dropped {root:?}");
        }
        assert!(!union.reads(GlobalRoot::Pdi));

        assert_eq!([event, person].into_iter().collect::<GlobalsPlan>(), union);
        assert_eq!(
            std::iter::empty::<GlobalsPlan>().collect::<GlobalsPlan>(),
            GlobalsPlan::NONE,
        );
        assert_eq!(event.union(GlobalsPlan::NONE), event);
        assert_eq!(event.union(GlobalsPlan::FULL), GlobalsPlan::FULL);
        assert!(union.covers(event) && union.covers(person));
        assert!(!event.covers(union));
        assert!(GlobalsPlan::FULL.covers(union) && union.covers(GlobalsPlan::NONE));
    }

    /// A plan that reads only `event` names no payload, which is what lets a build skip both JSON
    /// parses; the two payload-bearing sides have to answer independently.
    #[test]
    fn a_build_parses_only_the_payloads_its_parse_plan_reaches() {
        let plan = |root| GlobalsPlan::NONE.with(root);
        let build = |root| GlobalsBuild::whole(plan(root));

        assert!(!build(GlobalRoot::Event).parses_properties());
        assert!(!build(GlobalRoot::Event).parses_person_properties());
        for root in [GlobalRoot::Properties, GlobalRoot::ElementsChain] {
            assert!(build(root).parses_properties(), "{root:?}");
            assert!(!build(root).parses_person_properties(), "{root:?}");
        }
        for root in [GlobalRoot::Person, GlobalRoot::Pdi] {
            assert!(build(root).parses_person_properties(), "{root:?}");
            assert!(!build(root).parses_properties(), "{root:?}");
        }
        assert!(GlobalsBuild::whole(GlobalsPlan::FULL).parses_properties());
        assert!(GlobalsBuild::whole(GlobalsPlan::FULL).parses_person_properties());

        // The narrow side is what the dict holds; the wide side is what was parsed for it, so a
        // bucket that reads only `event` still pays a parse its team needs elsewhere.
        let team = plan(GlobalRoot::Event).with(GlobalRoot::Properties);
        let narrowed = GlobalsBuild::narrowed(plan(GlobalRoot::Event), team);
        assert_eq!(narrowed.materialize(), plan(GlobalRoot::Event));
        assert!(narrowed.parses_properties());
    }
}
