//! Mirrors `docs/01-introduction.test.ts`.

mod common;

use std::sync::Arc;

use common::{items, shared};
use ingestion_framework::{
    chunk_step, create_ok_context, dlq, drop, new_chunk_pipeline, new_pipeline, ok, redirect, step,
    PipelineResultType, ProcessingStep,
};

#[tokio::test]
async fn steps_use_the_factory_pattern_for_dependency_injection_and_naming() {
    fn create_uppercase_step() -> ProcessingStep<String, String> {
        step("uppercaseStep", |input: String| async move {
            Ok(ok(input.to_uppercase()))
        })
    }
    struct MultiplierConfig {
        factor: i64,
    }
    fn create_multiply_step(config: MultiplierConfig) -> ProcessingStep<i64, i64> {
        step("multiplyStep", move |input: i64| async move {
            Ok(ok(input * config.factor))
        })
    }

    let string_pipeline = new_pipeline::<String, ()>()
        .pipe(create_uppercase_step())
        .build();
    let number_pipeline = new_pipeline::<i64, ()>()
        .pipe(create_multiply_step(MultiplierConfig { factor: 3 }))
        .build();

    let r = string_pipeline
        .process(create_ok_context("hello".into(), ()))
        .await
        .unwrap();
    assert_eq!(r.value().map(String::as_str), Some("HELLO"));
    let r = number_pipeline
        .process(create_ok_context(5, ()))
        .await
        .unwrap();
    assert_eq!(r.value(), Some(&15));
}

#[tokio::test]
async fn steps_accumulate_data_through_the_pipeline() {
    #[derive(Clone)]
    struct Input {
        event_id: String,
    }
    struct Validated {
        event_id: String,
        is_valid: bool,
    }
    struct Enriched {
        event_id: String,
        is_valid: bool,
        timestamp: i64,
    }
    let pipeline = new_pipeline::<Input, ()>()
        .pipe(step("validateStep", |i: Input| async move {
            Ok(ok(Validated {
                event_id: i.event_id,
                is_valid: true,
            }))
        }))
        .pipe(step("enrichStep", |i: Validated| async move {
            Ok(ok(Enriched {
                event_id: i.event_id,
                is_valid: i.is_valid,
                timestamp: chrono::Utc::now().timestamp_millis(),
            }))
        }))
        .pipe(step("finalizeStep", |i: Enriched| async move {
            Ok(ok(format!(
                "Event {} valid={} at {}",
                i.event_id, i.is_valid, i.timestamp
            )))
        }))
        .build();

    let r = pipeline
        .process(create_ok_context(
            Input {
                event_id: "evt-123".into(),
            },
            (),
        ))
        .await
        .unwrap();
    let summary = r.value().unwrap();
    assert!(summary.contains("evt-123"));
    assert!(summary.contains("valid=true"));
}

#[tokio::test]
async fn a_step_can_return_ok_to_pass_data_forward() {
    let pipeline = new_pipeline::<String, ()>()
        .pipe(step("processDataStep", |i: String| async move {
            Ok(ok(i.to_uppercase()))
        }))
        .build();
    let r = pipeline
        .process(create_ok_context("hello".into(), ()))
        .await
        .unwrap();
    assert_eq!(r.value().unwrap(), "HELLO");
}

#[tokio::test]
async fn a_pipeline_transforms_input_through_a_sequence_of_steps() {
    let pipeline = new_pipeline::<String, ()>()
        .pipe(step("uppercaseStep", |i: String| async move {
            Ok(ok(i.to_uppercase()))
        }))
        .pipe(step("addExclamationStep", |i: String| async move {
            Ok(ok(i + "!"))
        }))
        .build();
    let r = pipeline
        .process(create_ok_context("hello".into(), ()))
        .await
        .unwrap();
    assert_eq!(r.value().unwrap(), "HELLO!");
}

#[tokio::test]
async fn a_step_can_return_dlq_to_signal_an_error() {
    let pipeline = new_pipeline::<i64, ()>()
        .pipe(step("validateDataStep", |v: i64| async move {
            if v < 0 {
                return Ok(dlq(
                    "Invalid value: must be non-negative",
                    Some(anyhow::anyhow!("Validation failed")),
                ));
            }
            Ok(ok(v))
        }))
        .build();
    let r = pipeline.process(create_ok_context(-1, ())).await.unwrap();
    assert_eq!(r.result.result_type(), PipelineResultType::Dlq);
    assert_eq!(r.result.result_type() as i32, 1);
}

