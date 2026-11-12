use std::collections::{HashMap, HashSet};
use std::num::NonZeroUsize;
use std::time::{Duration, Instant};

use super::governor::{Adaptation, GovernorSettings};
use super::key_queues::KeyRun;
use super::packer::{PackTargets, Packer};
use super::retry_policy::RetryPolicy;
use super::state_machine::BatcherStateMachine;
use super::test_support::message;
use super::worker_assigner::WorkerAssigner;
use crate::aperture::{ring_slice, sorted_ring};
use crate::routing::{Candidate, Router, RoutingStrategy};
use crate::worker_registry::WorkerId;

const LATENCY_BUDGET: Duration = Duration::from_secs(1);
const SLOW_RTT: Duration = Duration::from_secs(2);

#[derive(Debug)]
struct Fleet {
    workers: usize,
    peers: usize,
    min_width: usize,
    max_per_worker: usize,
    min_permits: usize,
    draining: Vec<usize>,
    unhealthy: Vec<usize>,
}

impl Fleet {
    fn new(workers: usize, peers: usize, min_width: usize, max: usize, min: usize) -> Self {
        Self {
            workers,
            peers,
            min_width,
            max_per_worker: max,
            min_permits: min,
            draining: Vec::new(),
            unhealthy: Vec::new(),
        }
    }

    fn draining(self, positions: impl IntoIterator<Item = usize>) -> Self {
        Self {
            draining: positions.into_iter().collect(),
            ..self
        }
    }

    fn unhealthy(self, positions: impl IntoIterator<Item = usize>) -> Self {
        Self {
            unhealthy: positions.into_iter().collect(),
            ..self
        }
    }

    fn worker(position: usize) -> WorkerId {
        WorkerId::from(format!("http://10.0.{}.{}:6738", position / 200, position % 200).as_str())
    }

    fn ring(&self) -> Vec<WorkerId> {
        sorted_ring(
            (0..self.workers)
                .filter(|p| !self.draining.contains(p))
                .map(Self::worker)
                .collect(),
        )
    }

    fn healthy(&self) -> Vec<WorkerId> {
        let unhealthy: HashSet<WorkerId> =
            self.unhealthy.iter().map(|p| Self::worker(*p)).collect();
        self.ring()
            .into_iter()
            .filter(|w| !unhealthy.contains(w))
            .collect()
    }

    fn slices(&self) -> Vec<Vec<Candidate>> {
        let (ring, healthy) = (self.ring(), self.healthy());
        (0..self.peers)
            .map(|index| {
                let slice = ring_slice(&ring, &healthy, Some(index), self.peers, self.min_width)
                    .expect("every peer gets a slice");
                assert!(
                    !slice.is_empty(),
                    "{self:?}: peer {index} got an empty slice"
                );
                slice
            })
            .collect()
    }

    fn batcher(&self, now: Instant) -> BatcherStateMachine {
        let packer = Packer::new(PackTargets {
            events: NonZeroUsize::new(1),
            bytes: None,
            latency_budget: Duration::ZERO,
        });
        let assigner = WorkerAssigner::new(
            Router::with_seed(RoutingStrategy::Aperture, 0),
            self.max_per_worker,
        )
        .expect("valid request cap");
        let retry = RetryPolicy::new(
            Duration::from_millis(200),
            Duration::from_millis(20),
            Duration::from_millis(100),
        )
        .expect("valid retry policy");
        BatcherStateMachine::new(packer, assigner, retry, Duration::from_secs(60), now)
            .expect("valid batcher")
            .with_governor(GovernorSettings {
                adaptation: Adaptation::On,
                latency_budget: Some(LATENCY_BUDGET),
                min_permits_per_worker: self.min_permits,
                ..GovernorSettings::observing()
            })
            .expect("valid governor settings")
    }
}

fn backlog(requests: usize) -> Vec<KeyRun> {
    (0..requests)
        .map(|n| {
            let key = format!("k{n}");
            KeyRun {
                messages: vec![message(&key, 0, n as i64)],
                routing_key: key.into(),
            }
        })
        .collect()
}

fn requests_held_under_a_backlog(fleet: &Fleet) -> HashMap<WorkerId, usize> {
    let now = Instant::now();
    let mut held = HashMap::new();
    for slice in fleet.slices() {
        let requests = slice.len() * fleet.max_per_worker + 1;
        let (_, effects) = fleet
            .batcher(now)
            .on_groups(now, &slice, 0, backlog(requests));
        for send in effects.sends {
            *held.entry(send.worker).or_insert(0) += 1;
        }
    }
    held
}

