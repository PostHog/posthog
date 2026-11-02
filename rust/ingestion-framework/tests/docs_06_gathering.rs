//! Mirrors `docs/06-gathering.test.ts`.

mod common;

use common::{collect_chunks, items, sleep_ms};
use ingestion_framework::{new_chunk_pipeline, ok, step, ProcessingStep};

fn variable_delay_numbers() -> ProcessingStep<i64, i64> {
    step("variableDelayStep", |n: i64| async move {
        sleep_ms(match n {
            1 => 30,
            2 => 10,
            _ => 20,
        })
        .await;
        Ok(ok(n * 10))
    })
}

#[tokio::test(start_paused = true)]
async fn gather_after_concurrently_collects_items_into_one_chunk() {
    let streaming = new_chunk_pipeline::<i64, ()>()
        .concurrently(|b| b.pipe(variable_delay_numbers()), None)
        .build();
    streaming.feed(items([1, 2, 3]));
    assert_eq!(
        collect_chunks(streaming.as_ref()).await,
        vec![vec![10], vec![20], vec![30]]
    );

    let gathering = new_chunk_pipeline::<i64, ()>()
        .concurrently(|b| b.pipe(variable_delay_numbers()), None)
        .gather()
        .build();
    gathering.feed(items([1, 2, 3]));
    assert_eq!(
        collect_chunks(gathering.as_ref()).await,
        vec![vec![10, 20, 30]]
    );
}

type Event = (&'static str, i64);

fn variable_delay_events() -> ProcessingStep<Event, Event> {
    step("variableDelayStep", |e: Event| async move {
        sleep_ms(if e.0 == "alice" { 30 } else { 10 }).await;
        Ok(ok(e))
    })
}

#[tokio::test(start_paused = true)]
async fn gather_after_concurrently_per_group_collects_groups_into_one_chunk() {
    let events = [("alice", 1), ("bob", 2), ("alice", 3), ("bob", 4)];
    let streaming = new_chunk_pipeline::<Event, ()>()
        .concurrently_per_group(
            |e: &Event| e.0,
            |g| g.sequentially(|b| b.pipe(variable_delay_events())),
            None,
        )
        .build();
    streaming.feed(items(events));
    assert_eq!(
        collect_chunks(streaming.as_ref()).await,
        vec![
            vec![("bob", 2), ("bob", 4)],
            vec![("alice", 1), ("alice", 3)]
        ]
    );

    let gathering = new_chunk_pipeline::<Event, ()>()
        .concurrently_per_group(
            |e: &Event| e.0,
            |g| g.sequentially(|b| b.pipe(variable_delay_events())),
            None,
        )
        .gather()
        .build();
    gathering.feed(items(events));
    assert_eq!(
        collect_chunks(gathering.as_ref()).await,
        vec![vec![("bob", 2), ("bob", 4), ("alice", 1), ("alice", 3)]]
    );
}
