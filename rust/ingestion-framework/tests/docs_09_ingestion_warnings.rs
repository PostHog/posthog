//! Mirrors `docs/09-ingestion-warnings.test.ts`.

mod common;

use std::sync::Arc;

use common::{shared, MockOutputs, TeamCtx};
use ingestion_framework::warning_handling::OutputsWarningEmitter;
use ingestion_framework::{
    chunk_step, create_ok_context, new_chunk_pipeline, ok, PipelineWarning, PromiseScheduler,
    SideEffect, SideEffectHandlingConfig, INGESTION_WARNINGS_OUTPUT,
};
use serde_json::json;

fn team() -> TeamCtx {
    TeamCtx { team_id: 2 }
}

/// it('steps can add warnings to results')
#[tokio::test]
async fn steps_can_add_warnings_to_results() {
    let pipeline = new_chunk_pipeline::<(&'static str, Option<()>), TeamCtx>()
        .pipe_chunk(chunk_step(
            "validationStep",
            |items: Vec<(&'static str, Option<()>)>| async move {
                Ok(items
                    .into_iter()
                    .map(|item| {
                        let mut r = ok(item);
                        if item.1.is_none() {
                            r = r.with_warning(PipelineWarning::new(
                                "schema_validation_failed",
                                json!({"eventName": item.0}),
                            ));
                        }
                        r
                    })
                    .collect())
            },
        ))
        .build();
    pipeline.feed(vec![create_ok_context(("pageview", None), team())]);
    let results = pipeline.next().await.unwrap().unwrap();
    assert_eq!(results.len(), 1);
    assert!(results[0].is_ok());
    assert_eq!(
        results[0].context.warnings,
        vec![PipelineWarning::new(
            "schema_validation_failed",
            json!({"eventName": "pageview"})
        )]
    );
}

/// it('warnings accumulate through the pipeline')
#[tokio::test]
async fn warnings_accumulate_through_the_pipeline() {
    let pipeline = new_chunk_pipeline::<&'static str, TeamCtx>()
        .pipe_chunk(chunk_step(
            "timestampCheckStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|n| {
                        ok(n).with_warning(PipelineWarning::new(
                            "ignored_invalid_timestamp",
                            json!({"eventName": n}),
                        ))
                    })
                    .collect())
            },
        ))
        .pipe_chunk(chunk_step(
            "propertiesCheckStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|n| {
                        ok(n).with_warning(PipelineWarning::new(
                            "schema_validation_failed",
                            json!({"eventName": n}),
                        ))
                    })
                    .collect())
            },
        ))
        .build();
    pipeline.feed(vec![create_ok_context("click", team())]);
    let results = pipeline.next().await.unwrap().unwrap();
    let types: Vec<_> = results[0]
        .context
        .warnings
        .iter()
        .map(|w| w.warning_type.as_str())
        .collect();
    assert_eq!(
        types,
        ["ignored_invalid_timestamp", "schema_validation_failed"]
    );
}

/// it('a step can add multiple warnings')
#[tokio::test]
async fn a_step_can_add_multiple_warnings() {
    struct Event {
        timestamp: &'static str,
        group_key: String,
        process_person: serde_json::Value,
    }
    let pipeline = new_chunk_pipeline::<Event, TeamCtx>()
        .pipe_chunk(chunk_step(
            "comprehensiveValidationStep",
            |items: Vec<Event>| async move {
                Ok(items
                    .into_iter()
                    .map(|item| {
                        let mut warnings = Vec::new();
                        if item.group_key.len() > 400 {
                            warnings.push(PipelineWarning::new(
                                "group_key_too_long",
                                json!({"groupKey": &item.group_key[..20], "max": 400}),
                            ));
                        }
                        if chrono::DateTime::parse_from_rfc3339(item.timestamp).is_err() {
                            warnings.push(PipelineWarning::new(
                                "ignored_invalid_timestamp",
                                json!({"value": item.timestamp}),
                            ));
                        }
                        if !item.process_person.is_null() && !item.process_person.is_boolean() {
                            warnings.push(PipelineWarning::new(
                                "invalid_process_person_profile",
                                json!({"received": "string"}),
                            ));
                        }
                        ok(item).with_warnings(warnings)
                    })
                    .collect())
            },
        ))
        .build();
    pipeline.feed(vec![create_ok_context(
        Event {
            timestamp: "not-a-date",
            group_key: "g".repeat(500),
            process_person: json!("yes"),
        },
        team(),
    )]);
    let results = pipeline.next().await.unwrap().unwrap();
    let types: Vec<_> = results[0]
        .context
        .warnings
        .iter()
        .map(|w| w.warning_type.clone())
        .collect();
    assert_eq!(types.len(), 3);
    for t in [
        "group_key_too_long",
        "ignored_invalid_timestamp",
        "invalid_process_person_profile",
    ] {
        assert!(types.contains(&t.to_string()));
    }
}

