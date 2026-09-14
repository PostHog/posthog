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

/// One writer lane: a dedup buffer plus the channel to its writer task.
/// Partitions map to lanes by `partition % lanes`, so a partition's
/// messages always flow through the same lane — Kafka's cumulative
/// per-partition commits stay safe because each lane commits only the
/// partitions it owns, in order.
struct Lane {
    buffer: PersonBuffer,
    flush_tx: mpsc::Sender<FlushBatch>,
}

/// Reads from Kafka, decodes Person protos, buffers with dedup per lane,
/// and sends batches to the lane writer tasks for PG upsert + offset commit.
pub struct ConsumerTask {
    consumer: Arc<PersonConsumer>,
    lanes: Vec<Lane>,
    flush_interval: Duration,
    flush_buffer_size: usize,
    handle: Handle,
}

impl ConsumerTask {
    /// `lane_txs` carries one sender per writer lane; each lane gets its own
    /// dedup buffer of `per_lane_capacity` entries. A single-element vec
    /// reproduces the single-writer pipeline.
    pub fn new(
        consumer: Arc<PersonConsumer>,
        lane_txs: Vec<mpsc::Sender<FlushBatch>>,
        per_lane_capacity: usize,
        flush_interval: Duration,
        flush_buffer_size: usize,
        handle: Handle,
    ) -> Self {
        assert!(!lane_txs.is_empty(), "at least one writer lane is required");
        // The nonblocking size flush must fire while the lane still has
        // headroom below its hard cap; otherwise every flush degrades to the
        // blocking backpressure path and one busy writer stalls consumption
        // for all lanes again.
        let max_flush_size = (per_lane_capacity / 2).max(1);
        let flush_buffer_size = if flush_buffer_size > max_flush_size {
            warn!(
                configured = flush_buffer_size,
                clamped = max_flush_size,
                per_lane_capacity,
                "flush_buffer_size clamped to half the per-lane capacity"
            );
            max_flush_size
        } else {
            flush_buffer_size
        };
        let lanes = lane_txs
            .into_iter()
            .map(|flush_tx| Lane {
                buffer: PersonBuffer::new(per_lane_capacity),
                flush_tx,
            })
            .collect();
        Self {
            consumer,
            lanes,
            flush_interval,
            flush_buffer_size,
            handle,
        }
    }

