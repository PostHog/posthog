//! Worker selection strategies for the batcher's requests.
//!
//! The batcher's worker assigner owns the stateful concerns (per-worker
//! request and message load). This module is the pure decision layer: given
//! the set of healthy workers and their per-worker load, pick a target.
//! Keeping it free of batcher state makes the algorithms trivially
//! unit-testable and lets the routing policy evolve (P2C cost functions,
//! subsetting) without touching the batcher's bookkeeping.

use std::collections::HashMap;
use std::num::NonZeroU64;
use std::str::FromStr;

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

use crate::worker_registry::WorkerId;

/// How requests are placed on workers.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum RoutingStrategy {
    /// Power-of-two-choices: sample two random workers, pick the lighter. Herd
    /// resistant when many consumers share a worker pool, because each consumer
    /// samples a different random pair instead of converging on one global best.
    #[default]
    P2c,
    /// Deterministic aperture: each consumer places requests only within
    /// its weighted slice of the worker ring (see [`crate::aperture`]), with
    /// weighted P2C selection inside the slice. Consolidates small batches onto
    /// few workers while every worker gets the same share of the fleet's
    /// slices. Requires peer awareness (`PEER_SERVICE_NAME`); behaves as plain
    /// P2C over the full pool while the peer set is unknown.
    Aperture,
}

impl FromStr for RoutingStrategy {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "p2c" | "power_of_two" | "power-of-two" => Ok(RoutingStrategy::P2c),
            "aperture" => Ok(RoutingStrategy::Aperture),
            other => Err(format!(
                "unknown routing strategy '{other}' (expected 'p2c' or 'aperture')"
            )),
        }
    }
}

impl RoutingStrategy {
    /// Canonical config-string form, as accepted by [`FromStr`].
    pub fn as_str(&self) -> &'static str {
        match self {
            RoutingStrategy::P2c => "p2c",
            RoutingStrategy::Aperture => "aperture",
        }
    }
}

/// A worker that may take a request, and its share of this consumer's
/// requests relative to the other candidates.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Candidate {
    pub worker: WorkerId,
    pub weight: NonZeroU64,
    /// The weight of a worker that the candidate set covers whole.
    pub full_weight: NonZeroU64,
}

impl Candidate {
    /// `weight` above `full_weight` is clamped to `full_weight`.
    pub fn new(worker: WorkerId, weight: NonZeroU64, full_weight: NonZeroU64) -> Self {
        Self {
            worker,
            weight: weight.min(full_weight),
            full_weight,
        }
    }

    pub fn uniform(worker: WorkerId) -> Self {
        Self::new(worker, NonZeroU64::MIN, NonZeroU64::MIN)
    }

    /// The requests this consumer may keep in flight on the worker:
    /// `max_per_worker` scaled by `weight / full_weight` and rounded up, so a
    /// candidate keeps at least one slot when `max_per_worker` is not zero.
    pub fn slots(&self, max_per_worker: usize) -> usize {
        let full = u128::from(self.full_weight.get());
        let scaled = (max_per_worker as u128 * u128::from(self.weight.get())).div_ceil(full);
        scaled as usize
    }
}

/// Per-worker load for a single routing decision, keyed by worker id. A missing
/// entry counts as zero load.
pub type WorkerLoad = HashMap<WorkerId, usize>;

fn load_of(load: &WorkerLoad, worker: &WorkerId) -> usize {
    load.get(worker).copied().unwrap_or(0)
}

/// Stateful worker selector. Holds the routing strategy and, for P2C, the RNG
/// used to sample candidates. One per batcher; selection requires `&mut self`
/// because P2C advances the RNG.
pub struct Router {
    strategy: RoutingStrategy,
    rng: StdRng,
}

impl Router {
    /// Production constructor — seeds the RNG from system entropy.
    pub fn new(strategy: RoutingStrategy) -> Self {
        Self {
            strategy,
            rng: StdRng::from_entropy(),
        }
    }

    /// Deterministic constructor for tests — seeds the RNG from a fixed value.
    #[cfg(test)]
    pub fn with_seed(strategy: RoutingStrategy, seed: u64) -> Self {
        Self {
            strategy,
            rng: StdRng::seed_from_u64(seed),
        }
    }

    pub fn strategy(&self) -> RoutingStrategy {
        self.strategy
    }

