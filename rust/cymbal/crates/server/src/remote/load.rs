//! Per-endpoint stage-load observations and capacity translation.
//!
//! Endpoints can return `StageLoad` either inside a successful response or as
//! trailer metadata on a failed status. Observations live in a TTL cache keyed
//! by `(target, stage, endpoint)` and feed both routing decisions (via
//! [`endpoint_capacity_from_load`]) and `cymbal_remote_endpoint_*` metrics
//! emitted by [`record_endpoint_load_metrics`].

use std::net::SocketAddr;
use std::time::{Duration, Instant};

use cymbal_api::cymbal::v1::StageLoad;
use cymbal_core::routing::{CapacityFreshness, EndpointCapacity, EndpointLocalState};

use crate::observability::{
    REMOTE_ENDPOINT_IN_FLIGHT_BATCHES, REMOTE_ENDPOINT_IN_FLIGHT_ITEMS,
    REMOTE_ENDPOINT_LOAD_OBSERVATIONS,
};

pub(super) const ENDPOINT_LOAD_OBSERVATION_TTL: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub(super) struct EndpointLoadKey {
    pub(super) target_name: String,
    pub(super) stage_id: String,
    pub(super) address: SocketAddr,
}

impl EndpointLoadKey {
    pub(super) fn new(
        target_name: impl Into<String>,
        stage_id: impl Into<String>,
        address: SocketAddr,
    ) -> Self {
        Self {
            target_name: target_name.into(),
            stage_id: stage_id.into(),
            address,
        }
    }
}

#[derive(Debug, Clone)]
pub(super) struct EndpointObservedLoad {
    pub(super) load: StageLoad,
    observed_at: Instant,
}

impl EndpointObservedLoad {
    pub(super) fn new(load: StageLoad) -> Self {
        Self {
            load,
            observed_at: Instant::now(),
        }
    }

    pub(super) fn is_fresh(&self) -> bool {
        self.observed_at.elapsed() <= ENDPOINT_LOAD_OBSERVATION_TTL
    }

    pub(super) fn local_state(&self) -> EndpointLocalState {
        if stage_load_is_overloaded(&self.load) {
            EndpointLocalState::overloaded()
        } else {
            EndpointLocalState::available()
        }
    }
}

pub(super) fn stage_load_is_overloaded(load: &StageLoad) -> bool {
    load.overloaded
        || load.draining
        || (load.max_in_flight_stage_batches > 0
            && load.current_in_flight_stage_batches >= load.max_in_flight_stage_batches)
        || (load.max_in_flight_items > 0
            && load.current_in_flight_items >= load.max_in_flight_items)
}

pub(super) fn endpoint_capacity_from_load(
    address: SocketAddr,
    observed_load: Option<&EndpointObservedLoad>,
) -> EndpointCapacity<SocketAddr> {
    let Some(observed_load) = observed_load else {
        return EndpointCapacity {
            endpoint: address,
            current_in_flight_items: 0,
            max_in_flight_items: 0,
            current_in_flight_batches: None,
            max_in_flight_batches: None,
            draining: false,
            overloaded: false,
            ejected: false,
            freshness: CapacityFreshness::Missing,
        };
    };

    let freshness = if observed_load.is_fresh()
        && (observed_load.load.max_in_flight_items > 0
            || stage_load_is_overloaded(&observed_load.load))
    {
        CapacityFreshness::Fresh
    } else {
        CapacityFreshness::Stale
    };
    let use_load_state = freshness == CapacityFreshness::Fresh;
    EndpointCapacity {
        endpoint: address,
        current_in_flight_items: observed_load.load.current_in_flight_items,
        max_in_flight_items: observed_load.load.max_in_flight_items,
        current_in_flight_batches: Some(observed_load.load.current_in_flight_stage_batches),
        max_in_flight_batches: Some(observed_load.load.max_in_flight_stage_batches),
        draining: use_load_state && observed_load.load.draining,
        overloaded: use_load_state && stage_load_is_overloaded(&observed_load.load),
        ejected: false,
        freshness,
    }
}

pub(super) fn record_endpoint_load_metrics(
    stage_id: &str,
    target_name: &str,
    address: SocketAddr,
    load: &StageLoad,
) {
    let endpoint_label = address.to_string();
    let overloaded = stage_load_is_overloaded(load).to_string();
    metrics::counter!(
        REMOTE_ENDPOINT_LOAD_OBSERVATIONS,
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "endpoint" => endpoint_label.clone(),
        "overloaded" => overloaded.clone(),
    )
    .increment(1);
    metrics::gauge!(
        REMOTE_ENDPOINT_IN_FLIGHT_BATCHES,
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "endpoint" => endpoint_label.clone(),
        "kind" => "current",
    )
    .set(load.current_in_flight_stage_batches as f64);
    metrics::gauge!(
        REMOTE_ENDPOINT_IN_FLIGHT_BATCHES,
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "endpoint" => endpoint_label.clone(),
        "kind" => "max",
    )
    .set(load.max_in_flight_stage_batches as f64);
    metrics::gauge!(
        REMOTE_ENDPOINT_IN_FLIGHT_ITEMS,
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "endpoint" => endpoint_label.clone(),
        "kind" => "current",
    )
    .set(load.current_in_flight_items as f64);
    metrics::gauge!(
        REMOTE_ENDPOINT_IN_FLIGHT_ITEMS,
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "endpoint" => endpoint_label.clone(),
        "kind" => "max",
    )
    .set(load.max_in_flight_items as f64);
    tracing::debug!(
        stage_id,
        target = target_name,
        endpoint = %endpoint_label,
        current_in_flight_stage_batches = load.current_in_flight_stage_batches,
        max_in_flight_stage_batches = load.max_in_flight_stage_batches,
        current_in_flight_items = load.current_in_flight_items,
        max_in_flight_items = load.max_in_flight_items,
        draining = load.draining,
        overloaded = overloaded,
        "observed remote stage endpoint load"
    );
}
