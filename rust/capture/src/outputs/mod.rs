//! The outputs layer: the produce surface every endpoint publishes through.
//!
//! [`Outputs`] is an open trait — a produce surface handling every
//! destination its configuration maps. Implementations own the whole
//! realization strategy: payload assembly (lane resolution, serialization,
//! headers), namespace realization (abstract [`Address`](crate::pipeline::Address)
//! → concrete topic/path), backend composition, and multi-target policy:
//!
//! - [`kafka::KafkaOutputs`] — one cluster: topic table + producer.
//! - [`s3::S3Outputs`] — the S3 buffer.
//! - [`policies::FailoverOutputs`] — health-gated primary/secondary
//!   (kafka + s3 fallback today), optionally breaker-driven.
//! - [`policies::SplitOutputs`] — token-routed split across two surfaces.
//! - the per-mode tables below — dispatch-by-pipeline across per-pipeline
//!   surfaces.
//! - (future) managed-kafka outputs — dynamic broker/topic/partition
//!   assignment driven by a repartitioning coordinator; just another
//!   implementation.
//!
//! Sinks below this layer are pure transport and never see an `Address`.
//! This is capture's version of the Node.js `IngestionOutputs` model: steps
//! publish to an outputs surface; producer selection, topic resolution, and
//! multi-target routing are its business, configured at boot.

pub mod kafka;
pub mod policies;
pub mod s3;
pub mod simple;
pub mod testing;
pub mod topics;

use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;

use metrics::{counter, histogram};
use tokio::task::JoinSet;
use tracing::log::error;
use tracing::{info_span, Instrument};

use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::api::CaptureError;
use crate::config::{EnvelopeCompression, KafkaConfig};
use crate::pipeline::{resolve, Address, KeyPolicy, LaneEffect, Pipeline};
use crate::serialization::{Format, Serializer};
use crate::v0_request::ProcessedEvent;

/// A serialized, addressed, ready-to-publish payload plus the correlation
/// UUID of the event it came from: the outputs-layer interchange between
/// payload assembly and namespace realization. The address is abstract on
/// purpose — each outputs implementation realizes it in its own namespace
/// (Kafka: a topic via its cluster's table; S3: the buffer; print/noop:
/// trivially), so the same prepared payload can be handed to any target of a
/// failover pair.
#[derive(Debug, Clone)]
pub struct AddressedPayload {
    pub uuid: Uuid,
    pub address: Address,
    pub payload: Vec<u8>,
    pub headers: CapturedEventHeaders,
    pub key: Option<String>,
}

/// One target's payload-assembly configuration: the output→topic wiring and
/// the per-destination payload serializers. The outputs layer runs the whole
/// prep dance with this — lane lookup, serialization, headers, topic and
/// partition key — and hands the sink ready-to-publish payloads. Cheap to
/// clone (an `Arc` and two `Copy` serializers), which matters in the
/// scatter-gather prep path where it is cloned once per spawned task.
#[derive(Clone, Copy)]
pub struct PrepSpec {
    default_serializer: Serializer,
    session_replay_serializer: Serializer,
}

impl PrepSpec {
    pub fn new(replay_envelope_compression: EnvelopeCompression) -> Self {
        Self {
            default_serializer: Serializer::json(),
            session_replay_serializer: Serializer::new(
                Format::Json,
                replay_envelope_compression.into(),
            ),
        }
    }

    /// The payload encoding for an event's pipeline. Replay has its own
    /// (envelope-compressed) contract with its consumers; everything else is
    /// plain json.
    fn serializer_for(&self, pipeline: Pipeline) -> Serializer {
        match pipeline {
            Pipeline::SessionReplay => self.session_replay_serializer,
            _ => self.default_serializer,
        }
    }
}

impl From<&KafkaConfig> for PrepSpec {
    fn from(config: &KafkaConfig) -> Self {
        Self::new(config.kafka_replay_envelope_compression)
    }
}

