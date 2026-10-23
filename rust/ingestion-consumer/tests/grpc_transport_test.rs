mod common;

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use common::one_message_batcher;
use common_kafka_consumer::Partition;
use ingestion_consumer::batcher::worker_pool::WorkerPoolSource;
use ingestion_consumer::grpc_transport::{GrpcPort, GrpcTransport, SendOptions};
use ingestion_consumer::routing::RoutingStrategy;
use ingestion_consumer::transport::{SendOutcome, TransportError};
use ingestion_consumer::types::{Accumulator, SerializedKafkaMessage};
use ingestion_consumer::worker_registry::{WorkerRegistry, WorkerRegistryConfig};
use ingestion_worker_proto::ingestion::worker::v1::worker_ingest_server::{
    WorkerIngest, WorkerIngestServer,
};
use ingestion_worker_proto::ingestion::worker::v1::{
    ingest_stream_request, ingest_stream_response, IngestStreamRequest, IngestStreamResponse,
    MessageRef, StreamReady, SubBatch, SubBatchAck, SubBatchStatus,
};
use rstest::rstest;
use tokio::sync::{mpsc, oneshot, Mutex};
use tokio_stream::wrappers::UnboundedReceiverStream;
use tokio_stream::StreamExt;
use tonic::{Request, Response, Status, Streaming};

#[derive(Clone, Copy)]
enum AckMode {
    Immediate,
    Manual,
    NackSeq(u64),
    BusySeq(u64),
    AckExceptSeq(u64),
}

enum ManualAck {
    Ok { seq: u64, accepted: u32 },
    Nack(u64),
    Ack(SubBatchAck),
}

type ManualAcks = Arc<Mutex<Option<mpsc::UnboundedReceiver<ManualAck>>>>;

struct MockWorker {
    mode: AckMode,
    received: Arc<Mutex<Vec<SubBatch>>>,
    hellos: Arc<Mutex<Vec<u64>>>,
    manual_acks: ManualAcks,
}

#[tonic::async_trait]
impl WorkerIngest for MockWorker {
    type IngestStreamStream = UnboundedReceiverStream<Result<IngestStreamResponse, Status>>;

    async fn ingest_stream(
        &self,
        request: Request<Streaming<IngestStreamRequest>>,
    ) -> Result<Response<Self::IngestStreamStream>, Status> {
        let mut inbound = request.into_inner();
        let (tx, rx) = mpsc::unbounded_channel();
        let mode = self.mode;
        let received = Arc::clone(&self.received);
        let hellos = Arc::clone(&self.hellos);
        let manual = self.manual_acks.lock().await.take();

        tokio::spawn(async move {
            // The real worker greets with `ready` to flush headers; the stream ignores it.
            let _ = tx.send(Ok(IngestStreamResponse {
                msg: Some(ingest_stream_response::Msg::Ready(StreamReady {})),
            }));
            if let Some(mut manual) = manual {
                let tx = tx.clone();
                tokio::spawn(async move {
                    while let Some(ack) = manual.recv().await {
                        let ack = match ack {
                            ManualAck::Ok { seq, accepted } => SubBatchAck {
                                seq,
                                status: SubBatchStatus::Ok as i32,
                                accepted,
                                error: String::new(),
                                unfinished: vec![],
                            },
                            ManualAck::Nack(seq) => SubBatchAck {
                                seq,
                                status: SubBatchStatus::Failed as i32,
                                accepted: 0,
                                error: "poisoned".to_string(),
                                unfinished: vec![],
                            },
                            ManualAck::Ack(ack) => ack,
                        };
                        let _ = tx.send(Ok(IngestStreamResponse {
                            msg: Some(ingest_stream_response::Msg::Ack(ack)),
                        }));
                    }
                });
            }
            while let Some(Ok(frame)) = inbound.next().await {
                match frame.msg {
                    Some(ingest_stream_request::Msg::Hello(hello)) => {
                        hellos.lock().await.push(hello.stream_epoch);
                    }
                    Some(ingest_stream_request::Msg::SubBatch(sub_batch)) => {
                        let seq = sub_batch.seq;
                        let accepted = sub_batch.messages.len() as u32;
                        received.lock().await.push(sub_batch);
                        match mode {
                            AckMode::Immediate => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                                        seq,
                                        status: SubBatchStatus::Ok as i32,
                                        accepted,
                                        error: String::new(),
                                        unfinished: vec![],
                                    })),
                                }));
                            }
                            AckMode::NackSeq(nack) if seq == nack => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                                        seq,
                                        status: SubBatchStatus::Failed as i32,
                                        accepted: 0,
                                        error: "poisoned".to_string(),
                                        unfinished: vec![],
                                    })),
                                }));
                            }
                            AckMode::NackSeq(_) => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                                        seq,
                                        status: SubBatchStatus::Ok as i32,
                                        accepted,
                                        error: String::new(),
                                        unfinished: vec![],
                                    })),
                                }));
                            }
                            AckMode::BusySeq(busy) if seq == busy => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                                        seq,
                                        status: SubBatchStatus::Busy as i32,
                                        accepted: 0,
                                        error: "at capacity".to_string(),
                                        unfinished: vec![],
                                    })),
                                }));
                            }
                            AckMode::BusySeq(_) => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                                        seq,
                                        status: SubBatchStatus::Ok as i32,
                                        accepted,
                                        error: String::new(),
                                        unfinished: vec![],
                                    })),
                                }));
                            }
                            AckMode::AckExceptSeq(stuck) if seq == stuck => {}
                            AckMode::AckExceptSeq(_) => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                                        seq,
                                        status: SubBatchStatus::Ok as i32,
                                        accepted,
                                        error: String::new(),
                                        unfinished: vec![],
                                    })),
                                }));
                            }
                            AckMode::Manual => {}
                        }
                    }
                    None => {}
                }
            }
        });

        Ok(Response::new(UnboundedReceiverStream::new(rx)))
    }
}

