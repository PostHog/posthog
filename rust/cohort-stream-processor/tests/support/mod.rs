use std::time::Duration;

use futures::{Stream, StreamExt};
use rdkafka::error::{KafkaError, KafkaResult, RDKafkaErrorCode};

pub async fn recv<S, T>(stream: &mut S) -> KafkaResult<T>
where
    S: Stream<Item = KafkaResult<T>> + Unpin,
{
    loop {
        match stream.next().await.expect("Kafka consumer stream ended") {
            Err(
                error @ KafkaError::MessageConsumption(RDKafkaErrorCode::BrokerTransportFailure),
            ) => {
                eprintln!("Kafka test reader is waiting for transport recovery: {error}");
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            result => return result,
        }
    }
}