    pub async fn run(mut self) {
        let _guard = self.handle.process_scope();
        let mut flush_timer = tokio::time::interval(self.flush_interval);

        info!(lanes = self.lanes.len(), "Consumer task starting");

        loop {
            // Backpressure: a full lane drains one capped batch before the
            // loop re-checks, so even the hard-cap path releases its backlog
            // as bounded batches rather than one giant flush.
            if let Some(idx) = self.lanes.iter().position(|l| l.buffer.is_full()) {
                counter!("personhog_writer_flushes_by_trigger_total", "trigger" => "backpressure")
                    .increment(1);
                self.send_flush(idx).await;
                continue;
            }

            tokio::select! {
                biased;

                _ = self.handle.shutdown_recv() => {
                    info!("Shutdown signal, flushing remaining buffers");
                    for idx in 0..self.lanes.len() {
                        while !self.lanes[idx].buffer.is_empty() {
                            counter!("personhog_writer_flushes_by_trigger_total", "trigger" => "shutdown")
                                .increment(1);
                            self.send_flush(idx).await;
                        }
                    }
                    break;
                }

                _ = flush_timer.tick() => {
                    // Drain each lane fully, one capped batch at a time. The
                    // blocking send paces the drain at the writer's speed, so
                    // a backlogged lane empties as a sequence of bounded
                    // batches instead of one giant one.
                    for idx in 0..self.lanes.len() {
                        while !self.lanes[idx].buffer.is_empty() {
                            counter!("personhog_writer_flushes_by_trigger_total", "trigger" => "timer")
                                .increment(1);
                            self.send_flush(idx).await;
                        }
                    }
                }

                msg = self.consumer.recv() => {
                    match msg {
                        Ok(borrowed_msg) => {
                            let partition = borrowed_msg.partition();
                            let offset = borrowed_msg.offset();
                            let ts_ms = borrowed_msg.timestamp().to_millis();

                            if let Some(payload) = borrowed_msg.payload() {
                                match Person::decode(payload) {
                                    Ok(person) => {
                                        counter!("personhog_writer_messages_consumed_total")
                                            .increment(1);
                                        let idx = (partition as usize) % self.lanes.len();
                                        let lane = &mut self.lanes[idx];
                                        lane.buffer.insert(person, partition, offset, ts_ms);

                                        // Size-triggered flushes never block the
                                        // consume loop: if this lane's writer is
                                        // still busy, keep buffering and reading —
                                        // other lanes' writers stay fed. The lane's
                                        // hard capacity above is the real limit.
                                        if lane.buffer.len() >= self.flush_buffer_size
                                            && self.try_send_flush(idx)
                                        {
                                            counter!(
                                                "personhog_writer_flushes_by_trigger_total",
                                                "trigger" => "size"
                                            )
                                            .increment(1);
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
                            // A non-fatal error is librdkafka riding out a
                            // blip and needs nothing from us. A fatal
                            // client state never recovers: left here, the
                            // loop re-polls a dead client forever while
                            // the pod reports healthy and its partitions'
                            // records go unwritten.
                            if let Some((code, reason)) = self.consumer.fatal_error() {
                                self.handle.signal_failure(format!(
                                    "Kafka client entered a fatal state ({code:?}): {reason}"
                                ));
                                return;
                            }
                        }
                    }
                }
            }
        }

        info!("Consumer task stopped");
    }

    /// Drain up to `flush_buffer_size` rows (whole partitions only) from a
    /// lane's buffer into a batch. Offset and buffer-size gauges are
    /// recorded here, per flush — updating them per message is too
    /// expensive for the consume loop (dynamic-label registry lookups).
    fn take_batch(&mut self, idx: usize) -> Option<FlushBatch> {
        let lane = &mut self.lanes[idx];
        let batch = lane.buffer.drain_up_to(self.flush_buffer_size)?;

        for (partition, offset) in &batch.offsets {
            gauge!(
                "personhog_writer_partition_offset",
                "partition" => partition.to_string()
            )
            .set(*offset as f64);
        }
        let total: usize = self.lanes.iter().map(|l| l.buffer.len()).sum();
        gauge!("personhog_writer_buffer_size").set(total as f64);

        Some(FlushBatch {
            persons: batch.persons,
            offsets: batch.offsets,
            oldest_message_ts_ms: batch.oldest_message_ts_ms,
        })
    }

    /// Drain one capped batch from a lane and send it to the writer task,
    /// waiting until the writer accepts it. Used on the timer, shutdown, and
    /// hard-capacity paths, where blocking the consume loop is intended
    /// backpressure.
    async fn send_flush(&mut self, idx: usize) {
        let Some(batch) = self.take_batch(idx) else {
            return;
        };
        let count = batch.persons.len();

        let start = std::time::Instant::now();
        if self.lanes[idx].flush_tx.send(batch).await.is_err() {
            error!(rows = count, lane = idx, "writer task gone, dropping batch");
            self.handle
                .signal_failure(format!("Writer task channel closed (lane {idx})"));
        }
        histogram!("personhog_writer_channel_send_duration_ms")
            .record(start.elapsed().as_secs_f64() * 1000.0);
    }

    /// Flush a lane only if its writer channel has capacity right now.
    /// Returns whether a batch was handed off. Never awaits, so a busy
    /// writer on one lane can't stall consumption for the others.
    fn try_send_flush(&mut self, idx: usize) -> bool {
        let tx = self.lanes[idx].flush_tx.clone();
        // Bound to a local first: the permit borrows `tx`, so a tail-expression
        // match would outlive it.
        let flushed = match tx.try_reserve() {
            Ok(permit) => {
                if let Some(batch) = self.take_batch(idx) {
                    permit.send(batch);
                }
                true
            }
            Err(mpsc::error::TrySendError::Full(())) => false,
            Err(mpsc::error::TrySendError::Closed(())) => {
                error!(lane = idx, "writer task gone, cannot flush");
                self.handle
                    .signal_failure(format!("Writer task channel closed (lane {idx})"));
                true
            }
        };
        flushed
    }
}