struct MockHandle {
    addr: SocketAddr,
    received: Arc<Mutex<Vec<SubBatch>>>,
    hellos: Arc<Mutex<Vec<u64>>>,
}

async fn start_mock(
    mode: AckMode,
    manual: Option<mpsc::UnboundedReceiver<ManualAck>>,
) -> MockHandle {
    let received = Arc::new(Mutex::new(Vec::new()));
    let hellos = Arc::new(Mutex::new(Vec::new()));
    let worker = MockWorker {
        mode,
        received: Arc::clone(&received),
        hellos: Arc::clone(&hellos),
        manual_acks: Arc::new(Mutex::new(manual)),
    };
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        tonic::transport::Server::builder()
            .add_service(
                WorkerIngestServer::new(worker)
                    .accept_compressed(tonic::codec::CompressionEncoding::Gzip)
                    .send_compressed(tonic::codec::CompressionEncoding::Gzip),
            )
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });
    MockHandle {
        addr,
        received,
        hellos,
    }
}

fn msg(distinct_id: &str, offset: i64) -> SerializedKafkaMessage {
    let mut headers = HashMap::new();
    headers.insert("token".to_string(), "tok".to_string());
    headers.insert("distinct_id".to_string(), distinct_id.to_string());
    SerializedKafkaMessage {
        topic: "events".into(),
        partition: 0,
        offset,
        timestamp: 0,
        key: Some(distinct_id.to_string()),
        value: Some("{}".to_string()),
        headers,
        generation: 0,
    }
}

fn worker_url(addr: SocketAddr) -> String {
    format!("http://{}:9001", addr.ip())
}

#[tokio::test]
async fn sub_batches_reach_the_worker_in_enqueue_order() {
    let mock = start_mock(AckMode::Immediate, None).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);

    // Three back-to-back sends drain onto the stream in one go, in order.
    let pending: Vec<_> = (0..3)
        .map(|i| transport.begin_send(&url, &format!("batch-{i}"), vec![msg("d1", i)], false))
        .collect();
    for (i, p) in pending.into_iter().enumerate() {
        let outcome = p.wait().await.expect("send should succeed");
        assert!(
            matches!(outcome, SendOutcome::Accepted(1)),
            "sub-batch {i}: {outcome:?}"
        );
    }

    let received = mock.received.lock().await;
    let batch_ids: Vec<_> = received.iter().map(|s| s.batch_id.clone()).collect();
    assert_eq!(batch_ids, vec!["batch-0", "batch-1", "batch-2"]);
    let seqs: Vec<_> = received.iter().map(|s| s.seq).collect();
    assert_eq!(seqs, vec![1, 2, 3], "seq is per-stream monotonic from 1");
}

#[tokio::test]
async fn out_of_order_acks_resolve_the_right_sends() {
    let (ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);

    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1), msg("d1", 2)], false);
    let second = transport.begin_send(&url, "batch-2", vec![msg("d2", 3)], false);

    // Ack seq 2 before seq 1.
    wait_for_received(&mock, 2).await;
    ack_tx
        .send(ManualAck::Ok {
            seq: 2,
            accepted: 1,
        })
        .unwrap();
    let second = tokio::spawn(second.wait());
    tokio::time::sleep(Duration::from_millis(200)).await;
    assert!(
        !second.is_finished(),
        "a later ack must wait for every earlier seq"
    );
    ack_tx
        .send(ManualAck::Ok {
            seq: 1,
            accepted: 2,
        })
        .unwrap();
    assert!(matches!(
        first.wait().await.expect("first ack"),
        SendOutcome::Accepted(2)
    ));
    assert!(matches!(
        second.await.unwrap().expect("second ack"),
        SendOutcome::Accepted(1)
    ));
}

