//! The worker side of `ingestion.worker.v1.WorkerIngest`, so the Rust `ingestion-consumer` can own Kafka and dispatch to this pipeline.
//!
//! It never answers `BUSY` or `PARTIAL`: the batch limit is applied by not reading the next frame, and a sub-batch runs to its end whatever its soft budget.

use std::pin::Pin;
use std::sync::Arc;

use futures::Stream;
use ingestion_framework::KafkaMessage;
use ingestion_worker_proto::ingestion::worker::v1 as proto;
use proto::worker_ingest_server::{WorkerIngest, WorkerIngestServer};
use tokio::sync::{mpsc, Semaphore};
use tonic::{Request, Response, Status, Streaming};

use super::consumer_loop::BatchProcessor;

/// Above the consumer's `INGESTION_TRANSPORT_MAX_BODY_BYTES` frame target, as the Node worker's `INGESTION_API_GRPC_READ_MAX_BYTES` is.
const MAX_DECODING_MESSAGE_BYTES: usize = 32 * 1024 * 1024;

pub struct LogsWorkerIngest {
    processor: Arc<dyn BatchProcessor>,
    /// Shared by every stream, so the limit is per worker, as the consumer's `INGESTION_WORKER_CONCURRENT_BATCHES` assumes.
    slots: Arc<Semaphore>,
}

impl LogsWorkerIngest {
    pub fn new(processor: Arc<dyn BatchProcessor>, concurrent_batches: usize) -> Self {
        Self {
            processor,
            slots: Arc::new(Semaphore::new(concurrent_batches.max(1))),
        }
    }

    pub fn into_server(self) -> WorkerIngestServer<Self> {
        // The consumer gzips its frames unless `INGESTION_TRANSPORT_GZIP` is off.
        WorkerIngestServer::new(self)
            .accept_compressed(tonic::codec::CompressionEncoding::Gzip)
            .max_decoding_message_size(MAX_DECODING_MESSAGE_BYTES)
    }
}

pub fn to_kafka_message(message: proto::KafkaMessage) -> KafkaMessage {
    KafkaMessage {
        topic: message.topic,
        partition: message.partition,
        offset: message.offset,
        key: message.key.map(String::into_bytes),
        value: message
            .value_bytes
            .or_else(|| message.value.map(|text| text.into_bytes().into())),
        headers: message
            .headers
            .into_iter()
            .map(|(key, value)| (key, Some(value.into_bytes())))
            .collect(),
        timestamp: Some(message.timestamp),
    }
}

fn ack(
    seq: u64,
    status: proto::SubBatchStatus,
    accepted: u32,
    error: String,
) -> proto::IngestStreamResponse {
    proto::IngestStreamResponse {
        msg: Some(proto::ingest_stream_response::Msg::Ack(
            proto::SubBatchAck {
                seq,
                status: status as i32,
                accepted,
                error,
                unfinished: Vec::new(),
            },
        )),
    }
}

async fn run_sub_batch(
    processor: &dyn BatchProcessor,
    messages: Vec<KafkaMessage>,
) -> anyhow::Result<()> {
    if let Some(background_task) = processor.process(messages).await? {
        background_task.await?;
    }
    Ok(())
}

type AckFrame = Result<proto::IngestStreamResponse, Status>;

#[tonic::async_trait]
impl WorkerIngest for LogsWorkerIngest {
    type IngestStreamStream = Pin<Box<dyn Stream<Item = AckFrame> + Send>>;

    async fn ingest_stream(
        &self,
        request: Request<Streaming<proto::IngestStreamRequest>>,
    ) -> Result<Response<Self::IngestStreamStream>, Status> {
        let mut frames = request.into_inner();
        let (acks, ack_stream) = mpsc::unbounded_channel::<AckFrame>();
        let processor = Arc::clone(&self.processor);
        let slots = Arc::clone(&self.slots);

        tokio::spawn(async move {
            match frames.message().await {
                Ok(Some(proto::IngestStreamRequest {
                    msg: Some(proto::ingest_stream_request::Msg::Hello(_)),
                })) => {}
                Ok(None) | Err(_) => return,
                Ok(Some(_)) => {
                    let _ = acks.send(Err(Status::invalid_argument(
                        "the first frame of a stream must be a hello",
                    )));
                    return;
                }
            }
            let ready = proto::IngestStreamResponse {
                msg: Some(proto::ingest_stream_response::Msg::Ready(
                    proto::StreamReady {},
                )),
            };
            if acks.send(Ok(ready)).is_err() {
                return;
            }

            let mut next_seq = 1;
            loop {
                let sub_batch = match frames.message().await {
                    Ok(Some(proto::IngestStreamRequest {
                        msg: Some(proto::ingest_stream_request::Msg::SubBatch(sub_batch)),
                    })) => sub_batch,
                    Ok(Some(_)) => {
                        let _ = acks.send(Err(Status::invalid_argument(
                            "expected a sub-batch after the hello",
                        )));
                        return;
                    }
                    Ok(None) | Err(_) => return,
                };
                if sub_batch.seq != next_seq {
                    let _ = acks.send(Err(Status::failed_precondition(format!(
                        "sub-batch seq {} arrived where {next_seq} was expected",
                        sub_batch.seq
                    ))));
                    return;
                }
                next_seq += 1;

                // Waiting here stops the read of later frames, so HTTP/2 flow control holds the consumer back.
                let Ok(slot) = Arc::clone(&slots).acquire_owned().await else {
                    return;
                };
                let processor = Arc::clone(&processor);
                let acks = acks.clone();
                tokio::spawn(async move {
                    let seq = sub_batch.seq;
                    let accepted = sub_batch.messages.len() as u32;
                    let messages = sub_batch
                        .messages
                        .into_iter()
                        .map(to_kafka_message)
                        .collect();
                    let result = run_sub_batch(processor.as_ref(), messages).await;
                    drop(slot);
                    metrics::counter!(
                        "logs_ingestion_worker_sub_batches_total",
                        "status" => if result.is_ok() { "ok" } else { "failed" },
                    )
                    .increment(1);
                    let frame = match result {
                        Ok(()) => ack(seq, proto::SubBatchStatus::Ok, accepted, String::new()),
                        Err(error) => {
                            tracing::error!(error = %error, seq, "logs worker sub-batch failed");
                            ack(seq, proto::SubBatchStatus::Failed, 0, format!("{error:#}"))
                        }
                    };
                    let _ = acks.send(Ok(frame));
                });
            }
        });

        let stream = futures::stream::unfold(ack_stream, |mut ack_stream| async move {
            ack_stream.recv().await.map(|frame| (frame, ack_stream))
        });
        Ok(Response::new(Box::pin(stream)))
    }
}
