//! Worker stream-level tests for the gRPC transport against an in-process mock worker.
//!
//! Each test targets one property the worker stream must hold for per-key ordering:
//! wire order equals enqueue order, acks correlate out of order, and a
//! failure fences everything outstanding (in order, with the messages handed
//! back) so the dispatcher's deferral path can replay it.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use ingestion_consumer::grpc_transport::{GrpcPort, GrpcTransport};
use ingestion_consumer::transport::TransportError;
use ingestion_consumer::types::SerializedKafkaMessage;
use ingestion_worker_proto::ingestion::worker::v1::worker_ingest_server::{
    WorkerIngest, WorkerIngestServer,
};
use ingestion_worker_proto::ingestion::worker::v1::{
    ingest_stream_request, ingest_stream_response, IngestStreamRequest, IngestStreamResponse,
    StreamReady, SubBatch, SubBatchAck, SubBatchStatus,
};
use tokio::sync::{mpsc, Mutex};
use tokio_stream::wrappers::UnboundedReceiverStream;
use tokio_stream::StreamExt;
use tonic::{Request, Response, Status, Streaming};

/// What the mock does with each sub-batch it reads.
#[derive(Clone, Copy)]
enum AckMode {
    /// Ack immediately, in read order.
    Immediate,
    /// Buffer everything; the test triggers acks explicitly.
    Manual,
    /// Nack the sub-batch with this seq (and ack the others immediately).
    NackSeq(u64),
    /// Report busy for the sub-batch with this seq (and ack the others).
    BusySeq(u64),
    /// Ack every sub-batch immediately except this seq, which is never acked —
    /// a stuck oldest entry while its siblings keep acking.
    AckExceptSeq(u64),
}

/// Manual mode: the test drives the worker's acks through this.
#[derive(Clone, Copy)]
enum ManualAck {
    Ok { seq: u64, accepted: u32 },
    Nack(u64),
}

type ManualAcks = Arc<Mutex<Option<mpsc::UnboundedReceiver<ManualAck>>>>;

struct MockWorker {
    mode: AckMode,
    /// Sub-batches in the order the worker read them, across all streams.
    received: Arc<Mutex<Vec<SubBatch>>>,
    /// Hellos in connection order (stream epochs prove reconnects).
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
            // Mirror the real worker: greet with `ready` so response headers
            // flush; the worker stream must ignore it.
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
                            },
                            ManualAck::Nack(seq) => SubBatchAck {
                                seq,
                                status: SubBatchStatus::Failed as i32,
                                accepted: 0,
                                error: "poisoned".to_string(),
                            },
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
        topic: "events".to_string(),
        partition: 0,
        offset,
        timestamp: 0,
        key: Some(distinct_id.to_string()),
        value: Some("{}".to_string()),
        headers,
    }
}

/// The worker stream's worker URL: HTTP port is fake, the gRPC port is the mock's.
fn worker_url(addr: SocketAddr) -> String {
    format!("http://{}:9001", addr.ip())
}

#[tokio::test]
async fn sub_batches_reach_the_worker_in_enqueue_order() {
    let mock = start_mock(AckMode::Immediate, None).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        2,
        Duration::from_secs(30),
    );
    let url = worker_url(mock.addr);

    // Enqueue three sub-batches back to back — more than the un-acked cap, so
    // ordering must survive the ledger pacing too.
    let pending: Vec<_> = (0..3)
        .map(|i| transport.begin_send(&url, &format!("batch-{i}"), vec![msg("d1", i)], false))
        .collect();
    for (i, p) in pending.into_iter().enumerate() {
        let accepted = p.wait().await.expect("send should succeed");
        assert_eq!(accepted, 1, "sub-batch {i}");
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
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        2,
        Duration::from_secs(30),
    );
    let url = worker_url(mock.addr);

    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1), msg("d1", 2)], false);
    let second = transport.begin_send(&url, "batch-2", vec![msg("d2", 3)], false);

    // Wait until both are on the wire, then ack seq 2 before seq 1 with
    // distinct counts — each pending must get its own, and the later one
    // must not resolve ahead of the earlier one.
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
    assert_eq!(first.wait().await.expect("first ack"), 2);
    assert_eq!(second.await.unwrap().expect("second ack"), 1);
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