async fn wait_for_received(mock: &MockHandle, count: usize) {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(10);
    while mock.received.lock().await.len() < count {
        assert!(
            tokio::time::Instant::now() < deadline,
            "sub-batches never reached the worker"
        );
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

const BUDGET: Duration = Duration::from_millis(250);

fn partial_ack(seq: u64, accepted: u32, unfinished: &[i64]) -> SubBatchAck {
    SubBatchAck {
        seq,
        status: SubBatchStatus::Partial as i32,
        accepted,
        error: String::new(),
        unfinished: unfinished
            .iter()
            .map(|&offset| MessageRef {
                partition: 0,
                offset,
            })
            .collect(),
    }
}

#[tokio::test]
async fn a_partial_ack_resolves_the_send_without_fencing_the_stream() {
    let (ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);
    let budgeted = SendOptions {
        replay: false,
        soft_budget: Some(BUDGET),
    };

    let pending = transport.begin_send_with(
        &url,
        "batch-1",
        vec![msg("d1", 1), msg("d2", 2), msg("d1", 3)],
        budgeted,
    );
    wait_for_received(&mock, 1).await;
    // The worker lists its unfinished messages in its own order.
    ack_tx
        .send(ManualAck::Ack(partial_ack(1, 1, &[3, 1])))
        .unwrap();
    match pending
        .wait()
        .await
        .expect("a partial ack is not a failure")
    {
        SendOutcome::Partial {
            accepted,
            unfinished,
        } => {
            assert_eq!(accepted, 1);
            let offsets: Vec<i64> = unfinished.iter().map(|message| message.offset).collect();
            assert_eq!(
                offsets,
                vec![1, 3],
                "unfinished messages come back in send order"
            );
        }
        other => panic!("expected a partial outcome, got {other:?}"),
    }

    let next = transport.begin_send(&url, "batch-2", vec![msg("d1", 4)], false);
    wait_for_received(&mock, 2).await;
    ack_tx
        .send(ManualAck::Ok {
            seq: 2,
            accepted: 1,
        })
        .unwrap();
    assert!(matches!(
        next.wait().await.expect("the stream stays up"),
        SendOutcome::Accepted(1)
    ));
    assert_eq!(mock.hellos.lock().await.len(), 1, "no reconnect");
}

#[rstest]
#[case::both_copies_unfinished(partial_ack(1, 0, &[1, 1]), vec![1, 1])]
#[case::one_copy_unfinished(partial_ack(1, 1, &[1]), vec![1])]
#[tokio::test]
async fn a_partial_ack_counts_a_message_the_sub_batch_carries_twice(
    #[case] ack: SubBatchAck,
    #[case] expected_unfinished: Vec<i64>,
) {
    let (ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);
    let budgeted = SendOptions {
        replay: false,
        soft_budget: Some(BUDGET),
    };

    let pending =
        transport.begin_send_with(&url, "batch-1", vec![msg("d1", 1), msg("d1", 1)], budgeted);
    wait_for_received(&mock, 1).await;
    ack_tx.send(ManualAck::Ack(ack)).unwrap();

    match pending
        .wait()
        .await
        .expect("a partial ack is not a failure")
    {
        SendOutcome::Partial {
            accepted,
            unfinished,
        } => {
            let offsets: Vec<i64> = unfinished.iter().map(|message| message.offset).collect();
            assert_eq!(offsets, expected_unfinished);
            assert_eq!(
                accepted as usize + offsets.len(),
                2,
                "each copy is either accepted or unfinished"
            );
        }
        other => panic!("expected a partial outcome, got {other:?}"),
    }
}

#[rstest]
#[case::partial_without_a_budget(None, partial_ack(1, 1, &[1]))]
#[case::partial_with_no_unfinished_messages(Some(BUDGET), partial_ack(1, 2, &[]))]
#[case::partial_listing_a_message_not_sent(Some(BUDGET), partial_ack(1, 1, &[9]))]
#[case::partial_listing_the_offset_on_another_partition(
    Some(BUDGET),
    SubBatchAck { unfinished: vec![MessageRef { partition: 1, offset: 1 }], ..partial_ack(1, 1, &[]) }
)]
#[case::partial_listing_a_message_more_often_than_carried(Some(BUDGET), partial_ack(1, 0, &[1, 1]))]
#[case::partial_missing_a_message(Some(BUDGET), partial_ack(1, 0, &[1]))]
#[case::unfinished_messages_on_an_ok_ack(
    Some(BUDGET),
    SubBatchAck { status: SubBatchStatus::Ok as i32, ..partial_ack(1, 2, &[1]) }
)]
#[tokio::test]
async fn a_malformed_ack_fences_the_stream_as_a_fault(
    #[case] soft_budget: Option<Duration>,
    #[case] ack: SubBatchAck,
) {
    let (ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);
    let options = SendOptions {
        replay: false,
        soft_budget,
    };
    let pending =
        transport.begin_send_with(&url, "batch-1", vec![msg("d1", 1), msg("d1", 2)], options);
    wait_for_received(&mock, 1).await;

    ack_tx.send(ManualAck::Ack(ack)).unwrap();
    let error = pending
        .wait()
        .await
        .expect_err("a malformed ack fails the send");
    assert!(
        matches!(error.error, TransportError::WorkerStreamFailed(_)),
        "{:?}",
        error.error
    );
    assert_eq!(
        error.messages.len(),
        2,
        "every message comes back for a retry"
    );
}

