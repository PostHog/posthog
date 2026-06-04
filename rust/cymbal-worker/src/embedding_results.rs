use std::str::FromStr;

use anyhow::Context;
use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use common_types::embedding::EmbeddingResponse;
use temporal_sdk::prelude::client::{sdk_client_options, WorkflowClientTrait, WorkflowOptions};
use temporal_sdk::prelude::worker::Url;
use temporal_sdk::prelude::workflow::AsJsonPayloadExt;
use tracing::{info, warn};

use crate::{config::Config, workflows::PROCESS_EMBEDDING_RESULT_WORKFLOW_TYPE};

pub async fn run_embedding_result_consumer(config: Config) -> anyhow::Result<()> {
    let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())
        .context("failed to initialize embedding result Kafka consumer")?;
    let temporal_client = sdk_client_options(Url::from_str(&config.temporal_address)?)
        .build()
        .context("failed to build Temporal client options")?
        .connect(&config.temporal_namespace, None)
        .await
        .context("failed to connect Temporal client for embedding result consumer")?;

    info!(
        topic = %config.consumer.kafka_consumer_topic,
        group = %config.consumer.kafka_consumer_group,
        "subscribing to embedding result topic"
    );

    loop {
        match consumer.json_recv::<EmbeddingResponse>().await {
            Ok((response, offset)) => {
                if !is_stacktrace_embedding_response(&response) {
                    offset
                        .store()
                        .context("failed to store ignored embedding result offset")?;
                    consumer
                        .commit()
                        .context("failed to commit ignored embedding result offset")?;
                    continue;
                }

                let workflow_id = format!(
                    "cymbal-embedding-result-{}-{}",
                    offset.partition(),
                    offset.get_value()
                );
                let raw_message = serde_json::to_string(&response)
                    .context("failed to serialize embedding result for workflow input")?;
                let input = vec![raw_message.as_json_payload()?];

                temporal_client
                    .start_workflow(
                        input,
                        config.temporal_task_queue.clone(),
                        workflow_id.clone(),
                        PROCESS_EMBEDDING_RESULT_WORKFLOW_TYPE.to_string(),
                        None,
                        WorkflowOptions::default(),
                    )
                    .await
                    .with_context(|| format!("failed to start workflow {workflow_id}"))?;

                info!(
                    workflow_id,
                    team_id = response.request.team_id,
                    product = %response.request.product,
                    document_type = %response.request.document_type,
                    document_id = %response.request.document_id,
                    "started Cymbal embedding result workflow"
                );

                offset
                    .store()
                    .context("failed to store embedding result offset")?;
                consumer
                    .commit()
                    .context("failed to commit embedding result offset")?;
            }
            Err(RecvErr::Kafka(error)) => {
                return Err(error).context("failed to receive embedding result from Kafka");
            }
            Err(RecvErr::Serde(error)) => {
                warn!(?error, "skipping malformed embedding result message");
            }
            Err(RecvErr::Empty) => {
                warn!("skipping empty embedding result message");
            }
        }
    }
}

fn is_stacktrace_embedding_response(response: &EmbeddingResponse) -> bool {
    response.request.product == "error_tracking"
        && matches!(
            response.request.document_type.as_str(),
            "stacktrace" | "fingerprint"
        )
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use chrono::Utc;
    use common_types::embedding::{EmbeddingModel, EmbeddingRequest, EmbeddingResponse};

    use super::is_stacktrace_embedding_response;

    fn response(product: &str, document_type: &str) -> EmbeddingResponse {
        EmbeddingResponse {
            request: EmbeddingRequest {
                team_id: 1,
                product: product.to_string(),
                document_type: document_type.to_string(),
                rendering: "text".to_string(),
                document_id: "document-id".to_string(),
                timestamp: Utc::now(),
                content: "content".to_string(),
                models: vec![EmbeddingModel::OpenAITextEmbeddingSmall],
                metadata: HashMap::new(),
            },
            results: vec![],
        }
    }

    #[test]
    fn identifies_error_tracking_stacktrace_embedding_results() {
        assert!(is_stacktrace_embedding_response(&response(
            "error_tracking",
            "stacktrace"
        )));
        assert!(is_stacktrace_embedding_response(&response(
            "error_tracking",
            "fingerprint"
        )));
        assert!(!is_stacktrace_embedding_response(&response(
            "error_tracking",
            "session_summary"
        )));
        assert!(!is_stacktrace_embedding_response(&response(
            "other_product",
            "stacktrace"
        )));
    }
}