/// it('handleIngestionWarnings converts warnings to side effects')
#[tokio::test]
async fn handle_ingestion_warnings_converts_warnings_to_side_effects() {
    let outputs = MockOutputs::default();
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<&'static str, TeamCtx>()
        .pipe_chunk(chunk_step(
            "warningStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|n| {
                        ok(n).with_warning(PipelineWarning::new(
                            "client_ingestion_warning",
                            json!({"eventName": n}),
                        ))
                    })
                    .collect())
            },
        ))
        .team_aware(|b| b)
        .handle_ingestion_warnings(Arc::new(OutputsWarningEmitter {
            outputs: Arc::new(outputs.clone()),
        }))
        .handle_side_effects(
            Arc::new(scheduler),
            SideEffectHandlingConfig {
                await_side_effects: true,
            },
        )
        .build();
    pipeline.feed(vec![create_ok_context("pageview", TeamCtx { team_id: 42 })]);
    let results = pipeline.next().await.unwrap().unwrap();
    assert!(results[0].context.warnings.is_empty());
    let calls = outputs.calls();
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0].0, INGESTION_WARNINGS_OUTPUT);
    let body: serde_json::Value =
        serde_json::from_slice(calls[0].1.value.as_ref().unwrap()).unwrap();
    assert_eq!(body["team_id"], 42);
    assert_eq!(body["type"], "client_ingestion_warning");
}

/// it('handleIngestionWarnings preserves existing side effects')
#[tokio::test]
async fn handle_ingestion_warnings_preserves_existing_side_effects() {
    let outputs = MockOutputs::default();
    let log = shared(Vec::<String>::new());
    let l = log.clone();
    let pipeline = new_chunk_pipeline::<&'static str, TeamCtx>()
        .pipe_chunk(chunk_step(
            "stepWithBothSideEffectsAndWarnings",
            move |items: Vec<&'static str>| {
                let l = l.clone();
                async move {
                    Ok(items
                        .into_iter()
                        .map(|n| {
                            let l = l.clone();
                            ok(n)
                                .with_side_effect(SideEffect::spawn(async move {
                                    l.lock().unwrap().push(format!("processed: {n}"));
                                    Ok(())
                                }))
                                .with_warning(PipelineWarning::new(
                                    "client_ingestion_warning",
                                    json!({}),
                                ))
                        })
                        .collect())
                }
            },
        ))
        .team_aware(|b| b)
        .handle_ingestion_warnings(Arc::new(OutputsWarningEmitter {
            outputs: Arc::new(outputs.clone()),
        }))
        .handle_side_effects(
            Arc::new(PromiseScheduler::new()),
            SideEffectHandlingConfig {
                await_side_effects: true,
            },
        )
        .build();
    pipeline.feed(vec![create_ok_context("click", team())]);
    pipeline.next().await.unwrap();
    assert!(log
        .lock()
        .unwrap()
        .contains(&"processed: click".to_string()));
    assert_eq!(outputs.calls().len(), 1);
}

/// it('warnings can include a key for debouncing')
#[tokio::test]
async fn warnings_can_include_a_key_for_debouncing() {
    let pipeline = new_chunk_pipeline::<&'static str, TeamCtx>()
        .pipe_chunk(chunk_step(
            "userWarningStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|d| {
                        let mut w = PipelineWarning::new(
                            "cannot_merge_already_identified",
                            json!({"distinctId": d}),
                        );
                        w.key = Some(d.to_string());
                        ok(d).with_warning(w)
                    })
                    .collect())
            },
        ))
        .build();
    pipeline.feed(vec![create_ok_context("user-123", team())]);
    let results = pipeline.next().await.unwrap().unwrap();
    let w = &results[0].context.warnings[0];
    assert_eq!(w.warning_type, "cannot_merge_already_identified");
    assert_eq!(w.key.as_deref(), Some("user-123"));
    assert!(!w.always_send);
}

/// it('alwaysSend bypasses debouncing for critical warnings')
#[tokio::test]
async fn always_send_bypasses_debouncing_for_critical_warnings() {
    let pipeline = new_chunk_pipeline::<&'static str, TeamCtx>()
        .pipe_chunk(chunk_step(
            "criticalWarningStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|n| {
                        let mut w =
                            PipelineWarning::new("message_size_too_large", json!({"eventName": n}));
                        w.key = Some("quota".into());
                        w.always_send = true;
                        ok(n).with_warning(w)
                    })
                    .collect())
            },
        ))
        .build();
    pipeline.feed(vec![create_ok_context("important_event", team())]);
    let results = pipeline.next().await.unwrap().unwrap();
    let w = &results[0].context.warnings[0];
    assert_eq!(w.key.as_deref(), Some("quota"));
    assert!(w.always_send);
    assert_eq!(w.details["eventName"], "important_event");
}