#[rstest]
#[case::a_single_frame_carries_the_budget(1_000, Some(BUDGET), vec![250])]
#[case::a_split_send_carries_no_budget(200, Some(BUDGET), vec![0, 0, 0])]
#[case::no_budget_carries_none(1_000, None, vec![0])]
#[case::a_zero_budget_carries_none(1_000, Some(Duration::ZERO), vec![0])]
#[case::a_sub_millisecond_budget_rounds_up(1_000, Some(Duration::from_micros(500)), vec![1])]
#[tokio::test]
async fn a_budget_rides_only_a_single_frame_send(
    #[case] max_body_bytes: usize,
    #[case] soft_budget: Option<Duration>,
    #[case] frame_budgets: Vec<u64>,
) {
    let mock = start_mock(AckMode::Immediate, None).await;
    let mut transport =
        GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    transport.set_max_body_bytes(max_body_bytes);
    let url = worker_url(mock.addr);
    let options = SendOptions {
        replay: false,
        soft_budget,
    };

    transport
        .begin_send_with(
            &url,
            "batch-1",
            vec![msg("d1", 1), msg("d1", 2), msg("d1", 3)],
            options,
        )
        .wait()
        .await
        .expect("the worker accepts every frame");

    let budgets: Vec<u64> = mock
        .received
        .lock()
        .await
        .iter()
        .map(|sub_batch| sub_batch.soft_budget_ms)
        .collect();
    assert_eq!(budgets, frame_budgets);
}

#[rstest]
#[case::ok(ManualAck::Ok { seq: 2, accepted: 2 })]
#[case::partial(ManualAck::Ack(partial_ack(2, 1, &[3])))]
#[tokio::test]
async fn a_failure_fences_a_later_sub_batch_the_worker_already_acked(
    #[case] second_ack: ManualAck,
) {
    // Else seq 2's keys would release and replay ahead of seq 1's.
    let (ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);
    let budgeted = SendOptions {
        replay: false,
        soft_budget: Some(BUDGET),
    };

    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let second =
        transport.begin_send_with(&url, "batch-2", vec![msg("d1", 2), msg("d1", 3)], budgeted);
    wait_for_received(&mock, 2).await;

    ack_tx.send(second_ack).unwrap();
    let second = tokio::spawn(second.wait());
    tokio::time::sleep(Duration::from_millis(200)).await;
    assert!(!second.is_finished(), "seq 2 must wait for seq 1");

    ack_tx.send(ManualAck::Nack(1)).unwrap();
    let first_err = first.wait().await.expect_err("nacked send must fail");
    assert_eq!(first_err.messages[0].offset, 1);
    assert!(matches!(
        first_err.error,
        TransportError::WorkerStreamFailed(_)
    ));
    let second_err = second
        .await
        .unwrap()
        .expect_err("an acked send behind a failure must fence with it");
    let offsets: Vec<i64> = second_err
        .messages
        .iter()
        .map(|message| message.offset)
        .collect();
    assert_eq!(offsets, vec![2, 3], "every message comes back for deferral");
}

#[tokio::test]
async fn sends_enqueued_during_a_fence_are_fenced_until_the_callers_requeue() {
    // Else the next send could reach the worker before the requeued messages.
    let mock = start_mock(AckMode::NackSeq(1), None).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);

    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let first_err = first.wait().await.expect_err("nacked send must fail");
    let guard = first_err
        .fence_guard
        .expect("a fenced send carries a guard");

    let second = transport.begin_send(&url, "batch-2", vec![msg("d1", 2)], false);
    let second_err = tokio::time::timeout(Duration::from_secs(2), second.wait())
        .await
        .expect("a send during a fence must fail promptly")
        .expect_err("a send during a fence must fail");
    assert_eq!(second_err.messages[0].offset, 2);
    assert!(matches!(
        second_err.error,
        TransportError::WorkerStreamFailed(_)
    ));
    assert_eq!(mock.received.lock().await.len(), 1);

    drop(guard);
    drop(second_err);
    let third = transport.begin_send(&url, "batch-3", vec![msg("d1", 3)], false);
    let _ = tokio::time::timeout(Duration::from_secs(5), third.wait())
        .await
        .expect("the worker stream must resume once the fence is released");
    let batch_ids: Vec<_> = mock
        .received
        .lock()
        .await
        .iter()
        .map(|s| s.batch_id.clone())
        .collect();
    assert_eq!(batch_ids, vec!["batch-1", "batch-3"]);
}

