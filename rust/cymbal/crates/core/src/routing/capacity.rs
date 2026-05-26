//! Endpoint capacity snapshots and freshness accounting.
//!
//! Snapshots are produced by the transport layer (where load observations
//! actually come from) and consumed by partitioning to decide how many items
//! each endpoint can accept. This module deliberately stays free of tonic,
//! metrics, and DNS concerns.

use std::hash::Hash;

use super::policy::{EndpointLocalState, EndpointStateMap};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CapacityFreshness {
    Fresh,
    Stale,
    Missing,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EndpointCapacity<EndpointId> {
    pub endpoint: EndpointId,
    pub current_in_flight_items: u64,
    pub max_in_flight_items: u64,
    pub current_in_flight_batches: Option<u64>,
    pub max_in_flight_batches: Option<u64>,
    pub draining: bool,
    pub overloaded: bool,
    pub ejected: bool,
    pub freshness: CapacityFreshness,
}

impl<EndpointId> EndpointCapacity<EndpointId> {
    pub fn fresh(
        endpoint: EndpointId,
        current_in_flight_items: u64,
        max_in_flight_items: u64,
    ) -> Self {
        Self {
            endpoint,
            current_in_flight_items,
            max_in_flight_items,
            current_in_flight_batches: None,
            max_in_flight_batches: None,
            draining: false,
            overloaded: false,
            ejected: false,
            freshness: CapacityFreshness::Fresh,
        }
    }

    pub fn with_freshness(mut self, freshness: CapacityFreshness) -> Self {
        self.freshness = freshness;
        self
    }

    pub fn draining(mut self) -> Self {
        self.draining = true;
        self
    }

    pub fn overloaded(mut self) -> Self {
        self.overloaded = true;
        self
    }

    pub fn ejected(mut self) -> Self {
        self.ejected = true;
        self
    }

    pub fn local_state(&self) -> EndpointLocalState {
        EndpointLocalState {
            draining: self.draining,
            ejected: self.ejected,
            overloaded: self.overloaded,
        }
    }

    pub fn fresh_available_items(&self) -> u64 {
        if self.freshness != CapacityFreshness::Fresh || !self.local_state().is_available() {
            return 0;
        }

        self.max_in_flight_items
            .saturating_sub(self.current_in_flight_items)
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapacitySnapshot<EndpointId> {
    pub endpoints: Vec<EndpointCapacity<EndpointId>>,
}

impl<EndpointId> CapacitySnapshot<EndpointId>
where
    EndpointId: Eq + Hash,
{
    pub fn new(endpoints: Vec<EndpointCapacity<EndpointId>>) -> Self {
        Self { endpoints }
    }

    pub fn capacity_for(&self, endpoint: &EndpointId) -> Option<&EndpointCapacity<EndpointId>> {
        self.endpoints
            .iter()
            .find(|capacity| &capacity.endpoint == endpoint)
    }

    pub fn fresh_available_items(&self) -> u64 {
        self.endpoints
            .iter()
            .map(EndpointCapacity::fresh_available_items)
            .sum()
    }

    pub fn endpoint_states_for(&self, endpoints: &[EndpointId]) -> EndpointStateMap<EndpointId>
    where
        EndpointId: Clone,
    {
        endpoints
            .iter()
            .filter_map(|endpoint| {
                self.capacity_for(endpoint).and_then(|capacity| {
                    let state = capacity.local_state();
                    if state.is_available() {
                        None
                    } else {
                        Some((endpoint.clone(), state))
                    }
                })
            })
            .collect()
    }

    pub fn effective_remaining_for(
        &self,
        endpoint: &EndpointId,
        conservative_stale_capacity_items: u64,
        conservative_missing_capacity_items: u64,
    ) -> u64 {
        let Some(capacity) = self.capacity_for(endpoint) else {
            return conservative_missing_capacity_items;
        };
        if !capacity.local_state().is_available() {
            return 0;
        }

        match capacity.freshness {
            CapacityFreshness::Fresh => capacity
                .max_in_flight_items
                .saturating_sub(capacity.current_in_flight_items),
            CapacityFreshness::Stale => conservative_stale_capacity_items,
            CapacityFreshness::Missing => conservative_missing_capacity_items,
        }
    }
}
