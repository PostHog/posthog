mod exception;
mod frame;

pub use exception::*;
pub use frame::*;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct Context {
    pub before: Vec<ContextLine>,
    pub line: ContextLine,
    pub after: Vec<ContextLine>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct ContextLine {
    pub number: u32,
    pub line: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewFingerprintEvent {
    pub team_id: i32,
    pub fingerprint: String,
    pub exception_list: Vec<ExceptionData>,
}

impl NewFingerprintEvent {
    pub fn new(team_id: i32, fingerprint: String, exception_list: Vec<ExceptionData>) -> Self {
        Self {
            team_id,
            fingerprint,
            exception_list,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingRecord {
    team_id: i32,
    model_name: String,
    embedding_version: i64,
    fingerprint: String,
    embeddings: Vec<f64>,
}

impl EmbeddingRecord {
    pub fn new(
        team_id: i32,
        model_name: String,
        embedding_version: i64,
        fingerprint: String,
        embeddings: Vec<f64>,
    ) -> Self {
        Self {
            team_id,
            model_name,
            embedding_version,
            fingerprint,
            embeddings,
        }
    }
}
