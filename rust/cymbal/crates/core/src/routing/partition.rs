//! Capacity-aware partitioning of items into per-endpoint sub-batches.
//!
//! This module ties policy, capacity, and routing keys together to produce the
//! sub-batches a dispatcher will actually send. It owns local reservations so
//! repeated picks within a single partition call do not oversubscribe an
//! endpoint. It does not own attempt sequencing or fallback decisions; those
//! live in `fallback`.

use std::collections::HashMap;
use std::hash::Hash;

use rand::Rng;

use super::capacity::CapacitySnapshot;
use super::key::RoutingKeyExtractor;
use super::policy::{pick_candidates_with_rng, RoutingPolicy};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IndexedItem<Item> {
    pub index: usize,
    pub item: Item,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EndpointSubBatch<EndpointId, Item> {
    pub endpoint: EndpointId,
    pub items: Vec<IndexedItem<Item>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UnroutableReason {
    NoEndpoints,
    NoCandidates,
    OverCapacity,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnroutableItem<Item> {
    pub item: IndexedItem<Item>,
    pub reason: UnroutableReason,
    pub candidates_considered: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PartitionedSubBatches<EndpointId, Item> {
    pub sub_batches: Vec<EndpointSubBatch<EndpointId, Item>>,
    pub unroutable: Vec<UnroutableItem<Item>>,
}

impl<EndpointId, Item> Default for PartitionedSubBatches<EndpointId, Item> {
    fn default() -> Self {
        Self {
            sub_batches: Vec::new(),
            unroutable: Vec::new(),
        }
    }
}

/// Per-call configuration for [`CapacityAwarePartitioner::partition`]. Grouped
/// into a struct so the partition method can stay below the `too_many_arguments`
/// clippy ceiling without losing the named-argument readability at call sites.
pub struct PartitionRequest<'a, EndpointId, Extractor> {
    pub stage_id: &'a str,
    pub endpoints: &'a [EndpointId],
    pub capacity: &'a CapacitySnapshot<EndpointId>,
    pub policy: &'a RoutingPolicy,
    pub extractor: &'a Extractor,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapacityAwarePartitioner {
    pub conservative_stale_capacity_items: u64,
    pub conservative_missing_capacity_items: u64,
}

impl CapacityAwarePartitioner {
    pub fn new(
        conservative_stale_capacity_items: u64,
        conservative_missing_capacity_items: u64,
    ) -> Self {
        Self {
            conservative_stale_capacity_items,
            conservative_missing_capacity_items,
        }
    }

    pub fn partition<EndpointId, Item, Extractor, Random>(
        &self,
        items: Vec<Item>,
        request: PartitionRequest<'_, EndpointId, Extractor>,
        rng: &mut Random,
    ) -> PartitionedSubBatches<EndpointId, Item>
    where
        EndpointId: Clone + Eq + Hash + Ord,
        Extractor: RoutingKeyExtractor<Item>,
        Random: Rng + ?Sized,
    {
        let PartitionRequest {
            stage_id,
            endpoints,
            capacity,
            policy,
            extractor,
        } = request;
        let mut result = PartitionedSubBatches::default();
        if endpoints.is_empty() {
            result.unroutable = items
                .into_iter()
                .enumerate()
                .map(|(index, item)| UnroutableItem {
                    item: IndexedItem { index, item },
                    reason: UnroutableReason::NoEndpoints,
                    candidates_considered: 0,
                })
                .collect();
            return result;
        }

        let endpoint_states = capacity.endpoint_states_for(endpoints);
        let mut reservations: HashMap<EndpointId, u64> = HashMap::new();
        let mut sub_batch_indexes: HashMap<EndpointId, usize> = HashMap::new();

        for (index, item) in items.into_iter().enumerate() {
            let routing_key = extractor.routing_key(&item);
            let candidates = pick_candidates_with_rng(
                stage_id,
                &routing_key,
                endpoints,
                &endpoint_states,
                policy,
                rng,
            );
            let candidates_considered = candidates.len();
            let Some(endpoint) =
                self.first_candidate_with_capacity(&candidates, capacity, &reservations)
            else {
                result.unroutable.push(UnroutableItem {
                    item: IndexedItem { index, item },
                    reason: if candidates.is_empty() {
                        UnroutableReason::NoCandidates
                    } else {
                        UnroutableReason::OverCapacity
                    },
                    candidates_considered,
                });
                continue;
            };

            *reservations.entry(endpoint.clone()).or_default() += 1;
            let indexed_item = IndexedItem { index, item };
            if let Some(sub_batch_index) = sub_batch_indexes.get(&endpoint).copied() {
                result.sub_batches[sub_batch_index].items.push(indexed_item);
            } else {
                let sub_batch_index = result.sub_batches.len();
                result.sub_batches.push(EndpointSubBatch {
                    endpoint: endpoint.clone(),
                    items: vec![indexed_item],
                });
                sub_batch_indexes.insert(endpoint, sub_batch_index);
            }
        }

        result
    }

    fn first_candidate_with_capacity<EndpointId>(
        &self,
        candidates: &[EndpointId],
        capacity: &CapacitySnapshot<EndpointId>,
        reservations: &HashMap<EndpointId, u64>,
    ) -> Option<EndpointId>
    where
        EndpointId: Clone + Eq + Hash,
    {
        candidates.iter().find_map(|endpoint| {
            let effective_remaining = capacity.effective_remaining_for(
                endpoint,
                self.conservative_stale_capacity_items,
                self.conservative_missing_capacity_items,
            );
            let locally_reserved = reservations.get(endpoint).copied().unwrap_or_default();
            (effective_remaining > locally_reserved).then(|| endpoint.clone())
        })
    }
}

impl Default for CapacityAwarePartitioner {
    fn default() -> Self {
        Self::new(1, 1)
    }
}
