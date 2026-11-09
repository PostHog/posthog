mod common;

use common::{collect_chunks, items, shared};
use ingestion_framework::{chunk_step, dlq, new_chunk_pipeline, ok, step};

#[tokio::test]
async fn chunk_pipelines_process_multiple_items_at_once() {
    let calls = shared(0);
    let c = calls.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step("chunkDoubleStep", move |items: Vec<i64>| {
            *c.lock().unwrap() += 1;
            async move { Ok(items.into_iter().map(|n| ok(n * 2)).collect()) }
        }))
        .build();
    pipeline.feed(items([1, 2, 3, 4, 5]));
    let results = pipeline.next().await.unwrap().unwrap();
    assert_eq!(*calls.lock().unwrap(), 1);
    let v: Vec<_> = results.iter().map(|r| *r.value().unwrap()).collect();
    assert_eq!(v, [2, 4, 6, 8, 10]);
}

#[tokio::test]
async fn feed_accepts_items_and_next_returns_results_then_null() {
    let pipeline = new_chunk_pipeline::<String, ()>()
        .pipe_chunk(chunk_step(
            "uppercaseStep",
            |items: Vec<String>| async move {
                Ok(items.into_iter().map(|s| ok(s.to_uppercase())).collect())
            },
        ))
        .build();
    pipeline.feed(items(["a", "b", "c"].map(String::from)));
    let v: Vec<_> = pipeline
        .next()
        .await
        .unwrap()
        .unwrap()
        .into_iter()
        .map(|r| r.result.into_value().unwrap())
        .collect();
    assert_eq!(v, ["A", "B", "C"]);
    assert!(pipeline.next().await.unwrap().is_none());
}

#[tokio::test]
async fn chunk_steps_must_return_same_number_of_results_as_inputs() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step("validChunkStep", |items: Vec<i64>| async move {
            Ok(items.into_iter().map(|n| ok(n * 2)).collect())
        }))
        .build();
    pipeline.feed(items([1, 2, 3]));
    assert_eq!(pipeline.next().await.unwrap().unwrap().len(), 3);
}

#[tokio::test]
async fn mismatched_result_count_throws_an_error() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step("badChunkStep", |items: Vec<i64>| async move {
            Ok(vec![ok(items[0])])
        }))
        .build();
    pipeline.feed(items([1, 2, 3]));
    let err = pipeline.next().await.unwrap_err();
    assert!(
        err.to_string()
            .contains("different number of results than input values"),
        "{err}"
    );
}

#[tokio::test]
async fn chunk_steps_receive_only_ok_items_from_previous_steps() {
    let received = shared(Vec::<i64>::new());
    let r = received.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step("filterStep", |items: Vec<i64>| async move {
            Ok(items
                .into_iter()
                .map(|n| {
                    if n > 3 {
                        dlq(format!("Number {n} is too large"), None)
                    } else {
                        ok(n)
                    }
                })
                .collect())
        }))
        .pipe_chunk(chunk_step("processStep", move |items: Vec<i64>| {
            r.lock().unwrap().extend(items.iter().copied());
            async move { Ok(items.into_iter().map(|n| ok(n * 10)).collect()) }
        }))
        .build();
    pipeline.feed(items([1, 2, 3, 4, 5]));
    pipeline.next().await.unwrap();
    assert_eq!(*received.lock().unwrap(), vec![1, 2, 3]);
}

#[tokio::test]
async fn two_batches_emerge_as_a_single_chunk() {
    let lengths = shared(Vec::<usize>::new());
    let l = lengths.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step("recordingStep", move |items: Vec<i64>| {
            l.lock().unwrap().push(items.len());
            async move { Ok(items.into_iter().map(ok).collect()) }
        }))
        .build();
    pipeline.feed(items([1, 2]));
    pipeline.feed(items([3, 4, 5]));
    assert_eq!(pipeline.next().await.unwrap().unwrap().len(), 5);
    assert_eq!(*lengths.lock().unwrap(), vec![5]);
}

#[tokio::test]
async fn one_batch_spreads_across_multiple_chunks() {
    let pipeline = new_chunk_pipeline::<(&'static str, i64), ()>()
        .concurrently_per_group(
            |e: &(&'static str, i64)| e.0,
            |group| {
                group.sequentially(|b| b.pipe(step("identityStep", |e| async move { Ok(ok(e)) })))
            },
            None,
        )
        .build();
    pipeline.feed(items([("alice", 1), ("bob", 2), ("alice", 3), ("bob", 4)]));
    let chunks = collect_chunks(pipeline.as_ref()).await;
    assert_eq!(chunks.len(), 2);
    assert_eq!(chunks.iter().map(Vec::len).collect::<Vec<_>>(), [2, 2]);
}
