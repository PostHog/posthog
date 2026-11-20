mod support;

use std::time::Duration;

use futures::stream;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};

#[tokio::test(start_paused = true)]
async fn transport_errors_do_not_discard_messages() {
    use RDKafkaErrorCode::{AllBrokersDown, BrokerTransportFailure};

    for codes in [
        &[][..],
        &[BrokerTransportFailure],
        &[BrokerTransportFailure; 3],
        &[AllBrokersDown],
        &[BrokerTransportFailure, AllBrokersDown],
    ] {
        let errors = codes
            .iter()
            .map(|&code| Err(KafkaError::MessageConsumption(code)));
        let mut messages = stream::iter(errors.chain([Ok(1), Ok(2)]));

        assert_eq!(support::recv(&mut messages).await.unwrap(), 1);
        assert_eq!(support::recv(&mut messages).await.unwrap(), 2);
    }
}

#[tokio::test(start_paused = true)]
async fn other_errors_fail_without_waiting() {
    for error in [
        KafkaError::MessageConsumption(RDKafkaErrorCode::TopicAuthorizationFailed),
        KafkaError::MessageConsumption(RDKafkaErrorCode::UnknownTopicOrPartition),
        KafkaError::MessageConsumptionFatal(RDKafkaErrorCode::BrokerTransportFailure),
    ] {
        let mut messages = stream::iter([Err::<(), _>(error.clone()), Ok(())]);
        let start = tokio::time::Instant::now();

        assert_eq!(support::recv(&mut messages).await, Err(error));
        assert_eq!(start.elapsed(), Duration::ZERO);
    }
}

#[tokio::test(start_paused = true)]
async fn repeated_transport_errors_obey_the_callers_deadline() {
    let error = KafkaError::MessageConsumption(RDKafkaErrorCode::BrokerTransportFailure);
    let mut messages = stream::repeat(Err::<(), _>(error));
    let deadline = Duration::from_secs(1);
    let start = tokio::time::Instant::now();

    assert!(tokio::time::timeout(deadline, support::recv(&mut messages))
        .await
        .is_err());
    assert_eq!(start.elapsed(), deadline);
}
