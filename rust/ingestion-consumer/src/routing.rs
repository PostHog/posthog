//! Worker selection strategies for unpinned routing keys.
//!
//! The dispatcher owns the stateful concerns (grouping, sticky pins, ref-counts,
//! in-flight accounting). This module is the pure decision layer: given the set
//! of healthy workers and their per-worker load, pick a target. Keeping it free
//! of dispatcher state makes the algorithms trivially unit-testable and lets the
//! routing policy evolve (P2C cost functions, subsetting) without touching the
//! dispatcher's bookkeeping.

use std::str::FromStr;

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

/// How unpinned routing keys are assigned to workers. Pinned keys always go to
/// their existing worker regardless of strategy.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum RoutingStrategy {
    /// Largest-first bin-packing onto the globally least-loaded worker. Accurate
    /// when one consumer exclusively owns its workers (the co-located sidecar),
    /// because then this consumer's in-flight counts are the ground truth.
    #[default]
    BinPack,
    /// Power-of-two-choices: sample two random workers, pick the lighter. Herd
    /// resistant when many consumers share a worker pool, because each consumer
    /// samples a different random pair instead of converging on one global best.
    P2c,
}

impl FromStr for RoutingStrategy {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "binpack" | "bin_pack" | "bin-pack" => Ok(RoutingStrategy::BinPack),
            "p2c" | "power_of_two" | "power-of-two" => Ok(RoutingStrategy::P2c),
            other => Err(format!(
                "unknown routing strategy '{other}' (expected 'binpack' or 'p2c')"
            )),
        }
    }
}

/// Stateful worker selector. Holds the routing strategy and, for P2C, the RNG
/// used to sample candidates. One per dispatcher; selection requires `&mut self`
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
    pub fn with_seed(strategy: RoutingStrategy, seed: u64) -> Self {
        Self {
            strategy,
            rng: StdRng::seed_from_u64(seed),
        }
    }

    pub fn strategy(&self) -> RoutingStrategy {
        self.strategy
    }

    /// Whether the caller should present groups largest-first before selecting.
    /// Bin-packing wants the heavy hitters placed first so they drive the load
    /// distribution; P2C is per-group and order-independent.
    pub fn prefers_largest_first(&self) -> bool {
        matches!(self.strategy, RoutingStrategy::BinPack)
    }

    /// Select a worker for one group. `healthy` lists candidate worker indices;
    /// `in_flight` and `provisional` are indexed by worker index, and a worker's
    /// load is their sum (outstanding messages plus what has been provisionally
    /// assigned earlier in this round). Returns `None` when no workers are
    /// healthy.
    pub fn select(
        &mut self,
        healthy: &[usize],
        in_flight: &[usize],
        provisional: &[usize],
    ) -> Option<usize> {
        match self.strategy {
            RoutingStrategy::BinPack => select_least_loaded(healthy, in_flight, provisional),
            RoutingStrategy::P2c => select_p2c(healthy, in_flight, provisional, &mut self.rng),
        }
    }
}

/// Pick the globally least-loaded healthy worker. Ties resolve to the lowest
/// worker index (matching the prior `min_by_key` behavior).
fn select_least_loaded(
    healthy: &[usize],
    in_flight: &[usize],
    provisional: &[usize],
) -> Option<usize> {
    healthy
        .iter()
        .copied()
        .min_by_key(|&idx| in_flight[idx] + provisional[idx])
}

