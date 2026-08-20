//! Lane-level tests for the gRPC transport against an in-process mock worker.
//!
//! Each test targets one property the lane must hold for per-key ordering:
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
    ingest_stream_request, IngestStreamRequest, IngestStreamResponse, SubBatch, SubBatchStatus,
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
}

/// Manual mode: the test sends (seq, accepted) acks through this.
type ManualAcks = Arc<Mutex<Option<mpsc::UnboundedReceiver<(u64, u32)>>>>;

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
            // Mirror the real worker: greet with seq 0 so response headers
            // flush; the lane must ignore it.
            let _ = tx.send(Ok(IngestStreamResponse {
                seq: 0,
                status: SubBatchStatus::Ok as i32,
                accepted: 0,
                error: String::new(),
            }));
            if let Some(mut manual) = manual {
                let tx = tx.clone();
                tokio::spawn(async move {
                    while let Some((seq, accepted)) = manual.recv().await {
                        let _ = tx.send(Ok(IngestStreamResponse {
                            seq,
                            status: SubBatchStatus::Ok as i32,
                            accepted,
                            error: String::new(),
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
                                    seq,
                                    status: SubBatchStatus::Ok as i32,
                                    accepted,
                                    error: String::new(),
                                }));
                            }
                            AckMode::NackSeq(nack) if seq == nack => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    seq,
                                    status: SubBatchStatus::Failed as i32,
                                    accepted: 0,
                                    error: "poisoned".to_string(),
                                }));
                            }
                            AckMode::NackSeq(_) => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    seq,
                                    status: SubBatchStatus::Ok as i32,
                                    accepted,
                                    error: String::new(),
                                }));
                            }
                            AckMode::BusySeq(busy) if seq == busy => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    seq,
                                    status: SubBatchStatus::Busy as i32,
                                    accepted: 0,
                                    error: "at capacity".to_string(),
                                }));
                            }
                            AckMode::BusySeq(_) => {
                                let _ = tx.send(Ok(IngestStreamResponse {
                                    seq,
                                    status: SubBatchStatus::Ok as i32,
                                    accepted,
                                    error: String::new(),
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
    manual: Option<mpsc::UnboundedReceiver<(u64, u32)>>,
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

/// The lane's worker URL: HTTP port is fake, the gRPC port is the mock's.
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
    // distinct counts — each pending must get its own.
    let deadline = tokio::time::Instant::now() + Duration::from_secs(10);
    while mock.received.lock().await.len() < 2 {
        assert!(
            tokio::time::Instant::now() < deadline,
            "sub-batches never reached the worker"
        );
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    ack_tx.send((2, 1)).unwrap();
    assert_eq!(second.wait().await.expect("second ack"), 1);
    ack_tx.send((1, 2)).unwrap();
    assert_eq!(first.wait().await.expect("first ack"), 2);
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
    assert!(matches!(first_err.error, TransportError::LaneFailed(_)));

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
async fn the_lane_reconnects_with_a_new_stream_epoch_after_a_fence() {
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
    // lane has no per-send timeout — without the watchdog the consumer waits
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
async fn removing_a_worker_fences_its_in_flight_send_with_messages() {
    // Regression: reaping a worker that still has in-flight work must resolve
    // its un-acked sends with the messages intact, so the deferral path can
    // replay them. Aborting the lane task instead dropped the sends unresolved,
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
    // Wait until the send is on the wire (in the lane's ledger) before reaping.
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
        .expect("reaped lane must fence, not hang")
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
    let err = pending.wait().await.expect_err("busy fences the lane");
    assert_eq!(err.messages.len(), 1, "messages come back for deferral");
    assert!(err.error.is_retriable(), "busy is retriable backpressure");
    assert!(matches!(err.error, TransportError::LaneBusy(_)));
}
