//! The outputs layer: the produce surface a pipeline publishes through.
//!
//! An [`Output`] owns one or more targets and the **policy** that picks
//! between them per batch. All multi-target behavior lives here and only
//! here — a sink is always a single backend; anything that picks between
//! sinks is an output policy:
//!
//! - single — one backend.
//! - failover — health-gated primary/secondary (Kafka → S3 today): skip the
//!   primary while its advisory handle reports unhealthy, and re-publish the
//!   batch to the secondary on a retriable failure.
//! - split — token-routed primary/secondary (the AI → secondary cluster
//!   migration): each event publishes through exactly one target.
//!
//! Targets are outputs themselves, so policies compose the way the old sink
//! composites did (e.g. split over a failover pair). Leaves drive the full
//! dance internally — lane resolution, serialization, and topic assembly via
//! the backend's prep path, then the mechanism publish — so no caller ever
//! sees a two-phase protocol.
//!
//! This is capture's version of the Node.js `IngestionOutputs` model: steps
//! publish to an output; producer selection, topic resolution, and
//! multi-target routing are the output's business, configured at boot.
//!
//! [`OutputTable`] is the handle the router state holds: the
//! `(pipeline, lane)` → output mapping. Every address resolves to the one
//! deployment-wide output today (per-lane topics still resolve inside the
//! prep path via the `OutputRegistry`); the table is where per-address
//! wiring lands when the first config needs it.

use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;

use metrics::{counter, gauge, histogram};
use tokio::task::JoinSet;
use tracing::log::error;
use tracing::{info_span, Instrument};

use crate::api::CaptureError;
use crate::config::{AiRouting, EnvelopeCompression, KafkaConfig};
use crate::failover::{AttemptOutcome, BreakerState, FailoverController, Route as FailoverRoute};
use crate::pipeline::{resolve, KeyPolicy, LaneEffect, Pipeline};
use crate::serialization::{Format, Serializer};
use crate::sinks::sink::{fold_results, AddressedPayload, Sink};
use crate::v0_request::ProcessedEvent;

/// One target's payload-assembly configuration: the output→topic wiring and
/// the per-destination payload serializers. The outputs layer runs the whole
/// prep dance with this — lane lookup, serialization, headers, topic and
/// partition key — and hands the sink ready-to-publish payloads. Cheap to
/// clone (an `Arc` and two `Copy` serializers), which matters in the
/// scatter-gather prep path where it is cloned once per spawned task.
#[derive(Clone, Copy)]
pub struct PrepSpec {
    default_serializer: Serializer,
    replay_serializer: Serializer,
}

impl PrepSpec {
    pub fn new(replay_envelope_compression: EnvelopeCompression) -> Self {
        Self {
            default_serializer: Serializer::json(),
            replay_serializer: Serializer::new(Format::Json, replay_envelope_compression.into()),
        }
    }

