//! End-to-end demo: the analytics pipeline composed as one fluent builder chain — a
//! heatmap `Branching` split in the sync segment, then a grouped async stage
//! (`concurrently_per_group` on `token:distinct_id`) and a per-item async stage
//! (`concurrently`), all part of the *composition* (`build_analytics_pipeline`). The
//! test invokes `pipeline.run_batch(..)` and then `handle_results(..)` — no stage wiring
//! outside the built pipeline.

use capture_pipelines_poc::events::capabilities::{HasGeo, HasToken};
use capture_pipelines_poc::events::parsed::ParsedEvent;
use capture_pipelines_poc::pipeline::{
    analytics_topic_for, build_analytics_pipeline, handle_results, AnalyticsFx, AnalyticsOutputs,
    GeoAnnotate, OverflowCheck, Verdict,
};
use capture_pipelines_poc::steps::enrich::Enrich;
use capture_pipelines_poc::steps::restrictions::ApplyRestrictions;
use capture_pipelines_poc::steps::validate::Validate;
use capture_pipelines_poc::{builder, MemProducer, OutputRegistry, StepResult};

fn ev(token: &str, distinct_id: &str, event: &str) -> ParsedEvent {
    ParsedEvent {
        token: token.to_string(),
        event: event.to_string(),
        distinct_id: Some(distinct_id.to_string()),
        team_id: 42,
        timestamp: 1_700_000_000_000,
    }
}

#[tokio::test]
async fn analytics_pipeline_end_to_end() {
    // Construct the two async stage processors and grab shared probe handles *before*
    // moving them into the composition, so we can observe concurrency afterward.
    let overflow = OverflowCheck::new();
    let overflow_probe = overflow.probe();
    let geo = GeoAnnotate::new();
    let geo_probe = geo.probe();

    // One fluent composition — sync steps, Branching, and both async stages — as one
    // flat monomorphized type (`AnalyticsPipeline`; the boxless proof is the ZST
    // `composed_pipeline_with_async_stage_is_a_flat_struct` test in `framework::batch`).
    let pipeline = build_analytics_pipeline(overflow, geo);

    let registry = OutputRegistry::new(analytics_topic_for, MemProducer::new());
    assert!(registry.check().is_ok());

    let mut fx = AnalyticsFx::default();

    let long_token = "a".repeat(41); // > 40 chars → Validate warns
    let batch = vec![
        ev("A", "u1", "e1"),                   // 0: continue (group A:u1)
        ev("B", "u1", "e1"),                   // 1: continue (group B:u1)
        ev("A", "u1", "e2"),                   // 2: continue (group A:u1, after e1)
        ev("dlq_tok", "u1", "$pageview"),      // 3: standard branch → redirect DLQ
        ev("dlq_tok", "u2", "$$heatmap"),      // 4: HEATMAP branch skips restrictions → continue
        ev("C", "u1", "e1"),                   // 5: continue (group C:u1)
        ev("A", "u1", "e3"),                   // 6: continue (group A:u1, after e2)
        ev("good", "u9", ""),                  // 7: drop invalid_event_name
        ev(&long_token, "u1", "$pageview"),    // 8: continue + warning
        ev("overflow_tok", "u1", "$pageview"), // 9: standard branch → redirect overflow
        ev("redis_down", "u1", "$pageview"),   // 10: quota errors → fail-open passthrough
    ];
    let raw: Vec<Vec<u8>> = batch.iter().map(|e| e.token.clone().into_bytes()).collect();

    // Run the whole composed pipeline (sync + both async stages) over the batch, then
    // handle results (produce redirects, map to outcomes) — no stage wiring here.
    let final_verdicts = pipeline.run_batch(batch, &mut fx).await;
    let verdicts = handle_results(final_verdicts, &raw, &registry);

    // Positional per-event verdicts, incl. the heatmap-branch split and fail-open.
    assert_eq!(
        verdicts,
        vec![
            Verdict::Continue,
            Verdict::Continue,
            Verdict::Continue,
            Verdict::Redirect(AnalyticsOutputs::Dlq),
            Verdict::Continue, // $$heatmap on a DLQ token — branch skipped restrictions
            Verdict::Continue,
            Verdict::Continue,
            Verdict::Drop("invalid_event_name"),
            Verdict::Continue,
            Verdict::Redirect(AnalyticsOutputs::Overflow),
            Verdict::Continue, // fail-open passthrough on limiter error
        ]
    );

    // Branch routing is real: the same DLQ token redirects on `$pageview` (idx 3) but
    // passes through on `$$heatmap` (idx 4).
    assert_eq!(verdicts[3], Verdict::Redirect(AnalyticsOutputs::Dlq));
    assert_eq!(verdicts[4], Verdict::Continue);

    // In-group ordering preserved through the grouped async stage: A:u1's events stay
    // e1 → e2 → e3 despite groups running concurrently.
    assert_eq!(overflow_probe.order_for("A:u1"), vec!["e1", "e2", "e3"]);

    // Cross-group concurrency actually happened: all 6 survivor groups overlapped in the
    // grouped stage, and all 8 survivors overlapped in the per-item concurrent stage.
    assert_eq!(overflow_probe.max_in_flight(), 6);
    assert_eq!(geo_probe.max_in_flight(), 8);

    // Redirects produced to the right topics with the original payload bytes.
    assert_eq!(
        registry.producer().sent(),
        vec![
            ("events_dlq", b"dlq_tok".to_vec()),
            ("events_overflow", b"overflow_tok".to_vec()),
        ]
    );

    // Warning collected via the composed Fx (the long-token event).
    assert_eq!(fx.warnings.len(), 1);
    assert_eq!(fx.warnings.warnings()[0].kind, "long_token");
}

/// Open-extension proof. `Enrich` is inserted *before* `Validate`, wrapping every event
/// in `WithGeo` and adding a brand-new capability (`HasGeo`). `Validate` and
/// `ApplyRestrictions` are the exact, unmodified crate steps — yet the pipeline still
/// compiles and runs, because those steps bound only the capabilities they read and
/// `WithGeo` forwards them. The enrichment survives to the end.
#[test]
fn open_extension_upstream_enrichment_needs_no_downstream_changes() {
    let pipeline = builder::<ParsedEvent>()
        .step(Enrich { geo: "US" })
        .step(Validate)
        .step(ApplyRestrictions {
            dlq_token: "dlq_tok",
            overflow_token: "overflow_tok",
        })
        .build();

    let mut fx = AnalyticsFx::default();
    let verdict = pipeline.run_one(ev("good", "u1", "$pageview"), &mut fx);

    let survivor = match verdict {
        StepResult::Continue(s) => s,
        _ => panic!("expected the event to pass through"),
    };
    // Geo, added upstream by Enrich, is readable through two phase wrappers via the
    // forwarded `HasGeo` capability — no downstream step was changed to carry it.
    assert_eq!(survivor.geo(), "US");
    assert_eq!(survivor.token(), "good");
}