/// CPU-bound prep work for one event: serialize payload + build headers +
/// pick topic/key. Safe to run concurrently across events in a batch because
/// it touches no producer state — the sink's publish phase is what enforces
/// per-partition ordering.
///
/// The lane decision is [`resolve`] — pure policy over the metadata stamped
/// upstream. This function only applies it: serializer choice, header stamps,
/// counters, topic and partition key resolution. It consults no limiter and
/// decides nothing.
fn prepare_payload(
    spec: &PrepSpec,
    event: ProcessedEvent,
) -> Result<AddressedPayload, CaptureError> {
    let (event, metadata) = (event.event, event.metadata);

    let decision = resolve(&metadata);
    let serializer = spec.serializer_for(decision.address.pipeline());
    let payload = serializer.serialize(&event)?;

    // Correlation UUID, captured before the (memory-hungry) event is
    // dropped so the prepared payload can key its per-event `SinkResult`.
    let uuid = event.uuid;
    let event_key = event.key();

    // Use the event's to_headers() method for consistent header serialization
    let mut headers = event.to_headers();

    drop(event); // Events can be EXTREMELY memory hungry

    // Generic metadata-driven header stamps, independent of the lane
    // decision: applied to every event.
    if metadata.skip_person_processing {
        headers.set_force_disable_person_processing(true);
    }
    if metadata.skip_heatmap_processing {
        headers.set_skip_heatmap_processing(true);
    }

    match decision.effect {
        LaneEffect::Standard => {}
        LaneEffect::Dlq => {
            counter!(
                "capture_events_rerouted_dlq",
                &[("reason", "event_restriction")]
            )
            .increment(1);

            // Set DLQ specific headers
            // DLQ reason cannot be known beyond being triggered by an event restriction.
            headers.set_dlq_reason("event_restriction".to_string());
            // Unlike with our node code, DLQ step will always be static.
            headers.set_dlq_step("capture".to_string());
            headers.set_dlq_timestamp(
                chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            );
        }
        LaneEffect::CustomTopic => {
            counter!(
                "capture_events_rerouted_custom_topic",
                &[("reason", "event_restriction")]
            )
            .increment(1);
        }
        LaneEffect::ForceDisablePersonProcessing => {
            headers.set_force_disable_person_processing(true);
        }
    }

    let partition_key: Option<String> = match decision.key_policy {
        KeyPolicy::EventKey => Some(event_key),
        KeyPolicy::Null => None,
        KeyPolicy::SessionId => Some(
            metadata
                .session_id
                .clone()
                .ok_or(CaptureError::MissingSessionId)?,
        ),
    };

    // The serializer's content headers signal the encoding on the wire, so
    // old and new encodings coexist on one destination during a rollout.
    if let Some(encoding) = serializer.content_encoding() {
        headers.set_content_encoding(encoding.to_string());
    }

    // The address stays abstract: each sink realizes it in its own namespace
    // (Kafka resolves it against its per-cluster topic table at publish time).
    Ok(AddressedPayload {
        uuid,
        address: decision.address,
        payload,
        headers,
        key: partition_key,
    })
}

/// Batches below this size take the serial fast path in `prepare_batch`:
/// spawning N `JoinSet` tasks to run `prepare_payload` in parallel is
/// net-negative when each task does only payload serialization and a header
/// build — the scheduler overhead dominates the CPU savings. Scatter-gather
/// kicks in at or above this threshold where parallel prep wins back its
/// spawn cost.
pub(crate) const SCATTER_GATHER_MIN_BATCH: usize = 8;

