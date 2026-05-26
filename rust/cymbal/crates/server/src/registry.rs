//! Stage contracts and execution placement for Cymbal orchestration.
//!
//! The registry is intentionally small: it records which stage IDs exist, what
//! type IDs they consume/produce, and whether the pipeline should execute them
//! locally or through a remote stage target. Pipeline validation happens here so
//! the service layer can reject invalid chains before starting stage work.

use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};

use cymbal_alerting::ALERTING_STAGE_TYPE;
use cymbal_alerting::{AlertingEvent, ALERTING_STAGE_ID};
use cymbal_core::{
    LinearPipelineSpec, PipelineSpecError, StageEffectMode, StageLinkRule, StagePayload,
    StageProgressMode, StageSpec, StageType, TransientFailurePolicy,
};
use cymbal_domain::{EventResult, InputEvent};
use cymbal_grouping::{GroupedEvent, GROUPING_STAGE_ID, GROUPING_STAGE_TYPE};
use cymbal_linking::{LINKING_STAGE_ID, LINKING_STAGE_TYPE};
use cymbal_resolution::{ResolvedEvent, RESOLUTION_STAGE_ID, RESOLUTION_STAGE_TYPE};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StageExecution {
    Local,
    Remote { target_name: String },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StageContract {
    pub stage_type: StageType,
    pub stage_id: String,
    pub input_type: StageType,
    pub output_type: StageType,
    pub progress: StageProgressMode,
    pub effects: StageEffectMode,
    pub execution: StageExecution,
    pub retryable_on_transient_failure: bool,
}

impl StageContract {
    pub fn stage_spec(&self) -> StageSpec {
        StageSpec {
            stage_id: self.stage_id.clone(),
            stage_type: self.stage_type,
            input_type: self.input_type,
            output_type: self.output_type,
            progress: self.progress,
            effects: self.effects,
            transient_failure_policy: self.transient_failure_policy(),
        }
    }

    fn transient_failure_policy(&self) -> TransientFailurePolicy {
        if self.retryable_on_transient_failure {
            TransientFailurePolicy::RetryableIfStageDeclaresSafe
        } else {
            TransientFailurePolicy::NotRetryableAfterDispatch
        }
    }
}

#[derive(Debug, Clone)]
pub struct StageRegistry {
    contracts: HashMap<String, StageContract>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StageRegistryError {
    UnknownStage(String),
    EmptyPipeline,
    InvalidPipelineSpec(PipelineSpecError),
    InvalidFirstStage {
        stage_id: String,
        expected_type: String,
        actual_type: String,
    },
    InvalidStageLink {
        previous_stage_id: String,
        stage_id: String,
        expected_type: String,
        actual_type: String,
    },
    InvalidFinalStage {
        stage_id: String,
        expected_type: String,
        actual_type: String,
    },
}

impl Display for StageRegistryError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            StageRegistryError::UnknownStage(stage_id) => write!(formatter, "unknown stage {stage_id}"),
            StageRegistryError::EmptyPipeline => write!(formatter, "pipeline must include at least one stage"),
            StageRegistryError::InvalidPipelineSpec(error) => write!(formatter, "{error}"),
            StageRegistryError::InvalidFirstStage {
                stage_id,
                expected_type,
                actual_type,
            } => write!(
                formatter,
                "stage {stage_id} has input type {actual_type}, expected {expected_type}"
            ),
            StageRegistryError::InvalidStageLink {
                previous_stage_id,
                stage_id,
                expected_type,
                actual_type,
            } => write!(
                formatter,
                "stage {stage_id} has input type {actual_type}, expected {expected_type} from {previous_stage_id}"
            ),
            StageRegistryError::InvalidFinalStage {
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

impl Error for StageRegistryError {}

impl From<PipelineSpecError> for StageRegistryError {
    fn from(error: PipelineSpecError) -> Self {
        match error {
            PipelineSpecError::EmptyPipeline => StageRegistryError::EmptyPipeline,
            PipelineSpecError::InvalidFirstStageInput {
                stage_id,
                expected_type,
                actual_type,
            } => StageRegistryError::InvalidFirstStage {
                stage_id,
                expected_type,
                actual_type,
            },
            PipelineSpecError::InvalidStageLink {
                previous_stage_id,
                stage_id,
                expected_type,
                actual_type,
            } => StageRegistryError::InvalidStageLink {
                previous_stage_id,
                stage_id,
                expected_type,
                actual_type,
            },
            PipelineSpecError::InvalidFinalStageOutput {
                stage_id,
                expected_type,
                actual_type,
            } => StageRegistryError::InvalidFinalStage {
                stage_id,
                expected_type,
                actual_type,
            },
            PipelineSpecError::DuplicateStageId { .. } => {
                StageRegistryError::InvalidPipelineSpec(error)
            }
        }
    }
}

impl StageRegistry {
    pub fn local_default() -> Self {
        Self::new(vec![
            resolution_contract(),
            grouping_contract(),
            linking_contract(),
            alerting_contract(),
        ])
    }

    pub fn local_for_stage_ids(stage_ids: &[String]) -> Result<Self, StageRegistryError> {
        let all_contracts = known_contracts();
        let mut contracts = Vec::with_capacity(stage_ids.len());

        for stage_id in stage_ids {
            let Some(contract) = all_contracts.get(stage_id).cloned() else {
                return Err(StageRegistryError::UnknownStage(stage_id.clone()));
            };
            contracts.push(contract);
        }

        Ok(Self::new(contracts))
    }

    pub fn new(contracts: Vec<StageContract>) -> Self {
        Self {
            contracts: contracts
                .into_iter()
                .map(|contract| (contract.stage_id.clone(), contract))
                .collect(),
        }
    }

    pub fn set_remote_stage(
        &mut self,
        stage_id: &str,
        target_name: impl Into<String>,
    ) -> Result<(), StageRegistryError> {
        let Some(contract) = self.contracts.get_mut(stage_id) else {
            return Err(StageRegistryError::UnknownStage(stage_id.to_string()));
        };
        contract.execution = StageExecution::Remote {
            target_name: target_name.into(),
        };

        Ok(())
    }

    pub fn set_retryable_on_transient_failure(
        &mut self,
        stage_id: &str,
        retryable: bool,
    ) -> Result<(), StageRegistryError> {
        let Some(contract) = self.contracts.get_mut(stage_id) else {
            return Err(StageRegistryError::UnknownStage(stage_id.to_string()));
        };
        contract.retryable_on_transient_failure = retryable;

        Ok(())
    }

    pub fn default_pipeline_stage_ids() -> Vec<String> {
        vec![
            RESOLUTION_STAGE_ID.to_string(),
            GROUPING_STAGE_ID.to_string(),
            LINKING_STAGE_ID.to_string(),
        ]
    }

    pub fn default_execution_stage_ids() -> Vec<String> {
        vec![
            RESOLUTION_STAGE_ID.to_string(),
            GROUPING_STAGE_ID.to_string(),
            LINKING_STAGE_ID.to_string(),
            ALERTING_STAGE_ID.to_string(),
        ]
    }

    pub fn contract(&self, stage_id: &str) -> Result<&StageContract, StageRegistryError> {
        self.contracts
            .get(stage_id)
            .ok_or_else(|| StageRegistryError::UnknownStage(stage_id.to_string()))
    }

    /// Stage IDs this registry hosts, sorted for stable wire output. Used by
    /// the stage service to advertise capability on `StageLoad.served_stage_ids`
    /// so callers can filter version-skewed candidates.
    pub fn registered_stage_ids(&self) -> Vec<String> {
        let mut ids: Vec<String> = self.contracts.keys().cloned().collect();
        ids.sort();
        ids
    }

    pub fn validate_pipeline(&self, stage_ids: &[String]) -> Result<(), StageRegistryError> {
        self.pipeline_spec(stage_ids)?
            .validate()
            .map_err(Into::into)
    }

    pub fn pipeline_spec(
        &self,
        stage_ids: &[String],
    ) -> Result<LinearPipelineSpec, StageRegistryError> {
        let stages = stage_ids
            .iter()
            .map(|stage_id| self.contract(stage_id).map(StageContract::stage_spec))
            .collect::<Result<Vec<_>, _>>()?;

        Ok(LinearPipelineSpec {
            input_type: InputEvent::TYPE,
            terminal_type: EventResult::TYPE,
            stages,
            allowed_links: vec![StageLinkRule::ExactType],
        })
    }
}

fn known_contracts() -> HashMap<String, StageContract> {
    [
        resolution_contract(),
        grouping_contract(),
        linking_contract(),
        alerting_contract(),
    ]
    .into_iter()
    .map(|contract| (contract.stage_id.clone(), contract))
    .collect()
}

fn resolution_contract() -> StageContract {
    StageContract {
        stage_type: RESOLUTION_STAGE_TYPE,
        stage_id: RESOLUTION_STAGE_ID.to_string(),
        input_type: InputEvent::TYPE,
        output_type: ResolvedEvent::TYPE,
        progress: StageProgressMode::ItemProgress,
        effects: StageEffectMode::IdempotentSideEffects,
        execution: StageExecution::Local,
        retryable_on_transient_failure: true,
    }
}

fn grouping_contract() -> StageContract {
    StageContract {
        stage_type: GROUPING_STAGE_TYPE,
        stage_id: GROUPING_STAGE_ID.to_string(),
        input_type: ResolvedEvent::TYPE,
        output_type: GroupedEvent::TYPE,
        progress: StageProgressMode::ItemProgress,
        effects: StageEffectMode::Pure,
        execution: StageExecution::Local,
        retryable_on_transient_failure: true,
    }
}

fn linking_contract() -> StageContract {
    StageContract {
        stage_type: LINKING_STAGE_TYPE,
        stage_id: LINKING_STAGE_ID.to_string(),
        input_type: GroupedEvent::TYPE,
        output_type: EventResult::TYPE,
        progress: StageProgressMode::BatchBarrier,
        effects: StageEffectMode::OrderedSideEffects,
        execution: StageExecution::Local,
        retryable_on_transient_failure: true,
    }
}

fn alerting_contract() -> StageContract {
    StageContract {
        stage_type: ALERTING_STAGE_TYPE,
        stage_id: ALERTING_STAGE_ID.to_string(),
        input_type: AlertingEvent::TYPE,
        output_type: EventResult::TYPE,
        progress: StageProgressMode::BatchBarrier,
        effects: StageEffectMode::OrderedSideEffects,
        execution: StageExecution::Local,
        retryable_on_transient_failure: true,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_pipeline_stage_ids_are_valid() {
        let registry = StageRegistry::local_default();

        registry
            .validate_pipeline(&StageRegistry::default_pipeline_stage_ids())
            .unwrap();
    }

    #[test]
    fn registered_stage_ids_reflects_constructed_subset_and_is_sorted() {
        // A stage-mode pod is built with only the stages it hosts; the IDs it
        // advertises on `StageLoad.served_stage_ids` must match exactly so
        // the dispatcher can filter out version-skewed pods.
        let registry = StageRegistry::local_for_stage_ids(&[
            RESOLUTION_STAGE_ID.to_string(),
            LINKING_STAGE_ID.to_string(),
        ])
        .unwrap();

        assert_eq!(
            registry.registered_stage_ids(),
            vec!["linking:v1".to_string(), "resolution:v1".to_string()]
        );
    }

    #[test]
    fn default_contracts_have_stable_ids_and_type_ids() {
        let registry = StageRegistry::local_default();

        let resolution = registry.contract(RESOLUTION_STAGE_ID).unwrap();
        assert_eq!(resolution.stage_id, "resolution:v1");
        assert_eq!(
            resolution.input_type.to_string(),
            "cymbal.core.InputEvent@2"
        );
        assert_eq!(
            resolution.output_type.to_string(),
            "cymbal.resolution.ResolvedEvent@2"
        );

        let grouping = registry.contract(GROUPING_STAGE_ID).unwrap();
        assert_eq!(grouping.stage_id, "grouping:v1");
        assert_eq!(
            grouping.input_type.to_string(),
            "cymbal.resolution.ResolvedEvent@2"
        );
        assert_eq!(
            grouping.output_type.to_string(),
            "cymbal.grouping.GroupedEvent@2"
        );

        let linking = registry.contract(LINKING_STAGE_ID).unwrap();
        assert_eq!(linking.stage_id, "linking:v1");
        assert_eq!(
            linking.input_type.to_string(),
            "cymbal.grouping.GroupedEvent@2"
        );
        assert_eq!(linking.output_type.to_string(), "cymbal.core.EventResult@2");
    }

    #[test]
    fn pipeline_spec_builds_generic_spec_with_exact_stage_links() {
        let registry = StageRegistry::local_default();
        let spec = registry
            .pipeline_spec(&StageRegistry::default_pipeline_stage_ids())
            .unwrap();

        assert_eq!(spec.input_type, InputEvent::TYPE);
        assert_eq!(spec.terminal_type, EventResult::TYPE);
        assert_eq!(
            spec.stages
                .iter()
                .map(|stage| stage.stage_id.as_str())
                .collect::<Vec<_>>(),
            vec![RESOLUTION_STAGE_ID, GROUPING_STAGE_ID, LINKING_STAGE_ID]
        );
        assert_eq!(spec.allowed_links, vec![StageLinkRule::ExactType]);
        spec.validate().unwrap();
    }

    #[test]
    fn stage_spec_preserves_contract_metadata_while_execution_stays_in_server() {
        let mut registry = StageRegistry::local_default();
        registry
            .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-workers")
            .unwrap();

        let resolution = registry.contract(RESOLUTION_STAGE_ID).unwrap();
        let spec = resolution.stage_spec();

        assert_eq!(
            resolution.execution,
            StageExecution::Remote {
                target_name: "resolution-workers".to_string()
            }
        );
        assert_eq!(spec.stage_id, RESOLUTION_STAGE_ID);
        assert_eq!(spec.stage_type, RESOLUTION_STAGE_TYPE);
        assert_eq!(spec.input_type, InputEvent::TYPE);
        assert_eq!(spec.output_type, ResolvedEvent::TYPE);
        assert_eq!(spec.progress, StageProgressMode::ItemProgress);
        assert_eq!(spec.effects, StageEffectMode::IdempotentSideEffects);
        assert_eq!(
            spec.transient_failure_policy,
            TransientFailurePolicy::RetryableIfStageDeclaresSafe
        );
    }

    #[test]
    fn rejects_pipeline_with_invalid_first_stage() {
        let registry = StageRegistry::local_default();
        let result = registry
            .validate_pipeline(&[GROUPING_STAGE_ID.to_string(), LINKING_STAGE_ID.to_string()]);

        assert_eq!(
            result,
            Err(StageRegistryError::InvalidFirstStage {
                stage_id: GROUPING_STAGE_ID.to_string(),
                expected_type: "cymbal.core.InputEvent@2".to_string(),
                actual_type: "cymbal.resolution.ResolvedEvent@2".to_string(),
            })
        );
    }

    #[test]
    fn rejects_unknown_stages() {
        let registry = StageRegistry::local_default();
        let result = registry.validate_pipeline(&["missing:v1".to_string()]);

        assert_eq!(
            result,
            Err(StageRegistryError::UnknownStage("missing:v1".to_string()))
        );
    }

    #[test]
    fn rejects_pipeline_that_does_not_finish_with_event_results() {
        let registry = StageRegistry::local_default();
        let result = registry.validate_pipeline(&[RESOLUTION_STAGE_ID.to_string()]);

        assert!(matches!(
            result,
            Err(StageRegistryError::InvalidFinalStage { .. })
        ));
    }
}
