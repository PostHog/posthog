use std::collections::HashMap;
use std::sync::Arc;

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use tracing::{error, info, warn};

use crate::aggregator::Aggregator;
use crate::app_context::AppContext;
use crate::fan_out::fan_out;
use crate::metrics_consts::*;
use crate::types::Event;

/// One worker loop: consumes events from Kafka, fans them out into tuples,
/// accumulates per-tuple counts in an in-memory buffer, and on each flush
/// timer drains the buffer to the output topic and stores input offsets.
///
/// Multiple workers can run concurrently against the same shared
/// `SingleTopicConsumer`; rdkafka multiplexes partition assignments
/// across them and each holds its own independent buffer.
pub async fn worker_loop(
    ctx: Arc<AppContext>,
    consumer: SingleTopicConsumer,
    handle: lifecycle::Handle,
) {
    let _guard = handle.process_scope();

    let mut aggregator = Aggregator::new();
    // Latest seen offset per partition; replaced as newer offsets arrive,
    // stored at flush time so commits trail durable produce.
    let mut pending_offsets: HashMap<i32, Offset> = HashMap::new();

    let mut flush_timer = tokio::time::interval(ctx.flush_interval);
    // Skip the immediate tick at startup; first flush fires after one interval.
    flush_timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    flush_timer.reset();

    loop {
        tokio::select! {
            _ = handle.shutdown_recv() => {
                info!("worker received shutdown; draining final flush");
                flush(&mut aggregator, &mut pending_offsets, &ctx, FLUSH_REASON_SHUTDOWN).await;
                return;
            }
            _ = flush_timer.tick() => {
                flush(&mut aggregator, &mut pending_offsets, &ctx, FLUSH_REASON_TIMER).await;
            }
            recv = consumer.json_recv::<Event>() => {
                match recv {
                    Ok((event, offset)) => {
                        handle.report_healthy();
                        metrics::counter!(EVENTS_RECEIVED).increment(1);

                        if ctx.should_process(event.team_id) {
                            let tuples = fan_out(&event);
                            metrics::counter!(TUPLES_AGGREGATED).increment(tuples.len() as u64);
                            aggregator.record_many(tuples);
                        } else {
                            metrics::counter!(EVENTS_FILTERED).increment(1);
                        }

                        pending_offsets.insert(offset.partition(), offset);

                        // Memory-pressure flush: if the buffer hits the cap before
                        // the timer fires, flush early to bound memory.
                        if aggregator.len() >= ctx.max_entries_per_partition {
                            flush(&mut aggregator, &mut pending_offsets, &ctx, FLUSH_REASON_BACKPRESSURE).await;
                        }
                    }
                    Err(RecvErr::Empty) | Err(RecvErr::Serde(_)) => {
                        // SingleTopicConsumer auto-stores poison-pill offsets.
                    }
                    Err(RecvErr::Kafka(e)) => {
                        metrics::counter!(KAFKA_RECV_ERRORS).increment(1);
                        warn!(error = %e, "kafka recv error");
                    }
                }
            }
        }
    }
}

/// Drain the aggregator, produce one message per unique tuple, wait for the
/// produce queue to ack, then store the input offsets we've collected so far.
async fn flush(
    aggregator: &mut Aggregator,
    pending_offsets: &mut HashMap<i32, Offset>,
    ctx: &AppContext,
    reason: &'static str,
) {
    let counts = aggregator.drain();
    if counts.is_empty() && pending_offsets.is_empty() {
        return;
    }

    metrics::counter!(FLUSH_TOTAL, "reason" => reason).increment(1);
    metrics::histogram!(FLUSH_TUPLES).record(counts.len() as f64);

    for (tuple, count) in &counts {
        if let Err(e) = ctx.producer.emit(tuple, *count) {
            metrics::counter!(PRODUCE_FAILED).increment(1);
            error!(error = %e, "producer emit failed; tuple dropped");
        }
    }

    if !counts.is_empty() {
        if let Err(e) = ctx.producer.flush(ctx.producer_flush_timeout).await {
            // If we can't confirm durability, hold the offsets — they'll be
            // re-tried on the next flush. We'd rather replay events than lose
            // counts. AggregatingMergeTree absorbs any resulting duplicates.
            metrics::counter!(PRODUCER_FLUSH_FAILED).increment(1);
            error!(error = %e, "producer flush failed; deferring offset commits");
            return;
        }
    }

    // Produce confirmed; safe to advance our position.
    let to_store = std::mem::take(pending_offsets);
    for (partition, offset) in to_store {
        if let Err(e) = offset.store() {
            metrics::counter!(OFFSET_STORE_FAILED).increment(1);
            warn!(partition, error = %e, "offset store failed");
        }
    }
}
