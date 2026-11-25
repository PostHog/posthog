use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Questions keyed by caller-selected IDs.
pub type Questions = BTreeMap<String, Question>;
/// Probability of each possible choice.
pub type Probabilities = BTreeMap<String, f64>;

/// One decision requested of System One.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Question {
    /// Probability of a proposition being true.
    Noul {
        /// Proposition to evaluate.
        instructions: String,
        /// Descriptions of the true and false outcomes.
        criteria: BTreeMap<bool, String>,
    },
    /// Select one named alternative.
    Choice {
        /// Decision to make.
        instructions: String,
        /// Option IDs and their meanings.
        criteria: BTreeMap<String, String>,
    },
    /// Fractional index into ordered rubric levels.
    Score {
        /// Property to score.
        instructions: String,
        /// Rubric from lowest to highest.
        criteria: Vec<String>,
    },
}

/// A typed answer, including the model's available calibration data.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Answer {
    /// Probability that the proposition holds.
    Noul {
        /// Probability of true.
        noul: f64,
        /// Additional calibration when supplied.
        #[serde(flatten)]
        calibration: Calibration,
    },
    /// Winning option and distribution.
    Choice {
        /// Selected option ID.
        choice: String,
        /// Model calibration.
        #[serde(flatten)]
        calibration: Calibration,
    },
    /// Assessment against the ordered rubric.
    Score {
        /// Fractional rubric index.
        score: f64,
        /// Additional calibration when supplied.
        #[serde(flatten)]
        calibration: Calibration,
    },
    /// The model declined this question.
    Refusal,
}

/// Optional confidence and class probabilities returned by the decision host.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Calibration {
    /// Probability of the selected answer, when supplied.
    pub confidence: Option<f64>,
    /// Per-alternative probabilities, when supplied.
    #[serde(default)]
    pub probabilities: Probabilities,
}

/// Decision response keyed by the original question IDs.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Decisions {
    /// Serving model.
    pub model: String,
    /// One answer per requested question.
    pub answers: BTreeMap<String, Answer>,
    /// Token accounting returned by the gateway.
    pub usage: serde_json::Value,
}

/// A turn sent to a writing model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    /// Speaker in the conversation.
    pub role: Role,
    /// Plain text content.
    pub content: String,
}

/// Chat completion message role.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    /// Host instructions.
    System,
    /// Person or topic context.
    User,
    /// Prior model response.
    Assistant,
}
