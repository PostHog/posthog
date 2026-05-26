use std::sync::{Arc, Mutex};
use std::time::Instant;

use async_trait::async_trait;
use cymbal_core::{
    apply_rate_limit_mode, evaluate_rate_limit, BatchContext, CircuitBreaker, CircuitBreakerConfig,
    CircuitDecision, EmissionOrder, IdentifiedItem, LinearPipelineRunner,
    LinearPipelineRunnerOptions, LinearPipelineSpec, Metadata, PipelineItem, RateLimitApplication,
    RateLimitDecision, RateLimitKeyExtractor, RateLimitMode, RateLimiter, Sink, StageBatchOutcome,
    StageDriver, StageEffectMode, StageError, StageLinkRule, StagePayload, StageProgressMode,
    StageSpec, StageType, TerminalItem, TransientFailurePolicy,
};

const RAW_WIDGET_TYPE: StageType = stage_type("example.widget", "raw", 1);
const ADMISSION_OUTPUT_TYPE: StageType = stage_type("example.widget", "admission-output", 1);
const ENRICHED_WIDGET_TYPE: StageType = stage_type("example.widget", "enriched", 1);
const WIDGET_RESULT_TYPE: StageType = stage_type("example.widget", "result", 1);

const fn stage_type(namespace: &'static str, name: &'static str, version: u16) -> StageType {
    StageType {
        namespace,
        name,
        version,
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct RawWidgetEvent {
    event_id: String,
    tenant_id: i64,
    value: &'static str,
}

impl StagePayload for RawWidgetEvent {
    const TYPE: StageType = RAW_WIDGET_TYPE;
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct EnrichedWidgetEvent {
    event_id: String,
    tenant_id: i64,
    value: String,
}

impl StagePayload for EnrichedWidgetEvent {
    const TYPE: StageType = ENRICHED_WIDGET_TYPE;
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct WidgetResult {
    event_id: String,
    status: String,
}

impl StagePayload for WidgetResult {
    const TYPE: StageType = WIDGET_RESULT_TYPE;
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum WidgetItem {
    Raw(RawWidgetEvent),
    Enriched(EnrichedWidgetEvent),
}

impl IdentifiedItem for WidgetItem {
    fn item_id(&self) -> &str {
        match self {
            Self::Raw(event) => event.event_id.as_str(),
            Self::Enriched(event) => event.event_id.as_str(),
        }
    }
}

impl PipelineItem for WidgetItem {
    fn payload_type(&self) -> StageType {
        match self {
            Self::Raw(_) => RawWidgetEvent::TYPE,
            Self::Enriched(_) => EnrichedWidgetEvent::TYPE,
        }
    }
}

impl IdentifiedItem for WidgetResult {
    fn item_id(&self) -> &str {
        self.event_id.as_str()
    }
}

impl TerminalItem for WidgetResult {
    fn payload_type(&self) -> StageType {
        Self::TYPE
    }
}

struct TenantKeyExtractor;

impl RateLimitKeyExtractor<RawWidgetEvent> for TenantKeyExtractor {
    type Key = i64;

    fn key(&self, item: &RawWidgetEvent) -> Option<Self::Key> {
        Some(item.tenant_id)
    }
}

struct WidgetLimiter;

#[async_trait]
impl RateLimiter<i64> for WidgetLimiter {
    async fn check(&self, key: &i64, _cost: u64) -> RateLimitDecision<i64> {
        if *key == 13 {
            return RateLimitDecision::Limited {
                key: *key,
                reason: "tenant_over_limit".to_string(),
            };
        }

        RateLimitDecision::Allowed { key: *key }
    }
}

#[derive(Clone)]
struct WidgetDriver {
    limiter: Arc<WidgetLimiter>,
    circuit: Arc<Mutex<CircuitBreaker>>,
}

impl WidgetDriver {
    fn new() -> Self {
        Self {
            limiter: Arc::new(WidgetLimiter),
            circuit: Arc::new(Mutex::new(CircuitBreaker::new(CircuitBreakerConfig {
                min_requests: 1,
                ..CircuitBreakerConfig::default()
            }))),
        }
    }

    fn circuit_window_len(&self) -> usize {
        self.circuit.lock().unwrap().window_len()
    }
}

#[async_trait]
impl StageDriver<WidgetItem, WidgetResult> for WidgetDriver {
    async fn run_stage(
        &self,
        _context: Arc<BatchContext>,
        stage: &StageSpec,
        items: Vec<WidgetItem>,
    ) -> Result<StageBatchOutcome<WidgetItem, WidgetResult>, StageError> {
        match stage.stage_id.as_str() {
            "admit" => self.admit(items).await,
            "enrich" => self.enrich(items),
            "finish" => self.finish(items),
            stage_id => Err(StageError::Internal(format!(
                "test driver does not implement stage {stage_id}"
            ))),
        }
    }
}

impl WidgetDriver {
    async fn admit(
        &self,
        items: Vec<WidgetItem>,
    ) -> Result<StageBatchOutcome<WidgetItem, WidgetResult>, StageError> {
        let mut continue_items = Vec::new();
        let mut terminal_items = Vec::new();

        for item in items {
            let WidgetItem::Raw(event) = item else {
                return Err(StageError::InvalidInput(
                    "admission expected raw widget events".to_string(),
                ));
            };
            let decision = evaluate_rate_limit(
                &event,
                RateLimitMode::Enforcing,
                &TenantKeyExtractor,
                Some(self.limiter.as_ref()),
                1,
            )
            .await;

            match apply_rate_limit_mode(event, RateLimitMode::Enforcing, decision) {
                RateLimitApplication::Continue { item, .. } => {
                    continue_items.push(WidgetItem::Raw(item))
                }
                RateLimitApplication::Limited { item, decision } => {
                    terminal_items.push(WidgetResult {
                        event_id: item.event_id,
                        status: format!("limited:{:?}", decision),
                    })
                }
            }
        }

        Ok(StageBatchOutcome::new(continue_items, terminal_items))
    }

    fn enrich(
        &self,
        items: Vec<WidgetItem>,
    ) -> Result<StageBatchOutcome<WidgetItem, WidgetResult>, StageError> {
        let mut circuit = self.circuit.lock().unwrap();
        let check = circuit.check(Instant::now(), "widget-enrich");
        if check.decision != CircuitDecision::Allow {
            return Err(StageError::Transient(
                "enrichment circuit is open".to_string(),
            ));
        }
        circuit.record_success();
        drop(circuit);

        let mut continue_items = Vec::new();
        for item in items {
            let WidgetItem::Raw(event) = item else {
                return Err(StageError::InvalidInput(
                    "enrichment expected raw widget events".to_string(),
                ));
            };
            continue_items.push(WidgetItem::Enriched(EnrichedWidgetEvent {
                event_id: event.event_id,
                tenant_id: event.tenant_id,
                value: format!("enriched:{}", event.value),
            }));
        }

        Ok(StageBatchOutcome::continue_only(continue_items))
    }

    fn finish(
        &self,
        items: Vec<WidgetItem>,
    ) -> Result<StageBatchOutcome<WidgetItem, WidgetResult>, StageError> {
        let mut terminal_items = Vec::new();
        for item in items {
            let WidgetItem::Enriched(event) = item else {
                return Err(StageError::InvalidInput(
                    "finish expected enriched widget events".to_string(),
                ));
            };
            terminal_items.push(WidgetResult {
                event_id: event.event_id,
                status: format!("stored:{}:tenant:{}", event.value, event.tenant_id),
            });
        }

        Ok(StageBatchOutcome::terminal_only(terminal_items))
    }
}

#[derive(Default, Clone)]
struct RecordingSink {
    emitted: Arc<Mutex<Vec<WidgetResult>>>,
}

impl RecordingSink {
    fn statuses(&self) -> Vec<String> {
        self.emitted
            .lock()
            .unwrap()
            .iter()
            .map(|item| item.status.clone())
            .collect()
    }
}

#[async_trait]
impl Sink<WidgetResult> for RecordingSink {
    async fn emit(&mut self, item: WidgetResult) -> Result<(), StageError> {
        self.emitted.lock().unwrap().push(item);
        Ok(())
    }
}

fn stage(stage_id: &'static str, input_type: StageType, output_type: StageType) -> StageSpec {
    StageSpec {
        stage_id: stage_id.to_string(),
        stage_type: stage_type("example.widget.stage", stage_id, 1),
        input_type,
        output_type,
        progress: StageProgressMode::BatchBarrier,
        effects: StageEffectMode::Pure,
        transient_failure_policy: TransientFailurePolicy::RetryableBeforeWork,
    }
}

fn widget_pipeline_spec() -> LinearPipelineSpec {
    LinearPipelineSpec {
        input_type: RawWidgetEvent::TYPE,
        terminal_type: WidgetResult::TYPE,
        stages: vec![
            stage("admit", RawWidgetEvent::TYPE, ADMISSION_OUTPUT_TYPE),
            stage("enrich", RawWidgetEvent::TYPE, EnrichedWidgetEvent::TYPE),
            stage("finish", EnrichedWidgetEvent::TYPE, WidgetResult::TYPE),
        ],
        allowed_links: vec![
            StageLinkRule::ExactType,
            StageLinkRule::FanOutContinue {
                stage_output_type: ADMISSION_OUTPUT_TYPE,
                next_input_type: RawWidgetEvent::TYPE,
                terminal_type: WidgetResult::TYPE,
            },
        ],
    }
}

fn raw(event_id: &str, tenant_id: i64, value: &'static str) -> WidgetItem {
    WidgetItem::Raw(RawWidgetEvent {
        event_id: event_id.to_string(),
        tenant_id,
        value,
    })
}

#[tokio::test]
async fn non_exception_pipeline_uses_core_framework_primitives() {
    let spec = widget_pipeline_spec();
    spec.validate().unwrap();

    let driver = WidgetDriver::new();
    let sink = RecordingSink::default();
    let runner = LinearPipelineRunner::new(
        spec,
        driver.clone(),
        LinearPipelineRunnerOptions {
            emission_order: EmissionOrder::InputOrder,
        },
    );

    runner
        .run(
            Arc::new(BatchContext {
                batch_id: "widget-batch".to_string(),
                metadata: Metadata::new(),
            }),
            vec![
                raw("a", 1, "alpha"),
                raw("b", 13, "beta"),
                raw("c", 1, "gamma"),
            ],
            sink.clone(),
        )
        .await
        .unwrap();

    assert_eq!(
        sink.statuses(),
        vec![
            "stored:enriched:alpha:tenant:1".to_string(),
            "limited:Limited { key: 13, reason: \"tenant_over_limit\" }".to_string(),
            "stored:enriched:gamma:tenant:1".to_string(),
        ]
    );
    assert_eq!(driver.circuit_window_len(), 1);
}
