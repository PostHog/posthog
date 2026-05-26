//! Domain-agnostic linear pipeline contracts and validation.
//!
//! These types describe the shape of a product-owned pipeline without knowing
//! how the product executes stages, serializes payloads, routes remote work, or
//! emits terminal results. They are intentionally metadata-only: runtime
//! orchestration and deployment placement stay in higher-level crates.

use std::collections::HashSet;
use std::error::Error;
use std::fmt::{Display, Formatter};

use crate::{StageProgressMode, StageType};

pub type StageId = String;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StageSpec {
    pub stage_id: StageId,
    pub stage_type: StageType,
    pub input_type: StageType,
    pub output_type: StageType,
    pub progress: StageProgressMode,
    pub effects: StageEffectMode,
    pub transient_failure_policy: TransientFailurePolicy,
}

/// Coarse metadata for whether a stage can be reordered, retried, or run with
/// item-level concurrency by a future runner.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StageEffectMode {
    Pure,
    IdempotentSideEffects,
    OrderedSideEffects,
}

/// Coarse metadata for how transient request-level failures may be retried.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransientFailurePolicy {
    RetryableBeforeWork,
    RetryableIfStageDeclaresSafe,
    NotRetryableAfterDispatch,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LinearPipelineSpec {
    pub input_type: StageType,
    pub terminal_type: StageType,
    pub stages: Vec<StageSpec>,
    pub allowed_links: Vec<StageLinkRule>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StageLinkRule {
    /// The previous stage output type must exactly match the next stage input
    /// type.
    ExactType,
    /// The previous stage outputs a product-owned wrapper that may contain
    /// continue items for the next stage or terminal items that bypass it.
    FanOutContinue {
        stage_output_type: StageType,
        next_input_type: StageType,
        terminal_type: StageType,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PipelineSpecError {
    EmptyPipeline,
    DuplicateStageId {
        stage_id: StageId,
    },
    InvalidFirstStageInput {
        stage_id: StageId,
        expected_type: String,
        actual_type: String,
    },
    InvalidStageLink {
        previous_stage_id: StageId,
        stage_id: StageId,
        expected_type: String,
        actual_type: String,
    },
    InvalidFinalStageOutput {
        stage_id: StageId,
        expected_type: String,
        actual_type: String,
    },
}

impl LinearPipelineSpec {
    pub fn validate(&self) -> Result<(), PipelineSpecError> {
        let Some(first_stage) = self.stages.first() else {
            return Err(PipelineSpecError::EmptyPipeline);
        };

        let mut stage_ids = HashSet::with_capacity(self.stages.len());
        for stage in &self.stages {
            if !stage_ids.insert(&stage.stage_id) {
                return Err(PipelineSpecError::DuplicateStageId {
                    stage_id: stage.stage_id.clone(),
                });
            }
        }

        if first_stage.input_type != self.input_type {
            return Err(PipelineSpecError::InvalidFirstStageInput {
                stage_id: first_stage.stage_id.clone(),
                expected_type: self.input_type.to_string(),
                actual_type: first_stage.input_type.to_string(),
            });
        }

        for stage_pair in self.stages.windows(2) {
            let previous_stage = &stage_pair[0];
            let next_stage = &stage_pair[1];
            if !self.link_is_allowed(previous_stage.output_type, next_stage.input_type) {
                return Err(PipelineSpecError::InvalidStageLink {
                    previous_stage_id: previous_stage.stage_id.clone(),
                    stage_id: next_stage.stage_id.clone(),
                    expected_type: previous_stage.output_type.to_string(),
                    actual_type: next_stage.input_type.to_string(),
                });
            }
        }

        let final_stage = self
            .stages
            .last()
            .expect("non-empty pipeline has a final stage");
        if final_stage.output_type != self.terminal_type {
            return Err(PipelineSpecError::InvalidFinalStageOutput {
                stage_id: final_stage.stage_id.clone(),
                expected_type: self.terminal_type.to_string(),
                actual_type: final_stage.output_type.to_string(),
            });
        }

        Ok(())
    }

    fn link_is_allowed(&self, stage_output_type: StageType, next_input_type: StageType) -> bool {
        self.allowed_links.iter().any(|rule| match rule {
            StageLinkRule::ExactType => stage_output_type == next_input_type,
            StageLinkRule::FanOutContinue {
                stage_output_type: allowed_stage_output_type,
                next_input_type: allowed_next_input_type,
                terminal_type: allowed_terminal_type,
            } => {
                stage_output_type == *allowed_stage_output_type
                    && next_input_type == *allowed_next_input_type
                    && self.terminal_type == *allowed_terminal_type
            }
        })
    }
}

impl Display for PipelineSpecError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            PipelineSpecError::EmptyPipeline => write!(formatter, "pipeline must include at least one stage"),
            PipelineSpecError::DuplicateStageId { stage_id } => {
                write!(formatter, "pipeline contains duplicate stage ID {stage_id}")
            }
            PipelineSpecError::InvalidFirstStageInput {
                stage_id,
                expected_type,
                actual_type,
            } => write!(
                formatter,
                "stage {stage_id} has input type {actual_type}, expected {expected_type}"
            ),
            PipelineSpecError::InvalidStageLink {
                previous_stage_id,
                stage_id,
                expected_type,
                actual_type,
            } => write!(
                formatter,
                "stage {stage_id} has input type {actual_type}, expected {expected_type} from {previous_stage_id}"
            ),
            PipelineSpecError::InvalidFinalStageOutput {
                stage_id,
                expected_type,
                actual_type,
            } => write!(
                formatter,
                "stage {stage_id} has output type {actual_type}, expected {expected_type}"
            ),
        }
    }
}

