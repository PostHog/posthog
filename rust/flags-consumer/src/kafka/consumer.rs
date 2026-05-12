use std::collections::HashSet;
use std::time::Duration;

use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::kafka::messages::KafkaMessage;
use crate::metric_consts;
use crate::pipeline::batch::EventWithOffset;

/// Single-topic consumer loop, generic over the message type `M`.
pub async fn consume_loop<M: KafkaMessage>(
    consumer: SingleTopicConsumer,
    tx: mpsc::Sender<EventWithOffset>,
    team_filter: Option<HashSet<i32>>,
    shutdown: CancellationToken,
) {
    loop {
        tokio::select! {
            biased;
            _ = shutdown.cancelled() => {
                tracing::info!("{} consumer shutting down", M::SOURCE);
                break;
            }
            result = consumer.json_recv::<M>() => {
                match result {
                    Ok((msg, offset)) => {
                        metrics::counter!(metric_consts::MESSAGES_RECEIVED, "source" => M::SOURCE)
                            .increment(1);

                        if let Some(ref filter) = team_filter {
                            if !filter.contains(&msg.team_id()) {
                                if let Err(e) = offset.store() {
                                    tracing::warn!(error = %e, "{} failed to store filtered offset", M::SOURCE);
                                }
                                metrics::counter!(metric_consts::MESSAGES_FILTERED, "source" => M::SOURCE)
                                    .increment(1);
                                continue;
                            }
                        }

                        let event = msg.classify();
                        if tx.send(EventWithOffset { event, offset }).await.is_err() {
                            tracing::info!("{} channel closed, exiting", M::SOURCE);
                            break;
                        }
                    }
                    Err(RecvErr::Serde(e)) => {
                        tracing::warn!("{} serde error (poison pill skipped): {e}", M::SOURCE);
                        metrics::counter!(metric_consts::MESSAGES_SKIPPED, "source" => M::SOURCE, "reason" => "serde")
                            .increment(1);
                    }
                    Err(RecvErr::Empty) => {
                        metrics::counter!(metric_consts::MESSAGES_SKIPPED, "source" => M::SOURCE, "reason" => "empty")
                            .increment(1);
                    }
                    Err(RecvErr::Kafka(e)) => {
                        tracing::error!("{} kafka error: {e}", M::SOURCE);
                        metrics::counter!(metric_consts::KAFKA_ERRORS, "source" => M::SOURCE).increment(1);
                        tokio::time::sleep(Duration::from_millis(100)).await;
                    }
                }
            }
        }
    }
}