#[tokio::test]
async fn an_oversized_sub_batch_rides_the_stream_as_ordered_chunks() {
    // One frame over the worker's cap would fence and replay forever.
    let mock = start_mock(AckMode::Immediate, None).await;
    let mut transport =
        GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    // One `msg()` estimates to ~143 bytes, so each 200-byte frame fits one message.
    transport.set_max_body_bytes(200);
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(
        &url,
        "batch-1",
        vec![msg("d1", 1), msg("d1", 2), msg("d1", 3)],
        false,
    );
    let outcome = pending.wait().await.expect("all chunks accepted");
    assert!(
        matches!(outcome, SendOutcome::Accepted(3)),
        "accepted counts sum across chunks: {outcome:?}"
    );

    let received = mock.received.lock().await;
    let frames: Vec<(u64, &str, Vec<i64>)> = received
        .iter()
        .map(|s| {
            (
                s.seq,
                s.batch_id.as_str(),
                s.messages.iter().map(|m| m.offset).collect(),
            )
        })
        .collect();
    assert_eq!(
        frames,
        vec![
            (1, "batch-1", vec![1]),
            (2, "batch-1", vec![2]),
            (3, "batch-1", vec![3]),
        ],
        "one message per frame, consecutive seqs, in offset order"
    );
}

#[tokio::test]
async fn a_failed_chunk_hands_back_the_whole_sub_batch() {
    // One nacked chunk fails the whole send, acked chunks included.
    let mock = start_mock(AckMode::NackSeq(2), None).await;
    let mut transport =
        GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    // One `msg()` estimates to ~143 bytes, so each 200-byte frame fits one message.
    transport.set_max_body_bytes(200);
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(
        &url,
        "batch-1",
        vec![msg("d1", 1), msg("d1", 2), msg("d1", 3)],
        false,
    );
    let err = pending
        .wait()
        .await
        .expect_err("a nacked chunk fails the send");
    assert!(matches!(err.error, TransportError::WorkerStreamFailed(_)));
    let offsets: Vec<i64> = err.messages.iter().map(|m| m.offset).collect();
    assert_eq!(
        offsets,
        vec![1, 2, 3],
        "the whole sub-batch comes back in order"
    );
    assert!(err.fence_guard.is_some(), "a fenced send carries a guard");
}

#[tokio::test]
async fn chunks_acked_out_of_order_then_fenced_hand_back_messages_in_send_order() {
    let (ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let mut transport =
        GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    transport.set_max_body_bytes(200);
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(
        &url,
        "batch-1",
        vec![msg("d1", 1), msg("d2", 2), msg("d3", 3)],
        false,
    );
    wait_for_received(&mock, 3).await;
    for seq in [3, 2] {
        ack_tx.send(ManualAck::Ok { seq, accepted: 1 }).unwrap();
    }
    ack_tx.send(ManualAck::Nack(1)).unwrap();

    let err = pending
        .wait()
        .await
        .expect_err("a nacked chunk fails the send");
    let offsets: Vec<i64> = err.messages.iter().map(|m| m.offset).collect();
    assert_eq!(offsets, vec![1, 2, 3]);
}

#[tokio::test]
async fn a_nack_fences_everything_outstanding_in_order() {
    // A surviving later sub-batch would overtake the failed one.
    let mock = start_mock(AckMode::NackSeq(1), None).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);

    // All three ride the stream at once; the first's nack fences the other two in order.
    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let second = transport.begin_send(&url, "batch-2", vec![msg("d1", 2)], false);
    let third = transport.begin_send(&url, "batch-3", vec![msg("d2", 3)], false);

    let first_err = first.wait().await.expect_err("nacked send must fail");
    assert_eq!(first_err.messages.len(), 1);
    assert_eq!(
        first_err.messages[0].offset, 1,
        "messages come back for the requeue"
    );
    assert!(matches!(
        first_err.error,
        TransportError::WorkerStreamFailed(_)
    ));

    let second_err = second
        .wait()
        .await
        .expect_err("queued send behind the nack must fail");
    assert_eq!(second_err.messages[0].offset, 2);
    let third_err = third
        .wait()
        .await
        .expect_err("queued send behind the nack must fail");
    assert_eq!(third_err.messages[0].offset, 3);
}

#[tokio::test]
async fn the_worker_stream_reconnects_with_a_new_stream_epoch_after_a_fence() {
    let mock = start_mock(AckMode::NackSeq(1), None).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);

    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    first.wait().await.expect_err("nacked");

    // The mock nacks seq 1 on every stream; only the reconnect is asserted.
    let retry = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], true);
    retry
        .wait()
        .await
        .expect_err("mock nacks seq 1 on every stream");

    let hellos = mock.hellos.lock().await;
    assert_eq!(hellos.len(), 2, "one hello per stream incarnation");
    assert!(
        hellos[1] > hellos[0],
        "stream epoch must increase on reconnect"
    );
}

