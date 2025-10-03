mod exception;
mod frame;

use std::{fmt::Display, str::FromStr};

pub use exception::*;
pub use frame::*;

use serde::{Deserialize, Serialize};
use thiserror::Error;

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

#[derive(Clone)]
pub struct EmbeddingModelList(pub Vec<EmbeddingModel>);

impl FromStr for EmbeddingModelList {
    type Err = ModelParsingError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        s.split(',')
            .map(|s| s.parse())
            .collect::<Result<Vec<_>, ModelParsingError>>()
            .map(EmbeddingModelList)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum EmbeddingModel {
    #[serde(rename = "text-embedding-3-small")]
    OpenAITextEmbeddingSmall,
    #[serde(rename = "text-embedding-3-large")]
    OpenAITextEmbeddingLarge,
}

#[derive(Error, Debug, Clone)]
#[error("Invalid Model: {model}")]
pub struct ModelParsingError {
    pub model: String,
}

impl FromStr for EmbeddingModel {
    type Err = ModelParsingError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim() {
            "text-embedding-3-small" => Ok(EmbeddingModel::OpenAITextEmbeddingSmall),
            "text-embedding-3-large" => Ok(EmbeddingModel::OpenAITextEmbeddingLarge),
            m => Err(ModelParsingError {
                model: m.to_string(),
            }),
        }
    }
}

impl Display for EmbeddingModel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall => write!(f, "text-embedding-3-small"),
            EmbeddingModel::OpenAITextEmbeddingLarge => write!(f, "text-embedding-3-large"),
        }
    }
}

fn default_embedding_model() -> Vec<EmbeddingModel> {
    vec![EmbeddingModel::OpenAITextEmbeddingLarge]
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewFingerprintEvent {
    pub team_id: i32,
    pub fingerprint: String,
    #[serde(default = "default_embedding_model")]
    pub models: Vec<EmbeddingModel>,
    pub exception_list: Vec<ExceptionData>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingRecord {
    team_id: i32,
    model_name: EmbeddingModel,
    embedding_version: i64,
    fingerprint: String,
    embeddings: Vec<f64>,
}

impl EmbeddingRecord {
    pub fn new(
        team_id: i32,
        model_name: EmbeddingModel,
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
