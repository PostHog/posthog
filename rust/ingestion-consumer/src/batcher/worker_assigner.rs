//! Picks each request's worker when it is sent, against the load in flight.

use std::collections::HashMap;

use crate::routing::{Candidate, Router, WorkerLoad};
use crate::worker_registry::WorkerId;

pub struct WorkerAssigner {
    router: Router,
    max_requests_per_worker: usize,
    message_load: WorkerLoad,
    request_load: HashMap<WorkerId, usize>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkerInFlight {
    pub worker: WorkerId,
    pub requests: usize,
    pub messages: usize,
}

impl WorkerAssigner {
    pub fn new(router: Router, max_requests_per_worker: usize) -> Result<Self, String> {
        if max_requests_per_worker == 0 {
            return Err("max_requests_per_worker must be > 0".to_string());
        }
        Ok(Self {
            router,
            max_requests_per_worker,
            message_load: WorkerLoad::new(),
            request_load: HashMap::new(),
        })
    }

    pub fn max_requests_per_worker(&self) -> usize {
        self.max_requests_per_worker
    }

    pub fn in_flight_messages(&self) -> usize {
        self.message_load.values().sum()
    }

    /// Every worker with a request in flight.
    pub fn in_flight_per_worker(&self) -> Vec<WorkerInFlight> {
        self.request_load
            .iter()
            .map(|(worker, requests)| WorkerInFlight {
                worker: worker.clone(),
                requests: *requests,
                messages: self.message_load.get(worker).copied().unwrap_or(0),
            })
            .collect()
    }

    pub fn free_slots(&self, pool: &[Candidate]) -> usize {
        pool.iter()
            .map(|candidate| {
                candidate
                    .slots(self.max_requests_per_worker)
                    .saturating_sub(self.requests_on(&candidate.worker))
            })
            .sum()
    }

    pub fn assign(&mut self, pool: &[Candidate], message_count: usize) -> Option<WorkerId> {
        // A worker at the cap is skipped, so one slow worker cannot hold
        // every send slot.
        let open: Vec<Candidate> = pool
            .iter()
            .filter(|candidate| {
                self.requests_on(&candidate.worker) < candidate.slots(self.max_requests_per_worker)
            })
            .cloned()
            .collect();
        let worker = self.router.select(&open, &self.message_load)?;
        *self.message_load.entry(worker.clone()).or_insert(0) += message_count;
        *self.request_load.entry(worker.clone()).or_insert(0) += 1;
        Some(worker)
    }

    /// True when the worker has nothing left in flight.
    pub fn release(&mut self, worker: &WorkerId, message_count: usize) -> bool {
        if let Some(load) = self.message_load.get_mut(worker) {
            *load = load.saturating_sub(message_count);
        }
        let idle = match self.request_load.get_mut(worker) {
            Some(requests) => {
                *requests = requests.saturating_sub(1);
                *requests == 0
            }
            None => true,
        };
        if idle {
            self.request_load.remove(worker);
            self.message_load.remove(worker);
        }
        idle
    }

    pub fn requests_on(&self, worker: &WorkerId) -> usize {
        self.request_load.get(worker).copied().unwrap_or(0)
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU64;

    use super::*;
    use crate::routing::RoutingStrategy;

    fn wid(s: &str) -> WorkerId {
        WorkerId::from(s)
    }

    fn pool(workers: &[&str]) -> Vec<Candidate> {
        workers.iter().map(|w| Candidate::uniform(wid(w))).collect()
    }

    #[test]
    fn a_zero_request_cap_is_rejected() {
        assert!(WorkerAssigner::new(Router::new(RoutingStrategy::P2c), 0).is_err());
    }

    #[test]
    fn a_worker_at_the_request_cap_is_skipped_until_a_request_settles() {
        let pool = pool(&["a", "b"]);
        let mut assigner =
            WorkerAssigner::new(Router::with_seed(RoutingStrategy::P2c, 0), 1).unwrap();

        let first = assigner.assign(&pool, 10).unwrap();
        let second = assigner.assign(&pool, 10).unwrap();
        assert_ne!(first, second);
        assert_eq!(assigner.assign(&pool, 10), None, "both at the cap");
        assert_eq!(assigner.free_slots(&pool), 0);

        assert!(assigner.release(&first, 10));
        assert_eq!(assigner.assign(&pool, 10), Some(first));
    }

    #[test]
    fn a_candidate_covering_part_of_a_worker_gets_that_part_of_its_slots() {
        let quarters = |w: &str, n: u64| {
            Candidate::new(
                wid(w),
                NonZeroU64::new(n).unwrap(),
                NonZeroU64::new(4).unwrap(),
            )
        };
        let pool = vec![quarters("whole", 4), quarters("half", 2)];
        let mut assigner =
            WorkerAssigner::new(Router::with_seed(RoutingStrategy::P2c, 0), 4).unwrap();
        assert_eq!(assigner.free_slots(&pool), 6);

        let mut sent = HashMap::new();
        while let Some(worker) = assigner.assign(&pool, 1) {
            *sent.entry(worker).or_insert(0) += 1;
        }
        assert_eq!(sent, HashMap::from([(wid("whole"), 4), (wid("half"), 2)]));
        assert_eq!(assigner.free_slots(&pool), 0);
    }

    #[test]
    fn placement_follows_the_in_flight_message_load() {
        let pool = pool(&["a", "b"]);
        let mut assigner =
            WorkerAssigner::new(Router::with_seed(RoutingStrategy::P2c, 0), 10).unwrap();

        let heavy = assigner.assign(&pool, 100).unwrap();
        let light = assigner.assign(&pool, 1).unwrap();
        assert_ne!(heavy, light);
        assert_eq!(
            assigner.assign(&pool, 1),
            Some(light),
            "the other worker is lighter"
        );
    }
}
