//! Deterministic aperture: weighted ring-slice candidate selection.
//!
//! Every consumer sorts the full worker set into the same ring, takes an arc
//! of it, and places its requests only on the workers under that arc (via the
//! configured selection strategy). Because peers agree on both the ring order
//! (same EndpointSlices, same sort) and their own indices
//! ([`k8s_awareness::PeerTracker`]), the arcs need no coordination, so each
//! consumer talks to a handful of workers instead of the whole pool, which is
//! what keeps sub-batches consolidated. Modeled on Finagle's deterministic
//! aperture.
//!
//! The ring is measured in units: each worker spans `peer_count` units, so the
//! ring is `ring_len x peer_count` units long. Peer `i`'s arc starts at unit
//! `i x ring_len` and is `m x ring_len` units long, where
//! `m = ceil(min_width x peer_count / ring_len)`. So the arcs start at equal
//! distances, every unit is under exactly `m` arcs, and every worker gets the
//! same total weight, `m x peer_count`, from the fleet. A worker gets the
//! weight of the units of it that the arc covers, so a worker at an end of the
//! arc gets a smaller share of this consumer's requests.
//!
//! Unroutable ring positions (unhealthy or draining workers) are skipped and
//! the arc extends further around the ring, so the *effective* width holds
//! under partial failure.

use std::collections::HashSet;
use std::num::NonZeroU64;

use crate::routing::Candidate;
use crate::worker_registry::WorkerId;

/// The weighted candidate workers for one assignment round: walk the ring
/// from the start of this dispatcher's arc, giving each healthy worker the
/// units of it that the arc covers, until the arc is used up or the ring is
/// exhausted. `ring` is the canonically sorted full worker set; `healthy` the
/// subset this dispatcher may route to.
///
/// Returns `None` (caller falls back to the full healthy pool) when the
/// slice can't be computed: no peers known yet, an out-of-range index, or an
/// empty ring.
pub fn ring_slice(
    ring: &[WorkerId],
    healthy: &[WorkerId],
    peer_index: Option<usize>,
    peer_count: usize,
    min_width: usize,
) -> Option<Vec<Candidate>> {
    let index = peer_index?;
    if ring.is_empty() || peer_count == 0 || index >= peer_count || min_width == 0 {
        return None;
    }

    let ring_len = ring.len() as u64;
    let peers = peer_count as u64;
    let multiple = (min_width as u64 * peers)
        .div_ceil(ring_len)
        .clamp(1, peers);
    let start = index as u64 * ring_len;
    let first = (start / peers) as usize;
    let mut remaining = multiple * ring_len;

    let full_weight = NonZeroU64::new(peers)?;
    let healthy_set: HashSet<&WorkerId> = healthy.iter().collect();
    let mut candidates: Vec<Candidate> = Vec::new();
    // One step past a full turn: an arc that ends in its first worker covers
    // the units of that worker before the start.
    for offset in 0..=ring.len() {
        if remaining == 0 {
            break;
        }
        let worker = &ring[(first + offset) % ring.len()];
        if !healthy_set.contains(worker) {
            continue;
        }
        let span = if offset == 0 {
            peers - start % peers
        } else if offset == ring.len() {
            start % peers
        } else {
            peers
        };
        let Some(weight) = NonZeroU64::new(span.min(remaining)) else {
            continue;
        };
        remaining -= weight.get();
        match candidates.first_mut() {
            Some(head) if offset == ring.len() && head.worker == *worker => {
                head.weight = head.weight.saturating_add(weight.get());
            }
            _ => candidates.push(Candidate::new(worker.clone(), weight, full_weight)),
        }
    }

    if candidates.is_empty() {
        return None;
    }
    Some(candidates)
}

