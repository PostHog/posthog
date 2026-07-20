use chrono::{DateTime, Utc};
use common_kafka::kafka_messages::internal_events::{InternalEvent, InternalEventEvent};
use common_kafka::kafka_producer::{send_iter_to_kafka, KafkaContext, KafkaProduceError};
use common_types::embedding::{EmbeddingModel, EmbeddingRequest};
use rdkafka::producer::FutureProducer;
use rdkafka::types::RDKafkaErrorCode;
use serde_json::Value;
use tracing::debug;
use uuid::Uuid;

use crate::core::error::UnhandledError;
use crate::metric_consts::FINGERPRINT_EMBEDDING_SKIPPED;
use crate::modes::notifications::stacktrace::print_stacktrace;
use crate::modes::notifications::types::NotificationIssue;
use crate::modes::processing::fingerprinting::FingerprintRecordPart;
use crate::types::ProcessedExceptionProperties;

/// SDKs whose fingerprint embeddings we don't generate — they emit too many
/// distinct issues, so embedding every fingerprint isn't worth the cost.
const EMBEDDING_DISABLED_LIBS: &[&str] = &["posthog-elixir"];

struct IssueLifecycleInternalEvent<'a, I: NotificationIssue> {
    event: &'static str,
    notification_id: Uuid,
    issue: &'a I,
    assignee: Option<String>,
    processed_properties: &'a ProcessedExceptionProperties,
    event_timestamp: &'a DateTime<Utc>,
}

pub async fn send_new_fingerprint_event<I: NotificationIssue>(
    producer: &FutureProducer<KafkaContext>,
    embedding_worker_topic: &str,
    issue: &I,
    processed_properties: &ProcessedExceptionProperties,
) -> Result<(), UnhandledError> {
    if let Some(reason) = skip_fingerprint_embedding_reason(processed_properties) {
        metrics::counter!(FINGERPRINT_EMBEDDING_SKIPPED, "reason" => reason).increment(1);
        debug!(
            team_id = issue.team_id(),
            fingerprint = %processed_properties.fingerprint(),
            reason,
            "skipping fingerprint embedding request"
        );
        return Ok(());
    }

    let request = fingerprint_embedding_request(issue, processed_properties);

    let res = send_iter_to_kafka(producer, embedding_worker_topic, &[request])
        .await
        .into_iter()
        .collect::<Result<Vec<_>, _>>();
    if let Err(err) = res {
        return Err(UnhandledError::KafkaProduceError(err));
    }
    Ok(())
}

/// Returns the reason a fingerprint embedding request should be skipped, or
/// `None` if it should be sent. We don't embed issues grouped by a fingerprint
/// the user controls — manual fingerprints and custom grouping rules — since
/// embedding-based similarity grouping doesn't apply to them, nor events from
/// SDKs in `EMBEDDING_DISABLED_LIBS` (they emit too many issues).
fn skip_fingerprint_embedding_reason(
    processed_properties: &ProcessedExceptionProperties,
) -> Option<&'static str> {
    if processed_properties
        .fingerprint_record()
        .iter()
        .any(|part| matches!(part, FingerprintRecordPart::Manual))
    {
        return Some("manual_fingerprint");
    }

    if processed_properties
        .fingerprint_record()
        .iter()
        .any(|part| matches!(part, FingerprintRecordPart::Custom { .. }))
    {
        return Some("custom_grouping_rule");
    }

    let lib = processed_properties
        .properties()
        .get("$lib")
        .and_then(Value::as_str);
    if lib.is_some_and(|lib| EMBEDDING_DISABLED_LIBS.contains(&lib)) {
        return Some("disabled_sdk");
    }

    None
}

fn fingerprint_embedding_request<I: NotificationIssue>(
    issue: &I,
    processed_properties: &ProcessedExceptionProperties,
) -> EmbeddingRequest {
    EmbeddingRequest {
        team_id: issue.team_id(),
        product: "error_tracking".to_string(),
        document_type: "fingerprint".to_string(),
        rendering: "type_message_and_stack".to_string(),
        document_id: processed_properties.fingerprint().to_string(),
        timestamp: issue.created_at(),
        content: print_stacktrace(processed_properties, Some(7000)),
        models: vec![EmbeddingModel::OpenAITextEmbeddingLarge],
        metadata: Default::default(),
    }
}

pub async fn send_issue_created_internal_event<I: NotificationIssue>(
    producer: &FutureProducer<KafkaContext>,
    internal_events_topic: &str,
    notification_id: Uuid,
    issue: &I,
    assignee: Option<String>,
    processed_properties: &ProcessedExceptionProperties,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    send_internal_event_with_producer(
        producer,
        internal_events_topic,
        IssueLifecycleInternalEvent {
            event: "$error_tracking_issue_created",
            notification_id,
            issue,
            assignee,
            processed_properties,
            event_timestamp,
        },
    )
    .await
}

pub async fn send_issue_reopened_internal_event<I: NotificationIssue>(
    producer: &FutureProducer<KafkaContext>,
    internal_events_topic: &str,
    notification_id: Uuid,
    issue: &I,
    assignee: Option<String>,
    processed_properties: &ProcessedExceptionProperties,
    event_timestamp: &DateTime<Utc>,
) -> Result<(), UnhandledError> {
    send_internal_event_with_producer(
        producer,
        internal_events_topic,
        IssueLifecycleInternalEvent {
            event: "$error_tracking_issue_reopened",
            notification_id,
            issue,
            assignee,
            processed_properties,
            event_timestamp,
        },
    )
    .await
}