impl Error for PipelineSpecError {}

#[cfg(test)]
mod tests {
    use super::*;

    const RAW_TYPE: StageType = stage_type("example.widget", "raw", 1);
    const GATE_TYPE: StageType = stage_type("example.widget", "gate", 1);
    const ENRICHED_TYPE: StageType = stage_type("example.widget", "enriched", 1);
    const STORED_TYPE: StageType = stage_type("example.widget", "stored", 1);
    const TERMINAL_TYPE: StageType = stage_type("example.widget", "terminal", 1);
    const OTHER_TYPE: StageType = stage_type("example.widget", "other", 1);

    const fn stage_type(namespace: &'static str, name: &'static str, version: u16) -> StageType {
        StageType {
            namespace,
            name,
            version,
        }
    }

    fn stage(stage_id: &'static str, input_type: StageType, output_type: StageType) -> StageSpec {
        StageSpec {
            stage_id: stage_id.to_string(),
            stage_type: stage_type("example.stage", stage_id, 1),
            input_type,
            output_type,
            progress: StageProgressMode::ItemProgress,
            effects: StageEffectMode::Pure,
            transient_failure_policy: TransientFailurePolicy::RetryableBeforeWork,
        }
    }

    fn exact_spec(stages: Vec<StageSpec>) -> LinearPipelineSpec {
        LinearPipelineSpec {
            input_type: RAW_TYPE,
            terminal_type: TERMINAL_TYPE,
            stages,
            allowed_links: vec![StageLinkRule::ExactType],
        }
    }

    #[test]
    fn accepts_exact_type_links() {
        let spec = exact_spec(vec![
            stage("enrich:v1", RAW_TYPE, ENRICHED_TYPE),
            stage("store:v1", ENRICHED_TYPE, TERMINAL_TYPE),
        ]);

        assert_eq!(spec.validate(), Ok(()));
    }

    #[test]
    fn rejects_empty_pipeline() {
        let spec = exact_spec(vec![]);

        assert_eq!(spec.validate(), Err(PipelineSpecError::EmptyPipeline));
    }

    #[test]
    fn rejects_duplicate_stage_ids() {
        let spec = exact_spec(vec![
            stage("enrich:v1", RAW_TYPE, ENRICHED_TYPE),
            stage("enrich:v1", ENRICHED_TYPE, TERMINAL_TYPE),
        ]);

        assert_eq!(
            spec.validate(),
            Err(PipelineSpecError::DuplicateStageId {
                stage_id: "enrich:v1".to_string()
            })
        );
    }