    /// The payload encoding for an event's pipeline. Replay has its own
    /// (envelope-compressed) contract with its consumers; everything else is
    /// plain json.
    fn serializer_for(&self, pipeline: Pipeline) -> Serializer {
        match pipeline {
            Pipeline::Replay => self.replay_serializer,
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

/// A produce destination: a single backend, or a policy composing two of them.
/// The representation is private — construction happens at boot in `setup`,
/// and nothing outside this crate builds or inspects one.
pub struct Output {
    repr: Repr,
}

enum Repr {
    Single {
        sink: Arc<dyn Sink>,
        prep: PrepSpec,
    },
    /// Health-gated failover, Kafka primary / S3 secondary today. Publishes
    /// to the primary and re-publishes the batch to the secondary on a
    /// retriable failure; skips the primary entirely while the advisory
    /// lifecycle handle reports it unhealthy. Fatal errors are the event's
    /// fault and never fail over.
    Failover {
        primary: Box<Output>,
        secondary: Box<Output>,
        advisory_handle: Option<lifecycle::Handle>,
        /// Breaker-driven autonomous mode (dark-launched): `None` runs the
        /// reactive advisory mode.
        controller: Option<Arc<FailoverController>>,
    },
    /// Token-routed split, primary cluster / secondary cluster (e.g.
    /// WarpStream) today. Routing is decided per event before any prep, so
    /// each partition resolves topics and serializes through its own target.
    Split {
        primary: Box<Output>,
        secondary: Box<Output>,
        routing: AiRouting,
    },
}

impl Output {
    pub fn single(sink: Arc<dyn Sink>, prep: PrepSpec) -> Self {
        Output {
            repr: Repr::Single { sink, prep },
        }
    }

    pub fn failover(
        primary: Output,
        secondary: Output,
        advisory_handle: lifecycle::Handle,
    ) -> Self {
        gauge!("capture_primary_sink_health").set(1.0);
        Output {
            repr: Repr::Failover {
                primary: Box::new(primary),
                secondary: Box::new(secondary),
                advisory_handle: Some(advisory_handle),
                controller: None,
            },
        }
    }

    /// Breaker-driven failover (dark-launched behind `CAPTURE_FAILOVER_ENABLED`):
    /// the same primary/secondary pair, with autonomous switchover and recovery
    /// probing driven by the controller's circuit breaker.
    pub fn failover_with_breaker(
        primary: Output,
        secondary: Output,
        advisory_handle: lifecycle::Handle,
        controller: Arc<FailoverController>,
    ) -> Self {
        gauge!("capture_primary_sink_health").set(1.0);
        Output {
            repr: Repr::Failover {
                primary: Box::new(primary),
                secondary: Box::new(secondary),
                advisory_handle: Some(advisory_handle),
                controller: Some(controller),
            },
        }
    }

    /// Failover without an advisory handle: reactive only (used in tests).
    #[cfg(test)]
    pub(crate) fn failover_reactive(primary: Output, secondary: Output) -> Self {
        Output {
            repr: Repr::Failover {
                primary: Box::new(primary),
                secondary: Box::new(secondary),
                advisory_handle: None,
                controller: None,
            },
        }
    }

    pub fn split(primary: Output, secondary: Output, routing: AiRouting) -> Self {
        Output {
            repr: Repr::Split {
                primary: Box::new(primary),
                secondary: Box::new(secondary),
                routing,
            },
        }
    }

    /// Publish a batch of processed events through this output, collapsing
    /// per-event results to today's whole-request response (first failure
    /// wins). Policies operate on events, before any prep, so each target
    /// resolves topics and serializes for itself.
    pub async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        match &self.repr {
            Repr::Single { sink, prep } => {
                let prepared = prepare_batch(prep, events).await?;
                fold_results(sink.publish(prepared).await)
            }
            Repr::Failover {
                primary,
                secondary,
                advisory_handle,
                controller,
            } => {
                let advisory_healthy = advisory_handle
                    .as_ref()
                    .map(|h| h.is_healthy())
                    .unwrap_or(true);

                let Some(controller) = controller else {
                    // Reactive advisory mode: skip the primary while unhealthy,
                    // fail the batch over on a retriable error, never on fatal.
                    gauge!("capture_primary_sink_health").set(if advisory_healthy {
                        1.0
                    } else {
                        0.0
                    });

                    if !advisory_healthy {
                        counter!("capture_fallback_sink_failovers_total").increment(1);
                        return Box::pin(secondary.publish(events)).await;
                    }

                    return match Box::pin(primary.publish(events.clone())).await {
                        Ok(()) => Ok(()),
                        Err(CaptureError::RetryableSinkError) => {
                            error!("Primary sink failed, falling back");
                            counter!("capture_fallback_sink_failovers_total").increment(1);
                            Box::pin(secondary.publish(events)).await
                        }
                        Err(e) => Err(e),
                    };
                };

                // Breaker mode: the controller decides the route per batch —
                // autonomous open/half-open/closed switchover on top of the
                // reactive guarantee below.
                let healthy = advisory_healthy && controller.primary_available();
                let (route, state, error_ratio) = controller.poll(healthy);

                // Half-open admits a single probe at a time: while one batch is
                // testing the primary, others fall back rather than flood a
                // still-flaky primary. A `Primary` route here becomes `Fallback`
                // if we can't win the permit.
                let mut probing = false;
                let effective = if route == FailoverRoute::Primary {
                    if state == BreakerState::HalfOpen {
                        if controller.try_acquire_probe() {
                            probing = true;
                            FailoverRoute::Primary
                        } else {
                            FailoverRoute::Fallback
                        }
                    } else {
                        FailoverRoute::Primary
                    }
                } else {
                    FailoverRoute::Fallback
                };

                // The gauge tracks the *effective* routing decision (breaker +
                // health), not health alone: `capture_primary_sink_health == 0`
                // iff this batch is served by the secondary, preserving the
                // reactive mode's invariant.
                gauge!("capture_primary_sink_health").set(if effective == FailoverRoute::Primary {
                    1.0
                } else {
                    0.0
                });

                if effective == FailoverRoute::Fallback {
                    counter!("capture_fallback_sink_failovers_total").increment(1);
                    controller.report_routed_to_fallback(state, error_ratio);
                    return Box::pin(secondary.publish(events)).await;
                }

                // Primary route (closed, or the single admitted half-open
                // probe): attempt, then record. The result is already folded to
                // the whole-batch response, and the mechanism reports
                // batch-uniform results, so the fold *is* the attempt outcome.
                let result = Box::pin(primary.publish(events.clone())).await;
                let outcome = match &result {
                    Ok(()) => AttemptOutcome::Success,
                    Err(CaptureError::RetryableSinkError) => AttemptOutcome::Retriable,
                    Err(_) => AttemptOutcome::Fatal,
                };
                if probing {
                    controller.release_probe();
                }
                controller.record(outcome, state);

                // Preserve the reactive guarantee: a retriable primary failure
                // still fails this batch over to the secondary immediately, on
                // top of the breaker tripping for subsequent batches. A fatal
                // outcome is returned as-is (no failover), matching v0.
                if matches!(outcome, AttemptOutcome::Retriable) {
                    error!("Primary sink failed retriably, failing batch over to fallback");
                    counter!("capture_fallback_sink_failovers_total").increment(1);
                    return Box::pin(secondary.publish(events)).await;
                }
                result
            }
            Repr::Split {
                primary,
                secondary,
                routing,
            } => {
                // Partition by destination, preserving per-destination order.
                // The common case (every event routes the same way — e.g. a
                // single-token batch in full-secondary mode) leaves one Vec
                // empty and forwards the other whole.
                let mut to_primary: Vec<ProcessedEvent> = Vec::new();
                let mut to_secondary: Vec<ProcessedEvent> = Vec::new();
                for event in events {
                    if routing.routes_to_secondary(&event.event.token) {
                        to_secondary.push(event);
                    } else {
                        to_primary.push(event);
                    }
                }

                counter!("capture_split_sink_selected", "cluster" => "primary")
                    .increment(to_primary.len() as u64);
                counter!("capture_split_sink_selected", "cluster" => "secondary")
                    .increment(to_secondary.len() as u64);

                // A batch is built from a single request, so every event
                // carries the same request-level token and one partition is
                // always empty today; the both-non-empty arm is defensive
                // against a future multi-token batch path, not a hot path.
                match (to_primary.is_empty(), to_secondary.is_empty()) {
                    (false, true) => Box::pin(primary.publish(to_primary)).await,
                    (true, false) => Box::pin(secondary.publish(to_secondary)).await,
                    (false, false) => {
                        // Cross-destination ordering is irrelevant (separate
                        // clusters); publish concurrently and fail if either
                        // fails. Caveat for the day this arm goes live: failing
                        // the whole batch makes the caller retry both
                        // partitions, duplicating events the healthy cluster
                        // already accepted; avoiding that needs partial-batch
                        // retry, which the whole-request contract can't express.
                        let (p, s) = tokio::join!(
                            Box::pin(primary.publish(to_primary)),
                            Box::pin(secondary.publish(to_secondary)),
                        );
                        p.and(s)
                    }
                    (true, true) => Ok(()),
                }
            }
        }
    }

    /// Flush before shutdown. Failover flushes the primary only (matching the
    /// former `FallbackSink`); split flushes both clusters.
    pub fn flush(&self) -> Result<(), anyhow::Error> {
        match &self.repr {
            Repr::Single { sink, .. } => sink.flush(),
            Repr::Failover { primary, .. } => primary.flush(),
            Repr::Split {
                primary, secondary, ..
            } => {
                primary.flush()?;
                secondary.flush()?;
                Ok(())
            }
        }
    }
}

/// The `(pipeline, lane)` → output mapping the router state holds. Every
/// address resolves to the one deployment-wide output today; per-lane topics
/// resolve inside the prep path via the `OutputRegistry`, whose boot-time
/// completeness check guarantees the addresses this deployment can produce
/// to are wired.
/// Deployment-agnostic surface for shutdown handling; the publish surfaces
/// are the per-family capability traits below.
pub trait DeploymentOutputs: Send + Sync {
    fn flush(&self) -> Result<(), anyhow::Error>;
}

/// The publish capability of a deployment that runs the analytics family of
/// pipelines (analytics, ai, heatmaps, warnings, error tracking) — what the
/// `/capture`-family, AI, and OTEL handlers require of their state. Sealed by
/// construction: only per-mode output tables implement it.
#[async_trait]
pub trait PublishesAnalyticsFamily: DeploymentOutputs + 'static {
    // (object-safe async publish)
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;
}

/// The publish capability of a deployment that runs the AI pipeline — what
/// the AI and OTEL handlers require of their state. Narrower than
/// [`PublishesAnalyticsFamily`]: those handlers only ever produce `$ai_*`
/// events, so a future AI-only deployment can mount them with an ai-row-only
/// table.
#[async_trait]
pub trait PublishesAi: DeploymentOutputs + 'static {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;
}

