//! End-to-end demo: a mini analytics pipeline wired from the framework, exercising
//! every verdict path, fail-open passthrough, warnings, the output registry, and an
//! async chunk stage — all with static dispatch.

use capture_pipelines_poc::capability::{Restricted, Validated};
use capture_pipelines_poc::chain::{builder, Chain, Identity, Pipeline};
use capture_pipelines_poc::chunk::{run_chunk_stage, ChunkStep};
use capture_pipelines_poc::demo::{
    analytics_topic_for, AnalyticsFx, ApplyQuota, ApplyRestrictions, ParsedEvent, Validate,
};
use capture_pipelines_poc::fail_open::{FailOpen, FallibleStepExt};
use capture_pipelines_poc::observer::{CountingObserver, Observer};
use capture_pipelines_poc::outputs::{AnalyticsOutputs, MemProducer, OutputRegistry};
use capture_pipelines_poc::result::{NoOutputs, StepResult, VerdictKind};

/// The async chunk stage (deliberately in the test crate, where tokio is available):
/// pretend to do a batched lookup, yielding to the runtime, then stamp each survivor.
struct BatchAnnotate;

impl<Fx> ChunkStep<Restricted<Validated<ParsedEvent>>, Fx> for BatchAnnotate {
    type Out = Restricted<Validated<ParsedEvent>>;
    type Outputs = NoOutputs;

    async fn apply_chunk(
        &self,
        events: Vec<Restricted<Validated<ParsedEvent>>>,
        _fx: &mut Fx,
    ) -> Vec<StepResult<Restricted<Validated<ParsedEvent>>, NoOutputs>> {
        tokio::task::yield_now().await;
        events
            .into_iter()
            .map(|mut e| {
                e.skip_person = true; // the "annotation"
                StepResult::Continue(e)
            })
            .collect()
    }

    fn name(&self) -> &'static str {
        "batch_annotate"
    }
}

#[derive(Debug, PartialEq)]
enum Outcome {
    Continue,
    Drop(&'static str),
    RedirectDlq,
    RedirectOverflow,
}

fn ev(token: &str, event: &str) -> ParsedEvent {
    ParsedEvent {
        token: token.to_string(),
        event: event.to_string(),
        distinct_id: Some("user-1".to_string()),
        team_id: 42,
        timestamp: 1_700_000_000_000,
    }
}

#[tokio::test]
async fn analytics_pipeline_end_to_end() {
    // Compose the sync segment with the builder. The spelled-out type is the proof
    // that composition is one flat, monomorphized struct — no boxes, no dyn. The
    // verbosity is the whole point here, so the complexity lint is silenced.
    #[allow(clippy::type_complexity)]
    let pipeline: Pipeline<
        Chain<
            Chain<Chain<Identity<ParsedEvent>, Validate>, FailOpen<ApplyQuota>>,
            ApplyRestrictions,
        >,
    > = builder::<ParsedEvent>()
        .step(Validate)
        // The builder's `.step` is intentionally unconstrained, so the generic
        // `fail_open` needs its input/effects types named here (a real assembly infers
        // them from the surrounding pipeline types).
        .step(
            FallibleStepExt::<Validated<ParsedEvent>, AnalyticsFx>::fail_open(ApplyQuota {
                failing_token: "redis_down",
            }),
        )
        .step(ApplyRestrictions {
            dlq_token: "dlq_tok",
            overflow_token: "overflow_tok",
        })
        .build();

    let registry = OutputRegistry::new(analytics_topic_for, MemProducer::new());
    assert!(registry.check().is_ok(), "every output must have a topic");

    let mut fx = AnalyticsFx::default();
    let observer = CountingObserver::new();

    let long_token = "a".repeat(41); // > 40 chars → Validate warns
    let batch = vec![
        ev("good", "$pageview"),         // 0: continue
        ev("good2", ""),                 // 1: drop invalid_event_name
        ev("dlq_tok", "$pageview"),      // 2: redirect DLQ
        ev("overflow_tok", "$pageview"), // 3: redirect overflow
        ev("redis_down", "$pageview"),   // 4: limiter errors → fail-open passthrough
        ev("good3", "quota_blocked"),    // 5: drop quota_limited
        ev(&long_token, "$pageview"),    // 6: continue + warning
    ];
    let n = batch.len();
    // Raw payloads the harness would produce on redirect (token bytes, for assertion).
    let raw: Vec<Vec<u8>> = batch.iter().map(|e| e.token.clone().into_bytes()).collect();

    // --- Sync segment ---
    let sync_verdicts = pipeline.run_chunk(batch, &mut fx);

    let mut outcomes: Vec<Option<Outcome>> = (0..n).map(|_| None).collect();
    let mut survivors = Vec::new();
    let mut survivor_idx = Vec::new();

    for (i, verdict) in sync_verdicts.into_iter().enumerate() {
        observer.on_verdict("analytics_pipeline", verdict.kind());
        match verdict {
            StepResult::Continue(event) => {
                survivor_idx.push(i);
                survivors.push(event);
            }
            StepResult::Drop { reason } | StepResult::Dlq { reason } => {
                outcomes[i] = Some(Outcome::Drop(reason));
            }
            StepResult::Redirect { output, .. } => {
                // A redirect produces the original bytes to the resolved topic.
                registry.emit(output, raw[i].clone()).unwrap();
                outcomes[i] = Some(match output {
                    AnalyticsOutputs::Dlq => Outcome::RedirectDlq,
                    AnalyticsOutputs::Overflow => Outcome::RedirectOverflow,
                });
            }
        }
    }

    // --- Async chunk stage over survivors only ---
    let annotated = run_chunk_stage(&BatchAnnotate, survivors, &mut fx).await;
    assert_eq!(annotated.len(), survivor_idx.len(), "same-length invariant");
    for (idx, result) in survivor_idx.into_iter().zip(annotated) {
        assert!(result.is_continue());
        // Annotation applied.
        assert!(result.continued().unwrap().skip_person);
        outcomes[idx] = Some(Outcome::Continue);
    }

    let outcomes: Vec<Outcome> = outcomes.into_iter().map(|o| o.unwrap()).collect();

    // Order preservation + per-event verdicts.
    assert_eq!(
        outcomes,
        vec![
            Outcome::Continue,
            Outcome::Drop("invalid_event_name"),
            Outcome::RedirectDlq,
            Outcome::RedirectOverflow,
            Outcome::Continue, // fail-open passthrough on limiter error
            Outcome::Drop("quota_limited"),
            Outcome::Continue,
        ]
    );

    // Redirects landed on the right topics, with the original payload bytes.
    assert_eq!(
        registry.producer().sent(),
        vec![
            ("events_dlq", b"dlq_tok".to_vec()),
            ("events_overflow", b"overflow_tok".to_vec()),
        ]
    );

    // Warnings were collected via the composed Fx (the long-token event).
    assert_eq!(fx.warnings.len(), 1);
    assert_eq!(fx.warnings.warnings()[0].kind, "long_token");
    assert_eq!(fx.warnings.warnings()[0].team_id, 42);

    // The observer saw one verdict per event.
    assert_eq!(observer.total(), n as u64);
    assert_eq!(observer.count(VerdictKind::Redirect), 2);
    assert_eq!(observer.count(VerdictKind::Drop), 2);
    assert_eq!(observer.count(VerdictKind::Continue), 3);
}
