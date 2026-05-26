//! Routing policy, endpoint local state, and the candidate-selection
//! algorithm shared by all transports.
//!
//! Policies describe how a stage should order endpoints (affinity vs random
//! vs strict) and how many fallback candidates the policy allows. Capacity
//! and partitioning live in sibling modules; this module does not know about
//! item counts or sub-batches.

use std::cmp::{Ordering, Reverse};
use std::collections::hash_map::DefaultHasher;
use std::collections::HashMap;
use std::hash::{Hash, Hasher};

use rand::seq::SliceRandom;
use rand::Rng;

use super::key::RoutingKey;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RoutingMode {
    /// Rank endpoints with rendezvous/highest-random-weight hashing and keep
    /// the stable score order as fallback order.
    AffinityFirst,
    /// Shuffle healthy endpoints. Use only where cache/limiter locality is not
    /// part of the stage contract.
    Random,
    /// Use rendezvous hashing for the primary only and do not emit fallbacks.
    StrictAffinity,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RoutingPolicy {
    pub mode: RoutingMode,
    /// Maximum number of non-primary candidates to return. `None` means all
    /// healthy candidates are allowed by the policy.
    pub max_fallback_attempts: Option<usize>,
}

impl RoutingPolicy {
    pub fn affinity_first() -> Self {
        Self {
            mode: RoutingMode::AffinityFirst,
            max_fallback_attempts: None,
        }
    }

    pub fn random() -> Self {
        Self {
            mode: RoutingMode::Random,
            max_fallback_attempts: None,
        }
    }

    pub fn strict_affinity() -> Self {
        Self {
            mode: RoutingMode::StrictAffinity,
            max_fallback_attempts: Some(0),
        }
    }

    pub fn with_max_fallback_attempts(mut self, attempts: usize) -> Self {
        self.max_fallback_attempts = Some(attempts);
        self
    }

    fn candidate_limit(&self) -> Option<usize> {
        if self.mode == RoutingMode::StrictAffinity {
            return Some(1);
        }

        self.max_fallback_attempts
            .map(|attempts| attempts.saturating_add(1))
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EndpointLocalState {
    pub draining: bool,
    pub ejected: bool,
    pub overloaded: bool,
}

impl EndpointLocalState {
    pub fn available() -> Self {
        Self::default()
    }

    pub fn draining() -> Self {
        Self {
            draining: true,
            ejected: false,
            overloaded: false,
        }
    }

    pub fn ejected() -> Self {
        Self {
            draining: false,
            ejected: true,
            overloaded: false,
        }
    }

    pub fn overloaded() -> Self {
        Self {
            draining: false,
            ejected: false,
            overloaded: true,
        }
    }

    pub fn is_available(&self) -> bool {
        !self.draining && !self.ejected && !self.overloaded
    }
}

pub type EndpointStateMap<EndpointId> = HashMap<EndpointId, EndpointLocalState>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RemoteRoutingConfig {
    fallback_policy: RoutingPolicy,
    stage_policies: HashMap<String, RoutingPolicy>,
    use_observed_load: bool,
}

impl RemoteRoutingConfig {
    pub fn new(fallback_policy: RoutingPolicy) -> Self {
        Self {
            fallback_policy,
            stage_policies: HashMap::new(),
            use_observed_load: true,
        }
    }

    pub fn affinity_first_all() -> Self {
        Self::new(RoutingPolicy::affinity_first())
    }

    pub fn with_stage_policy(mut self, stage_id: impl Into<String>, policy: RoutingPolicy) -> Self {
        self.stage_policies.insert(stage_id.into(), policy);
        self
    }

    pub fn set_stage_policy(&mut self, stage_id: impl Into<String>, policy: RoutingPolicy) {
        self.stage_policies.insert(stage_id.into(), policy);
    }

    pub fn without_observed_load(mut self) -> Self {
        self.use_observed_load = false;
        self
    }

    pub fn use_observed_load(&self) -> bool {
        self.use_observed_load
    }

    pub fn policy_for_stage(&self, stage_id: &str) -> RoutingPolicy {
        self.stage_policies
            .get(stage_id)
            .cloned()
            .unwrap_or_else(|| self.fallback_policy.clone())
    }
}

impl Default for RemoteRoutingConfig {
    fn default() -> Self {
        Self::affinity_first_all()
    }
}

pub fn pick_candidates_with_rng<EndpointId, Random>(
    stage_id: &str,
    routing_key: &RoutingKey,
    endpoints: &[EndpointId],
    endpoint_states: &EndpointStateMap<EndpointId>,
    policy: &RoutingPolicy,
    rng: &mut Random,
) -> Vec<EndpointId>
where
    EndpointId: Clone + Eq + Hash + Ord,
    Random: Rng + ?Sized,
{
    let mut candidates = available_candidates(endpoints, endpoint_states);

    match effective_mode(routing_key, policy) {
        RoutingMode::AffinityFirst | RoutingMode::StrictAffinity => {
            candidates.sort_by(|left, right| {
                compare_affinity_candidates(stage_id, routing_key, left, right)
            });
        }
        RoutingMode::Random => {
            candidates.shuffle(rng);
        }
    }

    if let Some(limit) = policy.candidate_limit() {
        candidates.truncate(limit);
    }

    candidates
}

fn effective_mode(routing_key: &RoutingKey, policy: &RoutingPolicy) -> RoutingMode {
    if routing_key.has_affinity() {
        return policy.mode.clone();
    }

    RoutingMode::Random
}

fn available_candidates<EndpointId>(
    endpoints: &[EndpointId],
    endpoint_states: &EndpointStateMap<EndpointId>,
) -> Vec<EndpointId>
where
    EndpointId: Clone + Eq + Hash,
{
    endpoints
        .iter()
        .filter(|endpoint| {
            endpoint_states
                .get(endpoint)
                .is_none_or(EndpointLocalState::is_available)
        })
        .cloned()
        .collect()
}

fn compare_affinity_candidates<EndpointId>(
    stage_id: &str,
    routing_key: &RoutingKey,
    left: &EndpointId,
    right: &EndpointId,
) -> Ordering
where
    EndpointId: Hash + Ord,
{
    (Reverse(rendezvous_score(stage_id, routing_key, left)), left).cmp(&(
        Reverse(rendezvous_score(stage_id, routing_key, right)),
        right,
    ))
}

fn rendezvous_score<EndpointId>(
    stage_id: &str,
    routing_key: &RoutingKey,
    endpoint: &EndpointId,
) -> u64
where
    EndpointId: Hash,
{
    let mut hasher = DefaultHasher::new();
    stage_id.hash(&mut hasher);
    routing_key.hash(&mut hasher);
    endpoint.hash(&mut hasher);
    hasher.finish()
}