/// The publish capability of a deployment that runs the replay pipeline —
/// what the `/s` handler requires of its state.
#[async_trait]
pub trait PublishesReplay: DeploymentOutputs + 'static {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;
}

/// The output table of an Events/Ai deployment: one output per pipeline the
/// analytics-family ingress can produce. Required fields — the narrow list of
/// what this deployment must wire is the type itself.
pub struct AnalyticsFamilyOutputs {
    pub analytics: Output,
    pub ai: Output,
    pub heatmaps: Output,
    pub warnings: Output,
    pub error_tracking: Output,
}

/// The output table of a Recordings deployment: the replay pipeline only. A
/// replay deployment cannot even hold an analytics output.
pub struct ReplayOutputs {
    pub replay: Output,
}

impl AnalyticsFamilyOutputs {
    /// The row a pipeline publishes through. `None` is the structural
    /// backstop: replay events cannot arrive here because ingress mounting
    /// and table type both derive from `CaptureMode`.
    fn row(&self, pipeline: Pipeline) -> Option<&Output> {
        match pipeline {
            Pipeline::Analytics => Some(&self.analytics),
            Pipeline::Ai => Some(&self.ai),
            Pipeline::Heatmaps => Some(&self.heatmaps),
            Pipeline::Warnings => Some(&self.warnings),
            Pipeline::ErrorTracking => Some(&self.error_tracking),
            Pipeline::Replay => None,
        }
    }
}

