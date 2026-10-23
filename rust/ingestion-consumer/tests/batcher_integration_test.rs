mod common;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka_consumer::Partition;

use common::one_message_batcher;
use ingestion_consumer::batcher::worker_pool::WorkerPoolSource;
use ingestion_consumer::grpc_transport::{GrpcPort, GrpcTransport};
use ingestion_consumer::routing::RoutingStrategy;
use ingestion_consumer::types::{Accumulator, SerializedKafkaMessage};
use ingestion_consumer::worker_registry::{WorkerRegistry, WorkerRegistryConfig};

fn fast_config() -> WorkerRegistryConfig {
    WorkerRegistryConfig {
        probe_interval: Duration::from_millis(15),
        dead_declaration: Duration::from_millis(40),
        passive_window: Duration::from_secs(60),
        passive_error_threshold: 0.01,
        passive_min_samples: 1000,
        degraded_hold: Duration::from_millis(30),
        min_state_duration: Duration::ZERO,
        probe_failure_threshold: 2,
        drain_timeout: Duration::from_secs(5),
    }
}

fn make_msg(key: &str) -> SerializedKafkaMessage {
    SerializedKafkaMessage {
        topic: "test".into(),
        partition: 0,
        offset: 0,
        timestamp: 0,
        key: Some(key.to_string()),
        value: None,
        headers: HashMap::new(),
        generation: 0,
    }
}

#[tokio::test(flavor = "current_thread")]
async fn purging_a_just_submitted_batch_is_not_fatal() {
    let registry = Arc::new(WorkerRegistry::new(&[], fast_config()));
    let pool_source = WorkerPoolSource::new(registry, RoutingStrategy::P2c);
    let transport = Arc::new(GrpcTransport::new(
        GrpcPort::OffsetFromHttp(0),
        Duration::from_secs(30),
    ));
    let (batcher, mut outputs) = one_message_batcher(
        pool_source,
        transport,
        Duration::from_secs(10),
        Duration::from_millis(20),
    );

    let mut accumulator = Accumulator::default();
    accumulator.push(Partition(0), make_msg("a").into());
    batcher.submit(accumulator, &HashMap::new());
    // No await, so the task gets the submit and the purge before it runs.
    batcher.revoker().purge_revoked(&[("test".to_string(), 0)]);

    match tokio::time::timeout(Duration::from_millis(100), outputs.errors.recv()).await {
        Err(_) => {}
        Ok(Some(error)) => panic!("revoked work must not report a routing failure: {error}"),
        Ok(None) => panic!("batcher error channel closed unexpectedly"),
    }
}

#[tokio::test]
async fn dropping_an_idle_batcher_closes_its_outputs() {
    let registry = Arc::new(WorkerRegistry::new(&[], fast_config()));
    let pool_source = WorkerPoolSource::new(registry, RoutingStrategy::P2c);
    let transport = Arc::new(GrpcTransport::new(
        GrpcPort::OffsetFromHttp(0),
        Duration::from_secs(30),
    ));
    let (batcher, mut outputs) = one_message_batcher(
        pool_source,
        transport,
        Duration::from_secs(10),
        Duration::from_millis(20),
    );

    drop(batcher);

    let completion = tokio::time::timeout(Duration::from_millis(100), outputs.completions.recv())
        .await
        .expect("dropping the batcher must not leave an idle retry task retaining its senders");
    assert!(
        completion.is_none(),
        "an idle dropped batcher cannot produce a completion"
    );
    assert!(
        outputs.errors.recv().await.is_none(),
        "all output senders close with the dropped batcher"
    );
}