#[tokio::test]
async fn a_dead_worker_fences_instead_of_hanging() {
    // The caller's deferral path owns the retry pacing.
    let transport = GrpcTransport::new(GrpcPort::Fixed(1), Duration::from_secs(30));
    let pending = transport.begin_send(
        "http://127.0.0.1:9001",
        "batch-1",
        vec![msg("d1", 1)],
        false,
    );
    let err = tokio::time::timeout(Duration::from_secs(10), pending.wait())
        .await
        .expect("must resolve, not hang")
        .expect_err("connect failure");
    assert_eq!(err.messages.len(), 1);
}

#[tokio::test]
async fn a_worker_that_stops_acking_fences_after_the_watchdog_window() {
    let (_ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        Duration::from_millis(200),
    );
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let err = tokio::time::timeout(Duration::from_secs(10), pending.wait())
        .await
        .expect("watchdog must fence, not wait forever")
        .expect_err("un-acked send fails back to the caller");
    assert_eq!(err.messages.len(), 1, "messages come back for the requeue");
    assert_eq!(err.messages[0].offset, 1);
}

#[tokio::test]
async fn a_stuck_oldest_sub_batch_fences_even_while_siblings_keep_acking() {
    // Sibling acks must not extend the oldest sub-batch's deadline.
    let mock = start_mock(AckMode::AckExceptSeq(1), None).await;
    let transport = Arc::new(GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        Duration::from_millis(500),
    ));
    let url = worker_url(mock.addr);

    // Enqueued first, so it is seq 1 — the one the worker never acks.
    let stuck = transport.begin_send(&url, "batch-stuck", vec![msg("d1", 1)], false);

    // Feed acked siblings faster than the ack timeout.
    let feeder = {
        let transport = Arc::clone(&transport);
        let url = url.clone();
        tokio::spawn(async move {
            for i in 0..40 {
                let _ = transport.begin_send(
                    &url,
                    &format!("sibling-{i}"),
                    vec![msg("d2", 100 + i)],
                    false,
                );
                tokio::time::sleep(Duration::from_millis(80)).await;
            }
        })
    };

    // Fences at ~500ms, before the feed stops at ~3.2s (40 x 80ms).
    let err = tokio::time::timeout(Duration::from_secs(2), stuck.wait())
        .await
        .expect("stuck send must fence on its own deadline, not wait for the feed to stop")
        .expect_err("un-acked oldest send fails back to the caller");
    assert_eq!(err.messages.len(), 1, "messages come back for the requeue");
    assert_eq!(err.messages[0].offset, 1);

    feeder.abort();
}

#[tokio::test]
async fn removing_a_worker_lets_its_in_flight_send_settle_by_ack() {
    // A reaped worker that is slow, not dead, still finishes its request; a fence would make a survivor repeat it.
    let (ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    wait_for_received(&mock, 1).await;
    transport.remove_worker(&url);
    ack_tx
        .send(ManualAck::Ok {
            seq: 1,
            accepted: 1,
        })
        .unwrap();

    let outcome = tokio::time::timeout(Duration::from_secs(5), pending.wait())
        .await
        .expect("the removed worker stream still delivers the ack")
        .expect("the ack settles the send");
    assert!(matches!(outcome, SendOutcome::Accepted(1)), "{outcome:?}");
}

#[tokio::test]
async fn removing_a_worker_resolves_its_unacked_send_by_the_watchdog() {
    // Else the caller recovers the dropped send only by crashing and replaying.
    let (_ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        Duration::from_millis(200),
    );
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    for _ in 0..200 {
        if mock.received.lock().await.len() == 1 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    assert_eq!(
        mock.received.lock().await.len(),
        1,
        "send reached the worker"
    );

    transport.remove_worker(&url);

    let err = tokio::time::timeout(Duration::from_secs(5), pending.wait())
        .await
        .expect("reaped worker stream must fence at the ack timeout, not hang")
        .expect_err("the ack watchdog fences the unacked send");
    assert_eq!(err.messages.len(), 1, "messages come back for the requeue");
    assert_eq!(err.messages[0].offset, 1);
}

#[tokio::test]
async fn a_busy_status_fences_as_retriable_with_messages() {
    // Busy is backpressure: re-route without marking the worker unhealthy.
    let mock = start_mock(AckMode::BusySeq(1), None).await;
    let transport = GrpcTransport::new(GrpcPort::Fixed(mock.addr.port()), Duration::from_secs(30));
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let err = pending
        .wait()
        .await
        .expect_err("busy fences the worker stream");
    assert_eq!(err.messages.len(), 1, "messages come back for the requeue");
    assert!(err.error.is_retriable(), "busy is retriable backpressure");
    assert!(matches!(err.error, TransportError::WorkerStreamBusy(_)));
}

enum ControlledReply {
    Busy,
    Ok,
}

struct BusyAttempt {
    worker: usize,
    reply: oneshot::Sender<ControlledReply>,
}

struct ControlledBusyWorker {
    worker: usize,
    attempts: mpsc::UnboundedSender<BusyAttempt>,
}

#[tonic::async_trait]
impl WorkerIngest for ControlledBusyWorker {
    type IngestStreamStream = UnboundedReceiverStream<Result<IngestStreamResponse, Status>>;

    async fn ingest_stream(
        &self,
        request: Request<Streaming<IngestStreamRequest>>,
    ) -> Result<Response<Self::IngestStreamStream>, Status> {
        let mut inbound = request.into_inner();
        let attempts = self.attempts.clone();
        let worker = self.worker;
        let (tx, rx) = mpsc::unbounded_channel();
        tokio::spawn(async move {
            let _ = tx.send(Ok(IngestStreamResponse {
                msg: Some(ingest_stream_response::Msg::Ready(StreamReady {})),
            }));
            while let Some(Ok(frame)) = inbound.next().await {
                let Some(ingest_stream_request::Msg::SubBatch(sub_batch)) = frame.msg else {
                    continue;
                };
                let (reply, wait_for_reply) = oneshot::channel();
                let Some(reply) = async {
                    attempts.send(BusyAttempt { worker, reply }).ok()?;
                    wait_for_reply.await.ok()
                }
                .await
                else {
                    return;
                };
                let (status, accepted, error) = match reply {
                    ControlledReply::Busy => {
                        (SubBatchStatus::Busy as i32, 0, "at capacity".to_string())
                    }
                    ControlledReply::Ok => (
                        SubBatchStatus::Ok as i32,
                        sub_batch.messages.len() as u32,
                        String::new(),
                    ),
                };
                let _ = tx.send(Ok(IngestStreamResponse {
                    msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                        seq: sub_batch.seq,
                        status,
                        accepted,
                        error,
                        unfinished: vec![],
                    })),
                }));
            }
        });
        Ok(Response::new(UnboundedReceiverStream::new(rx)))
    }
}