/// The canonical worker ring: the full registered set, sorted. All dispatchers
/// see the same EndpointSlices, so sorting gives them the same ring.
pub fn sorted_ring(mut workers: Vec<WorkerId>) -> Vec<WorkerId> {
    workers.sort_unstable();
    workers
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    fn wid(n: usize) -> WorkerId {
        WorkerId::from(format!("http://10.0.0.{n}:6738").as_str())
    }

    fn ring(n: usize) -> Vec<WorkerId> {
        sorted_ring((1..=n).map(wid).collect())
    }

    fn weights(slice: &[Candidate]) -> Vec<(WorkerId, u64)> {
        slice
            .iter()
            .map(|c| (c.worker.clone(), c.weight.get()))
            .collect()
    }

    fn fleet_weights(ring: &[WorkerId], peers: usize, min_width: usize) -> HashMap<WorkerId, u64> {
        let mut total = HashMap::new();
        for index in 0..peers {
            for candidate in ring_slice(ring, ring, Some(index), peers, min_width).unwrap() {
                *total.entry(candidate.worker).or_insert(0) += candidate.weight.get();
            }
        }
        total
    }

    #[test]
    fn test_slices_tile_the_ring_across_peers() {
        let ring = ring(6);
        let mut seen = Vec::new();
        for index in 0..3 {
            let slice = ring_slice(&ring, &ring, Some(index), 3, 2).unwrap();
            assert_eq!(slice.len(), 2, "peer {index}");
            seen.extend(slice.into_iter().map(|c| c.worker));
        }
        seen.sort_unstable();
        seen.dedup();
        assert_eq!(seen.len(), 6, "slices must tile the ring without overlap");
    }

    #[test]
    fn test_every_worker_gets_the_same_fleet_weight_when_peers_do_not_divide_the_ring() {
        struct Case {
            workers: usize,
            peers: usize,
            min_width: usize,
        }
        let cases = [
            Case {
                workers: 7,
                peers: 3,
                min_width: 1,
            },
            Case {
                workers: 100,
                peers: 17,
                min_width: 3,
            },
            Case {
                workers: 250,
                peers: 30,
                min_width: 3,
            },
            Case {
                workers: 250,
                peers: 30,
                min_width: 32,
            },
            Case {
                workers: 50,
                peers: 8,
                min_width: 48,
            },
            Case {
                workers: 3,
                peers: 5,
                min_width: 1,
            },
            Case {
                workers: 5,
                peers: 3,
                min_width: 10,
            },
        ];
        for case in cases {
            let ring = ring(case.workers);
            let total = fleet_weights(&ring, case.peers, case.min_width);
            assert_eq!(total.len(), case.workers, "every worker is covered");
            let distinct: HashSet<u64> = total.values().copied().collect();
            assert_eq!(
                distinct.len(),
                1,
                "{} workers, {} peers, min width {}: {distinct:?}",
                case.workers,
                case.peers,
                case.min_width
            );
        }
    }

    #[test]
    fn test_every_worker_gets_the_same_fleet_slots_when_arcs_end_inside_workers() {
        let ring = ring(6);
        let mut slots: HashMap<WorkerId, usize> = HashMap::new();
        for index in 0..4 {
            for candidate in ring_slice(&ring, &ring, Some(index), 4, 3).unwrap() {
                *slots.entry(candidate.worker.clone()).or_insert(0) += candidate.slots(8);
            }
        }
        assert_eq!(slots.len(), 6);
        assert!(slots.values().all(|n| *n == 16), "{slots:?}");
    }

    #[test]
    fn test_arc_ends_get_the_covered_part_of_the_worker() {
        let ring = ring(7);
        let slice = ring_slice(&ring, &ring, Some(1), 3, 1).unwrap();
        assert_eq!(
            weights(&slice),
            vec![
                (ring[2].clone(), 2),
                (ring[3].clone(), 3),
                (ring[4].clone(), 2),
            ]
        );
    }

    #[test]
    fn test_width_is_at_least_the_minimum() {
        let ring = ring(8);
        let slice = ring_slice(&ring, &ring, Some(0), 2, 5).unwrap();
        assert_eq!(slice.len(), 8);
    }

    #[test]
    fn test_slice_wraps_around_the_ring() {
        let ring = ring(5);
        let slice = ring_slice(&ring, &ring, Some(2), 3, 3).unwrap();
        assert_eq!(
            weights(&slice),
            vec![
                (ring[3].clone(), 2),
                (ring[4].clone(), 3),
                (ring[0].clone(), 3),
                (ring[1].clone(), 2),
            ]
        );
    }

    #[test]
    fn test_an_arc_over_the_whole_ring_gives_every_worker_the_same_weight() {
        let ring = ring(4);
        let slice = ring_slice(&ring, &ring, Some(1), 3, 10).unwrap();
        assert_eq!(slice.len(), 4);
        assert!(slice.iter().all(|c| c.weight.get() == 3), "{slice:?}");
    }

    #[test]
    fn test_slice_extends_past_unhealthy_workers() {
        let ring = ring(6);
        let healthy: Vec<WorkerId> = ring.iter().filter(|w| **w != ring[1]).cloned().collect();
        let slice = ring_slice(&ring, &healthy, Some(0), 3, 2).unwrap();
        assert_eq!(
            weights(&slice),
            vec![(ring[0].clone(), 3), (ring[2].clone(), 3)]
        );
    }

    #[test]
    fn test_width_capped_by_healthy_pool() {
        let ring = ring(3);
        let slice = ring_slice(&ring, &ring, Some(0), 1, 10).unwrap();
        assert_eq!(
            slice.len(),
            3,
            "width beyond the pool returns every healthy worker"
        );
    }

    #[test]
    fn test_fallback_cases_return_none() {
        let ring = ring(4);
        assert!(
            ring_slice(&ring, &ring, None, 3, 2).is_none(),
            "self not ready yet"
        );
        assert!(
            ring_slice(&ring, &ring, Some(3), 3, 2).is_none(),
            "index out of range"
        );
        assert!(ring_slice(&[], &[], Some(0), 3, 2).is_none(), "empty ring");
        assert!(
            ring_slice(&ring, &[], Some(0), 3, 2).is_none(),
            "nothing healthy"
        );
        assert!(
            ring_slice(&ring, &ring, Some(0), 0, 2).is_none(),
            "no peers"
        );
    }
}
