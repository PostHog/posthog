use anyhow::{bail, Result};

/// Type-compatible placeholder required by the source-pinned classifier.
/// The training CLI rejects oracle mode before a replayer is constructed.
pub struct LlmClient {
    pub model: String,
}

impl LlmClient {
    pub fn one_shot(&self, _prompt: &str, _max_tokens: u32) -> Result<String> {
        bail!("hosted-model calls are disabled in the deterministic training evaluator")
    }
}