#[tokio::test]
async fn a_failure_fences_a_later_sub_batch_the_worker_already_acked() {
    // Regression: with more than one un-acked sub-batch, the worker may ack
    // seq 2 before seq 1. If seq 2 resolved on its own ack, its caller would
    // release its keys and never replay it, while seq 1's later failure
    // stashed only seq 1 — the older messages would replay after the newer
    // ones. A failure must fence the acked-but-unresolved tail too.
    let (ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        2,
        Duration::from_secs(30),
    );
    let url = worker_url(mock.addr);

    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let second = transport.begin_send(&url, "batch-2", vec![msg("d1", 2)], false);
    wait_for_received(&mock, 2).await;

    ack_tx
        .send(ManualAck::Ok {
            seq: 2,
            accepted: 1,
        })
        .unwrap();
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
    assert_eq!(
        second_err.messages[0].offset, 2,
        "messages come back for deferral"
    );
}

#[tokio::test]
async fn sends_enqueued_during_a_fence_are_fenced_until_the_callers_stash() {
    // Regression: a fence resolves its sends before their callers stash the
    // messages. In that gap the consumer loop can still enqueue a fenced
    // key's next group; if the next stream sent it, it would reach the worker
    // ahead of the stashed older group. The worker stream must keep fencing until
    // every fenced caller drops its guard.
    let mock = start_mock(AckMode::NackSeq(1), None).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        1,
        Duration::from_secs(30),
    );
    let url = worker_url(mock.addr);

    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let first_err = first.wait().await.expect_err("nacked send must fail");
    let guard = first_err
        .fence_guard
        .expect("a fenced send carries a guard");

    // Enqueued while the fence is unacknowledged: fails without riding a
    // stream.
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

    // Both callers stashed: the worker stream resumes and the next send reaches the
    // worker on a fresh stream.
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
    // The worker caps one frame; a sub-batch over the cap must split into
    // consecutive frames on the same stream instead of one frame the worker
    // rejects, fences, and replays forever.
    let mock = start_mock(AckMode::Immediate, None).await;
    let mut transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        2,
        Duration::from_secs(30),
    );
    // Frame size cap in bytes. One `msg()` estimates to ~143 bytes, so this
    // fits exactly one message per frame and three messages become three frames.
    transport.set_max_body_bytes(200);
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(
        &url,
        "batch-1",
        vec![msg("d1", 1), msg("d1", 2), msg("d1", 3)],
        false,
    );
    let accepted = pending.wait().await.expect("all chunks accepted");
    assert_eq!(accepted, 3, "accepted counts sum across chunks");

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
    // All-or-nothing like the HTTP path: chunk 1 is acked, chunk 2 nacked, so
    // the send fails with every message (acked ones included) for deferral,
    // and carries a fence guard.
    let mock = start_mock(AckMode::NackSeq(2), None).await;
    let mut transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        2,
        Duration::from_secs(30),
    );
    // Frame size cap in bytes. One `msg()` estimates to ~143 bytes, so this
    // fits exactly one message per frame and three messages become three frames.
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
async fn a_nack_fences_everything_outstanding_in_order() {
    // Regression: on a failure, every un-acked and queued sub-batch must fail
    // back to the caller with its messages (for the deferral path), and
    // nothing may be silently retried on the next stream — a later sub-batch
    // surviving the fence would leapfrog the failed one and reorder its keys.
    let mock = start_mock(AckMode::NackSeq(1), None).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        1,
        Duration::from_secs(30),
    );
    let url = worker_url(mock.addr);

    // With max_unacked=1, the second and third wait in the queue behind the
    // first — the nack must fence all three.
    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let second = transport.begin_send(&url, "batch-2", vec![msg("d1", 2)], false);
    let third = transport.begin_send(&url, "batch-3", vec![msg("d2", 3)], false);

    let first_err = first.wait().await.expect_err("nacked send must fail");
    assert_eq!(first_err.messages.len(), 1);
    assert_eq!(
        first_err.messages[0].offset, 1,
        "messages come back for deferral"
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

    // Only the nacked sub-batch reached the worker; the fenced ones never
    // rode a stream.
    assert_eq!(mock.received.lock().await.len(), 1);
}