async fn start_controlled_busy_worker(
    worker: usize,
    attempts: mpsc::UnboundedSender<BusyAttempt>,
) -> SocketAddr {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        tonic::transport::Server::builder()
            .add_service(
                WorkerIngestServer::new(ControlledBusyWorker { worker, attempts })
                    .accept_compressed(tonic::codec::CompressionEncoding::Gzip)
                    .send_compressed(tonic::codec::CompressionEncoding::Gzip),
            )
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });
    addr
}

fn registry_config() -> WorkerRegistryConfig {
    WorkerRegistryConfig {
        probe_interval: Duration::from_secs(60),
        dead_declaration: Duration::from_secs(60),
        passive_window: Duration::from_secs(60),
        passive_error_threshold: 1.0,
        passive_min_samples: usize::MAX,
        degraded_hold: Duration::ZERO,
        min_state_duration: Duration::ZERO,
        probe_failure_threshold: u32::MAX,
        drain_timeout: Duration::from_secs(60),
    }
}

#[tokio::test]
async fn the_watchdog_bounds_overlapping_busy_retries() {
    let (attempts_tx, mut attempts_rx) = mpsc::unbounded_channel();
    let first_addr = start_controlled_busy_worker(0, attempts_tx.clone()).await;
    let second_addr = start_controlled_busy_worker(1, attempts_tx).await;
    let worker_urls = vec![
        format!("http://{first_addr}"),
        format!("http://{second_addr}"),
    ];
    let registry = Arc::new(WorkerRegistry::new(&worker_urls, registry_config()));
    let pool_source = WorkerPoolSource::new(registry, RoutingStrategy::P2c);
    let transport = Arc::new(GrpcTransport::new(
        GrpcPort::OffsetFromHttp(0),
        Duration::from_secs(30),
    ));
    let (batcher, mut outputs) = one_message_batcher(
        pool_source,
        transport,
        Duration::from_millis(100),
        Duration::from_millis(20),
    );

    let mut accumulator = Accumulator::default();
    accumulator.push(Partition(0), msg("a", 1).into());
    accumulator.push(Partition(0), msg("b", 2).into());
    batcher.submit(accumulator, &HashMap::new());

    let first = tokio::time::timeout(Duration::from_secs(1), attempts_rx.recv())
        .await
        .expect("first key reaches a worker")
        .expect("attempt channel stays open");
    let second = tokio::time::timeout(Duration::from_secs(1), attempts_rx.recv())
        .await
        .expect("second key reaches a worker")
        .expect("attempt channel stays open");
    assert_ne!(
        first.worker, second.worker,
        "the two keys must occupy different workers"
    );

    // Keep one request held; release it if no retry arrives in time.
    let busy_replies = Arc::new(AtomicUsize::new(0));
    let replies = Arc::clone(&busy_replies);
    let final_attempt_released = Arc::new(AtomicBool::new(false));
    let released = Arc::clone(&final_attempt_released);
    let controller = tokio::spawn(async move {
        let mut reject = first;
        let mut held = second;
        loop {
            let _ = reject.reply.send(ControlledReply::Busy);
            replies.fetch_add(1, Ordering::Relaxed);
            match tokio::time::timeout(Duration::from_millis(750), attempts_rx.recv()).await {
                Ok(Some(next)) => {
                    reject = held;
                    held = next;
                }
                _ => {
                    let _ = held.reply.send(ControlledReply::Busy);
                    replies.fetch_add(1, Ordering::Relaxed);
                    released.store(true, Ordering::Relaxed);
                    return;
                }
            }
        }
    });
    let error = tokio::time::timeout(Duration::from_secs(3), outputs.errors.recv())
        .await
        .expect("watchdog must bound retries that make no acceptance progress")
        .expect("batcher error channel stays open");
    assert_eq!(
        error,
        "pending work made no progress within the stall timeout"
    );
    assert!(
        final_attempt_released.load(Ordering::Relaxed),
        "an in-flight attempt may settle after the deadline before the watchdog fails"
    );
    assert!(
        busy_replies.load(Ordering::Relaxed) >= 2,
        "the reproduction must overlap busy retry rounds"
    );
    controller.await.unwrap();
}

