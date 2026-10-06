//! Picks each request's worker when it is sent, against the load in flight.
//! A worker at its request cap takes no new request, so one slow worker
//! cannot hold every send slot.

use std::collections::HashMap;

use crate::routing::{Router, WorkerLoad};
use crate::worker_registry::WorkerId;

pub struct WorkerAssigner {
    router: Router,
    max_requests_per_worker: usize,
    message_load: WorkerLoad,
    request_load: HashMap<WorkerId, usize>,
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

    pub fn in_flight_messages(&self) -> usize {
        self.message_load.values().sum()
    }

    pub fn prefers_largest_first(&self) -> bool {
        self.router.prefers_largest_first()
    }

    pub fn free_slots(&self, pool: &[WorkerId]) -> usize {
        pool.iter()
            .map(|worker| self.max_requests_per_worker - self.requests_on(worker))
            .sum()
    }

    pub fn assign(&mut self, pool: &[WorkerId], message_count: usize) -> Option<WorkerId> {
        let open: Vec<WorkerId> = pool
            .iter()
            .filter(|worker| self.requests_on(worker) < self.max_requests_per_worker)
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
    use super::*;
    use crate::routing::RoutingStrategy;

    fn wid(s: &str) -> WorkerId {
        WorkerId::from(s)
    }

    #[test]
    fn a_zero_request_cap_is_rejected() {
        assert!(WorkerAssigner::new(Router::new(RoutingStrategy::BinPack), 0).is_err());
    }

    #[test]
    fn a_worker_at_the_request_cap_is_skipped_until_a_request_settles() {
        let pool = vec![wid("a"), wid("b")];
        let mut assigner = WorkerAssigner::new(Router::new(RoutingStrategy::BinPack), 1).unwrap();

        assert_eq!(assigner.assign(&pool, 10), Some(wid("a")));
        assert_eq!(assigner.assign(&pool, 10), Some(wid("b")));
        assert_eq!(assigner.assign(&pool, 10), None, "both at the cap");
        assert_eq!(assigner.free_slots(&pool), 0);

        assert!(assigner.release(&wid("a"), 10));
        assert_eq!(assigner.assign(&pool, 10), Some(wid("a")));
    }

    #[test]
    fn placement_follows_the_in_flight_message_load() {
        let pool = vec![wid("a"), wid("b")];
        let mut assigner = WorkerAssigner::new(Router::new(RoutingStrategy::BinPack), 10).unwrap();

        assert_eq!(assigner.assign(&pool, 100), Some(wid("a")));
        assert_eq!(assigner.assign(&pool, 1), Some(wid("b")));
        assert_eq!(assigner.assign(&pool, 1), Some(wid("b")), "b is lighter");
    }
}