/// Pick the lighter of two distinct random healthy workers. Degenerates to the
/// single worker when the pool has one, and to `None` when it is empty.
fn select_p2c(
    healthy: &[usize],
    in_flight: &[usize],
    provisional: &[usize],
    rng: &mut impl Rng,
) -> Option<usize> {
    let load = |idx: usize| in_flight[idx] + provisional[idx];
    match healthy.len() {
        0 => None,
        1 => Some(healthy[0]),
        len => {
            let a = healthy[rng.gen_range(0..len)];
            // Sample without replacement: redraw until distinct from the first pick.
            let mut b = healthy[rng.gen_range(0..len)];
            while b == a {
                b = healthy[rng.gen_range(0..len)];
            }
            Some(if load(a) <= load(b) { a } else { b })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ---- strategy parsing ----

    #[test]
    fn test_routing_strategy_parses_known_values() {
        assert_eq!("binpack".parse(), Ok(RoutingStrategy::BinPack));
        assert_eq!("bin-pack".parse(), Ok(RoutingStrategy::BinPack));
        assert_eq!("p2c".parse(), Ok(RoutingStrategy::P2c));
        assert_eq!("power-of-two".parse(), Ok(RoutingStrategy::P2c));
    }

    #[test]
    fn test_routing_strategy_is_case_and_whitespace_insensitive() {
        assert_eq!("  P2C ".parse(), Ok(RoutingStrategy::P2c));
        assert_eq!("BinPack".parse(), Ok(RoutingStrategy::BinPack));
    }

    #[test]
    fn test_routing_strategy_rejects_unknown_value() {
        assert!("round-robin".parse::<RoutingStrategy>().is_err());
    }

    #[test]
    fn test_routing_strategy_defaults_to_binpack() {
        assert_eq!(RoutingStrategy::default(), RoutingStrategy::BinPack);
    }

    // ---- least-loaded ----

    #[test]
    fn test_least_loaded_picks_minimum_load() {
        let healthy = [0, 1, 2];
        let in_flight = [5, 1, 3];
        let provisional = [0, 0, 0];
        assert_eq!(
            select_least_loaded(&healthy, &in_flight, &provisional),
            Some(1)
        );
    }

    #[test]
    fn test_least_loaded_sums_in_flight_and_provisional() {
        let healthy = [0, 1];
        let in_flight = [0, 1];
        // Provisional flips which worker is lighter.
        let provisional = [3, 0];
        assert_eq!(
            select_least_loaded(&healthy, &in_flight, &provisional),
            Some(1)
        );
    }

    #[test]
    fn test_least_loaded_breaks_ties_to_lowest_index() {
        let healthy = [0, 1, 2];
        let in_flight = [2, 2, 2];
        let provisional = [0, 0, 0];
        assert_eq!(
            select_least_loaded(&healthy, &in_flight, &provisional),
            Some(0)
        );
    }

    #[test]
    fn test_least_loaded_empty_pool_returns_none() {
        assert_eq!(select_least_loaded(&[], &[], &[]), None);
    }

    // ---- p2c ----

    #[test]
    fn test_p2c_empty_pool_returns_none() {
        let mut rng = StdRng::seed_from_u64(1);
        assert_eq!(select_p2c(&[], &[], &[], &mut rng), None);
    }

    #[test]
    fn test_p2c_single_worker_returns_it() {
        let mut rng = StdRng::seed_from_u64(1);
        assert_eq!(select_p2c(&[2], &[0, 0, 9], &[0, 0, 0], &mut rng), Some(2));
    }

    #[test]
    fn test_p2c_two_workers_always_picks_lighter() {
        // With exactly two candidates, sampling-without-replacement always draws
        // both, so the lighter one is chosen deterministically regardless of seed.
        for seed in 0..16 {
            let mut rng = StdRng::seed_from_u64(seed);
            assert_eq!(
                select_p2c(&[0, 1], &[3, 0], &[0, 0], &mut rng),
                Some(1),
                "seed {seed}"
            );
        }
    }

    #[test]
    fn test_p2c_only_ever_returns_a_healthy_worker() {
        let healthy = [1, 3, 4];
        let in_flight = [0, 2, 0, 5, 1];
        let provisional = [0; 5];
        let mut rng = StdRng::seed_from_u64(7);
        for _ in 0..200 {
            let pick = select_p2c(&healthy, &in_flight, &provisional, &mut rng).unwrap();
            assert!(healthy.contains(&pick));
        }
    }

    #[test]
    fn test_p2c_spreads_load_across_pool() {
        // A heavily skewed start should let P2C drain onto every worker over many
        // rounds (it never gets stuck on one). Assert all workers get picked.
        let healthy = [0, 1, 2, 3];
        let in_flight = [0, 0, 0, 0];
        let provisional = [0; 4];
        let mut rng = StdRng::seed_from_u64(42);
        let mut seen = [false; 4];
        for _ in 0..200 {
            let pick = select_p2c(&healthy, &in_flight, &provisional, &mut rng).unwrap();
            seen[pick] = true;
        }
        assert!(seen.iter().all(|&s| s), "every worker should be reachable");
    }

    // ---- router dispatch ----

    #[test]
    fn test_router_binpack_selects_least_loaded() {
        let mut router = Router::new(RoutingStrategy::BinPack);
        assert!(router.prefers_largest_first());
        assert_eq!(router.select(&[0, 1, 2], &[4, 1, 2], &[0, 0, 0]), Some(1));
    }

    #[test]
    fn test_router_p2c_does_not_prefer_largest_first() {
        let router = Router::with_seed(RoutingStrategy::P2c, 1);
        assert!(!router.prefers_largest_first());
        assert_eq!(router.strategy(), RoutingStrategy::P2c);
    }
}
