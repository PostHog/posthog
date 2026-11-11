mod common;

use std::sync::Arc;
use std::time::Duration;

use common::{test_message, MockOutputs, MsgCtx};
use ingestion_framework::{
    chunk_step, create_ok_context, dlq, drop, new_chunk_pipeline, ok, redirect, redirect_with,
    PipelineConfig, PipelineResultType, PromiseScheduler, SideEffectHandlingConfig, DLQ_OUTPUT,
};

fn config(outputs: &MockOutputs, scheduler: &PromiseScheduler) -> PipelineConfig {
    PipelineConfig {
        outputs: Arc::new(outputs.clone()),
        scheduler: Arc::new(scheduler.clone()),
        reject_on_dlq_failure: false,
    }
}

const AWAIT: SideEffectHandlingConfig = SideEffectHandlingConfig {
    await_side_effects: true,
};

#[tokio::test]
async fn dlq_sends_failed_items_to_dead_letter_topic_with_error_details() {
    let outputs = MockOutputs::default();
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<&'static str, MsgCtx>()
        .pipe_chunk(chunk_step(
            "validationStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|d| {
                        if d == "invalid" {
                            dlq(
                                "Validation failed",
                                Some(anyhow::anyhow!("Invalid data format")),
                            )
                        } else {
                            ok(d)
                        }
                    })
                    .collect())
            },
        ))
        .message_aware(|b| b)
        .handle_results(config(&outputs, &scheduler))
        .handle_side_effects(Arc::new(scheduler.clone()), AWAIT)
        .build();
    let message = test_message(None);
    pipeline.feed(vec![create_ok_context(
        "invalid",
        MsgCtx {
            message: message.clone(),
        },
    )]);
    let results = pipeline.next().await.unwrap().unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].result.result_type(), PipelineResultType::Dlq);
    let calls = outputs.calls();
    assert_eq!(calls.len(), 1);
    let (output, produced) = &calls[0];
    assert_eq!(output, DLQ_OUTPUT);
    assert_eq!(produced.value, message.value);
    assert_eq!(produced.key, message.key);
    assert_eq!(
        produced.headers.get("dlq_reason"),
        Some("Invalid data format")
    );
    assert_eq!(produced.headers.get("dlq_step"), Some("validationStep"));
    assert!(produced.headers.get("dlq_timestamp").is_some());
}

#[tokio::test]
async fn drop_discards_items_without_sending_to_kafka() {
    let outputs = MockOutputs::default();
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<&'static str, MsgCtx>()
        .pipe_chunk(chunk_step(
            "filterStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|t| {
                        if t.starts_with("internal-") {
                            drop("Internal event filtered")
                        } else {
                            ok(t)
                        }
                    })
                    .collect())
            },
        ))
        .message_aware(|b| b)
        .handle_results(config(&outputs, &scheduler))
        .handle_side_effects(Arc::new(scheduler.clone()), AWAIT)
        .build();
    pipeline.feed(vec![create_ok_context(
        "internal-heartbeat",
        MsgCtx {
            message: test_message(None),
        },
    )]);
    let results = pipeline.next().await.unwrap().unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].result.result_type(), PipelineResultType::Drop);
    assert!(outputs.calls().is_empty());
}

#[tokio::test]
async fn redirect_sends_items_to_a_named_output_with_optional_key_preservation() {
    let outputs = MockOutputs::default();
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<&'static str, MsgCtx>()
        .pipe_chunk(chunk_step(
            "routingStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|p| match p {
                        "high" => {
                            redirect_with("High priority routing", "high_priority", true, true)
                        }
                        "broadcast" => redirect_with("Broadcast routing", "broadcast", false, true),
                        _ => ok(p),
                    })
                    .collect())
            },
        ))
        .message_aware(|b| b)
        .handle_results(config(&outputs, &scheduler))
        .handle_side_effects(Arc::new(scheduler.clone()), AWAIT)
        .build();
    let message1 = test_message(Some(b"my-partition-key"));
    let message2 = test_message(Some(b"another-key"));
    pipeline.feed(vec![
        create_ok_context(
            "high",
            MsgCtx {
                message: message1.clone(),
            },
        ),
        create_ok_context(
            "broadcast",
            MsgCtx {
                message: message2.clone(),
            },
        ),
    ]);
    let results = pipeline.next().await.unwrap().unwrap();
    assert_eq!(results.len(), 2);
    assert!(results
        .iter()
        .all(|r| r.result.result_type() == PipelineResultType::Redirect));

    // Node produces in item order, so the call order is the feed order.
    let calls = outputs.calls();
    assert_eq!(calls.len(), 2);
    let (high_out, high) = &calls[0];
    let (broadcast_out, broadcast) = &calls[1];
    assert_eq!(high_out, "high_priority");
    assert_eq!(high.value, message1.value);
    assert_eq!(high.key.as_deref(), Some(&b"my-partition-key"[..]));
    assert_eq!(high.headers.get("redirect-step"), Some("routingStep"));
    assert!(high.headers.get("redirect-timestamp").is_some());
    assert_eq!(broadcast_out, "broadcast");
    assert_eq!(broadcast.value, message2.value);
    assert_eq!(broadcast.key, None);
    assert_eq!(broadcast.headers.get("redirect-step"), Some("routingStep"));
    assert!(broadcast.headers.get("redirect-timestamp").is_some());
}

#[tokio::test]
async fn redirect_with_await_ack_true_blocks_on_the_produce_ack() {
    let outputs = MockOutputs::default();
    outputs.close_gate();
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<&'static str, MsgCtx>()
        .pipe_chunk(chunk_step(
            "routingStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|_| redirect::<&str>("Overflow", "overflow"))
                    .collect())
            },
        ))
        .message_aware(|b| b)
        .handle_results(config(&outputs, &scheduler))
        .handle_side_effects(Arc::new(scheduler.clone()), AWAIT)
        .build();
    pipeline.feed(vec![create_ok_context(
        "x",
        MsgCtx {
            message: test_message(None),
        },
    )]);
    let mut next = Box::pin(pipeline.next());
    assert!(tokio::time::timeout(Duration::from_millis(50), &mut next)
        .await
        .is_err());
    outputs.open_gate();
    let results = next.await.unwrap().unwrap();
    assert_eq!(
        results[0].result.result_type(),
        PipelineResultType::Redirect
    );
}

#[tokio::test]
async fn redirect_with_await_ack_false_does_not_block_on_the_produce_ack() {
    let outputs = MockOutputs::default();
    outputs.close_gate();
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<&'static str, MsgCtx>()
        .pipe_chunk(chunk_step(
            "routingStep",
            |items: Vec<&'static str>| async move {
                Ok(items
                    .into_iter()
                    .map(|_| redirect_with::<&str>("Overflow", "overflow", true, false))
                    .collect())
            },
        ))
        .message_aware(|b| b)
        .handle_results(config(&outputs, &scheduler))
        .handle_side_effects(Arc::new(scheduler.clone()), AWAIT)
        .build();
    pipeline.feed(vec![create_ok_context(
        "x",
        MsgCtx {
            message: test_message(None),
        },
    )]);
    let results = pipeline.next().await.unwrap().unwrap();
    assert_eq!(
        results[0].result.result_type(),
        PipelineResultType::Redirect
    );
    assert_eq!(outputs.calls().len(), 1);
}
