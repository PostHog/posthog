mod common;

use common::{items, shared};
use ingestion_framework::{
    new_batching_pipeline, ok, step, AfterBatchInput, BatchingPipelineOptions, BeforeBatchInput,
    BeforeBatchOutput, FeedRejectionKind, FeedResult,
};

fn unbounded() -> BatchingPipelineOptions {
    BatchingPipelineOptions {
        concurrent_batches: usize::MAX,
    }
}

fn passthrough_before<CB: Send + 'static>(
    name: &str,
    make: impl Fn(u64) -> CB + Send + Sync + 'static,
) -> ingestion_framework::ProcessingStep<BeforeBatchInput<i64, ()>, BeforeBatchOutput<i64, (), CB>>
{
    ingestion_framework::before_batch_step(name, make)
}

#[tokio::test]
async fn each_feed_forms_one_batch_with_sequential_batch_id_and_message_id_tagging() {
    let before_ids = shared(Vec::<u64>::new());
    let after_ids = shared(Vec::<u64>::new());
    let (b, a) = (before_ids.clone(), after_ids.clone());
    let pipeline = new_batching_pipeline::<i64, _, (), (), u64, ()>(
        move |builder| {
            builder.pipe(step(
                "recordingBefore",
                move |input: BeforeBatchInput<i64, ()>| {
                    b.lock().unwrap().push(input.batch_id);
                    async move {
                        Ok(ok(BeforeBatchOutput {
                            batch_context: input.batch_id,
                            elements: input.elements,
                            batch_id: input.batch_id,
                        }))
                    }
                },
            ))
        },
        |builder| builder,
        move |builder| {
            builder.pipe(step(
                "recordingAfter",
                move |input: AfterBatchInput<_, (), u64>| {
                    a.lock().unwrap().push(input.batch_id);
                    async move { Ok(ok(input)) }
                },
            ))
        },
        unbounded(),
    );
    pipeline.feed(items([10, 20]), (), None).await.unwrap();
    pipeline.feed(items([30]), (), None).await.unwrap();
    let mut message_ids = Vec::new();
    while let Some(batch) = pipeline.next().await.unwrap() {
        for element in batch.elements {
            message_ids.push(element.context.message_id.unwrap());
        }
    }
    assert_eq!(*before_ids.lock().unwrap(), vec![0, 1]);
    assert_eq!(*after_ids.lock().unwrap(), vec![0, 1]);
    assert_eq!(message_ids, vec![0, 1, 2]);
}

#[tokio::test]
async fn batch_context_flows_from_before_batch_to_after_batch() {
    let seen = shared(None::<String>);
    let s = seen.clone();
    let pipeline = new_batching_pipeline::<i64, _, (), (), String, ()>(
        |builder| {
            builder.pipe(passthrough_before("attachStore", |id| {
                format!("store-{id}")
            }))
        },
        |builder| builder,
        move |builder| {
            builder.pipe(step(
                "readStore",
                move |input: AfterBatchInput<_, (), String>| {
                    *s.lock().unwrap() = Some((*input.batch_context).clone());
                    async move { Ok(ok(input)) }
                },
            ))
        },
        unbounded(),
    );
    pipeline.feed(items([1]), (), None).await.unwrap();
    pipeline.next().await.unwrap();
    assert_eq!(seen.lock().unwrap().as_deref(), Some("store-0"));
}

fn simple_pipeline(
    concurrent_batches: usize,
    before_ran: Option<std::sync::Arc<std::sync::Mutex<bool>>>,
) -> ingestion_framework::BatchingPipeline<
    i64,
    ingestion_framework::WithBatch<i64, ()>,
    (),
    (),
    (),
    (),
> {
    new_batching_pipeline(
        move |builder| {
            builder.pipe(step(
                "recordingBefore",
                move |input: BeforeBatchInput<i64, ()>| {
                    if let Some(r) = &before_ran {
                        *r.lock().unwrap() = true;
                    }
                    async move {
                        Ok(ok(BeforeBatchOutput {
                            batch_context: (),
                            elements: input.elements,
                            batch_id: input.batch_id,
                        }))
                    }
                },
            ))
        },
        |builder| builder,
        |builder| {
            builder.pipe(ingestion_framework::passthrough_after_batch_step(
                "passThroughAfter",
            ))
        },
        BatchingPipelineOptions { concurrent_batches },
    )
}

#[tokio::test]
async fn feed_reports_at_capacity_backpressure_when_concurrent_batches_is_exceeded() {
    let pipeline = simple_pipeline(1, None);
    assert_eq!(
        pipeline.feed(items([1]), (), None).await.unwrap(),
        FeedResult::Ok
    );
    match pipeline.feed(items([2]), (), None).await.unwrap() {
        FeedResult::Rejected { kind, .. } => assert_eq!(kind, FeedRejectionKind::AtCapacity),
        other => panic!("expected rejection, got {other:?}"),
    }
    let drained = pipeline.next().await.unwrap().unwrap();
    assert!(drained.elements.iter().all(|e| e.is_ok()));
    assert_eq!(
        pipeline.feed(items([3]), (), None).await.unwrap(),
        FeedResult::Ok
    );
}

#[tokio::test]
async fn an_empty_feed_is_a_no_op_that_runs_no_hooks_and_consumes_no_capacity() {
    let ran = shared(false);
    let pipeline = simple_pipeline(1, Some(ran.clone()));
    assert_eq!(
        pipeline.feed(vec![], (), None).await.unwrap(),
        FeedResult::Ok
    );
    assert!(!*ran.lock().unwrap());
    assert!(pipeline.next().await.unwrap().is_none());
    assert_eq!(
        pipeline.feed(items([1]), (), None).await.unwrap(),
        FeedResult::Ok
    );
    assert!(pipeline.next().await.unwrap().is_some());
}

#[tokio::test]
async fn a_before_batch_that_changes_the_element_count_throws() {
    let pipeline = new_batching_pipeline::<i64, _, (), (), (), ()>(
        |builder| {
            builder.pipe(step(
                "filteringBefore",
                |input: BeforeBatchInput<i64, ()>| async move {
                    let mut elements = input.elements;
                    elements.remove(0);
                    Ok(ok(BeforeBatchOutput {
                        batch_context: (),
                        elements,
                        batch_id: input.batch_id,
                    }))
                },
            ))
        },
        |builder| builder,
        |builder| {
            builder.pipe(ingestion_framework::passthrough_after_batch_step(
                "passThroughAfter",
            ))
        },
        BatchingPipelineOptions {
            concurrent_batches: 1,
        },
    );
    let err = pipeline.feed(items([1, 2]), (), None).await.unwrap_err();
    assert!(
        err.to_string().contains("changed element count (2 -> 1)"),
        "{err}"
    );
}
