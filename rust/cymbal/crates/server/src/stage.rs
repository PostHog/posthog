//! Internal remote-stage gRPC service.
//!
//! A stage pod can expose one or more local stages through the generic
//! `CymbalStageRuntime.ProcessStage` API. Each unary `StageBatch` carries a
//! `StageStart` envelope that selects the stage and declares the input/output
//! type IDs; this service validates those IDs before decoding the
//! stage-specific payload bytes.

use std::collections::HashMap;
use std::time::Instant;

use cymbal_alerting::{AlertingEvent, AlertingStage, ALERTING_STAGE_TYPE};
use cymbal_api::cymbal::v1::cymbal_stage_runtime_server::CymbalStageRuntime;
use cymbal_api::cymbal::v1::{
    StageBatch, StageBatchResult, StageItem, StageItemResult, StageStart,
};
use cymbal_core::{BatchContext, PipelineStage, StageInput, StagePayload};
use cymbal_domain::{EventResult, InputEvent};
use cymbal_grouping::{GroupedEvent, GroupingStage, GROUPING_STAGE_TYPE};
use cymbal_linking::{LinkingStage, LINKING_STAGE_TYPE};
use cymbal_resolution::{ResolutionStage, ResolvedEvent, RESOLUTION_STAGE_TYPE};
use cymbal_runtime::RuntimeStages;
use tonic::{Request, Response, Status};

use crate::api::stage_error_to_status;
use crate::codec::{decode_json_payload, encode_json_payload};
use crate::observability::{
    insert_stage_load_metadata, record_stage_item_admission_rejection, InFlightBatchTracker,
    InFlightItemTracker,
};
use crate::registry::StageRegistry;

#[derive(Debug, Clone)]
pub struct StageServiceLimits {
    pub max_stage_items: usize,
    pub default_max_in_flight_stage_items: usize,
    pub per_stage_max_in_flight_items: HashMap<String, usize>,
}

impl Default for StageServiceLimits {
    fn default() -> Self {
        Self {
            max_stage_items: 10_000,
            default_max_in_flight_stage_items: 640_000,
            per_stage_max_in_flight_items: HashMap::new(),
        }
    }
}

impl StageServiceLimits {
    pub fn max_in_flight_items_for(&self, stage_id: &str) -> usize {
        self.per_stage_max_in_flight_items
            .get(stage_id)
            .copied()
            .unwrap_or(self.default_max_in_flight_stage_items)
            .max(1)
    }
}

#[derive(Debug, Clone)]
pub struct CymbalStageService {
    registry: StageRegistry,
    limits: StageServiceLimits,
    in_flight: InFlightBatchTracker,
    item_permits: InFlightItemTracker,
    resolution_stage: ResolutionStage,
    grouping_stage: GroupingStage,
    linking_stage: LinkingStage,
    alerting_stage: AlertingStage,
}

impl CymbalStageService {
    pub fn new(registry: StageRegistry) -> Self {
        Self {
            registry,
            limits: StageServiceLimits::default(),
            in_flight: InFlightBatchTracker::default(),
            item_permits: InFlightItemTracker::default(),
            resolution_stage: ResolutionStage::new(),
            grouping_stage: GroupingStage::new(),
            linking_stage: LinkingStage::new(),
            alerting_stage: AlertingStage::new(),
        }
    }

    pub fn with_limits(mut self, limits: StageServiceLimits) -> Self {
        self.limits = limits;
        self
    }

    pub fn with_in_flight_tracker(mut self, in_flight: InFlightBatchTracker) -> Self {
        self.in_flight = in_flight;
        self
    }

