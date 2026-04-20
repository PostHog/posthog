use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use personhog_proto::personhog::types::v1::Person;
use prost::Message;
use rdkafka::message::Message as KafkaMessage;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::buffer::PersonBuffer;
use crate::kafka::PersonConsumer;

/// Batch of persons and their Kafka offsets, sent from consumer to writer.
pub struct FlushBatch {
    pub persons: Vec<Person>,
    pub offsets: HashMap<i32, i64>,
    /// Timestamp of the oldest Kafka message in this batch (millis since epoch).
    /// Used to compute end-to-end latency from ingestion to PG commit.
    pub oldest_message_ts_ms: Option<i64>,
}

/// Reads from Kafka, decodes Person protos, buffers with dedup, and
/// sends batches to the writer task for PG upsert + offset commit.
pub struct ConsumerTask {
    consumer: Arc<PersonConsumer>,
    buffer: PersonBuffer,
    flush_tx: mpsc::Sender<FlushBatch>,
    flush_interval: Duration,
    flush_buffer_size: usize,
    handle: Handle,
    /// Oldest message timestamp in the current buffer (millis since epoch).
    oldest_message_ts_ms: Option<i64>,
}

impl ConsumerTask {
    pub fn new(
        consumer: Arc<PersonConsumer>,
        buffer: PersonBuffer,
        flush_tx: mpsc::Sender<FlushBatch>,
        flush_interval: Duration,
        flush_buffer_size: usize,
        handle: Handle,
    ) -> Self {
        Self {
            consumer,
            buffer,
            flush_tx,
            flush_interval,
            flush_buffer_size,
            handle,
            oldest_message_ts_ms: None,
        }
    }

    pub async fn run(mut self) {
        let _guard = self.handle.process_scope();
        let mut flush_timer = tokio::time::interval(self.flush_interval);

        info!("Consumer task starting");

        loop {
            // Backpressure: flush immediately when buffer is full
            if self.buffer.is_full() {
                counter!("personhog_writer_flushes_by_trigger_total", "trigger" => "backpressure")
                    .increment(1);
                self.send_flush().await;
                continue;
            }

            tokio::select! {
                biased;

                _ = self.handle.shutdown_recv() => {
                    info!("Shutdown signal, flushing remaining buffer");
                    counter!("personhog_writer_flushes_by_trigger_total", "trigger" => "shutdown")
                        .increment(1);
                    self.send_flush().await;
                    break;
                }

                _ = flush_timer.tick() => {
                    if !self.buffer.is_empty() {
                        counter!("personhog_writer_flushes_by_trigger_total", "trigger" => "timer")
                            .increment(1);
                        self.send_flush().await;
                    }
                }

                msg = self.consumer.recv() => {
                    match msg {
                        Ok(borrowed_msg) => {
                            let partition = borrowed_msg.partition();
                            let offset = borrowed_msg.offset();

                            gauge!(
                                "personhog_writer_partition_offset",
                                "partition" => partition.to_string()
                            )
                            .set(offset as f64);

                            // Track the oldest message timestamp for e2e latency
                            if let Some(ts_ms) = borrowed_msg.timestamp().to_millis() {
                                match self.oldest_message_ts_ms {
                                    Some(existing) if ts_ms < existing => {
                                        self.oldest_message_ts_ms = Some(ts_ms);
                                    }
                                    None => {
                                        self.oldest_message_ts_ms = Some(ts_ms);
                                    }
                                    _ => {}
                                }
                            }

                            if let Some(payload) = borrowed_msg.payload() {
                                match Person::decode(payload) {
                                    Ok(person) => {
                                        counter!("personhog_writer_messages_consumed_total")
                                            .increment(1);
                                        self.buffer.insert(person, partition, offset);
                                        gauge!("personhog_writer_buffer_size")
                                            .set(self.buffer.len() as f64);

                                        if self.buffer.len() >= self.flush_buffer_size {
                                            counter!(
                                                "personhog_writer_flushes_by_trigger_total",
                                                "trigger" => "size"
                                            )
                                            .increment(1);
                                            self.send_flush().await;
                                        }
                                    }
                                    Err(e) => {
                                        counter!("personhog_writer_decode_errors_total")
                                            .increment(1);
                                        warn!(
                                            error = %e, partition, offset,
                                            "failed to decode Person proto"
                                        );
                                    }
                                }
                            }
                        }
                        Err(e) => {
                            counter!("personhog_writer_kafka_errors_total").increment(1);
                            warn!(error = %e, "Kafka recv error");
                        }
                    }
                }
            }
        }

        info!("Consumer task stopped");
    }

    /// Drain the buffer and send to the writer task. The bounded channel
    /// provides backpressure -- if the writer is busy, this blocks.
    async fn send_flush(&mut self) {
        let (persons, offsets) = self.buffer.drain();
        gauge!("personhog_writer_buffer_size").set(self.buffer.len() as f64);
        if persons.is_empty() {
            return;
        }

        let count = persons.len();
        let batch = FlushBatch {
            persons,
            offsets,
            oldest_message_ts_ms: self.oldest_message_ts_ms.take(),
        };

        let start = std::time::Instant::now();
        if self.flush_tx.send(batch).await.is_err() {
            error!(rows = count, "writer task gone, dropping batch");
            self.handle
                .signal_failure("Writer task channel closed".to_string());
        }
        histogram!("personhog_writer_channel_send_duration_seconds")
            .record(start.elapsed().as_secs_f64());
    }
}