#[tokio::test]
async fn the_worker_stream_reconnects_with_a_new_stream_epoch_after_a_fence() {
    let mock = start_mock(AckMode::NackSeq(1), None).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        2,
        Duration::from_secs(30),
    );
    let url = worker_url(mock.addr);

    let first = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    first.wait().await.expect_err("nacked");

    // The retry (as the deferral path would issue it) lands on a fresh stream
    // with a bumped epoch and replay=true, and succeeds: seq 1 is nacked only
    // once because NackSeq(1) nacks by seq, proving this send is seq 1 on a
    // NEW stream... so use a different worker mode expectation: the second
    // stream's seq-1 sub-batch is nacked again by this mock, which is fine —
    // what we assert is the reconnect (two hellos, increasing epochs).
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
    // Connect failure (nothing listening): the send must resolve with its
    // messages rather than waiting forever — the caller's deferral path owns
    // the retry pacing.
    let transport = GrpcTransport::new(GrpcPort::Fixed(1), 1, Duration::from_secs(30));
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
    // Regression: a worker at capacity (or wedged) simply never acks, and the
    // worker stream has no per-send timeout — without the watchdog the consumer waits
    // forever and the whole pod wedges, as seen in production. The fence must
    // hand the messages back so the deferral path re-routes them.
    let (_ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        2,
        Duration::from_millis(200),
    );
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let err = tokio::time::timeout(Duration::from_secs(10), pending.wait())
        .await
        .expect("watchdog must fence, not wait forever")
        .expect_err("un-acked send fails back to the caller");
    assert_eq!(err.messages.len(), 1, "messages come back for deferral");
    assert_eq!(err.messages[0].offset, 1);
}

#[tokio::test]
async fn a_stuck_oldest_sub_batch_fences_even_while_siblings_keep_acking() {
    // Regression: the watchdog must bound each sub-batch's own wait, not the
    // worker stream's time since its last ack. With more than one un-acked sub-batch, a
    // worker that keeps acking newer sub-batches but never the oldest used to
    // reset a single shared deadline on every ack, so the stuck send waited
    // forever and its Kafka batch never completed — the wedge the watchdog
    // exists to prevent.
    let mock = start_mock(AckMode::AckExceptSeq(1), None).await;
    let transport = Arc::new(GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        2,
        Duration::from_millis(500),
    ));
    let url = worker_url(mock.addr);

    // Enqueued first, so it is seq 1 — the one the worker never acks.
    let stuck = transport.begin_send(&url, "batch-stuck", vec![msg("d1", 1)], false);

    // Keep feeding siblings faster than the ack timeout. Each is acked and
    // drained (the worker stream holds at most one alongside the stuck entry), so a
    // watchdog keyed on the last ack would never fire.
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

    // The stuck send must fence on its own deadline (~500ms), well before the
    // feed stops (~3.2s) — proving sibling acks do not extend its wait.
    let err = tokio::time::timeout(Duration::from_secs(2), stuck.wait())
        .await
        .expect("stuck send must fence on its own deadline, not wait for the feed to stop")
        .expect_err("un-acked oldest send fails back to the caller");
    assert_eq!(err.messages.len(), 1, "messages come back for deferral");
    assert_eq!(err.messages[0].offset, 1);

    feeder.abort();
}

#[tokio::test]
async fn removing_a_worker_fences_its_in_flight_send_with_messages() {
    // Regression: reaping a worker that still has in-flight work must resolve
    // its un-acked sends with the messages intact, so the deferral path can
    // replay them. Aborting the worker stream task instead dropped the sends unresolved,
    // which the caller could only recover by crashing and replaying.
    let (_ack_tx, ack_rx) = mpsc::unbounded_channel();
    let mock = start_mock(AckMode::Manual, Some(ack_rx)).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        2,
        Duration::from_millis(200),
    );
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    // Wait until the send is on the wire (in the worker stream's ledger) before reaping.
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
        .expect("reaped worker stream must fence, not hang")
        .expect_err("reaped worker fences the in-flight send");
    assert_eq!(err.messages.len(), 1, "messages come back for deferral");
    assert_eq!(err.messages[0].offset, 1);
}

#[tokio::test]
async fn a_busy_status_fences_as_retriable_with_messages() {
    // A worker reporting busy is applying backpressure, not failing: the fenced
    // sends must carry their messages (to replay) and classify as retriable, so
    // the consumer re-routes without counting the worker as unhealthy.
    let mock = start_mock(AckMode::BusySeq(1), None).await;
    let transport = GrpcTransport::new(
        GrpcPort::Fixed(mock.addr.port()),
        1,
        Duration::from_secs(30),
    );
    let url = worker_url(mock.addr);

    let pending = transport.begin_send(&url, "batch-1", vec![msg("d1", 1)], false);
    let err = pending
        .wait()
        .await
        .expect_err("busy fences the worker stream");
    assert_eq!(err.messages.len(), 1, "messages come back for deferral");
    assert!(err.error.is_retriable(), "busy is retriable backpressure");
    assert!(matches!(err.error, TransportError::WorkerStreamBusy(_)));
}
