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
use ingestion_consumer::batcher::{Batcher, BatcherOutputs};
use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::grpc_transport::GrpcTransport;
use ingestion_consumer::routing::Router;
use ingestion_consumer::scheduler::SchedulerKind;
use lifecycle::Handle;

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

#[allow(clippy::too_many_arguments)]
pub fn batcher(
    kind: SchedulerKind,
    dispatcher: &Arc<Dispatcher>,
    transport: Arc<GrpcTransport>,
    handle: Handle,
    stall_timeout: Duration,
    retry_delay: Duration,
    pack_targets: PackTargets,
    budget: Option<RequestBudget>,
) -> (Batcher, BatcherOutputs) {
    match kind {
        SchedulerKind::PinStash => {
            debug_assert!(budget.is_none(), "pin_stash sends no budget");
            Batcher::new(Arc::clone(dispatcher), transport, handle, stall_timeout)
        }
        SchedulerKind::KeyTable => packing_key_table_batcher(
            dispatcher,
            transport,
            stall_timeout,
            retry_delay,
            pack_targets,
            budget,
        ),
    }
}

pub fn key_table_batcher(
    dispatcher: &Dispatcher,
    transport: Arc<GrpcTransport>,
    stall_timeout: Duration,
    retry_delay: Duration,
) -> (Batcher, BatcherOutputs) {
    packing_key_table_batcher(
        dispatcher,
        transport,
        stall_timeout,
        retry_delay,
        ONE_MESSAGE_PER_REQUEST,
        None,
    )
}

fn packing_key_table_batcher(
    dispatcher: &Dispatcher,
    transport: Arc<GrpcTransport>,
    stall_timeout: Duration,
    retry_delay: Duration,
    pack_targets: PackTargets,
    budget: Option<RequestBudget>,
) -> (Batcher, BatcherOutputs) {
    let pool_source = dispatcher.worker_pool_source();
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
    Batcher::with_state_machine(state_machine, pool_source, transport)
}
