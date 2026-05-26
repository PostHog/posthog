//! Cymbal resolution stage crate.
//!
//! This crate owns the first Rust-internal pipeline stage: turning raw input
//! events from the pipeline boundary into resolved events for downstream stages.

use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::Instant,
};

use async_trait::async_trait;
use cymbal_core::{
    run_buffered, Metadata, PipelineStage, StageConcurrencyLimiter, StageError, StageInput,
    StagePayload, StageType,
};
use cymbal_domain::{EventOutcome, EventResult, ExceptionProperties, InputEvent};
use cymbal_symbol_store::UnhandledError;
use serde::{Deserialize, Serialize};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

mod exception;
mod frame;
mod properties;
pub mod symbol;

use exception::{ExceptionResolver, ResolutionExceptionProperties};
use frame::FrameResolver;
pub use frame::{FrameRepository, NoopFrameRepository};
use properties::PropertiesResolver;
pub use symbol::{NoopSymbolResolver, SymbolResolver};

pub const RESOLUTION_STAGE_ID: &str = "resolution:v1";
pub const RESOLUTION_STAGE_TYPE: StageType = StageType {
    namespace: "cymbal.stage",
    name: "resolution",
    version: 1,
};
const SYMBOL_RESOLUTION_WAIT_SECONDS: &str = "cymbal_symbol_resolution_wait_seconds";
const SYMBOL_RESOLUTION_IN_FLIGHT: &str = "cymbal_symbol_resolution_in_flight";
const DEFAULT_RESOLUTION_STAGE_CONCURRENCY: usize = 64;

#[derive(Clone)]
pub struct ResolutionDeps {
    pub symbol_resolver: Arc<dyn SymbolResolver>,
    pub frame_repository: Arc<dyn FrameRepository>,
    pub symbol_resolution_limiter: Arc<Semaphore>,
    pub stage_concurrency_limiter: StageConcurrencyLimiter,
    symbol_resolution_in_flight: Arc<AtomicUsize>,
}

impl std::fmt::Debug for ResolutionDeps {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ResolutionDeps")
            .field("symbol_resolver", &"<dyn SymbolResolver>")
            .field("frame_repository", &"<dyn FrameRepository>")
            .field(
                "symbol_resolution_limiter_available_permits",
                &self.symbol_resolution_limiter.available_permits(),
            )
            .field(
                "stage_concurrency",
                &self.stage_concurrency_limiter.capacity(),
            )
            .field(
                "stage_concurrency_limiter_available_permits",
                &self.stage_concurrency_limiter.available_permits(),
            )
            .field(
                "symbol_resolution_in_flight",
                &self.symbol_resolution_in_flight.load(Ordering::Relaxed),
            )
            .finish()
    }
}

impl Default for ResolutionDeps {
    fn default() -> Self {
        Self {
            symbol_resolver: Arc::new(NoopSymbolResolver),
            frame_repository: Arc::new(NoopFrameRepository),
            symbol_resolution_limiter: Arc::new(Semaphore::new(1)),
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_RESOLUTION_STAGE_CONCURRENCY,
            ),
            symbol_resolution_in_flight: Arc::new(AtomicUsize::new(0)),
        }
    }
}