#[tokio::test]
async fn a_step_can_return_drop_to_silently_discard_an_item() {
    let pipeline = new_pipeline::<&'static str, ()>()
        .pipe(step("filterInternalStep", |t: &'static str| async move {
            if t == "internal" {
                return Ok(drop("Internal events are not processed"));
            }
            Ok(ok(t))
        }))
        .build();
    let r = pipeline
        .process(create_ok_context("internal", ()))
        .await
        .unwrap();
    assert_eq!(r.result.result_type() as i32, 2);
}

#[tokio::test]
async fn a_step_can_return_redirect_to_send_an_item_elsewhere() {
    let pipeline = new_pipeline::<&'static str, ()>()
        .pipe(step("routeByPriorityStep", |p: &'static str| async move {
            if p == "high" {
                return Ok(redirect("High priority event", "high_priority"));
            }
            Ok(ok(p))
        }))
        .build();
    let r = pipeline
        .process(create_ok_context("high", ()))
        .await
        .unwrap();
    assert_eq!(r.result.result_type() as i32, 3);
}

#[tokio::test]
async fn non_ok_results_short_circuit_the_pipeline_ok_results_propagate() {
    let pipeline = new_pipeline::<&'static str, ()>()
        .pipe(step("decisionStep", |action: &'static str| async move {
            Ok(match action {
                "dlq" => dlq("Error condition", None),
                "drop" => drop("Filtered out"),
                "redirect" => redirect("Redirecting", "other"),
                _ => ok(action),
            })
        }))
        .pipe(step("processStep", |action: &'static str| async move {
            if action != "ok" {
                anyhow::bail!("Unexpected action: {action}");
            }
            Ok(ok((action, true)))
        }))
        .build();

    let r = pipeline.process(create_ok_context("ok", ())).await.unwrap();
    assert!(r.is_ok());
    assert_eq!(r.context.last_step(), Some("processStep"));
    for (action, expected) in [("dlq", 1), ("drop", 2), ("redirect", 3)] {
        let r = pipeline
            .process(create_ok_context(action, ()))
            .await
            .unwrap();
        assert_eq!(r.result.result_type() as i32, expected);
        assert_eq!(r.context.last_step(), Some("decisionStep"));
    }
}

#[tokio::test]
async fn chunk_pipelines_are_created_using_new_chunk_pipeline_builder() {
    let pipeline = new_chunk_pipeline::<String, ()>()
        .pipe_chunk(chunk_step(
            "uppercaseChunkStep",
            |items: Vec<String>| async move {
                Ok(items.into_iter().map(|s| ok(s.to_uppercase())).collect())
            },
        ))
        .build();
    pipeline.feed(items(["a", "b", "c"].map(String::from)));
    let results = pipeline.next().await.unwrap().unwrap();
    let values: Vec<_> = results.iter().map(|r| r.value().unwrap().clone()).collect();
    assert_eq!(values, ["A", "B", "C"]);
}

#[tokio::test]
async fn pipe_chunk_processes_all_items_in_a_single_call() {
    let call_counts = shared(Vec::<usize>::new());
    let counts = call_counts.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step("chunkEnrichStep", move |items: Vec<i64>| {
            counts.lock().unwrap().push(items.len());
            async move { Ok(items.into_iter().map(|n| ok(n * 10)).collect()) }
        }))
        .build();
    pipeline.feed(items([1, 2, 3, 4, 5]));
    pipeline.next().await.unwrap();
    assert_eq!(*call_counts.lock().unwrap(), vec![5]);
}

#[tokio::test]
async fn feed_accepts_a_batch_and_next_returns_processed_chunks() {
    let pipeline = new_chunk_pipeline::<&'static str, ()>()
        .pipe_chunk(chunk_step(
            "passthroughStep",
            |items: Vec<&'static str>| async move { Ok(items.into_iter().map(ok).collect()) },
        ))
        .build();
    pipeline.feed(items(["x", "y"]));
    assert_eq!(pipeline.next().await.unwrap().unwrap().len(), 2);
    assert!(pipeline.next().await.unwrap().is_none());
    let _ = Arc::new(());
}
