//! Transport-neutral routing and capacity partitioning primitives.
//!
//! The types in this module intentionally avoid tonic, DNS, metrics, env vars,
//! and Cymbal server configuration. They operate on generic endpoint
//! identifiers so callers can use `SocketAddr`, logical pod IDs, or test-only
//! strings at the transport boundary.
//!
//! Submodules carve up responsibilities to keep ownership clear:
//!
//! * [`key`] — routing keys, cache key kinds, and the
//!   [`RoutingKeyExtractor`] trait. Pure data describing affinity intent.
//! * [`policy`] — routing modes, [`RoutingPolicy`], endpoint local state, the
//!   [`RemoteRoutingConfig`] container, and the candidate-selection algorithm
//!   ([`pick_candidates_with_rng`]).
//! * [`capacity`] — [`CapacityFreshness`], [`EndpointCapacity`], and
//!   [`CapacitySnapshot`]. Snapshots are produced by the transport layer and
//!   consumed by partitioning.
//! * [`partition`] — capacity-aware partitioning into per-endpoint sub-batches
//!   ([`CapacityAwarePartitioner`] and friends).
//! * [`fallback`] — attempt-failure classification and the
//!   [`FallbackPolicy`] decision table.
//!
//! Concerns that explicitly do not belong here: tonic clients, DNS, env
//! parsing, metrics/logging, readiness, shutdown, endpoint client creation,
//! or anything that depends on Cymbal server configuration. Those belong in
//! `cymbal-server`.

mod capacity;
mod fallback;
mod key;
mod partition;
mod policy;