impl ResolutionDeps {
    pub fn new(
        symbol_resolver: Arc<dyn SymbolResolver>,
        symbol_resolution_limiter: Arc<Semaphore>,
    ) -> Self {
        Self {
            symbol_resolver,
            frame_repository: Arc::new(NoopFrameRepository),
            symbol_resolution_limiter,
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_RESOLUTION_STAGE_CONCURRENCY,
            ),
            symbol_resolution_in_flight: Arc::new(AtomicUsize::new(0)),
        }
    }

    pub fn with_frame_repository(mut self, frame_repository: Arc<dyn FrameRepository>) -> Self {
        self.frame_repository = frame_repository;
        self
    }

    pub fn with_stage_concurrency(mut self, stage_concurrency: usize) -> Self {
        self.stage_concurrency_limiter = StageConcurrencyLimiter::new(stage_concurrency);
        self
    }

    pub async fn acquire_symbol_resolution_permit(
        &self,
    ) -> Result<SymbolResolutionPermit, UnhandledError> {
        let started_at = Instant::now();
        let permit = self
            .symbol_resolution_limiter
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| {
                UnhandledError::Other("Symbol resolution limiter is closed".to_string())
            })?;
        metrics::histogram!(SYMBOL_RESOLUTION_WAIT_SECONDS)
            .record(started_at.elapsed().as_secs_f64());
        let in_flight = self
            .symbol_resolution_in_flight
            .fetch_add(1, Ordering::Relaxed)
            + 1;
        metrics::gauge!(SYMBOL_RESOLUTION_IN_FLIGHT).set(in_flight as f64);
        Ok(SymbolResolutionPermit {
            _permit: permit,
            in_flight: self.symbol_resolution_in_flight.clone(),
        })
    }
}

pub struct SymbolResolutionPermit {
    _permit: OwnedSemaphorePermit,
    in_flight: Arc<AtomicUsize>,
}

impl Drop for SymbolResolutionPermit {
    fn drop(&mut self) {
        let in_flight = self
            .in_flight
            .fetch_sub(1, Ordering::Relaxed)
            .saturating_sub(1);
        metrics::gauge!(SYMBOL_RESOLUTION_IN_FLIGHT).set(in_flight as f64);
    }
}

#[derive(Clone, Debug, Default)]
pub struct ResolutionStage {
    deps: ResolutionDeps,
}

impl ResolutionStage {
    pub fn new() -> Self {
        Self::with_deps(ResolutionDeps::default())
    }

    pub fn with_deps(deps: ResolutionDeps) -> Self {
        Self { deps }
    }

