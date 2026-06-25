use chrono::{DateTime, Utc};
use common_kafka::kafka_messages::internal_events::{InternalEvent, InternalEventEvent};
use common_kafka::kafka_producer::{send_iter_to_kafka, KafkaContext, KafkaProduceError};
use common_types::embedding::{EmbeddingModel, EmbeddingRequest};
use rdkafka::producer::FutureProducer;
use rdkafka::types::RDKafkaErrorCode;

use crate::core::error::UnhandledError;
use crate::modes::notifications::stacktrace::print_stacktrace;
use crate::modes::notifications::types::NotificationIssue;
use crate::types::OutputErrProps;

pub async fn send_new_fingerprint_event_to_producer<I: NotificationIssue>(
    producer: &FutureProducer<KafkaContext>,
    embedding_worker_topic: &str,
    issue: &I,
    output_props: &OutputErrProps,
) -> Result<(), UnhandledError> {
    let request = fingerprint_embedding_request(issue, output_props);

    let res = send_iter_to_kafka(producer, embedding_worker_topic, &[request])
        .await
        .into_iter()
        .collect::<Result<Vec<_>, _>>();
    if let Err(err) = res {
        return Err(UnhandledError::KafkaProduceError(err));
    }
    Ok(())
}

fn fingerprint_embedding_request<I: NotificationIssue>(
    issue: &I,
    output_props: &OutputErrProps,
) -> EmbeddingRequest {
    EmbeddingRequest {
        team_id: issue.team_id(),
        product: "error_tracking".to_string(),
        document_type: "fingerprint".to_string(),
        rendering: "type_message_and_stack".to_string(),
        document_id: output_props.fingerprint.clone(),
        timestamp: issue.created_at(),
        content: print_stacktrace(output_props, Some(7000)),
        models: vec![EmbeddingModel::OpenAITextEmbeddingLarge],
        metadata: Default::default(),
    }
}

pub async fn send_issue_created_alert_to_producer<I: NotificationIssue>(
    producer: &FutureProducer<KafkaContext>,
    internal_events_topic: &str,
    issue: &I,
    assignee: Option<String>,
    output_props: OutputErrProps,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    send_internal_event_with_producer(
        producer,
        internal_events_topic,
        "$error_tracking_issue_created",
        issue,
        assignee,
        output_props,
        event_timestamp,
    )
    .await
}

pub async fn send_issue_reopened_alert_to_producer<I: NotificationIssue>(
    producer: &FutureProducer<KafkaContext>,
    internal_events_topic: &str,
    issue: &I,
    assignee: Option<String>,
    output_props: OutputErrProps,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    send_internal_event_with_producer(
        producer,
        internal_events_topic,
        "$error_tracking_issue_reopened",
        issue,
        assignee,
        output_props,
        event_timestamp,
    )
    .await
}

async fn send_internal_event_with_producer<I: NotificationIssue>(
    producer: &FutureProducer<KafkaContext>,
    internal_events_topic: &str,
    event: &str,
    issue: &I,
    assignee: Option<String>,
    output_props: OutputErrProps,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    let mut event = InternalEventEvent::new(event, issue.id(), Utc::now(), None);
    event
        .insert_prop("name", issue.name())
        .expect("Strings are serializable");
    event
        .insert_prop("description", issue.description())
        .expect("Strings are serializable");
    event.insert_prop("status", issue.status())?;
    event.insert_prop("fingerprint", &output_props.fingerprint)?;
    event.insert_prop("exception_timestamp", event_timestamp)?;
    event.insert_prop("exception_props", output_props)?;

    if let Some(assignee) = assignee {
        event
            .insert_prop("assignee", assignee)
            .expect("Strings are serializable");
    }

    let iter = [InternalEvent {
        team_id: issue.team_id(),
        event,
        person: None,
    }];

    let res = send_iter_to_kafka(producer, internal_events_topic, &iter)
        .await
        .into_iter()
        .collect::<Result<Vec<_>, _>>();

    match res {
        Ok(_) => Ok(()),
        Err(KafkaProduceError::KafkaProduceError { error })
            if matches!(
                error.rdkafka_error_code(),
                Some(RDKafkaErrorCode::MessageSizeTooLarge)
            ) =>
        {
            let mut iter = iter;
            iter[0].event.properties.remove("exception_props");
            iter[0].event.insert_prop("message_was_too_large", true)?;
            send_iter_to_kafka(producer, internal_events_topic, &iter)
                .await
                .into_iter()
                .collect::<Result<Vec<_>, _>>()?;
            Ok(())
        }
        Err(e) => Err(e.into()),
    }
}
