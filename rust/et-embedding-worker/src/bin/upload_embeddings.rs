use std::env;
use std::fs;
use std::sync::Arc;

use common_kafka::{
    config::KafkaConfig,
    kafka_producer::{create_kafka_producer, send_iter_to_kafka},
};
use common_types::error_tracking::EmbeddingRecord;
use envconfig::Envconfig;
use health::HealthRegistry;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct EmbeddingRecordRaw {
    fingerprint: String,
    team_id: String,
    embeddings: String, // JSON string that needs to be parsed
    #[serde(rename = "_offset")]
    _offset: String,
    #[serde(rename = "_partition")]
    _partition: String,
    #[serde(rename = "_timestamp")]
    _timestamp: String,
    model_name: String,
    embedding_version: String,
    inserted_at: String,
}

impl EmbeddingRecordRaw {
    fn to_embedding_record(&self) -> Result<EmbeddingRecord, Box<dyn std::error::Error>> {
        let team_id: i32 = self.team_id.parse()?;
        let embedding_version: i64 = self.embedding_version.parse()?;
        let embeddings: Vec<f64> = serde_json::from_str(&self.embeddings)?;

        Ok(EmbeddingRecord::new(
            team_id,
            self.model_name.clone(),
            embedding_version,
            self.fingerprint.clone(),
            embeddings,
        ))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        eprintln!("Usage: {} <json_file>", args[0]);
        std::process::exit(1);
    }

    let json_file = &args[1];

    // Read and parse the JSON file
    let json_content = fs::read_to_string(json_file)?;
    let raw_records: Vec<EmbeddingRecordRaw> = serde_json::from_str(&json_content)?;

    // Convert to EmbeddingRecord format
    let embedding_records: Result<Vec<EmbeddingRecord>, _> = raw_records
        .iter()
        .map(|raw| raw.to_embedding_record())
        .collect();

    let embedding_records = embedding_records?;

    println!(
        "Parsed {} embedding records from {}",
        embedding_records.len(),
        json_file
    );

    // Set up Kafka producer
    let config = KafkaConfig::init_from_env()?;
    let health = Arc::new(HealthRegistry::new("upload_embeddings"));
    let handle = health
        .register("rdkafka".to_string(), std::time::Duration::from_secs(30))
        .await;
    let producer = create_kafka_producer(&config, handle).await?;

    // Send to Kafka
    let topic = "clickhouse_error_tracking_issue_fingerprint_embeddings";
    println!(
        "Sending {} embedding records to topic: {}",
        embedding_records.len(),
        topic
    );

    send_iter_to_kafka(&producer, topic, &embedding_records)
        .await
        .into_iter()
        .collect::<Result<Vec<_>, _>>()?;

    println!(
        "Successfully uploaded {} embedding records to Kafka",
        embedding_records.len()
    );

    Ok(())
}