    async fn resolve_event(&self, event: InputEvent) -> Result<ResolvedEvent, StageError> {
        let properties = resolve_properties(event.properties, event.team_id, self.deps.clone())
            .await
            .map_err(unhandled_error_to_stage_error)?;
        Ok(ResolvedEvent {
            event_id: event.event_id,
            team_id: event.team_id,
            properties,
            metadata: Metadata::new(),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ResolvedEvent {
    pub event_id: String,
    pub team_id: i64,
    pub properties: ExceptionProperties,
    pub metadata: Metadata,
}

impl StagePayload for ResolvedEvent {
    const TYPE: StageType = StageType {
        namespace: "cymbal.resolution",
        name: "ResolvedEvent",
        version: 2,
    };
}

impl ResolvedEvent {
    pub fn into_next_result(self) -> EventResult {
        EventResult {
            event_id: self.event_id,
            outcome: EventOutcome::Next {
                properties: Some(self.properties),
                metadata: self.metadata,
            },
        }
    }
}

#[async_trait]
impl PipelineStage for ResolutionStage {
    type Input = InputEvent;
    type Output = ResolvedEvent;

    fn id(&self) -> StageType {
        RESOLUTION_STAGE_TYPE
    }

    async fn process(
        &self,
        input: StageInput<Self::Input>,
    ) -> Result<Vec<Self::Output>, StageError> {
        let stage = self.clone();
        run_buffered(
            &self.deps.stage_concurrency_limiter,
            input.items,
            move |event| {
                let stage = stage.clone();
                async move { stage.resolve_event(event).await }
            },
        )
        .await
    }
}

async fn resolve_properties(
    properties: ExceptionProperties,
    team_id: i64,
    deps: ResolutionDeps,
) -> Result<ExceptionProperties, UnhandledError> {
    if properties.exception_list_is_empty() {
        return Ok(properties);
    }

    let Ok(mut event) =
        serde_json::from_value::<ResolutionExceptionProperties>(serde_json::to_value(&properties)?)
    else {
        // Keep per-event invalid exception payloads isolated: a malformed exception list should
        // not fail the whole batch or prevent other events from being resolved.
        return Ok(properties);
    };
    if event.exception_list.is_empty() {
        return Ok(properties);
    }

    let team_id = team_id as i32;
    event.exception_list =
        ExceptionResolver::resolve_exception_list(team_id, event.exception_list, deps.clone())
            .await?;
    event.exception_list = FrameResolver::resolve_exception_list_frames(
        team_id,
        event.exception_list,
        Arc::new(event.debug_images.clone()),
        deps,
    )
    .await?;

    let resolved_properties = match PropertiesResolver.resolve(event) {
        Ok(properties) => properties,
        Err(_) => return Ok(properties),
    };
    Ok(resolved_properties)
}

fn unhandled_error_to_stage_error(error: UnhandledError) -> StageError {
    StageError::Transient(error.to_string())
}

#[cfg(test)]
mod tests {
    use std::{
        sync::{
            atomic::{AtomicUsize, Ordering},
            Mutex,
        },
        time::Duration,
    };

    use async_trait::async_trait;
    use common_types::error_tracking::FrameId;
    use cymbal_core::{BatchContext, PipelineStage, StageInput};
    use cymbal_domain::{Context, ContextLine, ReleaseRecord};
    use cymbal_symbol_store::{
        chunk_id::OrChunkId, proguard::ProguardRef, JsResolveErr, ProguardError, ResolveError,
    };
    use cymbal_symbolication::{apple::AppleDebugImage, Frame, RawFrame};
    use serde_json::{json, Value};

    use super::*;

    mod fixtures {
        use super::*;

        pub fn context() -> BatchContext {
            BatchContext {
                batch_id: "batch-1".to_string(),
                metadata: Metadata::new(),
            }
        }

        pub fn input_event(event_id: &str, team_id: i64, payload_json: &[u8]) -> InputEvent {
            InputEvent {
                event_id: event_id.to_string(),
                team_id,
                properties: properties_from_payload(payload_json),
            }
        }
    }

    fn properties_from_payload(payload_json: &[u8]) -> ExceptionProperties {
        let payload: Value = serde_json::from_slice(payload_json).unwrap();
        let properties = payload.get("properties").and_then(Value::as_object);
        properties
            .map(|properties| {
                ExceptionProperties::from_map_preserving_invalid_exception_fields(
                    properties.clone(),
                )
            })
            .unwrap_or_default()
    }

    fn resolvable_payload_json() -> Vec<u8> {
        serde_json::to_vec(&json!({
            "properties": {
                "$exception_list": [{
                    "type": "TypeError",
                    "value": "boom",
                    "stacktrace": {
                        "type": "raw",
                        "frames": [{
                            "platform": "custom",
                            "lang": "javascript",
                            "function": "minified",
                            "filename": "app.min.js",
                            "in_app": true,
                            "resolved": false
                        }]
                    }
                }]
            }
        }))
        .unwrap()
    }

    #[tokio::test]
    async fn resolution_stage_preserves_event_identity_and_properties() {
        let stage = ResolutionStage::new();
        let payload_json = br#"{"event":"$exception","message":"boom"}"#.to_vec();
        let input = StageInput::from_items(
            fixtures::context(),
            vec![fixtures::input_event("event-1", 2, &payload_json)],
        );

        let output: Vec<ResolvedEvent> = stage.process(input).await.unwrap();

        assert_eq!(output.len(), 1);
        assert_eq!(output[0].event_id, "event-1");
        assert_eq!(output[0].team_id, 2);
        assert!(output[0].properties.props.is_empty());
    }

    #[test]
    fn resolved_event_converts_to_next_result() {
        let properties = ExceptionProperties::from_map_preserving_invalid_exception_fields(
            json!({ "message": "boom" }).as_object().unwrap().clone(),
        );
        let event = ResolvedEvent {
            event_id: "event-1".to_string(),
            team_id: 1,
            properties,
            metadata: Metadata::new(),
        };

        let result = event.into_next_result();

        assert_eq!(result.event_id, "event-1");
        assert!(matches!(
            result.outcome,
            EventOutcome::Next {
                properties: Some(ref properties),
                ..
            } if properties.props.get("message") == Some(&json!("boom"))
        ));
    }

    #[tokio::test]
    async fn resolution_without_raw_frames_does_not_call_symbol_resolver() {
        let resolver = Arc::new(CountingResolver::default());
        let stage = ResolutionStage::with_deps(ResolutionDeps::new(
            resolver.clone(),
            Arc::new(Semaphore::new(1)),
        ));
        let payload_json = serde_json::to_vec(&json!({
            "properties": {
                "$exception_list": [{
                    "type": "TypeError",
                    "value": "boom",
                    "stacktrace": {
                        "frames": [{
                            "filename": "app.js",
                            "function": "runExample",
                            "in_app": true
                        }]
                    }
                }]
            }
        }))
        .unwrap();

        let output = stage
            .resolve_event(fixtures::input_event("event-1", 1, &payload_json))
            .await
            .unwrap();
        let payload = serde_json::to_value(&output.properties).unwrap();

        assert_eq!(resolver.raw_frame_calls.load(Ordering::SeqCst), 0);
        assert_eq!(
            payload.pointer("/$exception_functions"),
            Some(&json!(["runExample"]))
        );
    }

    #[tokio::test]
    async fn resolution_with_mocked_symbolication_resolves_raw_frames() {
        let resolver = Arc::new(CountingResolver::default());
        let stage = ResolutionStage::with_deps(ResolutionDeps::new(
            resolver.clone(),
            Arc::new(Semaphore::new(1)),
        ));
        let payload_json = serde_json::to_vec(&json!({
            "properties": {
                "$exception_list": [{
                    "type": "TypeError",
                    "value": "boom",
                    "stacktrace": {
                        "type": "raw",
                        "frames": [{
                            "platform": "custom",
                            "lang": "javascript",
                            "function": "minified",
                            "filename": "app.min.js",
                            "in_app": true,
                            "resolved": false
                        }]
                    }
                }]
            }
        }))
        .unwrap();

        let output = stage
            .resolve_event(fixtures::input_event("event-1", 1, &payload_json))
            .await
            .unwrap();
        let payload = serde_json::to_value(&output.properties).unwrap();

        assert_eq!(resolver.raw_frame_calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            payload.pointer("/$exception_functions"),
            Some(&json!(["resolvedFunction"]))
        );
        assert_eq!(
            payload.pointer("/$exception_sources"),
            Some(&json!(["src/app.ts"]))
        );
        assert_eq!(
            payload.pointer("/$exception_releases/release-hash/version"),
            Some(&json!("1.0.0"))
        );
        assert_eq!(
            payload.pointer("/$exception_list/0/stacktrace/type"),
            Some(&json!("resolved"))
        );
    }

    #[tokio::test]
    async fn resolution_persists_source_context_for_resolved_frames() {
        let resolver = Arc::new(CountingResolver::default());
        let repository = Arc::new(RecordingFrameRepository::default());
        let stage = ResolutionStage::with_deps(
            ResolutionDeps::new(resolver, Arc::new(Semaphore::new(1)))
                .with_frame_repository(repository.clone()),
        );
        let payload_json = serde_json::to_vec(&json!({
            "properties": {
                "$exception_list": [{
                    "type": "TypeError",
                    "value": "boom",
                    "stacktrace": {
                        "type": "raw",
                        "frames": [{
                            "platform": "web:javascript",
                            "filename": "https://example.com/app.min.js",
                            "function": "minified",
                            "lineno": 1,
                            "colno": 2,
                            "chunkId": "chunk-1",
                            "in_app": true
                        }]
                    }
                }]
            }
        }))
        .unwrap();

        stage
            .resolve_event(fixtures::input_event("event-1", 1, &payload_json))
            .await
            .unwrap();

        let saved = repository.saved.lock().unwrap();
        assert_eq!(saved.len(), 1);
        assert_eq!(saved[0].team_id, 1);
        assert_eq!(saved[0].symbol_set_ref, Some("chunk-1".to_string()));
        assert_eq!(
            saved[0].context.as_ref().map(|context| &context.line.line),
            Some(&"line".to_string())
        );
    }

    #[tokio::test]
    async fn resolution_resolves_events_with_bounded_concurrency() {
        let resolver = Arc::new(ConcurrentResolver::default());
        let stage = ResolutionStage::with_deps(
            ResolutionDeps::new(resolver.clone(), Arc::new(Semaphore::new(10)))
                .with_stage_concurrency(2),
        );
        let payload_json = resolvable_payload_json();

        let input = StageInput::from_items(
            fixtures::context(),
            vec![
                fixtures::input_event("event-1", 1, &payload_json),
                fixtures::input_event("event-2", 1, &payload_json),
                fixtures::input_event("event-3", 1, &payload_json),
            ],
        );

        let output = stage.process(input).await.unwrap();

        assert_eq!(output.len(), 3);
        assert_eq!(resolver.raw_frame_calls.load(Ordering::SeqCst), 3);
        assert_eq!(
            resolver.max_in_flight.load(Ordering::SeqCst),
            2,
            "resolution stage concurrency should be a hard event-level cap"
        );
    }

    #[tokio::test]
    async fn resolution_stage_concurrency_is_shared_across_concurrent_batches() {
        // The stage concurrency cap must be a property of the stage, not of a
        // single `process()` invocation. Two concurrent batches running through
        // the same stage should observe at most `stage_concurrency` in-flight
        // event resolutions in total, otherwise the operator-facing knob lies
        // about the actual cap when the runtime fans out multiple batches.
        let resolver = Arc::new(ConcurrentResolver::default());
        let stage = ResolutionStage::with_deps(
            ResolutionDeps::new(resolver.clone(), Arc::new(Semaphore::new(10)))
                .with_stage_concurrency(2),
        );
        let payload_json = resolvable_payload_json();

        let make_input = || {
            StageInput::from_items(
                fixtures::context(),
                vec![
                    fixtures::input_event("event-1", 1, &payload_json),
                    fixtures::input_event("event-2", 1, &payload_json),
                    fixtures::input_event("event-3", 1, &payload_json),
                ],
            )
        };

        let stage_a = stage.clone();
        let stage_b = stage.clone();
        let (output_a, output_b) =
            tokio::join!(stage_a.process(make_input()), stage_b.process(make_input()));

        assert_eq!(output_a.unwrap().len(), 3);
        assert_eq!(output_b.unwrap().len(), 3);
        assert_eq!(resolver.raw_frame_calls.load(Ordering::SeqCst), 6);
        assert_eq!(
            resolver.max_in_flight.load(Ordering::SeqCst),
            2,
            "stage concurrency must cap concurrent batches together, not per-call"
        );
    }

    #[tokio::test]
    async fn resolution_resolves_frames_sequentially_within_an_event() {
        let resolver = Arc::new(ConcurrentResolver::default());
        let stage = ResolutionStage::with_deps(
            ResolutionDeps::new(resolver.clone(), Arc::new(Semaphore::new(10)))
                .with_stage_concurrency(3),
        );
        let payload_json = serde_json::to_vec(&json!({
            "properties": {
                "$exception_list": [{
                    "type": "TypeError",
                    "value": "boom",
                    "stacktrace": {
                        "type": "raw",
                        "frames": [
                            { "platform": "custom", "lang": "javascript", "function": "one", "filename": "app.min.js", "in_app": true, "resolved": false },
                            { "platform": "custom", "lang": "javascript", "function": "two", "filename": "app.min.js", "in_app": true, "resolved": false },
                            { "platform": "custom", "lang": "javascript", "function": "three", "filename": "app.min.js", "in_app": true, "resolved": false }
                        ]
                    }
                }]
            }
        }))
        .unwrap();

        stage
            .resolve_event(fixtures::input_event("event-1", 1, &payload_json))
            .await
            .unwrap();

        assert_eq!(resolver.raw_frame_calls.load(Ordering::SeqCst), 3);
        assert!(
            resolver.max_in_flight.load(Ordering::SeqCst) == 1,
            "single-event frame resolution should not multiply stage concurrency"
        );
    }

    #[tokio::test]
    async fn empty_exception_list_passes_through_without_calling_resolver() {
        let resolver = Arc::new(CountingResolver::default());
        let stage = ResolutionStage::with_deps(ResolutionDeps::new(
            resolver.clone(),
            Arc::new(Semaphore::new(1)),
        ));
        let payload_json = serde_json::to_vec(&json!({
            "properties": { "$exception_list": [] }
        }))
        .unwrap();

        let output = stage
            .resolve_event(fixtures::input_event("event-1", 1, &payload_json))
            .await
            .unwrap();
        let payload = serde_json::to_value(&output.properties).unwrap();

        assert_eq!(resolver.raw_frame_calls.load(Ordering::SeqCst), 0);
        assert_eq!(payload.pointer("/$exception_list"), Some(&json!([])));
    }

    #[tokio::test]
    async fn symbol_resolver_error_propagates_as_transient_stage_error() {
        let stage = ResolutionStage::with_deps(ResolutionDeps::new(
            Arc::new(ErrorResolver),
            Arc::new(Semaphore::new(1)),
        ));
        let payload_json = serde_json::to_vec(&json!({
            "properties": {
                "$exception_list": [{
                    "type": "TypeError",
                    "value": "boom",
                    "stacktrace": {
                        "type": "raw",
                        "frames": [{
                            "platform": "custom",
                            "lang": "javascript",
                            "function": "minified",
                            "filename": "app.min.js",
                            "in_app": true,
                            "resolved": false
                        }]
                    }
                }]
            }
        }))
        .unwrap();

        let result = stage
            .resolve_event(fixtures::input_event("event-1", 1, &payload_json))
            .await;

        assert!(
            matches!(result, Err(StageError::Transient(_))),
            "unhandled symbol resolver errors must surface as transient stage errors"
        );
    }

    #[tokio::test]
    async fn symbol_resolution_permit_is_released_after_successful_resolution() {
        let semaphore = Arc::new(Semaphore::new(1));
        let stage = ResolutionStage::with_deps(ResolutionDeps::new(
            Arc::new(CountingResolver::default()),
            semaphore.clone(),
        ));
        let payload_json = serde_json::to_vec(&json!({
            "properties": {
                "$exception_list": [{
                    "type": "TypeError",
                    "value": "boom",
                    "stacktrace": {
                        "type": "raw",
                        "frames": [{
                            "platform": "custom",
                            "lang": "javascript",
                            "function": "minified",
                            "filename": "app.min.js",
                            "in_app": true,
                            "resolved": false
                        }]
                    }
                }]
            }
        }))
        .unwrap();

        let before = semaphore.available_permits();
        stage
            .resolve_event(fixtures::input_event("event-1", 1, &payload_json))
            .await
            .unwrap();
        let after = semaphore.available_permits();

        assert_eq!(
            before, after,
            "semaphore permit must be returned to the pool after resolution completes"
        );
    }

    #[tokio::test]
    async fn javascript_platform_alias_frame_is_dispatched_to_symbol_resolver() {
        let resolver = Arc::new(CountingResolver::default());
        let stage = ResolutionStage::with_deps(ResolutionDeps::new(
            resolver.clone(),
            Arc::new(Semaphore::new(1)),
        ));
        // Frames with bare "platform": "javascript" are the legacy alias for
        // "web:javascript". They should still be sent to the symbol resolver.
        let payload_json = serde_json::to_vec(&json!({
            "properties": {
                "$exception_list": [{
                    "type": "TypeError",
                    "value": "boom",
                    "stacktrace": {
                        "type": "raw",
                        "frames": [{
                            "platform": "javascript",
                            "function": "minifiedFn",
                            "filename": "app.min.js",
                            "in_app": true
                        }]
                    }
                }]
            }
        }))
        .unwrap();

        stage
            .resolve_event(fixtures::input_event("event-1", 1, &payload_json))
            .await
            .unwrap();

        assert_eq!(
            resolver.raw_frame_calls.load(Ordering::SeqCst),
            1,
            "JavaScriptPlatformAlias frames must be dispatched to the symbol resolver"
        );
    }

    #[tokio::test]
    async fn invalid_exception_payload_is_preserved_per_event() {
        let stage = ResolutionStage::new();
        let invalid_payload = br#"{"properties":{"$exception_list":"not a list"}}"#.to_vec();
        let valid_payload = br#"{"properties":{"$exception_list":[{"type":"Error","value":"boom","stacktrace":{"frames":[{"filename":"app.js","function":"run"}]}}]}}"#.to_vec();
        let input = StageInput::from_items(
            fixtures::context(),
            vec![
                fixtures::input_event("invalid", 1, &invalid_payload),
                fixtures::input_event("valid", 1, &valid_payload),
            ],
        );

        let output: Vec<ResolvedEvent> = stage.process(input).await.unwrap();

        assert_eq!(output.len(), 2);
        let invalid = serde_json::to_value(&output[0].properties).unwrap();
        assert_eq!(
            invalid.pointer("/$exception_list"),
            Some(&json!("not a list"))
        );
        let valid = serde_json::to_value(&output[1].properties).unwrap();
        assert_eq!(
            valid.pointer("/$exception_functions"),
            Some(&json!(["run"]))
        );
    }

    #[derive(Default)]
    struct CountingResolver {
        raw_frame_calls: AtomicUsize,
    }

    #[derive(Default)]
    struct ConcurrentResolver {
        raw_frame_calls: AtomicUsize,
        in_flight: AtomicUsize,
        max_in_flight: AtomicUsize,
    }

    impl ConcurrentResolver {
        fn observe_in_flight(&self, in_flight: usize) {
            let mut max_seen = self.max_in_flight.load(Ordering::SeqCst);
            while in_flight > max_seen {
                match self.max_in_flight.compare_exchange(
                    max_seen,
                    in_flight,
                    Ordering::SeqCst,
                    Ordering::SeqCst,
                ) {
                    Ok(_) => break,
                    Err(current) => max_seen = current,
                }
            }
        }
    }

    #[derive(Clone, Debug, PartialEq)]
    struct SavedFrame {
        team_id: i32,
        symbol_set_ref: Option<String>,
        context: Option<Context>,
    }

    #[derive(Default)]
    struct RecordingFrameRepository {
        saved: Mutex<Vec<SavedFrame>>,
    }

    #[async_trait]
    impl FrameRepository for RecordingFrameRepository {
        async fn save_resolved_frame(
            &self,
            team_id: i32,
            raw_frame: &RawFrame,
            frame: &Frame,
        ) -> Result<(), UnhandledError> {
            self.saved.lock().unwrap().push(SavedFrame {
                team_id,
                symbol_set_ref: raw_frame.symbol_set_ref(),
                context: frame.context.clone(),
            });
            Ok(())
        }
    }

    #[async_trait]
    impl SymbolResolver for ConcurrentResolver {
        async fn resolve_raw_frame(
            &self,
            _team_id: i32,
            _frame: &RawFrame,
            _debug_images: &[AppleDebugImage],
        ) -> Result<Vec<Frame>, UnhandledError> {
            self.raw_frame_calls.fetch_add(1, Ordering::SeqCst);
            let in_flight = self.in_flight.fetch_add(1, Ordering::SeqCst) + 1;
            self.observe_in_flight(in_flight);
            tokio::time::sleep(Duration::from_millis(25)).await;
            self.in_flight.fetch_sub(1, Ordering::SeqCst);

            Ok(vec![Frame {
                frame_id: FrameId::placeholder(),
                mangled_name: "minified".to_string(),
                line: Some(10),
                column: Some(5),
                source: Some("src/app.ts".to_string()),
                module: None,
                in_app: true,
                resolved_name: Some("resolvedFunction".to_string()),
                lang: "javascript".to_string(),
                resolved: true,
                resolve_failure: None,
                synthetic: false,
                suspicious: false,
                junk_drawer: None,
                code_variables: None,
                context: None,
                release: None,
            }])
        }

        async fn resolve_java_class(
            &self,
            _team_id: i32,
            _symbolset_ref: OrChunkId<ProguardRef>,
            class: String,
        ) -> Result<String, ResolveError> {
            Ok(class)
        }

        async fn resolve_dart_minified_name(
            &self,
            _team_id: i32,
            _symbolset_ref: String,
            minified_name: &str,
        ) -> Result<String, ResolveError> {
            Ok(minified_name.to_string())
        }
    }

    #[async_trait]
    impl SymbolResolver for CountingResolver {
        async fn resolve_raw_frame(
            &self,
            _team_id: i32,
            _frame: &RawFrame,
            _debug_images: &[AppleDebugImage],
        ) -> Result<Vec<Frame>, UnhandledError> {
            self.raw_frame_calls.fetch_add(1, Ordering::SeqCst);
            Ok(vec![Frame {
                frame_id: FrameId::placeholder(),
                mangled_name: "minified".to_string(),
                line: Some(10),
                column: Some(5),
                source: Some("src/app.ts".to_string()),
                module: None,
                in_app: true,
                resolved_name: Some("resolvedFunction".to_string()),
                lang: "javascript".to_string(),
                resolved: true,
                resolve_failure: None,
                synthetic: false,
                suspicious: false,
                junk_drawer: None,
                code_variables: None,
                context: Some(Context {
                    before: vec![ContextLine::new(9, "before")],
                    line: ContextLine::new(10, "line"),
                    after: vec![ContextLine::new(11, "after")],
                }),
                release: Some(ReleaseRecord {
                    id: uuid::Uuid::nil(),
                    team_id: 1,
                    hash_id: "release-hash".to_string(),
                    created_at: chrono::DateTime::parse_from_rfc3339("2025-01-02T03:04:05Z")
                        .unwrap()
                        .with_timezone(&chrono::Utc),
                    version: "1.0.0".to_string(),
                    project: "web".to_string(),
                    metadata: None,
                }),
            }])
        }

        async fn resolve_java_class(
            &self,
            _team_id: i32,
            _symbolset_ref: OrChunkId<ProguardRef>,
            class: String,
        ) -> Result<String, ResolveError> {
            Ok(class)
        }

        async fn resolve_dart_minified_name(
            &self,
            _team_id: i32,
            _symbolset_ref: String,
            minified_name: &str,
        ) -> Result<String, ResolveError> {
            Ok(minified_name.to_string())
        }
    }

    struct ErrorResolver;

    #[async_trait]
    impl SymbolResolver for ErrorResolver {
        async fn resolve_raw_frame(
            &self,
            _team_id: i32,
            _frame: &RawFrame,
            _debug_images: &[AppleDebugImage],
        ) -> Result<Vec<Frame>, UnhandledError> {
            Err(UnhandledError::Other("mock resolver failure".to_string()))
        }

        async fn resolve_java_class(
            &self,
            _team_id: i32,
            _symbolset_ref: OrChunkId<ProguardRef>,
            _class: String,
        ) -> Result<String, ResolveError> {
            Err(ProguardError::MissingClass.into())
        }

        async fn resolve_dart_minified_name(
            &self,
            _team_id: i32,
            _symbolset_ref: String,
            _minified_name: &str,
        ) -> Result<String, ResolveError> {
            Err(JsResolveErr::InvalidSourceAndMap.into())
        }
    }
}