/// Prep phase for a whole batch: turn `ProcessedEvent`s into ready-to-publish
/// [`AddressedPayload`]s in the original event order. Fail-fast: any single
/// prep error aborts the whole batch and produces zero records.
///
/// Small batches prep serially; batches at or above
/// `SCATTER_GATHER_MIN_BATCH` scatter prep across tokio workers and gather
/// back into input order so per-partition ordering downstream is unaffected.
/// (The histogram names keep their `kafka` prefix for dashboard continuity —
/// prep is generic now, but the metric contract is stable.)
pub(crate) async fn prepare_batch(
    spec: &PrepSpec,
    events: Vec<ProcessedEvent>,
) -> Result<Vec<AddressedPayload>, CaptureError> {
    let batch_size = events.len();

    // Small-batch fast path: the JoinSet spawn overhead dominates any
    // parallel-prep win, so stay single-threaded.
    if batch_size < SCATTER_GATHER_MIN_BATCH {
        let prep_start = Instant::now();
        let mut prepared: Vec<AddressedPayload> = Vec::with_capacity(batch_size);
        for event in events {
            match prepare_payload(spec, event) {
                Ok(payload) => prepared.push(payload),
                Err(err) => {
                    histogram!("capture_kafka_batch_prep_duration_seconds")
                        .record(prep_start.elapsed().as_secs_f64());
                    return Err(err);
                }
            }
        }
        histogram!("capture_kafka_batch_prep_duration_seconds")
            .record(prep_start.elapsed().as_secs_f64());
        return Ok(prepared);
    }

    // Parallel prep across tokio workers. Each task returns its input index
    // so results reassemble in the original event order before the serial
    // enqueue phase. This is where the CPU win lives: payload serialization
    // + header build run concurrently on up to N worker threads, rather
    // than sequentially on a single task.
    let prep_start = Instant::now();
    let mut prep_set: JoinSet<(usize, Result<AddressedPayload, CaptureError>)> = JoinSet::new();
    for (idx, event) in events.into_iter().enumerate() {
        let spec = *spec;
        prep_set.spawn(
            async move { (idx, prepare_payload(&spec, event)) }
                .instrument(info_span!("prepare_payload")),
        );
    }

    // Collect into a (idx, payload) Vec and sort rather than indexing into
    // a `Vec<Option<_>>`. Encodes the "every slot filled" invariant in the
    // type: no `Option`, no unreachable `expect`, no N-element `None`
    // preallocation. Our only cancellation source is `prep_set.abort_all()`
    // below, invoked only from an already-errored branch, so any
    // `JoinError` observed during normal drain implies a panic inside
    // `prepare_payload` — counted separately so it's alertable.
    let mut prepared: Vec<(usize, AddressedPayload)> = Vec::with_capacity(batch_size);
    while let Some(join_result) = prep_set.join_next().await {
        let (idx, result) = match join_result {
            Err(err) => {
                counter!("capture_kafka_prep_panic_total").increment(1);
                error!("join error while preparing payload: {err:#}");
                // Drain remaining prep tasks before returning so they can't
                // leak records downstream after we've already failed.
                // Record the histogram on the error path too so prep-duration
                // stays observable during failures (not just happy path).
                prep_set.abort_all();
                histogram!("capture_kafka_batch_prep_duration_seconds")
                    .record(prep_start.elapsed().as_secs_f64());
                return Err(CaptureError::RetryableSinkError);
            }
            Ok(inner) => inner,
        };
        match result {
            Ok(payload) => prepared.push((idx, payload)),
            Err(err) => {
                prep_set.abort_all();
                histogram!("capture_kafka_batch_prep_duration_seconds")
                    .record(prep_start.elapsed().as_secs_f64());
                return Err(err);
            }
        }
    }
    prepared.sort_unstable_by_key(|(idx, _)| *idx);
    debug_assert_eq!(prepared.len(), batch_size);
    histogram!("capture_kafka_batch_prep_duration_seconds")
        .record(prep_start.elapsed().as_secs_f64());

    Ok(prepared.into_iter().map(|(_, payload)| payload).collect())
}

/// A produce surface: publish a batch of processed events, handling every
/// destination this surface's configuration maps. Implementations own
/// payload assembly, namespace realization, backend composition, and policy;
/// callers never see a two-phase protocol. Composes freely: policy surfaces
/// (failover, split, dispatch tables) hold other `dyn Outputs`.
///
/// `publish` collapses per-event results to today's whole-request response
/// (first failure wins); it widens to per-event outcomes when the per-event
/// response model (v1 `BatchResponse`) is adopted.
#[async_trait]
pub trait Outputs: Send + Sync {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;

    /// Flush buffered/pending data before shutdown.
    fn flush(&self) -> Result<(), anyhow::Error>;
}

