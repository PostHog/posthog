use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::sync::Arc;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;

/// The catalog's content epoch. Compared for memo invalidation; advanced on a content change.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct Generation(pub u64);

impl Generation {
    /// The empty pre-load catalog; no team is evaluated against it.
    pub const INITIAL: Self = Self(0);

    pub fn next(self) -> Self {
        Self(self.0 + 1)
    }
}

#[derive(Debug, Default)]
pub struct FilterCatalog {
    teams: HashMap<TeamId, Arc<TeamFilters>>,
    generation: Generation,
}

impl FilterCatalog {
    pub fn new() -> Self {
        Self {
            teams: HashMap::new(),
            generation: Generation::INITIAL,
        }
    }

    /// The frozen filters for a team, or `None` if it has no realtime cohorts.
    pub fn team(&self, team_id: TeamId) -> Option<&Arc<TeamFilters>> {
        self.teams.get(&team_id)
    }

    pub fn generation(&self) -> Generation {
        self.generation
    }

    /// Stamp the content generation. Stamped once, pre-publication (by the refresh loop, before the
    /// atomic swap), so it consumes `self` rather than mutating a published catalog.
    pub fn with_generation(mut self, generation: Generation) -> Self {
        self.generation = generation;
        self
    }

    pub fn team_count(&self) -> usize {
        self.teams.len()
    }

    /// Total distinct conditionHashes across all teams (sum of the per-team dedup sets).
    pub fn total_unique_conditions(&self) -> usize {
        self.teams
            .values()
            .map(|team| team.unique_condition_hashes.len())
            .sum()
    }

    pub fn from_teams(teams: impl IntoIterator<Item = (TeamId, TeamFilters)>) -> Self {
        Self {
            teams: teams
                .into_iter()
                .map(|(team, filters)| (team, Arc::new(filters)))
                .collect(),
            generation: Generation::INITIAL,
        }
    }
}

/// Hashes only the per-team condition sets (order-independent via the sorts), deliberately excluding
/// `generation`. This backs the processor's `catalog_signature` memo invalidation: two catalogs with
/// the same conditions must hash equal so a no-op refresh reuses the generation and keeps memo entries
/// valid. `manager.rs`'s equivalence test guards the contract.
impl Hash for FilterCatalog {
    fn hash<H: Hasher>(&self, state: &mut H) {
        let mut teams: Vec<(&TeamId, &Arc<TeamFilters>)> = self.teams.iter().collect();
        teams.sort_unstable_by_key(|(team, _)| team.0);
        for (team, filters) in teams {
            team.0.hash(state);
            let mut hashes: Vec<[u8; 16]> =
                filters.unique_condition_hashes.iter().copied().collect();
            hashes.sort_unstable();
            hashes.hash(state);
        }
    }
}