    /// Select a worker for one request. `load` is the current per-worker load
    /// (outstanding messages plus what has been provisionally assigned earlier
    /// in this round). Returns `None` when there are no candidates.
    pub fn select(&mut self, candidates: &[Candidate], load: &WorkerLoad) -> Option<WorkerId> {
        select_p2c(candidates, load, &mut self.rng)
    }
}

/// Weighted power-of-two-choices: sample two distinct candidates in proportion
/// to weight, and pick the one with the lower load per unit of weight, so each
/// worker's share of the requests follows its weight.
fn select_p2c(candidates: &[Candidate], load: &WorkerLoad, rng: &mut impl Rng) -> Option<WorkerId> {
    match candidates.len() {
        0 => None,
        1 => Some(candidates[0].worker.clone()),
        _ => {
            // Positions, not ids, so duplicate worker ids cannot make the
            // second draw loop.
            let total: u64 = candidates.iter().map(|c| c.weight.get()).sum();
            let i = weighted_position(candidates, rng.gen_range(0..total), None);
            let rest = total - candidates[i].weight.get();
            let j = weighted_position(candidates, rng.gen_range(0..rest), Some(i));
            let (a, b) = (&candidates[i], &candidates[j]);
            // a.load / a.weight <= b.load / b.weight, without division.
            let a_cost = load_of(load, &a.worker) as u128 * u128::from(b.weight.get());
            let b_cost = load_of(load, &b.worker) as u128 * u128::from(a.weight.get());
            Some(if a_cost <= b_cost { a } else { b }.worker.clone())
        }
    }
}

