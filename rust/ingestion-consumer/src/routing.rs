//! Worker selection strategies for the batcher's requests.
//!
//! The batcher's worker assigner owns the stateful concerns (per-worker
//! request and message load). This module is the pure decision layer: given
//! the set of healthy workers and their per-worker load, pick a target.
//! Keeping it free of batcher state makes the algorithms trivially
//! unit-testable and lets the routing policy evolve (P2C cost functions,
//! subsetting) without touching the batcher's bookkeeping.

use std::collections::HashMap;
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
    /// its slice of the worker ring (see [`crate::aperture`]), with P2C
    /// selection inside the slice. Consolidates small batches onto few workers
    /// while the fleet's slices still tile the whole pool. Requires peer
    /// awareness (`PEER_SERVICE_NAME`); behaves as plain P2C over the full
    /// pool while the peer set is unknown.
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

    /// Select a worker for one request. `healthy` lists candidate worker ids;
    /// `load` is the current per-worker load (outstanding messages plus what has
    /// been provisionally assigned earlier in this round). Returns `None` when
    /// no workers are healthy.
    pub fn select(&mut self, healthy: &[WorkerId], load: &WorkerLoad) -> Option<WorkerId> {
        // Aperture narrows the candidate slice upstream (in the worker pool);
        // within the slice it selects exactly like P2C.
        select_p2c(healthy, load, &mut self.rng)
    }
}

/// Pick the lighter of two distinct random healthy workers. Degenerates to the
/// single worker when the pool has one, and to `None` when it is empty.
fn select_p2c(healthy: &[WorkerId], load: &WorkerLoad, rng: &mut impl Rng) -> Option<WorkerId> {
    match healthy.len() {
        0 => None,
        1 => Some(healthy[0].clone()),
        len => {
            // Sample two distinct *positions* in one step (no redraw loop): pick
            // the first, then offset by 1..len to land on a different position.
            // This terminates regardless of the slice's contents, so it stays
            // correct even if a caller ever passes duplicate worker ids.
            let i = rng.gen_range(0..len);
            let j = (i + 1 + rng.gen_range(0..len - 1)) % len;
            let (a, b) = (&healthy[i], &healthy[j]);
            Some(if load_of(load, a) <= load_of(load, b) {
                a.clone()
            } else {
                b.clone()
            })
        }
    }
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

    #[test]
    fn test_p2c_empty_pool_returns_none() {
        let mut rng = StdRng::seed_from_u64(1);
        assert_eq!(select_p2c(&[], &WorkerLoad::new(), &mut rng), None);
    }

    #[test]
    fn test_p2c_single_worker_returns_it() {
        let mut rng = StdRng::seed_from_u64(1);
        assert_eq!(
            select_p2c(&[wid(C)], &load(&[(C, 9)]), &mut rng),
            Some(wid(C))
        );
    }

    #[test]
    fn test_p2c_two_workers_always_picks_lighter() {
        // With exactly two candidates, sampling-without-replacement always draws
        // both, so the lighter one is chosen deterministically regardless of seed.
        let healthy = [wid(A), wid(B)];
        let l = load(&[(A, 3), (B, 0)]);
        for seed in 0..16 {
            let mut rng = StdRng::seed_from_u64(seed);
            assert_eq!(
                select_p2c(&healthy, &l, &mut rng),
                Some(wid(B)),
                "seed {seed}"
            );
        }
    }

    #[test]
    fn test_p2c_terminates_with_duplicate_ids() {
        // Regression: selection must not loop even if the candidate slice
        // contains duplicate worker ids.
        let healthy = [wid(C), wid(C)];
        let mut rng = StdRng::seed_from_u64(1);
        for _ in 0..50 {
            assert_eq!(
                select_p2c(&healthy, &WorkerLoad::new(), &mut rng),
                Some(wid(C))
            );
        }
    }

    #[test]
    fn test_p2c_only_ever_returns_a_healthy_worker() {
        let healthy = [wid(A), wid(B), wid(C)];
        let l = load(&[(A, 2), (C, 5)]);
        let mut rng = StdRng::seed_from_u64(7);
        for _ in 0..200 {
            let pick = select_p2c(&healthy, &l, &mut rng).unwrap();
            assert!(healthy.contains(&pick));
        }
    }

    #[test]
    fn test_p2c_spreads_across_pool() {
        let healthy = [wid(A), wid(B), wid(C)];
        let mut rng = StdRng::seed_from_u64(42);
        let mut seen = std::collections::HashSet::new();
        for _ in 0..200 {
            seen.insert(select_p2c(&healthy, &WorkerLoad::new(), &mut rng).unwrap());
        }
        assert_eq!(seen.len(), 3, "every worker should be reachable");
    }
}
