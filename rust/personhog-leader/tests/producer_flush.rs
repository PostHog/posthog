//! The kafka-producer lifecycle component must complete its shutdown
//! within its flush bound even when the broker is unreachable — a
//! wedged queue previously held the shutdown phase until the global
//! timeout, reporting every later phase as stuck along with it.

use std::time::{Duration, Instant};

use common_kafka::kafka_producer::KafkaContext;
use lifecycle::{ComponentOptions, Manager};
use personhog_leader::kafka::spawn_bounded_flush_on_shutdown;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::ClientConfig;

#[tokio::test]
async fn shutdown_flush_is_bounded_against_an_unreachable_broker() {
    let mut manager = Manager::builder("producer-flush-test")
        .with_global_shutdown_timeout(Duration::from_secs(10))
        .build();
    let handle = manager.register(
        "kafka-producer",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(6)),
    );
    let monitor = manager.monitor_background();

    // An unroutable broker, dialed directly so no startup ping rejects
    // it. The long message timeout keeps the queued record stuck for
    // the whole test: the flush must give up on its own bound, not on
    // the record expiring.
    let producer: FutureProducer<KafkaContext> = ClientConfig::new()
        .set("bootstrap.servers", "127.0.0.1:1")
        .set("message.timeout.ms", "60000")
        .create_with_context(KafkaContext::new(handle.clone()))
        .expect("producer builds without a broker");
    producer
        .send_result(FutureRecord::<(), _>::to("flush_test").payload(b"stuck"))
        .expect("record queues locally");

    spawn_bounded_flush_on_shutdown(producer, handle.clone(), Duration::from_secs(1));

    let start = Instant::now();
    handle.request_shutdown();
    monitor
        .wait()
        .await
        .expect("shutdown must conclude cleanly, not time out");
    assert!(
        start.elapsed() < Duration::from_secs(4),
        "shutdown took {:?}: the flush bound, not the graceful ceiling or the global \
         timeout, must end the wait",
        start.elapsed()
    );
}

/// The incident's failure mode was a stalled broker, not an absent one:
/// the connection succeeds and requests hang. The flush must give up on
/// its own bound there too — librdkafka's broker state differs from the
/// unroutable case (a live socket it waits on, not a connect it
/// retries), so the unroutable test alone does not cover it.
#[tokio::test]
async fn shutdown_flush_is_bounded_against_a_stalled_broker() {
    // Accept connections and never respond, holding each socket open:
    // the shape of a broker that is up but not answering.
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind stall listener");
    let addr = listener.local_addr().expect("listener addr");
    tokio::spawn(async move {
        let mut held = Vec::new();
        while let Ok((socket, _)) = listener.accept().await {
            held.push(socket);
        }
    });

    let mut manager = Manager::builder("producer-flush-stall-test")
        .with_global_shutdown_timeout(Duration::from_secs(10))
        .build();
    let handle = manager.register(
        "kafka-producer",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(6)),
    );
    let monitor = manager.monitor_background();

    let producer: FutureProducer<KafkaContext> = ClientConfig::new()
        .set("bootstrap.servers", addr.to_string())
        .set("message.timeout.ms", "60000")
        .create_with_context(KafkaContext::new(handle.clone()))
        .expect("producer builds against the stalled listener");
    producer
        .send_result(FutureRecord::<(), _>::to("flush_test").payload(b"stuck"))
        .expect("record queues locally");

    spawn_bounded_flush_on_shutdown(producer, handle.clone(), Duration::from_secs(1));

    let start = Instant::now();
    handle.request_shutdown();
    monitor
        .wait()
        .await
        .expect("shutdown must conclude cleanly, not time out");
    assert!(
        start.elapsed() < Duration::from_secs(4),
        "shutdown took {:?} against a stalled broker: the flush bound must end the wait",
        start.elapsed()
    );
}