impl ReplayOutputs {
    fn row(&self, pipeline: Pipeline) -> Option<&Output> {
        match pipeline {
            Pipeline::Replay => Some(&self.replay),
            _ => None,
        }
    }
}

macro_rules! impl_table_publish {
    ($table:ty) => {
        impl $table {
            async fn publish_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
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
        }
    };
}

impl_table_publish!(AnalyticsFamilyOutputs);
impl_table_publish!(ReplayOutputs);

impl DeploymentOutputs for AnalyticsFamilyOutputs {
    fn flush(&self) -> Result<(), anyhow::Error> {
        self.analytics.flush()?;
        self.ai.flush()?;
        self.heatmaps.flush()?;
        self.warnings.flush()?;
        self.error_tracking.flush()?;
        Ok(())
    }
}

impl DeploymentOutputs for ReplayOutputs {
    fn flush(&self) -> Result<(), anyhow::Error> {
        self.replay.flush()
    }
}

#[async_trait]
impl PublishesAnalyticsFamily for AnalyticsFamilyOutputs {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.publish_batch(events).await
    }
}

#[async_trait]
impl PublishesAi for AnalyticsFamilyOutputs {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.publish_batch(events).await
    }
}

#[async_trait]
impl PublishesReplay for ReplayOutputs {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.publish_batch(events).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sinks::test_sink::{FailSink, MockSink};
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

