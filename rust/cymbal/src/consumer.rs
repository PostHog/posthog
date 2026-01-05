use std::sync::Arc;

use crate::{
    app_context::AppContext,
    config::Config,
    metric_consts::{
        DROPPED_EVENTS, EMIT_EVENTS_TIME, ERRORS, EVENTS_WRITTEN, EVENT_BATCH_SIZE,
        EVENT_PROCESSED, EVENT_RECEIVED, HANDLE_BATCH_TIME, MAIN_LOOP_TIME,
    },
    pipeline::{errors::handle_errors, handle_batch, IncomingEvent},
};
use common_kafka::{kafka_consumer::RecvErr, kafka_producer::KafkaProduceError};
use metrics::histogram;
use rdkafka::types::RDKafkaErrorCode;
use tracing::{debug, error};

pub async fn start_consumer(config: &Config, context: Arc<AppContext>) {
    let batch_wait_time = std::time::Duration::from_secs(config.max_event_batch_wait_seconds);
    let batch_size = config.max_events_per_batch;

    loop {
        let whole_loop = common_metrics::timing_guard(MAIN_LOOP_TIME, &[]);
        context.worker_liveness.report_healthy().await;
        // Just grab the event as a serde_json::Value and immediately drop it,
        // we can work out a real type for it later (once we're deployed etc)
        let received: Vec<Result<(IncomingEvent, _), _>> = context
            .kafka_consumer
            .json_recv_batch(batch_size, batch_wait_time)
            .await;

        let mut transactional_producer = context.transactional_producer.lock().await;

        let mut to_process = Vec::with_capacity(received.len());
        let mut offsets = Vec::with_capacity(received.len());

        for message in received {
            match message {
                Ok((event, offset)) => {
                    to_process.push(event);
                    offsets.push(offset);
                }
                Err(RecvErr::Kafka(e)) => {
                    panic!("Kafka error: {e}")
                }
                Err(err) => {
                    // If we failed to parse the message, or it was empty, just log and continue, our
                    // consumer has already stored the offset for us.
                    metrics::counter!(ERRORS, "cause" => "recv_err").increment(1);
                    error!("Error receiving message: {:?}", err);
                    continue;
                }
            };
            metrics::counter!(EVENT_RECEIVED).increment(1);
        }

        histogram!(EVENT_BATCH_SIZE).record(to_process.len() as f64);
        let handle_batch_start = common_metrics::timing_guard(HANDLE_BATCH_TIME, &[]);
        let processed = match handle_batch(to_process, &offsets, context.clone()).await {
            Ok(events) => events,
            Err(failure) => {
                let (index, err) = (failure.index, failure.error);
                let offset = &offsets[index];
                error!("Error handling event: {:?}; offset: {:?}", err, offset);
                panic!("Unhandled error: {err:?}; offset: {offset:?}");
            }
        };
        handle_batch_start.label("outcome", "completed").fin();

        metrics::counter!(EVENT_PROCESSED).increment(processed.len() as u64);

        let txn = match transactional_producer.begin() {
            Ok(txn) => txn,
            Err(e) => {
                error!("Failed to start kafka transaction, {:?}", e);
                panic!("Failed to start kafka transaction: {e:?}");
            }
        };

        let to_emit = handle_errors(processed, context.clone()).await;

        metrics::counter!(EVENTS_WRITTEN).increment(to_emit.len() as u64);

        let emit_time = common_metrics::timing_guard(EMIT_EVENTS_TIME, &[]);
        debug!("Emitting {} events", to_emit.len());
        let results = txn
            .send_keyed_iter_to_kafka(
                &context.config.events_topic,
                |ev| Some(ev.uuid.to_string()),
                to_emit,
            )
            .await;

        for (result, offset) in results.into_iter().zip(offsets.iter()) {
            match result {
                Ok(_) => {}
                Err(KafkaProduceError::KafkaProduceError { error })
                    if matches!(
                        error.rdkafka_error_code(),
                        Some(RDKafkaErrorCode::MessageSizeTooLarge)
                    ) =>
                {
                    // If we got a message too large error, just commit the offset anyway and drop the exception, there's
                    // nothing else we can do.
                    error!(
                        "Dropping exception at offset {:?} due to {:?}",
                        offset, error
                    );
                    metrics::counter!(DROPPED_EVENTS, "reason" => "message_too_large").increment(1);
                }
                Err(e) => {
                    error!(
                        "Failed to send event to kafka: {:?}, related to offset {:?}",
                        e, offset
                    );
                    panic!("Failed to send event to kafka: {e:?}, related to offset {offset:?}");
                }
            }
        }
        emit_time.label("outcome", "completed").fin();

        let metadata = context.kafka_consumer.metadata();

        // TODO - probably being over-explicit with the error handling here, and could instead
        // let main return an error and use the question mark operator, but it's good
        // to be explicit about places we drop things at the top level, so
        match txn.associate_offsets(offsets, &metadata) {
            Ok(_) => {}
            Err(e) => {
                error!(
                    "Failed to associate offsets with kafka transaction, {:?}",
                    e
                );
                panic!("Failed to associate offsets with kafka transaction, {e:?}");
            }
        }

        match txn.commit() {
            Ok(_) => {}
            Err(e) => {
                error!("Failed to commit kafka transaction, {:?}", e);
                panic!("Failed to commit kafka transaction, {e:?}");
            }
        }

        whole_loop.label("finished", "true").fin();
    }
}