pub use capacity::{CapacityFreshness, CapacitySnapshot, EndpointCapacity};
pub use fallback::{AttemptFailureKind, FallbackDecision, FallbackPolicy};
pub use key::{RoutingCacheKeyKind, RoutingKey, RoutingKeyExtractor};
pub use partition::{
    CapacityAwarePartitioner, EndpointSubBatch, IndexedItem, PartitionRequest,
    PartitionedSubBatches, UnroutableItem, UnroutableReason,
};
pub use policy::{
    pick_candidates_with_rng, EndpointLocalState, EndpointStateMap, RemoteRoutingConfig,
    RoutingMode, RoutingPolicy,
};

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use rand::rngs::StdRng;
    use rand::SeedableRng;

    use super::*;

    fn seeded_rng() -> StdRng {
        StdRng::seed_from_u64(42)
    }

    fn endpoint(value: &str) -> String {
        value.to_string()
    }

    fn endpoints(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| endpoint(value)).collect()
    }

    fn affinity_candidates(endpoints: &[String], key: &RoutingKey) -> Vec<String> {
        pick_candidates_with_rng(
            "resolution:v1",
            key,
            endpoints,
            &EndpointStateMap::new(),
            &RoutingPolicy::affinity_first(),
            &mut seeded_rng(),
        )
    }

    fn capacity(endpoint: &str, current: u64, max: u64) -> EndpointCapacity<String> {
        EndpointCapacity::fresh(endpoint.to_string(), current, max)
    }

    struct ConstantRoutingKey(RoutingKey);

    impl<Item> RoutingKeyExtractor<Item> for ConstantRoutingKey {
        fn routing_key(&self, _item: &Item) -> RoutingKey {
            self.0.clone()
        }
    }

    fn item_team_id(item: &i32) -> RoutingKey {
        RoutingKey::team_id(*item as i64)
    }

    fn sub_batch_size<Item>(
        partitioned: &PartitionedSubBatches<String, Item>,
        endpoint: &str,
    ) -> usize {
        partitioned
            .sub_batches
            .iter()
            .find(|sub_batch| sub_batch.endpoint == endpoint)
            .map_or(0, |sub_batch| sub_batch.items.len())
    }

    #[test]
    fn affinity_first_ordering_is_deterministic() {
        let endpoints = endpoints(&["pod-a", "pod-b", "pod-c", "pod-d"]);

        let first = affinity_candidates(&endpoints, &RoutingKey::new("team_id:7"));
        let second = affinity_candidates(&endpoints, &RoutingKey::new("team_id:7"));

        assert_eq!(first, second);
        assert_eq!(first.len(), endpoints.len());
        assert_eq!(
            first.iter().cloned().collect::<HashSet<_>>(),
            endpoints.iter().cloned().collect::<HashSet<_>>()
        );
    }

    #[test]
    fn affinity_first_keeps_existing_relative_order_when_endpoint_list_changes() {
        let original = endpoints(&["pod-a", "pod-b", "pod-c", "pod-d"]);
        let mut expanded = original.clone();
        expanded.push(endpoint("pod-e"));

        let original_order = affinity_candidates(&original, &RoutingKey::new("team_id:7"));
        let expanded_order = affinity_candidates(&expanded, &RoutingKey::new("team_id:7"))
            .into_iter()
            .filter(|candidate| original.contains(candidate))
            .collect::<Vec<_>>();

        assert_eq!(expanded_order, original_order);
    }

    #[test]
    fn random_policy_uses_injected_rng() {
        let endpoints = endpoints(&["pod-a", "pod-b", "pod-c", "pod-d", "pod-e", "pod-f"]);
        let policy = RoutingPolicy::random();
        let key = RoutingKey::new("team_id:99");
        let mut first_rng = StdRng::seed_from_u64(7);
        let mut second_rng = StdRng::seed_from_u64(7);
        let mut different_rng = StdRng::seed_from_u64(8);

        let first = pick_candidates_with_rng(
            "alerting:v1",
            &key,
            &endpoints,
            &EndpointStateMap::new(),
            &policy,
            &mut first_rng,
        );
        let second = pick_candidates_with_rng(
            "alerting:v1",
            &key,
            &endpoints,
            &EndpointStateMap::new(),
            &policy,
            &mut second_rng,
        );
        let different = pick_candidates_with_rng(
            "alerting:v1",
            &key,
            &endpoints,
            &EndpointStateMap::new(),
            &policy,
            &mut different_rng,
        );

        assert_eq!(first, second);
        assert_ne!(first, different);
        assert_eq!(first.len(), endpoints.len());
    }

    #[test]
    fn empty_endpoint_list_returns_unroutable_items() {
        let partitioner = CapacityAwarePartitioner::default();
        let partitioned = partitioner.partition(
            vec![1, 2],
            PartitionRequest {
                stage_id: "resolution:v1",
                endpoints: &Vec::<String>::new(),
                capacity: &CapacitySnapshot::default(),
                policy: &RoutingPolicy::affinity_first(),
                extractor: &item_team_id,
            },
            &mut seeded_rng(),
        );

        assert!(partitioned.sub_batches.is_empty());
        assert_eq!(partitioned.unroutable.len(), 2);
        assert!(partitioned
            .unroutable
            .iter()
            .all(|item| item.reason == UnroutableReason::NoEndpoints));
    }

    #[test]
    fn multiple_pods_increase_aggregate_logical_capacity() {
        let endpoints = endpoints(&["pod-a", "pod-b"]);
        let snapshot =
            CapacitySnapshot::new(vec![capacity("pod-a", 0, 2), capacity("pod-b", 0, 2)]);
        let partitioner = CapacityAwarePartitioner::default();

        let partitioned = partitioner.partition(
            vec![1, 2, 3, 4],
            PartitionRequest {
                stage_id: "resolution:v1",
                endpoints: &endpoints,
                capacity: &snapshot,
                policy: &RoutingPolicy::affinity_first(),
                extractor: &ConstantRoutingKey(RoutingKey::team_id(7)),
            },
            &mut seeded_rng(),
        );

        assert_eq!(snapshot.fresh_available_items(), 4);
        assert_eq!(partitioned.unroutable.len(), 0);
        assert_eq!(
            partitioned
                .sub_batches
                .iter()
                .map(|sub_batch| sub_batch.items.len())
                .sum::<usize>(),
            4
        );
        assert!(partitioned.sub_batches.len() > 1);
    }

    #[test]
    fn local_reservations_spread_overflow_after_affinity_primary_fills() {
        let endpoints = endpoints(&["pod-a", "pod-b", "pod-c"]);
        let key = RoutingKey::team_id(7);
        let candidates = affinity_candidates(&endpoints, &key);
        let primary = candidates[0].clone();
        let secondary = candidates[1].clone();
        let snapshot = CapacitySnapshot::new(vec![
            EndpointCapacity::fresh(primary.clone(), 0, 1),
            EndpointCapacity::fresh(secondary.clone(), 0, 10),
            EndpointCapacity::fresh(candidates[2].clone(), 0, 10),
        ]);
        let partitioner = CapacityAwarePartitioner::default();

        let partitioned = partitioner.partition(
            vec![1, 2, 3],
            PartitionRequest {
                stage_id: "resolution:v1",
                endpoints: &endpoints,
                capacity: &snapshot,
                policy: &RoutingPolicy::affinity_first(),
                extractor: &ConstantRoutingKey(key.clone()),
            },
            &mut seeded_rng(),
        );

        assert_eq!(partitioned.unroutable.len(), 0);
        assert_eq!(sub_batch_size(&partitioned, &primary), 1);
        assert_eq!(sub_batch_size(&partitioned, &secondary), 2);
    }

    #[test]
    fn stale_and_missing_capacity_use_conservative_local_reservations() {
        let endpoints = endpoints(&["pod-stale", "pod-missing"]);
        let snapshot = CapacitySnapshot::new(vec![
            capacity("pod-stale", 0, 100).with_freshness(CapacityFreshness::Stale)
        ]);
        let partitioner = CapacityAwarePartitioner::new(1, 1);

        let partitioned = partitioner.partition(
            vec![1, 2, 3],
            PartitionRequest {
                stage_id: "resolution:v1",
                endpoints: &endpoints,
                capacity: &snapshot,
                policy: &RoutingPolicy::affinity_first(),
                extractor: &ConstantRoutingKey(RoutingKey::team_id(7)),
            },
            &mut seeded_rng(),
        );

        assert_eq!(snapshot.fresh_available_items(), 0);
        assert_eq!(partitioned.unroutable.len(), 1);
        assert_eq!(sub_batch_size(&partitioned, "pod-stale"), 1);
        assert_eq!(sub_batch_size(&partitioned, "pod-missing"), 1);
    }

    #[test]
    fn strict_affinity_overflow_is_unroutable_instead_of_fallback() {
        let endpoints = endpoints(&["pod-a", "pod-b", "pod-c"]);
        let key = RoutingKey::team_id(7);
        let primary = pick_candidates_with_rng(
            "linking:v1",
            &key,
            &endpoints,
            &EndpointStateMap::new(),
            &RoutingPolicy::strict_affinity(),
            &mut seeded_rng(),
        )[0]
        .clone();
        let snapshot = CapacitySnapshot::new(vec![
            EndpointCapacity::fresh(primary.clone(), 0, 1),
            capacity("pod-a", 0, 10),
            capacity("pod-b", 0, 10),
            capacity("pod-c", 0, 10),
        ]);
        let partitioner = CapacityAwarePartitioner::default();

        let partitioned = partitioner.partition(
            vec![1, 2],
            PartitionRequest {
                stage_id: "linking:v1",
                endpoints: &endpoints,
                capacity: &snapshot,
                policy: &RoutingPolicy::strict_affinity(),
                extractor: &ConstantRoutingKey(key.clone()),
            },
            &mut seeded_rng(),
        );

        assert_eq!(sub_batch_size(&partitioned, &primary), 1);
        assert_eq!(partitioned.unroutable.len(), 1);
        assert_eq!(
            partitioned.unroutable[0].reason,
            UnroutableReason::OverCapacity
        );
        assert_eq!(partitioned.unroutable[0].candidates_considered, 1);
    }

    #[test]
    fn endpoint_local_state_excludes_unavailable_candidates() {
        let endpoints = endpoints(&["pod-a", "pod-b", "pod-c", "pod-d"]);
        let mut states = EndpointStateMap::new();
        states.insert(endpoint("pod-b"), EndpointLocalState::ejected());
        states.insert(endpoint("pod-c"), EndpointLocalState::overloaded());
        states.insert(endpoint("pod-d"), EndpointLocalState::draining());

        let candidates = pick_candidates_with_rng(
            "grouping:v1",
            &RoutingKey::team_id(42),
            &endpoints,
            &states,
            &RoutingPolicy::affinity_first(),
            &mut seeded_rng(),
        );

        assert_eq!(candidates, vec![endpoint("pod-a")]);
    }

    #[test]
    fn max_fallback_attempts_limits_candidate_count() {
        let endpoints = endpoints(&["pod-a", "pod-b", "pod-c", "pod-d"]);

        let candidates = pick_candidates_with_rng(
            "resolution:v1",
            &RoutingKey::new("team_id:13"),
            &endpoints,
            &EndpointStateMap::new(),
            &RoutingPolicy::affinity_first().with_max_fallback_attempts(1),
            &mut seeded_rng(),
        );

        assert_eq!(candidates.len(), 2);
    }

    #[test]
    fn fallback_policy_allows_only_safe_pre_work_failures_by_default() {
        let policy = FallbackPolicy::pre_work_only();

        assert!(policy
            .decide(AttemptFailureKind::PreCallEjected, 0)
            .should_try_next_candidate());
        assert!(policy
            .decide(AttemptFailureKind::PreWorkResourceExhausted, 0)
            .should_try_next_candidate());
        assert!(policy
            .decide(AttemptFailureKind::PreWorkRejected, 0)
            .should_try_next_candidate());
        assert_eq!(
            policy.decide(AttemptFailureKind::AmbiguousTimeout, 0),
            FallbackDecision::RetryOriginalItems {
                retry_after_ms: None
            }
        );
        assert_eq!(
            policy.decide(AttemptFailureKind::AmbiguousTransport, 0),
            FallbackDecision::RetryOriginalItems {
                retry_after_ms: None
            }
        );
    }

    #[test]
    fn fallback_policy_honors_attempt_limits() {
        let policy = FallbackPolicy {
            allow_pre_work_fallback: true,
            allow_ambiguous_fallback: true,
            max_attempts: Some(1),
        };

        assert!(policy
            .decide(AttemptFailureKind::AmbiguousTransport, 0)
            .should_try_next_candidate());
        assert_eq!(
            policy.decide(AttemptFailureKind::AmbiguousTransport, 1),
            FallbackDecision::RetryOriginalItems {
                retry_after_ms: None
            }
        );
        assert_eq!(
            FallbackPolicy::no_fallback().decide(AttemptFailureKind::PreCallEjected, 0),
            FallbackDecision::RetryOriginalItems {
                retry_after_ms: None
            }
        );
    }
}