    fn spec() -> PrepSpec {
        PrepSpec::new(EnvelopeCompression::None)
    }

    fn tokens(sink: &MockSink) -> Vec<String> {
        sink.captured_events()
            .iter()
            .map(|e| e.token.clone())
            .collect()
    }

    #[tokio::test]
    async fn failover_publishes_to_secondary_on_retriable_failure() {
        let secondary = MockSink::new();
        let output = Output::failover_reactive(
            Output::single(Arc::new(FailSink(CaptureError::RetryableSinkError)), spec()),
            Output::single(Arc::new(secondary.clone()), spec()),
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
        let output = Output::failover_reactive(
            Output::single(Arc::new(FailSink(CaptureError::RetryableSinkError)), spec()),
            Output::single(Arc::new(FailSink(CaptureError::RetryableSinkError)), spec()),
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
        let secondary = MockSink::new();
        let output = Output::failover_reactive(
            Output::single(
                Arc::new(FailSink(CaptureError::NonRetryableSinkError)),
                spec(),
            ),
            Output::single(Arc::new(secondary.clone()), spec()),
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

        let primary = MockSink::new();
        let secondary = MockSink::new();
        let output = Output::failover(
            Output::single(Arc::new(primary.clone()), spec()),
            Output::single(Arc::new(secondary.clone()), spec()),
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
    use crate::sinks::sink::SinkResult;
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
    impl Sink for ProgrammableSink {
        async fn publish(&self, prepared: Vec<AddressedPayload>) -> Vec<SinkResult> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            let fail = self.fail.load(Ordering::SeqCst);
            prepared
                .into_iter()
                .map(|p| {
                    if fail {
                        SinkResult::err(p.uuid, CaptureError::RetryableSinkError)
                    } else {
                        SinkResult::ok(p.uuid)
                    }
                })
                .collect()
        }
    }

    fn breaker_output(
        primary: Arc<ProgrammableSink>,
        secondary: Arc<MockSink>,
        control_plane: Arc<dyn ControlPlane>,
        clock: Arc<ManualClock>,
    ) -> Output {
        let controller = Arc::new(FailoverController::with_parts(
            control_plane,
            clock,
            test_breaker_config(),
        ));
        Output {
            repr: Repr::Failover {
                primary: Box::new(Output::single(primary, spec())),
                secondary: Box::new(Output::single(secondary, spec())),
                advisory_handle: None,
                controller: Some(controller),
            },
        }
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
        let secondary = MockSink::new();
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
        let secondary = MockSink::new();
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
        let secondary = MockSink::new();
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
        let secondary = MockSink::new();
        let clock = ManualClock::new();
        let controller = Arc::new(FailoverController::with_parts(
            Arc::new(UpControlPlane),
            clock,
            test_breaker_config(),
        ));
        let output = Output {
            repr: Repr::Failover {
                primary: Box::new(Output::single(
                    Arc::new(FailSink(CaptureError::NonRetryableSinkError)),
                    spec(),
                )),
                secondary: Box::new(Output::single(Arc::new(secondary.clone()), spec())),
                advisory_handle: None,
                controller: Some(controller),
            },
        };

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
        let primary = MockSink::new();
        let secondary = MockSink::new();
        let output = Output::split(
            Output::single(Arc::new(primary.clone()), spec()),
            Output::single(Arc::new(secondary.clone()), spec()),
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
        let primary = MockSink::new();
        let secondary = MockSink::new();
        let output = Output::split(
            Output::single(Arc::new(primary.clone()), spec()),
            Output::single(Arc::new(secondary.clone()), spec()),
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
