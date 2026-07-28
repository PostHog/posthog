//! Domain layer: `Lookback`, `PinnedCondition`, and `EventNameSet` — the seed conditions, sited below
//! both `plan` and `pinned` to break their would-be cycle. Depends on `ids` and `cohort-core`.

use std::collections::BTreeSet;

use cohort_core::filters::CohortId;

use super::ids::{ConditionHash, DayIdx};

/// The scannable shape of a stored condition. Every variant maps to a concrete day range; the
/// unscannable cases are resolved away before storage (see [`super::pinned`]).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Lookback {
    SlidingDays(u32),
    SubDay,
    FixedRange {
        from_day: Option<DayIdx>,
        to_day: Option<DayIdx>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PinnedCondition {
    pub cohort_id: CohortId,
    pub hash: ConditionHash,
    pub event_name: String,
    pub lookback: Lookback,
}

/// The union of event names a run scans, sorted ascending and deduplicated by construction.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EventNameSet(Vec<String>);

impl EventNameSet {
    pub fn new(names: impl IntoIterator<Item = String>) -> Self {
        Self(
            names
                .into_iter()
                .collect::<BTreeSet<_>>()
                .into_iter()
                .collect(),
        )
    }

    pub fn from_conditions(conditions: &[PinnedCondition]) -> Self {
        Self::new(
            conditions
                .iter()
                .map(|condition| condition.event_name.clone()),
        )
    }

    pub fn iter(&self) -> impl Iterator<Item = &String> {
        self.0.iter()
    }

    pub fn as_slice(&self) -> &[String] {
        &self.0
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn into_vec(self) -> Vec<String> {
        self.0
    }
}

impl IntoIterator for EventNameSet {
    type Item = String;
    type IntoIter = std::vec::IntoIter<String>;

    fn into_iter(self) -> Self::IntoIter {
        self.0.into_iter()
    }
}