#[tokio::test]
async fn a_busy_send_is_retried_until_it_completes() {
    let (attempts_tx, mut attempts_rx) = mpsc::unbounded_channel();
    let addr = start_controlled_busy_worker(0, attempts_tx).await;
    let worker_urls = vec![format!("http://{addr}")];
    let registry = Arc::new(WorkerRegistry::new(&worker_urls, registry_config()));
    let pool_source = WorkerPoolSource::new(registry, RoutingStrategy::P2c);
    let transport = Arc::new(GrpcTransport::new(
        GrpcPort::OffsetFromHttp(0),
        Duration::from_secs(30),
    ));
    let (batcher, mut outputs) = one_message_batcher(
        pool_source,
        transport,
        Duration::from_millis(500),
        Duration::from_millis(20),
    );

    let mut accumulator = Accumulator::default();
    accumulator.push(Partition(0), msg("a", 1).into());
    batcher.submit(accumulator, &HashMap::new());

    let first = tokio::time::timeout(Duration::from_secs(1), attempts_rx.recv())
        .await
        .expect("initial send reaches the worker")
        .expect("attempt channel stays open");
    assert!(first.reply.send(ControlledReply::Busy).is_ok());
    let retry = tokio::time::timeout(Duration::from_secs(1), attempts_rx.recv())
        .await
        .expect("the retry reaches the worker")
        .expect("attempt channel stays open");
    assert!(retry.reply.send(ControlledReply::Ok).is_ok());

    let completion = tokio::time::timeout(Duration::from_secs(1), outputs.completions.recv())
        .await
        .expect("successful retry completes")
        .expect("completion channel stays open");
    assert_eq!(completion.accepted, 1);
    tokio::time::sleep(Duration::from_millis(550)).await;
    assert!(
        outputs.errors.try_recv().is_err(),
        "accepted retry resets the watchdog and idle work stays healthy"
    );
}

#[tokio::test]
async fn the_watchdog_allows_in_flight_success_after_the_deadline() {
    let (attempts_tx, mut attempts_rx) = mpsc::unbounded_channel();
    let addr = start_controlled_busy_worker(0, attempts_tx).await;
    let worker_urls = vec![format!("http://{addr}")];
    let registry = Arc::new(WorkerRegistry::new(&worker_urls, registry_config()));
    let pool_source = WorkerPoolSource::new(registry, RoutingStrategy::P2c);
    let transport = Arc::new(GrpcTransport::new(
        GrpcPort::OffsetFromHttp(0),
        Duration::from_secs(30),
    ));
    let (batcher, mut outputs) = one_message_batcher(
        pool_source,
        transport,
        Duration::from_millis(100),
        Duration::from_millis(20),
    );

    let mut accumulator = Accumulator::default();
    accumulator.push(Partition(0), msg("a", 1).into());
    batcher.submit(accumulator, &HashMap::new());

    let attempt = tokio::time::timeout(Duration::from_secs(1), attempts_rx.recv())
        .await
        .expect("send reaches the worker")
        .expect("attempt channel stays open");
    tokio::time::sleep(Duration::from_millis(150)).await;
    assert!(
        outputs.errors.try_recv().is_err(),
        "the watchdog must wait for an in-flight send after its deadline"
    );
    assert!(attempt.reply.send(ControlledReply::Ok).is_ok());
    let completion = tokio::time::timeout(Duration::from_secs(1), outputs.completions.recv())
        .await
        .expect("late successful send completes")
        .expect("completion channel stays open");
    assert_eq!(completion.accepted, 1);

    tokio::time::sleep(Duration::from_millis(150)).await;
    assert!(
        outputs.errors.try_recv().is_err(),
        "late acceptance resets the watchdog and idle work stays healthy"
    );
}
