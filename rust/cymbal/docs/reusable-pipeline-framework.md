# Reusable pipeline framework adoption

This guide shows how a non-Cymbal product can reuse Cymbal's transport-neutral framework pieces without importing the error-tracking domain.
The reusable APIs live in `cymbal-core`; your product owns payload DTOs, stage order, business semantics, transport, metrics, environment parsing, and deployment defaults.

A compiled version of the non-exception example below lives in `crates/core/tests/non_exception_pipeline.rs`.
Use that test as the fastest agent-explorable reference when changing the framework API.

## Minimal non-exception pipeline

Define product payloads normally and give any payload that can cross a stage boundary a stable `StagePayload::TYPE`.
Use a product namespace; the historical `cymbal.core.*` wire labels are reserved for existing Cymbal compatibility contracts.

```rust
use std::sync::Arc;

use async_trait::async_trait;
use cymbal_core::{
    apply_rate_limit_mode, evaluate_rate_limit, BatchContext, CircuitBreaker,
    CircuitBreakerConfig, CircuitDecision, EmissionOrder, IdentifiedItem,
    LinearPipelineRunner, LinearPipelineRunnerOptions, LinearPipelineSpec,
    PipelineItem, RateLimitApplication, RateLimitDecision, RateLimitKeyExtractor,
    RateLimitMode, RateLimiter, Sink, StageBatchOutcome, StageDriver,
    StageEffectMode, StageError, StageLinkRule, StagePayload, StageProgressMode,
    StageSpec, StageType, TerminalItem, TransientFailurePolicy,
};

const RAW_WIDGET: StageType = StageType { namespace: "example.widget", name: "raw", version: 1 };
const ADMISSION_OUTPUT: StageType = StageType { namespace: "example.widget", name: "admission-output", version: 1 };
const ENRICHED_WIDGET: StageType = StageType { namespace: "example.widget", name: "enriched", version: 1 };
const WIDGET_RESULT: StageType = StageType { namespace: "example.widget", name: "result", version: 1 };

#[derive(Clone)]
struct RawWidgetEvent { event_id: String, tenant_id: i64, value: String }
impl StagePayload for RawWidgetEvent { const TYPE: StageType = RAW_WIDGET; }

#[derive(Clone)]
struct EnrichedWidgetEvent { event_id: String, tenant_id: i64, value: String }
impl StagePayload for EnrichedWidgetEvent { const TYPE: StageType = ENRICHED_WIDGET; }

struct WidgetResult { event_id: String, status: String }
impl StagePayload for WidgetResult { const TYPE: StageType = WIDGET_RESULT; }

enum WidgetItem {
    Raw(RawWidgetEvent),
    Enriched(EnrichedWidgetEvent),
}

impl IdentifiedItem for WidgetItem {
    fn item_id(&self) -> &str {
        match self {
            WidgetItem::Raw(event) => &event.event_id,
            WidgetItem::Enriched(event) => &event.event_id,
        }
    }
}

impl PipelineItem for WidgetItem {
    fn payload_type(&self) -> StageType {
        match self {
            WidgetItem::Raw(_) => RawWidgetEvent::TYPE,
            WidgetItem::Enriched(_) => EnrichedWidgetEvent::TYPE,
        }
    }
}

impl IdentifiedItem for WidgetResult {
    fn item_id(&self) -> &str { &self.event_id }
}

impl TerminalItem for WidgetResult {
    fn payload_type(&self) -> StageType { Self::TYPE }
}
```

Describe and validate the linear contract before running it.
`StageSpec` is metadata only: it does not choose local vs remote placement, metrics labels, retries, or concrete stage implementations.
A fan-out/continue link lets a product-owned admission wrapper produce either continue items for the next stage or terminal outcomes that bypass the rest of the pipeline.