#[allow(clippy::too_many_arguments)]
pub async fn send_issue_spiking_internal_event<I: NotificationIssue>(
    producer: &FutureProducer<KafkaContext>,
    internal_events_topic: &str,
    notification_id: Uuid,
    issue: &I,
    processed_properties: &ProcessedExceptionProperties,
    detected_at: DateTime<Utc>,
    computed_baseline: f64,
    current_bucket_value: f64,
) -> Result<(), UnhandledError> {
    let mut event = InternalEventEvent::new(
        "$error_tracking_issue_spiking",
        issue.id(),
        Utc::now(),
        None,
    );
    event.uuid = notification_id.to_string();
    event
        .insert_prop("name", issue.name())
        .expect("insert_prop for name should never fail");
    event
        .insert_prop("description", issue.description())
        .expect("insert_prop for description should never fail");
    event
        .insert_prop("computed_baseline", computed_baseline)
        .expect("insert_prop for computed_baseline should never fail");
    event
        .insert_prop("current_bucket_value", current_bucket_value)
        .expect("insert_prop for current_bucket_value should never fail");
    event
        .insert_prop("fingerprint", processed_properties.fingerprint())
        .expect("insert_prop for fingerprint should never fail");
    // Spikes are detected on live traffic, so detection time is a good anchor for finding
    // example events.
    event
        .insert_prop("exception_timestamp", detected_at)
        .expect("insert_prop for exception_timestamp should never fail");
    event.insert_prop("exception_props", processed_properties)?;

    let iter = [InternalEvent {
        team_id: issue.team_id(),
        event,
        person: None,
    }];

    send_iter_to_kafka(producer, internal_events_topic, &iter)
        .await
        .into_iter()
        .collect::<Result<Vec<_>, _>>()?;
    Ok(())
}

async fn send_internal_event_with_producer<I: NotificationIssue>(
    producer: &FutureProducer<KafkaContext>,
    internal_events_topic: &str,
    request: IssueLifecycleInternalEvent<'_, I>,
) -> Result<(), UnhandledError> {
    let IssueLifecycleInternalEvent {
        event,
        notification_id,
        issue,
        assignee,
        processed_properties,
        event_timestamp,
    } = request;

    let mut event = InternalEventEvent::new(event, issue.id(), Utc::now(), None);
    event.uuid = notification_id.to_string();
    event
        .insert_prop("name", issue.name())
        .expect("Strings are serializable");
    event
        .insert_prop("description", issue.description())
        .expect("Strings are serializable");
    event.insert_prop("status", issue.status())?;
    event.insert_prop("fingerprint", processed_properties.fingerprint())?;
    event.insert_prop("exception_timestamp", event_timestamp)?;
    event.insert_prop("exception_props", processed_properties)?;

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

#[cfg(test)]
mod tests {
    use super::*;

    fn props_with(
        record: Vec<FingerprintRecordPart>,
        lib: Option<&str>,
    ) -> ProcessedExceptionProperties {
        let mut value = serde_json::json!({
            "$exception_list": [{"type": "Error", "value": "boom"}],
            "$exception_fingerprint": "test-fingerprint",
            "$exception_fingerprint_record": record,
            "$exception_issue_id": Uuid::nil(),
            "$exception_handled": false,
            "$exception_types": ["Error"],
            "$exception_values": ["boom"],
            "$exception_sources": [],
            "$exception_functions": [],
        });
        if let Some(lib) = lib {
            value
                .as_object_mut()
                .unwrap()
                .insert("$lib".to_string(), Value::String(lib.to_string()));
        }
        serde_json::from_value(value).unwrap()
    }

    #[test]
    fn sends_embedding_for_automatic_fingerprint() {
        let props = props_with(
            vec![FingerprintRecordPart::Exception {
                id: None,
                pieces: vec!["boom".to_string()],
            }],
            Some("posthog-python"),
        );
        assert_eq!(skip_fingerprint_embedding_reason(&props), None);
    }

    #[test]
    fn skips_embedding_for_manual_fingerprint() {
        let props = props_with(vec![FingerprintRecordPart::Manual], Some("posthog-python"));
        assert_eq!(
            skip_fingerprint_embedding_reason(&props),
            Some("manual_fingerprint")
        );
    }

    #[test]
    fn skips_embedding_for_custom_grouping_rule() {
        let props = props_with(
            vec![FingerprintRecordPart::Custom {
                rule_id: Uuid::nil(),
            }],
            Some("posthog-python"),
        );
        assert_eq!(
            skip_fingerprint_embedding_reason(&props),
            Some("custom_grouping_rule")
        );
    }

    #[test]
    fn skips_embedding_for_elixir_sdk() {
        let props = props_with(
            vec![FingerprintRecordPart::Exception {
                id: None,
                pieces: vec!["boom".to_string()],
            }],
            Some("posthog-elixir"),
        );
        assert_eq!(
            skip_fingerprint_embedding_reason(&props),
            Some("disabled_sdk")
        );
    }
}
