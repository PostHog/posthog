//! Which globals a set of conditions can name, so a builder materializes only those.
//!
//! Omitting a root is sound because `GET_GLOBAL` is the VM's only path into the globals dict and
//! [`super::Projection`] names every root a condition's `GET_GLOBAL`s can reach.
//!
//! Omitting one a condition does read is loud rather than silent: the VM raises
//! `VmError::UnknownGlobal` for an absent root, and pushes null only for a missing key under a
//! present one. A stub value under every root would turn the same bug into a wrong answer.

use std::fmt;
use std::ops::BitOr;

use super::{GlobalRoot, Projection};

const _: () = assert!(GlobalRoot::COUNT as u32 <= u32::BITS);

/// A set of [`GlobalRoot`]s, as a bitset over their ordinals.
#[derive(Clone, Copy, PartialEq, Eq, Default)]
pub struct RootSet(u32);

impl RootSet {
    pub const EMPTY: Self = Self(0);
    /// The ordinals are dense over `0..COUNT`, so every root is the mask of their bits.
    pub const ALL: Self = Self(((1u64 << GlobalRoot::COUNT) - 1) as u32);

    pub fn with(self, root: GlobalRoot) -> Self {
        Self(self.0 | Self::bit(root))
    }

    pub fn contains(self, root: GlobalRoot) -> bool {
        self.0 & Self::bit(root) != 0
    }

    /// Ordinal order, which is what makes [`fmt::Debug`] stable.
    pub fn iter(self) -> impl Iterator<Item = GlobalRoot> {
        (0..GlobalRoot::COUNT)
            .filter(move |&ordinal| self.0 & (1u32 << ordinal) != 0)
            .filter_map(GlobalRoot::from_ordinal)
    }

    fn bit(root: GlobalRoot) -> u32 {
        1u32 << root.ordinal()
    }
}

impl BitOr for RootSet {
    type Output = Self;

    fn bitor(self, other: Self) -> Self {
        Self(self.0 | other.0)
    }
}

/// Root names rather than a bit pattern, so a failing assertion is readable.
impl fmt::Debug for RootSet {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_set()
            .entries(self.iter().map(|root| root.as_str()))
            .finish()
    }
}

/// What a globals builder has to materialize for a set of conditions: every root any of them can
/// name. Unioned over an event-name bucket, because one globals dict serves the whole bucket.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct GlobalsPlan {
    roots: RootSet,
}

impl GlobalsPlan {
    /// Reads nothing. The identity of [`GlobalsPlan::union`].
    pub const NONE: Self = Self {
        roots: RootSet::EMPTY,
    };
    /// Reads everything.
    pub const FULL: Self = Self {
        roots: RootSet::ALL,
    };

    /// An `elements_chain` read needs `properties` too, for the `$elements_chain` fallback. No arm
    /// here handles that because the analysis already records the fallback as its own path.
    pub fn of(projection: &Projection) -> Self {
        match projection {
            Projection::FullColumns(_) => Self::FULL,
            Projection::Reads(paths) => Self {
                roots: paths
                    .iter()
                    .fold(RootSet::EMPTY, |roots, path| roots.with(path.root)),
            },
        }
    }

    pub fn union(self, other: Self) -> Self {
        Self {
            roots: self.roots | other.roots,
        }
    }

    pub fn reads(self, root: GlobalRoot) -> bool {
        self.roots.contains(root)
    }
}

impl FromIterator<GlobalsPlan> for GlobalsPlan {
    fn from_iter<I: IntoIterator<Item = GlobalsPlan>>(plans: I) -> Self {
        plans.into_iter().fold(Self::NONE, Self::union)
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
    fn a_root_set_holds_and_returns_every_root() {
        let all: Vec<GlobalRoot> = RootSet::ALL.iter().collect();
        assert_eq!(all.len(), GlobalRoot::COUNT as usize);
        for root in &all {
            assert!(RootSet::ALL.contains(*root), "ALL is missing {root:?}");
            assert!(!RootSet::EMPTY.contains(*root), "EMPTY holds {root:?}");
            assert_eq!(
                RootSet::EMPTY.with(*root).iter().collect::<Vec<_>>(),
                vec![*root],
            );
        }
        assert_eq!(RootSet::EMPTY.iter().count(), 0);
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
        for root in RootSet::ALL.iter() {
            assert!(GlobalsPlan::FULL.reads(root), "FULL omits {root:?}");
            assert!(!GlobalsPlan::NONE.reads(root), "NONE claims {root:?}");
        }
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
    }
}