/// The publish capability of a deployment that runs the analytics family of
/// pipelines (analytics, ai, heatmaps, warnings, error tracking) — what the
/// `/capture`-family handlers require of their state. A marker over
/// [`Outputs`], sealed by construction: only per-mode tables implement it,
/// so mounting an ingress on a table that cannot publish its family is a
/// compile error.
pub trait PublishesAnalyticsFamily: Outputs + 'static {}

/// The publish capability of a deployment that runs the AI pipeline — what
/// the AI and OTEL handlers require of their state. Narrower than
/// [`PublishesAnalyticsFamily`]: those handlers only ever produce `$ai_*`
/// events, so a future AI-only deployment can mount them with an ai-row-only
/// table.
pub trait PublishesAi: Outputs + 'static {}

/// The publish capability of a deployment that runs the session replay
/// pipeline — what the `/s` handler requires of its state.
pub trait PublishesSessionReplay: Outputs + 'static {}

/// The output table of an Events/Ai deployment: one produce surface per
/// pipeline the analytics-family ingress can produce. Required fields — the
/// narrow list of what this deployment must wire is the type itself. The
/// table is itself an [`Outputs`]: dispatch-by-pipeline is just another
/// produce surface, so tables nest like any other policy.
pub struct AnalyticsFamilyOutputs {
    pub analytics: Arc<dyn Outputs>,
    pub ai: Arc<dyn Outputs>,
    pub heatmaps: Arc<dyn Outputs>,
    pub warnings: Arc<dyn Outputs>,
    pub error_tracking: Arc<dyn Outputs>,
}

/// The output table of a Recordings deployment: the session replay pipeline
/// only. A replay deployment cannot even hold an analytics output.
pub struct SessionReplayOutputs {
    pub session_replay: Arc<dyn Outputs>,
}

impl AnalyticsFamilyOutputs {
    /// The surface a pipeline publishes through. `None` is the structural
    /// backstop: replay events cannot arrive here because ingress mounting
    /// and table type both derive from `CaptureMode`.
    fn row(&self, pipeline: Pipeline) -> Option<&Arc<dyn Outputs>> {
        match pipeline {
            Pipeline::Analytics => Some(&self.analytics),
            Pipeline::Ai => Some(&self.ai),
            Pipeline::Heatmaps => Some(&self.heatmaps),
            Pipeline::Warnings => Some(&self.warnings),
            Pipeline::ErrorTracking => Some(&self.error_tracking),
            Pipeline::SessionReplay => None,
        }
    }
}

impl SessionReplayOutputs {
    fn row(&self, pipeline: Pipeline) -> Option<&Arc<dyn Outputs>> {
        match pipeline {
            Pipeline::SessionReplay => Some(&self.session_replay),
            _ => None,
        }
    }
}

macro_rules! impl_table_outputs {
    ($table:ty, [$($row:ident),+]) => {
        #[async_trait]
        impl Outputs for $table {
            async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
                // Group by pipeline, preserving within-group order. Batches
                // are single-request, so almost always a single group; the
                // grouping exists for multi-address batches like heatmap
                // redirects (analytics original + heatmaps redirect).
                let mut groups: Vec<(Pipeline, Vec<ProcessedEvent>)> = Vec::new();
                for event in events {
                    let pipeline = Pipeline::from_metadata(&event.metadata);
                    match groups.iter_mut().find(|(p, _)| *p == pipeline) {
                        Some((_, group)) => group.push(event),
                        None => groups.push((pipeline, vec![event])),
                    }
                }
                for (pipeline, group) in groups {
                    let Some(output) = self.row(pipeline) else {
                        error!(
                            "no output configured for pipeline {pipeline:?}; \
                             ingress and output table disagree on this deployment's pipelines"
                        );
                        return Err(CaptureError::NonRetryableSinkError);
                    };
                    output.publish(group).await?;
                }
                Ok(())
            }

            fn flush(&self) -> Result<(), anyhow::Error> {
                $(self.$row.flush()?;)+
                Ok(())
            }
        }
    };
}