fn traffic_shares(fleet: &Fleet) -> HashMap<WorkerId, f64> {
    let mut share = HashMap::new();
    for slice in fleet.slices() {
        let total: u64 = slice.iter().map(|c| c.weight.get()).sum();
        for candidate in slice {
            *share.entry(candidate.worker).or_insert(0.0) +=
                candidate.weight.get() as f64 / total as f64;
        }
    }
    share
}

fn fleets() -> Vec<Fleet> {
    vec![
        Fleet::new(6, 4, 3, 4, 3),
        Fleet::new(6, 4, 3, 1, 1),
        Fleet::new(7, 3, 1, 8, 7),
        Fleet::new(2, 4, 1, 4, 3),
        Fleet::new(3, 5, 1, 2, 1),
        Fleet::new(12, 30, 3, 4, 2),
        Fleet::new(60, 7, 3, 8, 4),
        Fleet::new(100, 17, 3, 8, 7).draining(25..50),
        Fleet::new(40, 40, 3, 4, 3).draining((0..40).step_by(5)),
        Fleet::new(100, 17, 3, 8, 4).unhealthy([10]),
        Fleet::new(60, 7, 3, 8, 4).unhealthy([3, 4, 5]),
    ]
}

#[test]
fn every_healthy_worker_is_in_some_slice() {
    for fleet in fleets() {
        let covered: HashSet<WorkerId> = fleet
            .slices()
            .into_iter()
            .flatten()
            .map(|c| c.worker)
            .collect();
        let healthy: HashSet<WorkerId> = fleet.healthy().into_iter().collect();
        assert_eq!(covered, healthy, "{fleet:?}");
    }
}

#[test]
fn without_unhealthy_workers_every_worker_gets_the_same_share_of_the_traffic() {
    for fleet in fleets().into_iter().filter(|f| f.unhealthy.is_empty()) {
        let expected = fleet.peers as f64 / fleet.ring().len() as f64;
        for (worker, got) in traffic_shares(&fleet) {
            assert!(
                (got - expected).abs() < 1e-9,
                "{fleet:?}: {worker} gets {got}"
            );
        }
    }
}

#[test]
fn with_a_large_unhealthy_block_no_worker_gets_more_than_two_and_a_half_times_the_mean_share() {
    let blocks = [
        Fleet::new(464, 77, 3, 8, 4).unhealthy(100..216),
        Fleet::new(334, 18, 3, 8, 4).unhealthy(0..84),
        Fleet::new(100, 17, 3, 8, 4).unhealthy(40..65),
        Fleet::new(60, 7, 3, 8, 4).unhealthy(10..25),
    ];
    for fleet in blocks {
        let mean = fleet.peers as f64 / fleet.healthy().len() as f64;
        let hottest = traffic_shares(&fleet).values().cloned().fold(0.0, f64::max);
        assert!(
            hottest <= 2.5 * mean,
            "{fleet:?}: {:.2} x the mean",
            hottest / mean
        );
    }
}

#[test]
fn under_a_backlog_no_worker_holds_more_than_one_extra_slot_in_max_per_worker() {
    for fleet in fleets() {
        let held = requests_held_under_a_backlog(&fleet);
        let most = *held.values().max().unwrap();
        let least = *held.values().min().unwrap();
        assert!(
            most * fleet.max_per_worker <= least * (fleet.max_per_worker + 1),
            "{fleet:?}: {least} to {most} requests per worker"
        );
    }
}

#[test]
fn a_slow_response_shrinks_every_peer_that_has_room_to_shrink() {
    let now = Instant::now();
    for fleet in fleets()
        .into_iter()
        .filter(|f| f.min_permits < f.max_per_worker)
    {
        for slice in fleet.slices() {
            let requests = slice.len() * fleet.max_per_worker;
            let (batcher, effects) =
                fleet
                    .batcher(now)
                    .on_groups(now, &slice, 0, backlog(requests));
            let ceiling = batcher.snapshot().governor.ceiling;
            if ceiling < 2 {
                continue;
            }
            let first = effects.sends[0].request;
            let (batcher, _) = batcher.on_request_succeeded(now + SLOW_RTT, &slice, first, 1);
            assert_eq!(
                batcher.snapshot().governor.permits,
                ceiling - 1,
                "{fleet:?}: {slice:?}"
            );
        }
    }
}