/// `point` must be below the total weight of the positions other than `skip`.
fn weighted_position(candidates: &[Candidate], mut point: u64, skip: Option<usize>) -> usize {
    for (position, candidate) in candidates.iter().enumerate() {
        if Some(position) == skip {
            continue;
        }
        let weight = candidate.weight.get();
        if point < weight {
            return position;
        }
        point -= weight;
    }
    unreachable!("point is below the total weight of the positions not skipped")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn wid(s: &str) -> WorkerId {
        WorkerId::from(s)
    }

    fn load(pairs: &[(&str, usize)]) -> WorkerLoad {
        pairs.iter().map(|(w, n)| (wid(w), *n)).collect()
    }

    const A: &str = "http://w:1";
    const B: &str = "http://w:2";
    const C: &str = "http://w:3";

    // ---- strategy parsing ----

    #[test]
    fn test_routing_strategy_parses_known_values() {
        assert_eq!("p2c".parse(), Ok(RoutingStrategy::P2c));
        assert_eq!("power-of-two".parse(), Ok(RoutingStrategy::P2c));
        assert_eq!("aperture".parse(), Ok(RoutingStrategy::Aperture));
    }

    #[test]
    fn test_routing_strategy_is_case_and_whitespace_insensitive() {
        assert_eq!("  P2C ".parse(), Ok(RoutingStrategy::P2c));
        assert_eq!("Aperture".parse(), Ok(RoutingStrategy::Aperture));
    }

    #[test]
    fn test_routing_strategy_rejects_unknown_value() {
        assert!("round-robin".parse::<RoutingStrategy>().is_err());
        assert!("binpack".parse::<RoutingStrategy>().is_err());
    }

    #[test]
    fn test_routing_strategy_defaults_to_p2c() {
        assert_eq!(RoutingStrategy::default(), RoutingStrategy::P2c);
    }

    // ---- p2c ----

    fn uniform(workers: &[&str]) -> Vec<Candidate> {
        workers.iter().map(|w| Candidate::uniform(wid(w))).collect()
    }

    fn weighted(workers: &[(&str, u64)]) -> Vec<Candidate> {
        workers
            .iter()
            .map(|(w, weight)| {
                Candidate::new(wid(w), NonZeroU64::new(*weight).unwrap(), NonZeroU64::MAX)
            })
            .collect()
    }

    #[test]
    fn test_slots_scale_the_per_worker_cap_by_the_covered_part_rounded_up() {
        struct Case {
            weight: u64,
            full_weight: u64,
            max_per_worker: usize,
            slots: usize,
        }
        let cases = [
            Case {
                weight: 1,
                full_weight: 1,
                max_per_worker: 8,
                slots: 8,
            },
            Case {
                weight: 2,
                full_weight: 4,
                max_per_worker: 8,
                slots: 4,
            },
            Case {
                weight: 1,
                full_weight: 3,
                max_per_worker: 8,
                slots: 3,
            },
            Case {
                weight: 1,
                full_weight: 100,
                max_per_worker: 4,
                slots: 1,
            },
            Case {
                weight: 9,
                full_weight: 4,
                max_per_worker: 8,
                slots: 8,
            },
        ];
        for case in cases {
            let candidate = Candidate::new(
                wid(A),
                NonZeroU64::new(case.weight).unwrap(),
                NonZeroU64::new(case.full_weight).unwrap(),
            );
            assert_eq!(
                candidate.slots(case.max_per_worker),
                case.slots,
                "{} of {}",
                case.weight,
                case.full_weight
            );
        }
    }

    #[test]
    fn test_p2c_empty_pool_returns_none() {
        let mut rng = StdRng::seed_from_u64(1);
        assert_eq!(select_p2c(&[], &WorkerLoad::new(), &mut rng), None);
    }

    #[test]
    fn test_p2c_single_worker_returns_it() {
        let mut rng = StdRng::seed_from_u64(1);
        assert_eq!(
            select_p2c(&uniform(&[C]), &load(&[(C, 9)]), &mut rng),
            Some(wid(C))
        );
    }

    #[test]
    fn test_p2c_two_workers_always_picks_lighter() {
        let candidates = uniform(&[A, B]);
        let l = load(&[(A, 3), (B, 0)]);
        for seed in 0..16 {
            let mut rng = StdRng::seed_from_u64(seed);
            assert_eq!(
                select_p2c(&candidates, &l, &mut rng),
                Some(wid(B)),
                "seed {seed}"
            );
        }
    }

    #[test]
    fn test_p2c_two_workers_picks_the_lower_load_per_unit_of_weight() {
        let candidates = weighted(&[(A, 1), (B, 4)]);
        let l = load(&[(A, 2), (B, 4)]);
        for seed in 0..16 {
            let mut rng = StdRng::seed_from_u64(seed);
            assert_eq!(
                select_p2c(&candidates, &l, &mut rng),
                Some(wid(B)),
                "seed {seed}"
            );
        }
    }

    #[test]
    fn test_p2c_terminates_with_duplicate_ids() {
        let candidates = uniform(&[C, C]);
        let mut rng = StdRng::seed_from_u64(1);
        for _ in 0..50 {
            assert_eq!(
                select_p2c(&candidates, &WorkerLoad::new(), &mut rng),
                Some(wid(C))
            );
        }
    }

    #[test]
    fn test_p2c_only_ever_returns_a_candidate() {
        let candidates = weighted(&[(A, 1), (B, 5), (C, 2)]);
        let l = load(&[(A, 2), (C, 5)]);
        let mut rng = StdRng::seed_from_u64(7);
        for _ in 0..200 {
            let pick = select_p2c(&candidates, &l, &mut rng).unwrap();
            assert!(candidates.iter().any(|c| c.worker == pick));
        }
    }

    #[test]
    fn test_p2c_spreads_across_pool() {
        let candidates = uniform(&[A, B, C]);
        let mut rng = StdRng::seed_from_u64(42);
        let mut seen = std::collections::HashSet::new();
        for _ in 0..200 {
            seen.insert(select_p2c(&candidates, &WorkerLoad::new(), &mut rng).unwrap());
        }
        assert_eq!(seen.len(), 3, "every worker should be reachable");
    }

    #[test]
    fn test_p2c_without_load_picks_in_proportion_to_weight() {
        let candidates = weighted(&[(A, 1), (B, 3)]);
        let mut rng = StdRng::seed_from_u64(3);
        let picks_of_a = (0..4000)
            .filter(|_| select_p2c(&candidates, &WorkerLoad::new(), &mut rng) == Some(wid(A)))
            .count();
        assert!((900..1100).contains(&picks_of_a), "{picks_of_a} of 4000");
    }

    #[test]
    fn test_p2c_load_held_in_flight_follows_weight() {
        let candidates = weighted(&[(A, 1), (B, 2), (C, 3)]);
        let mut rng = StdRng::seed_from_u64(9);
        let mut l = WorkerLoad::new();
        for _ in 0..600 {
            let pick = select_p2c(&candidates, &l, &mut rng).unwrap();
            *l.entry(pick).or_insert(0) += 1;
        }
        for (worker, expected) in [(A, 100), (B, 200), (C, 300)] {
            let held = load_of(&l, &wid(worker));
            assert!(
                held.abs_diff(expected) <= 10,
                "{worker}: {held}, expected {expected}"
            );
        }
    }
}