impl_table_outputs!(
    AnalyticsFamilyOutputs,
    [analytics, ai, heatmaps, warnings, error_tracking]
);
impl_table_outputs!(SessionReplayOutputs, [session_replay]);

impl PublishesAnalyticsFamily for AnalyticsFamilyOutputs {}
impl PublishesAi for AnalyticsFamilyOutputs {}
impl PublishesSessionReplay for SessionReplayOutputs {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::AiRouting;
    use crate::failover::FailoverController;
    use crate::outputs::policies::{FailoverOutputs, SplitOutputs};
    use crate::outputs::testing::{FailOutputs, MockOutputs};
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::time::Duration;

    fn event_with_token(token: &str) -> ProcessedEvent {
        let timestamp = chrono::Utc::now();
        ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7_from_datetime(timestamp),
                distinct_id: "did".to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: "{}".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: token.to_string(),
                event: "test_event".to_string(),
                timestamp,
                is_cookieless_mode: false,
                historical_migration: false,
            },
            metadata: ProcessedEventMetadata {
                data_type: DataType::AnalyticsMain,
                session_id: None,
                computed_timestamp: None,
                event_name: "test_event".to_string(),
                force_overflow: false,
                skip_person_processing: false,
                redirect_to_dlq: false,
                redirect_to_topic: None,
                skip_heatmap_processing: false,
                overflow_reason: None,
            },
        }
    }

    fn tokens(sink: &MockOutputs) -> Vec<String> {
        sink.captured_events()
            .iter()
            .map(|e| e.token.clone())
            .collect()
    }

    #[tokio::test]
    async fn failover_publishes_to_secondary_on_retriable_failure() {
        let secondary = MockOutputs::new();
        let output = FailoverOutputs::reactive(
            Arc::new(FailOutputs(CaptureError::RetryableSinkError)),
            Arc::new(secondary.clone()),
        );

        output
            .publish(vec![event_with_token("tok")])
            .await
            .expect("failed to send event");
        output
            .publish(vec![event_with_token("tok"), event_with_token("tok")])
            .await
            .expect("failed to send batch");

        assert_eq!(secondary.captured_events().len(), 3);
    }

    #[tokio::test]
    async fn failover_returns_error_when_both_fail() {
        let output = FailoverOutputs::reactive(
            Arc::new(FailOutputs(CaptureError::RetryableSinkError)),
            Arc::new(FailOutputs(CaptureError::RetryableSinkError)),
        );

        assert!(matches!(
            output.publish(vec![event_with_token("tok")]).await,
            Err(CaptureError::RetryableSinkError)
        ));
        assert!(matches!(
            output
                .publish(vec![event_with_token("tok"), event_with_token("tok")])
                .await,
            Err(CaptureError::RetryableSinkError)
        ));
    }

    #[tokio::test]
    async fn failover_fatal_error_does_not_fail_over() {
        let secondary = MockOutputs::new();
        let output = FailoverOutputs::reactive(
            Arc::new(FailOutputs(CaptureError::NonRetryableSinkError)),
            Arc::new(secondary.clone()),
        );

        assert!(matches!(
            output.publish(vec![event_with_token("tok")]).await,
            Err(CaptureError::NonRetryableSinkError)
        ));
        assert!(secondary.captured_events().is_empty());
    }

    #[tokio::test]
    async fn advisory_handle_controls_primary_routing() {
        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_health_poll_interval(Duration::from_millis(50))
            .build();

        let kafka_handle = manager.register(
            "kafka-advisory",
            lifecycle::ComponentOptions::new()
                .with_liveness_deadline(Duration::from_millis(200))
                .is_advisory(true),
        );
        let _monitor = manager.monitor_background();

        let primary = MockOutputs::new();
        let secondary = MockOutputs::new();
        let output = FailoverOutputs::new(
            Arc::new(primary.clone()),
            Arc::new(secondary.clone()),
            kafka_handle.clone(),
        );

        // Advisory handle starts healthy: publishes go to the primary.
        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        output.publish(vec![event_with_token("a")]).await.unwrap();
        assert_eq!(primary.captured_events().len(), 1);
        assert!(secondary.captured_events().is_empty());

        // Let the advisory deadline expire: publishes skip the primary.
        tokio::time::sleep(Duration::from_millis(400)).await;
        output.publish(vec![event_with_token("b")]).await.unwrap();
        assert_eq!(primary.captured_events().len(), 1);
        assert_eq!(secondary.captured_events().len(), 1);

        // Recovery: report healthy again and the primary serves once more.
        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        output.publish(vec![event_with_token("c")]).await.unwrap();
        assert_eq!(primary.captured_events().len(), 2);
        assert_eq!(secondary.captured_events().len(), 1);
    }

    // ---- Breaker-mode failover (dark-launched) ---------------------------

    use crate::failover::testing::{test_breaker_config, ManualClock};
    use crate::failover::{ControlPlane, HealthReport, RouteResolution};
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    /// A sink whose publish outcome is toggleable, counting publish calls.
    struct ProgrammableSink {
        fail: AtomicBool,
        calls: AtomicUsize,
    }

    impl ProgrammableSink {
        fn new(fail: bool) -> Arc<Self> {
            Arc::new(Self {
                fail: AtomicBool::new(fail),
                calls: AtomicUsize::new(0),
            })
        }
        fn set_fail(&self, fail: bool) {
            self.fail.store(fail, Ordering::SeqCst);
        }
        fn calls(&self) -> usize {
            self.calls.load(Ordering::SeqCst)
        }
    }

    #[async_trait::async_trait]
    impl Outputs for ProgrammableSink {
        async fn publish(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            if self.fail.load(Ordering::SeqCst) {
                Err(CaptureError::RetryableSinkError)
            } else {
                Ok(())
            }
        }

        fn flush(&self) -> Result<(), anyhow::Error> {
            Ok(())
        }
    }

    fn breaker_output(
        primary: Arc<ProgrammableSink>,
        secondary: Arc<MockOutputs>,
        control_plane: Arc<dyn ControlPlane>,
        clock: Arc<ManualClock>,
    ) -> FailoverOutputs {
        let controller = Arc::new(FailoverController::with_parts(
            control_plane,
            clock,
            test_breaker_config(),
        ));
        FailoverOutputs::breaker_for_tests(primary, secondary, controller)
    }

    struct UpControlPlane;
    impl ControlPlane for UpControlPlane {
        fn resolve(&self) -> RouteResolution {
            RouteResolution {
                primary_available: true,
                primary_host: None,
            }
        }
        fn report_health(&self, _r: HealthReport) {}
    }

    #[tokio::test]
    async fn breaker_healthy_primary_serves_primary_only() {
        let primary = ProgrammableSink::new(false);
        let secondary = MockOutputs::new();
        let clock = ManualClock::new();
        let output = breaker_output(
            primary.clone(),
            Arc::new(secondary.clone()),
            Arc::new(UpControlPlane),
            clock,
        );

        for _ in 0..5 {
            output.publish(vec![event_with_token("tok")]).await.unwrap();
        }
        assert_eq!(primary.calls(), 5);
        assert!(secondary.captured_events().is_empty());
    }

    #[tokio::test]
    async fn breaker_opens_then_serves_fallback_then_recovers() {
        let primary = ProgrammableSink::new(true);
        let secondary = MockOutputs::new();
        let clock = ManualClock::new();
        let output = breaker_output(
            primary.clone(),
            Arc::new(secondary.clone()),
            Arc::new(UpControlPlane),
            clock.clone(),
        );

        // Failing primary: each batch attempts the primary (recording an
        // error) and reactively fails over to the secondary. After
        // min_samples=4 the breaker trips open.
        for _ in 0..4 {
            output.publish(vec![event_with_token("tok")]).await.unwrap();
        }
        assert_eq!(primary.calls(), 4);
        assert_eq!(secondary.captured_events().len(), 4);

        // Open: batches go straight to the secondary, primary untouched.
        output.publish(vec![event_with_token("tok")]).await.unwrap();
        assert_eq!(
            primary.calls(),
            4,
            "open breaker must not touch the primary"
        );
        assert_eq!(secondary.captured_events().len(), 5);

        // Heal the primary and let the cooldown elapse: half-open probes it,
        // and after required_successes=2 the breaker closes again.
        primary.set_fail(false);
        clock.advance(std::time::Duration::from_secs(6));
        output.publish(vec![event_with_token("tok")]).await.unwrap();
        output.publish(vec![event_with_token("tok")]).await.unwrap();
        output.publish(vec![event_with_token("tok")]).await.unwrap();
        assert_eq!(
            primary.calls(),
            7,
            "probes and closed traffic hit the primary"
        );
        assert_eq!(
            secondary.captured_events().len(),
            5,
            "no more fallback traffic"
        );
    }

    #[tokio::test]
    async fn breaker_control_plane_unavailable_forces_fallback() {
        struct DownControlPlane;
        impl ControlPlane for DownControlPlane {
            fn resolve(&self) -> RouteResolution {
                RouteResolution {
                    primary_available: false,
                    primary_host: None,
                }
            }
            fn report_health(&self, _r: HealthReport) {}
        }

        let primary = ProgrammableSink::new(false);
        let secondary = MockOutputs::new();
        let clock = ManualClock::new();
        let output = breaker_output(
            primary.clone(),
            Arc::new(secondary.clone()),
            Arc::new(DownControlPlane),
            clock,
        );

        output.publish(vec![event_with_token("tok")]).await.unwrap();
        assert_eq!(primary.calls(), 0);
        assert_eq!(secondary.captured_events().len(), 1);
    }

    #[tokio::test]
    async fn breaker_fatal_primary_failure_does_not_fail_over() {
        let secondary = MockOutputs::new();
        let clock = ManualClock::new();
        let controller = Arc::new(FailoverController::with_parts(
            Arc::new(UpControlPlane),
            clock,
            test_breaker_config(),
        ));
        let output = FailoverOutputs::breaker_for_tests(
            Arc::new(FailOutputs(CaptureError::NonRetryableSinkError)),
            Arc::new(secondary.clone()),
            controller,
        );

        // Fatal errors return as-is (the event's fault), never fail over, and
        // never trip the breaker — repeated fatals keep attempting the primary.
        for _ in 0..6 {
            assert!(matches!(
                output.publish(vec![event_with_token("tok")]).await,
                Err(CaptureError::NonRetryableSinkError)
            ));
        }
        assert!(secondary.captured_events().is_empty());
    }

    #[tokio::test]
    async fn split_routes_single_event_by_allowlist() {
        let primary = MockOutputs::new();
        let secondary = MockOutputs::new();
        let output = SplitOutputs::new(
            Arc::new(primary.clone()),
            Arc::new(secondary.clone()),
            AiRouting::SecondaryAllowlist(vec!["secondary_tok".to_string()].into_iter().collect()),
        );

        output
            .publish(vec![event_with_token("secondary_tok")])
            .await
            .unwrap();
        output
            .publish(vec![event_with_token("other")])
            .await
            .unwrap();

        assert_eq!(tokens(&secondary), vec!["secondary_tok"]);
        assert_eq!(tokens(&primary), vec!["other"]);
    }

    #[tokio::test]
    async fn split_batch_partitions_across_targets_preserving_order() {
        let primary = MockOutputs::new();
        let secondary = MockOutputs::new();
        let output = SplitOutputs::new(
            Arc::new(primary.clone()),
            Arc::new(secondary.clone()),
            AiRouting::SecondaryAllowlist(
                vec!["sec_1".to_string(), "sec_2".to_string()]
                    .into_iter()
                    .collect(),
            ),
        );

        output
            .publish(vec![
                event_with_token("sec_1"),
                event_with_token("pri_1"),
                event_with_token("sec_2"),
                event_with_token("pri_2"),
            ])
            .await
            .unwrap();

        assert_eq!(tokens(&secondary), vec!["sec_1", "sec_2"]);
        assert_eq!(tokens(&primary), vec!["pri_1", "pri_2"]);
    }
}
