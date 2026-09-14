use std::sync::Arc;
use std::time::Duration;

use common_kafka_consumer::Partition;
use lifecycle::{ComponentOptions, Manager, MonitorGuard};

use ingestion_consumer::batcher::{Batcher, BatcherOutputs};
use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::grpc_transport::{GrpcPort, GrpcTransport};
use ingestion_consumer::routing::RoutingStrategy;
use ingestion_consumer::scheduler::SchedulerKind;
use ingestion_consumer::types::Accumulator;
use ingestion_consumer::worker_registry::WorkerRegistry;

use super::{fast_config, make_msg};

pub struct WorkerlessBatcherHarness {
    dispatcher: Arc<Dispatcher>,
    outputs: BatcherOutputs,
    _monitor: MonitorGuard,
}

impl WorkerlessBatcherHarness {
    // Return the real batcher separately so tests control its lifetime explicitly.
    pub fn create() -> (Batcher, Self) {
        let registry = Arc::new(WorkerRegistry::new(&[], fast_config()));
        let dispatcher = Arc::new(Dispatcher::with_scheduler(
            registry,
            RoutingStrategy::BinPack,
            SchedulerKind::KeyTable,
        ));
        let transport = Arc::new(GrpcTransport::new(
            GrpcPort::OffsetFromHttp(0),
            1,
            Duration::from_secs(30),
        ));
        let mut manager = Manager::builder("workerless-key-table-batcher-test")
            .with_trap_signals(false)
            .build();
        let handle = manager.register("batcher", ComponentOptions::new());
        let monitor = manager.monitor_background();
        let (batcher, outputs) = Batcher::new(
            Arc::clone(&dispatcher),
            transport,
            handle,
            Duration::from_secs(10),
            Duration::from_millis(20),
        );

        (
            batcher,
            Self {
                dispatcher,
                outputs,
                _monitor: monitor,
            },
        )
    }

    pub fn submit_message(&self, batcher: &Batcher, key: &str) {
        let mut accumulator = Accumulator::default();
        accumulator.push(Partition(0), make_msg(key).into());
        batcher.submit(accumulator);
    }

    pub fn purge_revoked_partition(&self) {
        self.dispatcher.purge_revoked(&[("test".to_string(), 0)]);
    }

    pub async fn expect_no_routing_error(&mut self) {
        match tokio::time::timeout(Duration::from_millis(100), self.outputs.errors.recv()).await {
            Err(_) => {}
            Ok(Some(error)) => panic!("revoked work must not report a routing failure: {error}"),
            Ok(None) => panic!("batcher error channel closed unexpectedly"),
        }
    }

    pub async fn expect_outputs_closed(&mut self) {
        let completion =
            tokio::time::timeout(Duration::from_millis(100), self.outputs.completions.recv())
                .await
                .expect(
                    "dropping the batcher must not leave an idle retry task retaining its senders",
                );
        assert!(
            completion.is_none(),
            "an idle dropped batcher cannot produce a completion"
        );
        let error = tokio::time::timeout(Duration::from_millis(100), self.outputs.errors.recv())
            .await
            .expect("dropping the batcher must close its error channel");
        assert!(
            error.is_none(),
            "all output senders close with the dropped batcher"
        );
    }
}
