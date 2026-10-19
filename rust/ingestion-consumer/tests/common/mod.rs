//! Batcher construction shared by the integration suites. Each suite compiles
//! this module separately and uses part of it.
#![allow(dead_code)]

use std::num::NonZeroUsize;
use std::sync::Arc;
use std::time::{Duration, Instant};

use ingestion_consumer::batcher::packer::{PackTargets, Packer};
use ingestion_consumer::batcher::retry_policy::RetryPolicy;
use ingestion_consumer::batcher::state_machine::{BatcherStateMachine, RequestBudget};
use ingestion_consumer::batcher::worker_assigner::WorkerAssigner;
use ingestion_consumer::batcher::worker_pool::WorkerPoolSource;
use ingestion_consumer::batcher::{Batcher, BatcherOutputs};
use ingestion_consumer::grpc_transport::GrpcTransport;
use ingestion_consumer::routing::Router;

pub const PRODUCTION_PACK_TARGETS: PackTargets = PackTargets {
    events: NonZeroUsize::new(500),
    bytes: None,
    latency_budget: Duration::ZERO,
};

pub const ONE_MESSAGE_PER_REQUEST: PackTargets = PackTargets {
    events: NonZeroUsize::new(1),
    bytes: None,
    latency_budget: Duration::ZERO,
};

/// A batcher over `pool_source`'s workers, with the transport's un-acked cap
/// as its per-worker request cap.
pub fn batcher(
    pool_source: WorkerPoolSource,
    transport: Arc<GrpcTransport>,
    stall_timeout: Duration,
    retry_delay: Duration,
    pack_targets: PackTargets,
    budget: Option<RequestBudget>,
) -> (Batcher, BatcherOutputs) {
    let assigner =
        WorkerAssigner::new(Router::new(pool_source.strategy()), transport.max_unacked())
            .expect("valid request cap");
    let retry = RetryPolicy::uniform(retry_delay).expect("valid retry delay");
    let state_machine = BatcherStateMachine::new(
        Packer::new(pack_targets),
        assigner,
        retry,
        stall_timeout,
        Instant::now(),
    )
    .expect("valid stall timeout")
    .with_request_budget(budget);
    Batcher::new(state_machine, pool_source, transport, None)
}

/// A batcher that sends every message in its own request.
pub fn one_message_batcher(
    pool_source: WorkerPoolSource,
    transport: Arc<GrpcTransport>,
    stall_timeout: Duration,
    retry_delay: Duration,
) -> (Batcher, BatcherOutputs) {
    batcher(
        pool_source,
        transport,
        stall_timeout,
        retry_delay,
        ONE_MESSAGE_PER_REQUEST,
        None,
    )
}
