use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use ingestion_framework::KafkaMessage;
use ingestion_worker_proto::ingestion::worker::v1 as proto;
use logs_ingestion::service::consumer_loop::{BackgroundTask, BatchProcessor};
use logs_ingestion::service::grpc_worker::LogsWorkerIngest;
use proto::worker_ingest_client::WorkerIngestClient;
use tokio::sync::mpsc;
use tokio_stream::wrappers::{TcpListenerStream, UnboundedReceiverStream};
use tonic::Code;

/// Records what reached the pipeline. A message whose key is `fail` fails its batch in the background task, where the logs pipeline produces.
#[derive(Default)]
struct RecordingProcessor {
    seen: Mutex<Vec<KafkaMessage>>,
}

#[async_trait]
impl BatchProcessor for RecordingProcessor {
    async fn process(&self, messages: Vec<KafkaMessage>) -> anyhow::Result<Option<BackgroundTask>> {
        let fail = messages
            .iter()
            .any(|m| m.key.as_deref() == Some(b"fail".as_slice()));
        self.seen.lock().unwrap().extend(messages);
        Ok(Some(Box::pin(async move {
            anyhow::ensure!(!fail, "produce failed");
            Ok(())
        })))
    }
}

struct Stream {
    processor: Arc<RecordingProcessor>,
    frames: mpsc::UnboundedSender<proto::IngestStreamRequest>,
    responses: tonic::Streaming<proto::IngestStreamResponse>,
}

impl Stream {
    async fn open() -> Self {
        let processor = Arc::new(RecordingProcessor::default());
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = LogsWorkerIngest::new(processor.clone(), 2).into_server();
        tokio::spawn(
            tonic::transport::Server::builder()
                .add_service(server)
                .serve_with_incoming(TcpListenerStream::new(listener)),
        );
        let mut client = WorkerIngestClient::connect(format!("http://{address}"))
            .await
            .unwrap();
        let (frames, outgoing) = mpsc::unbounded_channel();
        let responses = client
            .ingest_stream(UnboundedReceiverStream::new(outgoing))
            .await
            .unwrap()
            .into_inner();
        Self {
            processor,
            frames,
            responses,
        }
    }

    fn hello(&self) {
        self.send(proto::ingest_stream_request::Msg::Hello(
            proto::StreamHello {
                consumer_id: "test".to_string(),
                stream_epoch: 1,
            },
        ));
    }

    fn sub_batch(&self, seq: u64, messages: Vec<proto::KafkaMessage>) {
        self.send(proto::ingest_stream_request::Msg::SubBatch(
            proto::SubBatch {
                seq,
                messages,
                ..Default::default()
            },
        ));
    }

    fn send(&self, msg: proto::ingest_stream_request::Msg) {
        self.frames
            .send(proto::IngestStreamRequest { msg: Some(msg) })
            .unwrap();
    }

    async fn next_ack(&mut self) -> proto::SubBatchAck {
        loop {
            match self.responses.message().await.unwrap().unwrap().msg {
                Some(proto::ingest_stream_response::Msg::Ack(ack)) => return ack,
                _ => continue,
            }
        }
    }
}

fn message(offset: i64, key: Option<&str>) -> proto::KafkaMessage {
    proto::KafkaMessage {
        topic: "logs".to_string(),
        partition: 3,
        offset,
        timestamp: 1_700_000_000_000,
        key: key.map(str::to_string),
        ..Default::default()
    }
}

#[tokio::test]
async fn a_binary_payload_reaches_the_pipeline_unchanged() {
    let mut stream = Stream::open().await;
    // An Avro container is not UTF-8, so it cannot travel in the text `value` field.
    let payload = bytes::Bytes::from_static(&[b'O', b'b', b'j', 1, 0xff, 0xfe, 0x00, 0x80]);
    let mut binary = message(7, None);
    binary.value_bytes = Some(payload.clone());
    binary
        .headers
        .insert("token".to_string(), "phc_test".to_string());
    let mut text = message(8, None);
    text.value = Some("{}".to_string());

    stream.hello();
    stream.sub_batch(1, vec![binary, text]);
    let ack = stream.next_ack().await;

    assert_eq!(
        (ack.seq, ack.status(), ack.accepted),
        (1, proto::SubBatchStatus::Ok, 2)
    );
    let seen = stream.processor.seen.lock().unwrap();
    assert_eq!(seen[0].value, Some(payload));
    assert_eq!((seen[0].partition, seen[0].offset), (3, 7));
    assert_eq!(seen[0].header("token").as_deref(), Some("phc_test"));
    assert_eq!(seen[1].value.as_deref(), Some(b"{}".as_slice()));
}

#[tokio::test]
async fn a_batch_that_fails_in_the_background_is_not_acked_ok() {
    let mut stream = Stream::open().await;

    stream.hello();
    stream.sub_batch(1, vec![message(1, Some("fail"))]);
    let ack = stream.next_ack().await;

    // An OK ack lets the consumer commit past the batch.
    assert_eq!(ack.status(), proto::SubBatchStatus::Failed);
    assert_eq!(ack.accepted, 0);
    assert!(ack.error.contains("produce failed"), "{}", ack.error);
}

#[tokio::test]
async fn a_seq_gap_closes_the_stream_before_the_pipeline_sees_the_batch() {
    let mut stream = Stream::open().await;

    stream.hello();
    stream.sub_batch(2, vec![message(1, None)]);
    let closed = async {
        loop {
            match stream.responses.message().await {
                Ok(Some(_)) => continue,
                Ok(None) => panic!("the stream ended without an error"),
                Err(status) => break status,
            }
        }
    };
    // A worker that accepts the gap acks it, and the stream stays open.
    let status = tokio::time::timeout(Duration::from_secs(5), closed)
        .await
        .expect("the worker did not close the stream");

    assert_eq!(status.code(), Code::FailedPrecondition);
    assert!(stream.processor.seen.lock().unwrap().is_empty());
}
