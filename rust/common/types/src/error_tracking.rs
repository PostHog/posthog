use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewFingerprint {}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingRecord {
    team_id: i32,
    model_name: String,
    embedding_version: i64,
    fingerprint: String,
    embeddings: Vec<f64>,
}
