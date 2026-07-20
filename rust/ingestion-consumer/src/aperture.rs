//! Deterministic aperture: ring-slice candidate selection.
//!
//! Every dispatcher sorts the full worker set into the same ring, takes the
//! slice starting at `peer_index * ring_len / peer_count`, and routes its
//! unpinned groups only within that slice (via the configured selection
//! strategy). Because peers agree on both the ring order (same EndpointSlices,
//! same sort) and their own indices ([`k8s_awareness::PeerTracker`]), the
//! slices tile the ring without any coordination — each dispatcher talks to
//! `width` workers instead of the whole pool, which is what keeps sub-batches
//! consolidated. Modeled on Finagle's deterministic aperture.
//!
//! Unroutable ring positions (unhealthy or draining workers) are skipped and
//! the slice extends further around the ring, so the *effective* width holds
//! under partial failure.

use std::collections::HashSet;

use crate::worker_registry::WorkerId;

/// The candidate workers for one assignment round: walk the ring from this
/// dispatcher's slice start, collecting healthy workers until `width` are
/// found or the ring is exhausted. `ring` is the canonically sorted full
/// worker set; `healthy` the subset this dispatcher may route to.
///
/// Returns `None` (caller falls back to the full healthy pool) when the
/// slice can't be computed: no peers known yet, an out-of-range index, or an
/// empty ring.
pub fn ring_slice(
    ring: &[WorkerId],
    healthy: &[WorkerId],
    peer_index: Option<usize>,
    peer_count: usize,
    width: usize,
) -> Option<Vec<WorkerId>> {
    let index = peer_index?;
    if ring.is_empty() || peer_count == 0 || index >= peer_count || width == 0 {
        return None;
    }

    let healthy_set: HashSet<&WorkerId> = healthy.iter().collect();
    let start = index * ring.len() / peer_count;

    let mut candidates = Vec::with_capacity(width.min(ring.len()));
    for offset in 0..ring.len() {
        let worker = &ring[(start + offset) % ring.len()];
        if healthy_set.contains(worker) {
            candidates.push(worker.clone());
            if candidates.len() == width {
                break;
            }
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
    use super::*;

    fn wid(n: usize) -> WorkerId {
        WorkerId::from(format!("http://10.0.0.{n}:6738").as_str())
    }

    fn ring(n: usize) -> Vec<WorkerId> {
        sorted_ring((1..=n).map(wid).collect())
    }

    #[test]
    fn test_slices_tile_the_ring_across_peers() {
        // 3 peers x width 2 over 6 workers: each peer gets a distinct pair and
        // the union covers the whole ring — the coordination-free guarantee
        // the whole design rests on.
        let ring = ring(6);
        let mut seen = Vec::new();
        for index in 0..3 {
            let slice = ring_slice(&ring, &ring, Some(index), 3, 2).unwrap();
            assert_eq!(slice.len(), 2, "peer {index}");
            seen.extend(slice);
        }
        let mut sorted = seen.clone();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(sorted.len(), 6, "slices must tile the ring without overlap");
    }

    #[test]
    fn test_slices_leave_gaps_when_width_undershoots_ring() {
        // 2 peers x width 3 over 8 workers: slice starts are spaced 4 apart,
        // so ring positions 3 and 7 receive no unpinned traffic. Full-pool
        // coverage requires `width x peer_count >= ring len` — an undersized
        // static width idles the uncovered workers.
        let ring = ring(8);
        let mut seen = HashSet::new();
        for index in 0..2 {
            seen.extend(ring_slice(&ring, &ring, Some(index), 2, 3).unwrap());
        }
        assert_eq!(seen.len(), 6, "only width x peers positions are covered");
        assert!(
            !seen.contains(&ring[3]) && !seen.contains(&ring[7]),
            "positions between slice starts are never routed to"
        );
    }

    #[test]
    fn test_slice_wraps_around_the_ring() {
        // Last peer's slice starts near the ring end and wraps to the front.
        let ring = ring(5);
        let slice = ring_slice(&ring, &ring, Some(2), 3, 3).unwrap();
        // start = 2 * 5 / 3 = 3 → positions 3, 4, 0.
        assert_eq!(
            slice,
            vec![ring[3].clone(), ring[4].clone(), ring[0].clone()]
        );
    }

    #[test]
    fn test_slice_extends_past_unhealthy_workers() {
        // An unroutable worker inside the slice must not shrink the effective
        // width — the slice walks on around the ring.
        let ring = ring(6);
        let healthy: Vec<WorkerId> = ring.iter().filter(|w| **w != ring[1]).cloned().collect();
        let slice = ring_slice(&ring, &healthy, Some(0), 3, 2).unwrap();
        assert_eq!(slice, vec![ring[0].clone(), ring[2].clone()]);
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