```rust
fn widget_stage(stage_id: &'static str, input_type: StageType, output_type: StageType) -> StageSpec {
    StageSpec {
        stage_id: stage_id.to_string(),
        stage_type: StageType { namespace: "example.widget.stage", name: stage_id, version: 1 },
        input_type,
        output_type,
        progress: StageProgressMode::BatchBarrier,
        effects: StageEffectMode::Pure,
        transient_failure_policy: TransientFailurePolicy::RetryableBeforeWork,
    }
}

let spec = LinearPipelineSpec {
    input_type: RawWidgetEvent::TYPE,
    terminal_type: WidgetResult::TYPE,
    stages: vec![
        widget_stage("admit", RawWidgetEvent::TYPE, ADMISSION_OUTPUT),
        widget_stage("enrich", RawWidgetEvent::TYPE, EnrichedWidgetEvent::TYPE),
        widget_stage("finish", EnrichedWidgetEvent::TYPE, WidgetResult::TYPE),
    ],
    allowed_links: vec![
        StageLinkRule::ExactType,
        StageLinkRule::FanOutContinue {
            stage_output_type: ADMISSION_OUTPUT,
            next_input_type: RawWidgetEvent::TYPE,
            terminal_type: WidgetResult::TYPE,
        },
    ],
};

spec.validate()?;
```

Implement a product driver around your local or remote execution choices.
Core's rate-limit/admission vocabulary is generic; the product still owns keys, backing limiters, metrics, and terminal-result mapping.
Core's circuit breaker is a state machine; the caller still owns endpoint storage, tracing, and transport fallback.

```rust
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
            return RateLimitDecision::Limited { key: *key, reason: "tenant_over_limit".to_string() };
        }
        RateLimitDecision::Allowed { key: *key }
    }
}

struct WidgetDriver {
    limiter: WidgetLimiter,
    circuit: std::sync::Mutex<CircuitBreaker>,
}

#[async_trait]
impl StageDriver<WidgetItem, WidgetResult> for WidgetDriver {
    async fn run_stage(
        &self,
        context: Arc<BatchContext>,
        stage: &StageSpec,
        items: Vec<WidgetItem>,
    ) -> Result<StageBatchOutcome<WidgetItem, WidgetResult>, StageError> {
        match stage.stage_id.as_str() {
            "admit" => {
                let mut continue_items = Vec::new();
                let mut terminal_items = Vec::new();

                for item in items {
                    let WidgetItem::Raw(event) = item else { return Err(StageError::InvalidInput("expected raw widget".into())); };
                    let decision = evaluate_rate_limit(
                        &event,
                        RateLimitMode::Enforcing,
                        &TenantKeyExtractor,
                        Some(&self.limiter),
                        1,
                    ).await;

                    match apply_rate_limit_mode(event, RateLimitMode::Enforcing, decision) {
                        RateLimitApplication::Continue { item, .. } => continue_items.push(WidgetItem::Raw(item)),
                        RateLimitApplication::Limited { item, .. } => terminal_items.push(WidgetResult {
                            event_id: item.event_id,
                            status: "limited".to_string(),
                        }),
                    }
                }

                Ok(StageBatchOutcome::new(continue_items, terminal_items))
            }
            "enrich" => {
                let mut circuit = self.circuit.lock().unwrap();
                let check = circuit.check(std::time::Instant::now(), &context.batch_id);
                if check.decision != CircuitDecision::Allow {
                    return Err(StageError::Transient("enrichment circuit is open".into()));
                }
                circuit.record_success();
                drop(circuit);

                // Call a local function or remote endpoint, then return continue items.
                Ok(StageBatchOutcome::continue_only(items))
            }
            "finish" => {
                // Map enriched items to product terminal results.
                Ok(StageBatchOutcome::terminal_only(Vec::new()))
            }
            _ => Err(StageError::Internal("unknown stage".into())),
        }
    }
}

let driver = WidgetDriver {
    limiter: WidgetLimiter,
    circuit: std::sync::Mutex::new(CircuitBreaker::new(CircuitBreakerConfig::default())),
};
let runner = LinearPipelineRunner::new(
    spec,
    driver,
    LinearPipelineRunnerOptions { emission_order: EmissionOrder::InputOrder },
);
runner.run(batch_context, input_items, result_sink).await?;
```

