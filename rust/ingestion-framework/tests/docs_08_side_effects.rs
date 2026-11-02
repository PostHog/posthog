//! Mirrors `docs/08-side-effects.test.ts`.

mod common;

use std::sync::Arc;

use common::{items, shared, sleep_ms};
use ingestion_framework::{
    create_ok_context, new_chunk_pipeline, new_pipeline, ok, step, ChunkProcessingStep,
    PromiseScheduler, SideEffect, SideEffectHandlingConfig,
};

async fn wait_all(side_effects: Vec<SideEffect>) {
    for s in side_effects {
        s.wait().await.unwrap();
    }
}

#[tokio::test]
async fn steps_can_add_side_effects_to_context() {
    let log = shared(Vec::<String>::new());
    let l = log.clone();
    let pipeline = new_pipeline::<String, ()>()
        .pipe(step("processWithLoggingStep", move |input: String| {
            let l = l.clone();
            async move {
                let result = input.to_uppercase();
                let message = format!("Processed: {input} -> {result}");
                let effect = SideEffect::spawn(async move {
                    l.lock().unwrap().push(message);
                    Ok(())
                });
                Ok(ok((result, true)).with_side_effect(effect))
            }
        }))
        .build();
    let mut r = pipeline
        .process(create_ok_context("hello".into(), ()))
        .await
        .unwrap();
    assert!(r.is_ok());
    assert_eq!(r.context.side_effects.len(), 1);
    // The side effect started when it was created, as a Node promise does.
    assert!(log
        .lock()
        .unwrap()
        .contains(&"Processed: hello -> HELLO".to_string()));
    wait_all(std::mem::take(&mut r.context.side_effects)).await;
    assert!(log
        .lock()
        .unwrap()
        .contains(&"Processed: hello -> HELLO".to_string()));
}

#[tokio::test]
async fn side_effects_accumulate_through_the_pipeline() {
    let audit = shared(Vec::<&'static str>::new());
    let audited = |name: &'static str, f: fn(i64) -> i64| {
        let a = audit.clone();
        step(name, move |v: i64| {
            let a = a.clone();
            async move {
                let effect = SideEffect::spawn(async move {
                    a.lock().unwrap().push(match name {
                        "step1" => "step1 completed",
                        "step2" => "step2 completed",
                        _ => "step3 completed",
                    });
                    Ok(())
                });
                Ok(ok(f(v)).with_side_effect(effect))
            }
        })
    };
    let pipeline = new_pipeline::<i64, ()>()
        .pipe(audited("step1", |v| v * 2))
        .pipe(audited("step2", |v| v + 10))
        .pipe(audited("step3", |v| v * v))
        .build();
    let mut r = pipeline.process(create_ok_context(5, ())).await.unwrap();
    assert_eq!(r.context.side_effects.len(), 3);
    wait_all(std::mem::take(&mut r.context.side_effects)).await;
    let audit = audit.lock().unwrap();
    assert_eq!(audit.len(), 3);
    for expected in ["step1 completed", "step2 completed", "step3 completed"] {
        assert!(audit.contains(&expected));
    }
}

#[tokio::test]
async fn a_step_can_add_multiple_side_effects() {
    let sinks = shared((0, 0, 0));
    let s = sinks.clone();
    let pipeline = new_pipeline::<(&'static str, &'static str), ()>()
        .pipe(step(
            "processEventStep",
            move |e: (&'static str, &'static str)| {
                let (s1, s2, s3) = (s.clone(), s.clone(), s.clone());
                async move {
                    Ok(ok((e, true))
                        .with_side_effect(SideEffect::spawn(async move {
                            s1.lock().unwrap().0 += 1;
                            Ok(())
                        }))
                        .with_side_effect(SideEffect::spawn(async move {
                            s2.lock().unwrap().1 += 1;
                            Ok(())
                        }))
                        .with_side_effect(SideEffect::spawn(async move {
                            s3.lock().unwrap().2 += 1;
                            Ok(())
                        })))
                }
            },
        ))
        .build();
    let mut r = pipeline
        .process(create_ok_context(("purchase", "user-1"), ()))
        .await
        .unwrap();
    assert_eq!(r.context.side_effects.len(), 3);
    wait_all(std::mem::take(&mut r.context.side_effects)).await;
    assert_eq!(*sinks.lock().unwrap(), (1, 1, 1));
}

fn delayed_effect_step(
    completed: Arc<std::sync::Mutex<Vec<&'static str>>>,
    delay: u64,
) -> ChunkProcessingStep<&'static str, &'static str> {
    ChunkProcessingStep::per_item(step("processStep", move |id: &'static str| {
        let completed = completed.clone();
        async move {
            let effect = SideEffect::spawn(async move {
                sleep_ms(delay).await;
                completed.lock().unwrap().push(id);
                Ok(())
            });
            Ok(ok(id).with_side_effect(effect))
        }
    }))
}

#[tokio::test(start_paused = true)]
async fn handle_side_effects_with_await_true_blocks_until_completion() {
    let completed = shared(Vec::new());
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<&'static str, ()>()
        .pipe_chunk(delayed_effect_step(completed.clone(), 10))
        .handle_side_effects(
            Arc::new(scheduler),
            SideEffectHandlingConfig {
                await_side_effects: true,
            },
        )
        .build();
    pipeline.feed(items(["a", "b", "c"]));
    pipeline.next().await.unwrap();
    let mut done = completed.lock().unwrap().clone();
    done.sort();
    assert_eq!(done, ["a", "b", "c"]);
}

#[tokio::test(start_paused = true)]
async fn handle_side_effects_with_await_false_schedules_for_background_execution() {
    let completed = shared(Vec::new());
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<&'static str, ()>()
        .pipe_chunk(delayed_effect_step(completed.clone(), 50))
        .handle_side_effects(
            Arc::new(scheduler.clone()),
            SideEffectHandlingConfig {
                await_side_effects: false,
            },
        )
        .build();
    pipeline.feed(items(["x", "y"]));
    pipeline.next().await.unwrap();
    assert!(completed.lock().unwrap().is_empty());
    scheduler.wait_for_all().await.unwrap();
    let mut done = completed.lock().unwrap().clone();
    done.sort();
    assert_eq!(done, ["x", "y"]);
}