    #[test]
    fn rejects_first_input_mismatch_with_expected_and_actual_types() {
        let spec = exact_spec(vec![stage("enrich:v1", OTHER_TYPE, TERMINAL_TYPE)]);

        assert_eq!(
            spec.validate(),
            Err(PipelineSpecError::InvalidFirstStageInput {
                stage_id: "enrich:v1".to_string(),
                expected_type: RAW_TYPE.to_string(),
                actual_type: OTHER_TYPE.to_string(),
            })
        );
    }

    #[test]
    fn rejects_invalid_adjacent_link_with_expected_and_actual_types() {
        let spec = exact_spec(vec![
            stage("enrich:v1", RAW_TYPE, ENRICHED_TYPE),
            stage("store:v1", OTHER_TYPE, TERMINAL_TYPE),
        ]);

        assert_eq!(
            spec.validate(),
            Err(PipelineSpecError::InvalidStageLink {
                previous_stage_id: "enrich:v1".to_string(),
                stage_id: "store:v1".to_string(),
                expected_type: ENRICHED_TYPE.to_string(),
                actual_type: OTHER_TYPE.to_string(),
            })
        );
    }

    #[test]
    fn accepts_configured_fan_out_continue_link() {
        let spec = LinearPipelineSpec {
            input_type: RAW_TYPE,
            terminal_type: TERMINAL_TYPE,
            stages: vec![
                stage("admit:v1", RAW_TYPE, GATE_TYPE),
                stage("enrich:v1", RAW_TYPE, ENRICHED_TYPE),
                stage("store:v1", ENRICHED_TYPE, TERMINAL_TYPE),
            ],
            allowed_links: vec![
                StageLinkRule::ExactType,
                StageLinkRule::FanOutContinue {
                    stage_output_type: GATE_TYPE,
                    next_input_type: RAW_TYPE,
                    terminal_type: TERMINAL_TYPE,
                },
            ],
        };

        assert_eq!(spec.validate(), Ok(()));
    }

    #[test]
    fn rejects_unconfigured_fan_out_continue_link() {
        let spec = LinearPipelineSpec {
            input_type: RAW_TYPE,
            terminal_type: TERMINAL_TYPE,
            stages: vec![
                stage("admit:v1", RAW_TYPE, GATE_TYPE),
                stage("enrich:v1", RAW_TYPE, TERMINAL_TYPE),
            ],
            allowed_links: vec![StageLinkRule::ExactType],
        };

        assert_eq!(
            spec.validate(),
            Err(PipelineSpecError::InvalidStageLink {
                previous_stage_id: "admit:v1".to_string(),
                stage_id: "enrich:v1".to_string(),
                expected_type: GATE_TYPE.to_string(),
                actual_type: RAW_TYPE.to_string(),
            })
        );
    }

    #[test]
    fn rejects_fan_out_continue_link_with_wrong_terminal_type() {
        let spec = LinearPipelineSpec {
            input_type: RAW_TYPE,
            terminal_type: TERMINAL_TYPE,
            stages: vec![
                stage("admit:v1", RAW_TYPE, GATE_TYPE),
                stage("enrich:v1", RAW_TYPE, TERMINAL_TYPE),
            ],
            allowed_links: vec![StageLinkRule::FanOutContinue {
                stage_output_type: GATE_TYPE,
                next_input_type: RAW_TYPE,
                terminal_type: OTHER_TYPE,
            }],
        };

        assert!(matches!(
            spec.validate(),
            Err(PipelineSpecError::InvalidStageLink { .. })
        ));
    }

    #[test]
    fn rejects_final_terminal_mismatch_with_expected_and_actual_types() {
        let spec = exact_spec(vec![
            stage("enrich:v1", RAW_TYPE, ENRICHED_TYPE),
            stage("store:v1", ENRICHED_TYPE, STORED_TYPE),
        ]);

        assert_eq!(
            spec.validate(),
            Err(PipelineSpecError::InvalidFinalStageOutput {
                stage_id: "store:v1".to_string(),
                expected_type: TERMINAL_TYPE.to_string(),
                actual_type: STORED_TYPE.to_string(),
            })
        );
    }
}