The runner validates the spec and input item types, executes stages in `LinearPipelineSpec` order, sends terminal items through `OrderedEmitter`, and ensures continue items match the next stage's declared input type.
`StageProgressMode::ItemProgress` is currently visible metadata; the generic runner still invokes each stage as one in-process batch.
Cymbal's streaming path keeps its custom chunking until the generic runner grows item-progress scheduling.

## Routing and capacity primitives

At dispatch time, collect concrete endpoint IDs, the latest per-endpoint load snapshots, a routing policy, and the item list.
The partitioner computes candidate endpoints per item, reserves local capacity inside the current input batch, and returns endpoint sub-batches plus explicit unroutable items.

```rust
use cymbal_core::routing::{
    CapacityAwarePartitioner, CapacitySnapshot, EndpointCapacity, FallbackPolicy, RoutingPolicy,
};

let endpoints = vec!["pod-a".to_string(), "pod-b".to_string()];
let capacity = CapacitySnapshot::new(vec![
    EndpointCapacity::fresh("pod-a".to_string(), 8, 16),
    EndpointCapacity::fresh("pod-b".to_string(), 0, 16),
]);
let policy = RoutingPolicy::affinity_first().with_max_fallback_attempts(1);
let partitioner = CapacityAwarePartitioner::new(1, 1);
let fallback = FallbackPolicy::pre_work_only();
```

Handle each `EndpointSubBatch` by calling the selected endpoint with that sub-batch.
If an endpoint rejects before work, classify it as `AttemptFailureKind::PreWorkResourceExhausted` or another pre-work kind and let the fallback policy decide whether to try the next candidate.
Treat timeouts and post-send transport failures as ambiguous unless your stage contract proves no side effects could have occurred.

## Ownership checklist

- `cymbal-core`: stage identity and codecs, batch context, generic stage traits/executors, linear pipeline spec validation, `LinearPipelineRunner`, ordered emission, generic circuit breaker, generic rate-limit/admission primitives, and routing/capacity/fallback primitives.
- Product pipeline crate: product payloads, item enum, terminal outcomes, concrete stage order, `StageDriver` adapters, side-effect safety choices, routing-key extraction, and final public semantics.
- Server/transport crate: endpoint discovery, client pools, local/remote placement, request/response codecs, status and load metadata conversion, env config, readiness/shutdown, metrics, and logs.

`cymbal-core` must not depend on `cymbal-domain`, stage crates, `cymbal-pipeline`, repositories, runtime, or `cymbal-server`.

## Cymbal-specific boundaries

Cymbal's error-tracking contracts live outside the framework crate.
`cymbal-domain` owns `InputEvent`, `RateLimitGateOutput`, `EventResult`, `EventOutcome`, exception properties, frames, releases, fingerprint record parts, and sanitizers.
`cymbal-pipeline` owns `ExceptionPipelineItem`, the concrete error-tracking stage order, and the adapters that pin the generic runner to those contracts.
`cymbal-server` owns local/remote placement, gRPC transport, metrics, environment parsing, and readiness.

The Rust module move did not change remote payload identities.
These `StagePayload::TYPE` strings are compatibility labels and remain stable until an explicit wire-version migration is planned:

- `InputEvent::TYPE` is `cymbal.core.InputEvent@2`.
- `RateLimitGateOutput::TYPE` is `cymbal.core.RateLimitGateOutput@2`.
- `EventResult::TYPE` is `cymbal.core.EventResult@2`.

The `StageType.namespace` value is a wire label, not a Rust module path.
Keeping the `cymbal.core.*` labels preserves remote-stage codecs, registry assertions, snapshots, and generated Node bindings.