    pub fn with_runtime_stages(mut self, stages: RuntimeStages) -> Self {
        self.resolution_stage = stages.resolution;
        self.grouping_stage = stages.grouping;
        self.linking_stage = stages.linking;
        self.alerting_stage = stages.alerting;
        self
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for CymbalStageService {
    async fn process_stage(
        &self,
        request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        let started_at = Instant::now();
        let _in_flight_guard = match self.in_flight.try_acquire("stage") {
            Ok(guard) => guard,
            Err(error) => {
                tracing::warn!(
                    current = error.current,
                    max = error.max,
                    "rejecting Cymbal stage batch because too many batches are already in flight"
                );
                let mut status = Status::resource_exhausted(error.to_string());
                insert_stage_load_metadata(status.metadata_mut(), &self.in_flight.load_snapshot());
                return Err(status);
            }
        };
        let batch = request.into_inner();
        let start = batch
            .start
            .ok_or_else(|| Status::invalid_argument("stage batch must include StageStart"))?;
        tracing::debug!(
            stage_id = %start.stage_id,
            input_type = %start.input_type,
            output_type = %start.output_type,
            "received process_stage batch"
        );
        let contract = self
            .registry
            .contract(&start.stage_id)
            .map_err(|error| Status::not_found(error.to_string()))?;

        let contract_input_type = contract.input_type.to_string();
        if start.input_type != contract_input_type {
            return Err(Status::invalid_argument(format!(
                "stage {} expected input type {}, got {}",
                start.stage_id, contract_input_type, start.input_type
            )));
        }
        let contract_output_type = contract.output_type.to_string();
        if start.output_type != contract_output_type {
            return Err(Status::invalid_argument(format!(
                "stage {} expected output type {}, got {}",
                start.stage_id, contract_output_type, start.output_type
            )));
        }

        let context = stage_start_to_core_context(&start);
        let batch_id = context.batch_id.clone();
        let items = batch.items;
        if items.len() > self.limits.max_stage_items {
            let mut status = Status::resource_exhausted(format!(
                "stage batch has more than {} items",
                self.limits.max_stage_items
            ));
            let mut load = self.stage_load_snapshot(&start.stage_id);
            load.overloaded = true;
            insert_stage_load_metadata(status.metadata_mut(), &load);
            return Err(status);
        }
        let max_in_flight_items = self.limits.max_in_flight_items_for(&start.stage_id);
        let item_permits =
            match self
                .item_permits
                .try_acquire(&start.stage_id, items.len(), max_in_flight_items)
            {
                Ok(guard) => guard,
                Err(error) => {
                    record_stage_item_admission_rejection(&start.stage_id, "over_capacity");
                    tracing::warn!(
                        stage_id = %start.stage_id,
                        batch_id = %batch_id,
                        current_in_flight_items = error.current,
                        requested_items = error.requested,
                        max_in_flight_items = error.max,
                        "rejecting Cymbal stage batch because too many items are already in flight"
                    );
                    let mut status = Status::resource_exhausted(error.to_string());
                    let mut load = self.stage_load_snapshot(&start.stage_id);
                    load.overloaded = true;
                    insert_stage_load_metadata(status.metadata_mut(), &load);
                    return Err(status);
                }
            };
        tracing::info!(
            stage_id = %start.stage_id,
            batch_id = %batch_id,
            input_type = %start.input_type,
            output_type = %start.output_type,
            items = items.len(),
            "cymbal stage batch received"
        );
        let input_items = items.len();
        let output = match match contract.stage_type {
            RESOLUTION_STAGE_TYPE => self.process_resolution(context, items).await,
            GROUPING_STAGE_TYPE => self.process_grouping(context, items).await,
            LINKING_STAGE_TYPE => self.process_linking(context, items).await,
            ALERTING_STAGE_TYPE => self.process_alerting(context, items).await,
            unknown_stage_type => {
                tracing::info!(
                    stage_id = %start.stage_id,
                    stage_type = %unknown_stage_type,
                    batch_id = %batch_id,
                    input_items,
                    duration_ms = started_at.elapsed().as_millis(),
                    status = "error",
                    error = "unknown stage type",
                    "cymbal stage batch finished"
                );
                return Err(Status::not_found(format!(
                    "unknown stage type {} for {}",
                    unknown_stage_type, start.stage_id
                )));
            }
        } {
            Ok(output) => output,
            Err(error) => {
                tracing::info!(
                    stage_id = %start.stage_id,
                    batch_id = %batch_id,
                    input_items,
                    duration_ms = started_at.elapsed().as_millis(),
                    status = "error",
                    error = %error,
                    "cymbal stage batch finished"
                );
                return Err(error);
            }
        };

        tracing::info!(
            stage_id = %start.stage_id,
            batch_id = %batch_id,
            input_items,
            output_items = output.len(),
            duration_ms = started_at.elapsed().as_millis(),
            status = "ok",
            "cymbal stage batch finished"
        );
        drop(item_permits);
        Ok(Response::new(StageBatchResult {
            results: output,
            errors: Vec::new(),
            load: Some(self.stage_load_snapshot(&start.stage_id)),
        }))
    }
}

impl CymbalStageService {
    fn stage_load_snapshot(&self, stage_id: &str) -> cymbal_api::cymbal::v1::StageLoad {
        let mut load = self.in_flight.load_snapshot();
        load.current_in_flight_items = self.item_permits.current(stage_id) as u64;
        load.max_in_flight_items = self.limits.max_in_flight_items_for(stage_id) as u64;
        load.overloaded =
            load.overloaded || load.current_in_flight_items >= load.max_in_flight_items;
        // Advertise which stage IDs this pod actually handles. The dispatcher
        // uses this to filter remote candidates when callers and callees roll
        // independently — without it, a v2 caller can land on a pod that still
        // only knows v1 and only discovers the mismatch after the decode error.
        load.served_stage_ids = self.registry.registered_stage_ids();
        load
    }

    async fn process_resolution(
        &self,
        context: BatchContext,
        items: Vec<StageItem>,
    ) -> Result<Vec<StageItemResult>, Status> {
        let input_events = items
            .into_iter()
            .map(|item| decode_stage_item::<InputEvent>(item, InputEvent::TYPE.to_string()))
            .collect::<Result<Vec<_>, _>>()?;
        let resolved_events: Vec<ResolvedEvent> = self
            .resolution_stage
            .process(StageInput::from_items(context, input_events))
            .await
            .map_err(stage_error_to_status)?;

        resolved_events
            .into_iter()
            .map(encode_stage_item)
            .collect::<Result<Vec<_>, _>>()
    }

    async fn process_grouping(
        &self,
        context: BatchContext,
        items: Vec<StageItem>,
    ) -> Result<Vec<StageItemResult>, Status> {
        let resolved_events = items
            .into_iter()
            .map(|item| decode_stage_item::<ResolvedEvent>(item, ResolvedEvent::TYPE.to_string()))
            .collect::<Result<Vec<_>, _>>()?;
        let grouped_events: Vec<GroupedEvent> = self
            .grouping_stage
            .process(StageInput::from_items(context, resolved_events))
            .await
            .map_err(stage_error_to_status)?;

        grouped_events
            .into_iter()
            .map(encode_stage_item)
            .collect::<Result<Vec<_>, _>>()
    }

    async fn process_linking(
        &self,
        context: BatchContext,
        items: Vec<StageItem>,
    ) -> Result<Vec<StageItemResult>, Status> {
        let grouped_events = items
            .into_iter()
            .map(|item| decode_stage_item::<GroupedEvent>(item, GroupedEvent::TYPE.to_string()))
            .collect::<Result<Vec<_>, _>>()?;
        let event_results: Vec<EventResult> = self
            .linking_stage
            .process(StageInput::from_items(context, grouped_events))
            .await
            .map_err(stage_error_to_status)?;

        event_results
            .into_iter()
            .map(encode_stage_item)
            .collect::<Result<Vec<_>, _>>()
    }

    async fn process_alerting(
        &self,
        context: BatchContext,
        items: Vec<StageItem>,
    ) -> Result<Vec<StageItemResult>, Status> {
        let alerting_events = items
            .into_iter()
            .map(|item| decode_stage_item::<AlertingEvent>(item, AlertingEvent::TYPE.to_string()))
            .collect::<Result<Vec<_>, _>>()?;
        let event_results: Vec<EventResult> = self
            .alerting_stage
            .process(StageInput::from_items(context, alerting_events))
            .await
            .map_err(stage_error_to_status)?;

        event_results
            .into_iter()
            .map(encode_stage_item)
            .collect::<Result<Vec<_>, _>>()
    }
}

fn decode_stage_item<T>(item: StageItem, expected_type: String) -> Result<T, Status>
where
    T: serde::de::DeserializeOwned,
{
    if item.r#type != expected_type {
        return Err(Status::invalid_argument(format!(
            "item {} has type {}, expected {}",
            item.item_id, item.r#type, expected_type
        )));
    }

    decode_json_payload(&item.payload).map_err(stage_error_to_status)
}

fn encode_stage_item<T>(value: T) -> Result<StageItemResult, Status>
where
    T: StagePayload + serde::Serialize + StageItemId,
{
    let item_id = value.stage_item_id().to_string();
    let payload = encode_json_payload(&value).map_err(stage_error_to_status)?;

    Ok(StageItemResult {
        item_id,
        r#type: T::TYPE.to_string(),
        payload,
    })
}

fn stage_start_to_core_context(start: &StageStart) -> BatchContext {
    BatchContext {
        batch_id: start.batch_id.clone(),
        metadata: start.metadata.clone(),
    }
}

trait StageItemId {
    fn stage_item_id(&self) -> &str;
}

impl StageItemId for ResolvedEvent {
    fn stage_item_id(&self) -> &str {
        &self.event_id
    }
}

impl StageItemId for GroupedEvent {
    fn stage_item_id(&self) -> &str {
        &self.event_id
    }
}

impl StageItemId for EventResult {
    fn stage_item_id(&self) -> &str {
        &self.event_id
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::AtomicUsize;
    use std::sync::Arc;

    use cymbal_resolution::RESOLUTION_STAGE_ID;

    use super::*;
    use crate::observability::stage_load_from_metadata;

    fn resolution_batch() -> StageBatch {
        StageBatch {
            start: Some(StageStart {
                batch_id: "batch-1".to_string(),
                stage_id: RESOLUTION_STAGE_ID.to_string(),
                input_type: InputEvent::TYPE.to_string(),
                output_type: ResolvedEvent::TYPE.to_string(),
                metadata: Default::default(),
            }),
            items: Vec::new(),
        }
    }

    fn resolution_batch_with_items(item_ids: &[&str]) -> StageBatch {
        StageBatch {
            start: Some(StageStart {
                batch_id: "batch-1".to_string(),
                stage_id: RESOLUTION_STAGE_ID.to_string(),
                input_type: InputEvent::TYPE.to_string(),
                output_type: ResolvedEvent::TYPE.to_string(),
                metadata: Default::default(),
            }),
            items: item_ids
                .iter()
                .map(|item_id| StageItem {
                    item_id: (*item_id).to_string(),
                    r#type: InputEvent::TYPE.to_string(),
                    payload: serde_json::to_vec(&InputEvent {
                        event_id: (*item_id).to_string(),
                        team_id: 1,
                        properties: Default::default(),
                    })
                    .unwrap(),
                })
                .collect(),
        }
    }

    fn resolution_batch_with_invalid_payload(item_ids: &[&str]) -> StageBatch {
        let mut batch = resolution_batch_with_items(item_ids);
        for item in &mut batch.items {
            item.payload = b"not-json".to_vec();
        }
        batch
    }

    #[tokio::test]
    async fn stage_response_includes_in_flight_load_signal() {
        let tracker = InFlightBatchTracker::standalone(4);
        let service = CymbalStageService::new(
            StageRegistry::local_for_stage_ids(&[RESOLUTION_STAGE_ID.to_string()]).unwrap(),
        )
        .with_in_flight_tracker(tracker);

        let response = service
            .process_stage(Request::new(resolution_batch()))
            .await
            .unwrap()
            .into_inner();

        let load = response.load.unwrap();
        assert_eq!(load.current_in_flight_stage_batches, 1);
        assert_eq!(load.max_in_flight_stage_batches, 4);
        assert_eq!(load.current_in_flight_items, 0);
        assert_eq!(load.max_in_flight_items, 640_000);
        assert!(!load.overloaded);
    }

    #[tokio::test]
    async fn stage_response_releases_item_permits_before_load_signal() {
        let service = CymbalStageService::new(
            StageRegistry::local_for_stage_ids(&[RESOLUTION_STAGE_ID.to_string()]).unwrap(),
        )
        .with_limits(StageServiceLimits {
            max_stage_items: 10,
            default_max_in_flight_stage_items: 1,
            per_stage_max_in_flight_items: Default::default(),
        });

        let response = service
            .process_stage(Request::new(resolution_batch_with_items(&["event-1"])))
            .await
            .unwrap()
            .into_inner();

        let load = response.load.unwrap();
        assert_eq!(response.results.len(), 1);
        assert_eq!(load.current_in_flight_items, 0);
        assert_eq!(load.max_in_flight_items, 1);
        assert!(!load.overloaded);
    }

    #[tokio::test]
    async fn over_capacity_stage_items_reject_before_work_starts() {
        let service = CymbalStageService::new(
            StageRegistry::local_for_stage_ids(&[RESOLUTION_STAGE_ID.to_string()]).unwrap(),
        )
        .with_limits(StageServiceLimits {
            max_stage_items: 10,
            default_max_in_flight_stage_items: 1,
            per_stage_max_in_flight_items: Default::default(),
        });

        let status = service
            .process_stage(Request::new(resolution_batch_with_invalid_payload(&[
                "event-1", "event-2",
            ])))
            .await
            .unwrap_err();
        let load = stage_load_from_metadata(status.metadata()).unwrap();

        assert_eq!(status.code(), tonic::Code::ResourceExhausted);
        assert_eq!(load.current_in_flight_items, 0);
        assert_eq!(load.max_in_flight_items, 1);
        assert!(load.overloaded);
    }

    #[tokio::test]
    async fn overload_rejection_includes_load_metadata() {
        let counter = Arc::new(AtomicUsize::new(0));
        let tracker = InFlightBatchTracker::new(counter, 1);
        let _guard = tracker.try_acquire("test").unwrap();
        let service = CymbalStageService::new(
            StageRegistry::local_for_stage_ids(&[RESOLUTION_STAGE_ID.to_string()]).unwrap(),
        )
        .with_in_flight_tracker(tracker);

        let status = service
            .process_stage(Request::new(resolution_batch()))
            .await
            .unwrap_err();
        let load = stage_load_from_metadata(status.metadata()).unwrap();

        assert_eq!(status.code(), tonic::Code::ResourceExhausted);
        assert_eq!(load.current_in_flight_stage_batches, 1);
        assert_eq!(load.max_in_flight_stage_batches, 1);
        assert_eq!(load.current_in_flight_items, 0);
        assert_eq!(load.max_in_flight_items, 0);
        assert!(load.overloaded);
    }
}
