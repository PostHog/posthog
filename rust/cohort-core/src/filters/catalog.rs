use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::sync::Arc;

use common_types::cohort::TeamAllowlist;

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

/// Whether a catalog processes a team that its team map does not list.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum UnlistedTeams {
    /// The catalog was built for every team.
    Processed,
    /// The catalog was built for the listed teams only.
    NotProcessed,
}

#[derive(Debug)]
pub struct FilterCatalog {
    /// Processed teams, each with its filters, or `None` for a processed team with no parseable
    /// realtime cohort. Filters exist only as an entry of a processed team, so the catalog cannot hold
    /// filters for a team it does not process.
    teams: HashMap<TeamId, Option<Arc<TeamFilters>>>,
    unlisted: UnlistedTeams,
    generation: Generation,
}

impl FilterCatalog {
    /// The empty pre-load catalog, which processes no team.
    pub fn new() -> Self {
        Self::from_teams([])
    }

    /// A catalog for the teams in `processing`, with the filters of `teams`. A team outside
    /// `processing` gets no entry, so the catalog leaves its filters out.
    pub fn for_processing(
        processing: TeamAllowlist,
        teams: impl IntoIterator<Item = (TeamId, TeamFilters)>,
    ) -> Self {
        let filters = teams
            .into_iter()
            .map(|(team, filters)| (team, Arc::new(filters)));
        let (teams, unlisted) = match processing {
            TeamAllowlist::All => (
                filters
                    .map(|(team, filters)| (team, Some(filters)))
                    .collect(),
                UnlistedTeams::Processed,
            ),
            TeamAllowlist::Only(team_ids) => {
                let mut filters: HashMap<TeamId, Arc<TeamFilters>> = filters.collect();
                let teams = team_ids
                    .into_iter()
                    .map(|team_id| {
                        let team = TeamId(team_id);
                        (team, filters.remove(&team))
                    })
                    .collect();
                (teams, UnlistedTeams::NotProcessed)
            }
        };
        Self {
            teams,
            unlisted,
            generation: Generation::INITIAL,
        }
    }

    /// A catalog that processes exactly `teams`.
    pub fn from_teams(teams: impl IntoIterator<Item = (TeamId, TeamFilters)>) -> Self {
        Self {
            teams: teams
                .into_iter()
                .map(|(team, filters)| (team, Some(Arc::new(filters))))
                .collect(),
            unlisted: UnlistedTeams::NotProcessed,
            generation: Generation::INITIAL,
        }
    }

    /// Whether the catalog was built for `team_id`. True for a processed team with no realtime
    /// cohort, which [`Self::team`] has no filters for.
    pub fn processes(&self, team_id: TeamId) -> bool {
        match self.unlisted {
            UnlistedTeams::Processed => true,
            UnlistedTeams::NotProcessed => self.teams.contains_key(&team_id),
        }
    }

    /// The frozen filters for a team, or `None` if it has no realtime cohorts or is not processed.
    pub fn team(&self, team_id: TeamId) -> Option<&Arc<TeamFilters>> {
        self.teams.get(&team_id)?.as_ref()
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

    /// Teams with filters.
    pub fn team_count(&self) -> usize {
        self.with_filters().count()
    }

    /// Total distinct conditionHashes across all teams (sum of the per-team dedup sets).
    pub fn total_unique_conditions(&self) -> usize {
        self.with_filters()
            .map(|(_, team)| team.unique_condition_hashes.len())
            .sum()
    }

    fn with_filters(&self) -> impl Iterator<Item = (&TeamId, &Arc<TeamFilters>)> {
        self.teams
            .iter()
            .filter_map(|(team, filters)| Some((team, filters.as_ref()?)))
    }
}

impl Default for FilterCatalog {
    fn default() -> Self {
        Self::new()
    }
}

/// Hashes only the per-team condition sets (order-independent via the sorts), deliberately excluding
/// `generation` and which teams the catalog processes, because neither changes a condition's
/// evaluation. This backs the processor's `catalog_signature` memo invalidation: two catalogs with
/// the same conditions must hash equal so a no-op refresh reuses the generation and keeps memo
/// entries valid. `manager.rs`'s equivalence test guards the contract.
impl Hash for FilterCatalog {
    fn hash<H: Hasher>(&self, state: &mut H) {
        let mut teams: Vec<(&TeamId, &Arc<TeamFilters>)> = self.with_filters().collect();
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
