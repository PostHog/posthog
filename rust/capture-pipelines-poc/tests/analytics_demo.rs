//! End-to-end demo: a mini analytics pipeline wired from the framework, exercising
//! every verdict path, fail-open passthrough, warnings, the output registry, and an
//! async chunk stage — all with static dispatch. Also holds the open-extension
//! regression test proving a step's input is open to upstream enrichment.

use capture_pipelines_poc::events::capabilities::{HasGeo, HasToken};
use capture_pipelines_poc::events::parsed::ParsedEvent;
use capture_pipelines_poc::pipeline::{
    analytics_topic_for, build_analytics_pipeline, AnalyticsFx, AnalyticsOutputs,
};
use capture_pipelines_poc::steps::annotate::BatchAnnotate;
use capture_pipelines_poc::steps::enrich::Enrich;
use capture_pipelines_poc::steps::quota::ApplyQuota;
use capture_pipelines_poc::steps::restrictions::ApplyRestrictions;
use capture_pipelines_poc::steps::validate::Validate;
use capture_pipelines_poc::{
    builder, run_chunk_stage, CountingObserver, FailOpen, MemProducer, Observer, OutputRegistry,
    StepResult, VerdictKind,
};

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
    // The composed sync pipeline. Its type — `AnalyticsPipeline` — is a spelled-out
    // `Chain<Chain<…>>` (see `pipeline::AnalyticsPipeline`), the static-dispatch proof.
    // Its size is exactly the sum of its steps' own sizes (the ZST steps add nothing,
    // only the config-carrying ones do) — no box indirection anywhere.
    let pipeline = build_analytics_pipeline("redis_down", "dlq_tok", "overflow_tok");
    let flat_size =
        std::mem::size_of::<FailOpen<ApplyQuota>>() + std::mem::size_of::<ApplyRestrictions>();
    assert_eq!(
        std::mem::size_of_val(&pipeline),
        flat_size,
        "flat struct: size is the sum of its steps, no boxes",
    );

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

/// Open-extension proof. `Enrich` is inserted *before* `Validate`, wrapping every
/// event in `WithGeo` and adding a brand-new capability (`HasGeo`). Crucially,
/// `Validate` and `ApplyRestrictions` are the exact, unmodified crate steps — yet the
/// pipeline still compiles and runs, because those steps bound only the capabilities
/// they read and `WithGeo` forwards them. The enrichment data survives through the
/// `Restricted<Validated<WithGeo<ParsedEvent>>>` wrapper stack and is still readable
/// via the `HasGeo` capability downstream.
#[test]
fn open_extension_upstream_enrichment_needs_no_downstream_changes() {
    // Enrich -> Validate -> ApplyRestrictions, all reused unchanged.
    let pipeline = builder::<ParsedEvent>()
        .step(Enrich { geo: "US" })
        .step(Validate)
        .step(ApplyRestrictions {
            dlq_token: "dlq_tok",
            overflow_token: "overflow_tok",
        })
        .build();

    let mut fx = AnalyticsFx::default();
    let verdict = pipeline.run_one(ev("good", "$pageview"), &mut fx);

    let survivor = match verdict {
        StepResult::Continue(s) => s,
        _ => panic!("expected the event to pass through"),
    };
    // Geo, added upstream by Enrich, is readable through two phase wrappers via the
    // forwarded `HasGeo` capability — no downstream step was changed to carry it.
    assert_eq!(survivor.geo(), "US");
    // The original token is still readable via the forwarded `HasToken` capability.
    assert_eq!(survivor.token(), "good");
}
