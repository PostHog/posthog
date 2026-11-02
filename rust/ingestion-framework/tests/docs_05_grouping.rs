//! Mirrors `docs/05-grouping.test.ts`.

mod common;

use std::collections::HashMap;

use common::{collect_chunks, consume_all_within, items, shared, sleep_ms};
use ingestion_framework::{new_chunk_pipeline, ok, step};

type Event = (&'static str, i64);

fn events(list: &[Event]) -> Vec<ingestion_framework::OkResultWithContext<Event, ()>> {
    items(list.iter().copied())
}

#[tokio::test(start_paused = true)]
async fn concurrently_per_group_partitions_items_by_a_key_function() {
    let groups = shared(HashMap::<&'static str, Vec<i64>>::new());
    let g = groups.clone();
    let pipeline = new_chunk_pipeline::<Event, ()>()
        .concurrently_per_group(
            |e: &Event| e.0,
            move |group| {
                group.sequentially(move |b| {
                    b.pipe(step("processEventStep", move |e: Event| {
                        let g = g.clone();
                        async move {
                            g.lock().unwrap().entry(e.0).or_default().push(e.1);
                            sleep_ms(5).await;
                            Ok(ok(e))
                        }
                    }))
                })
            },
            None,
        )
        .build();
    pipeline.feed(events(&[
        ("alice", 1),
        ("bob", 2),
        ("alice", 3),
        ("bob", 4),
    ]));
    consume_all_within(pipeline.as_ref(), 20).await;
    let groups = groups.lock().unwrap();
    assert_eq!(groups["alice"], vec![1, 3]);
    assert_eq!(groups["bob"], vec![2, 4]);
}

#[tokio::test(start_paused = true)]
async fn items_in_the_same_group_are_processed_sequentially() {
    let order = shared(Vec::<i64>::new());
    let o = order.clone();
    let pipeline = new_chunk_pipeline::<Event, ()>()
        .concurrently_per_group(
            |e: &Event| e.0,
            move |group| {
                group.sequentially(move |b| {
                    b.pipe(step("processEventStep", move |e: Event| {
                        let o = o.clone();
                        async move {
                            o.lock().unwrap().push(e.1);
                            sleep_ms(10).await;
                            Ok(ok(e))
                        }
                    }))
                })
            },
            None,
        )
        .build();
    pipeline.feed(events(&[("alice", 1), ("alice", 2), ("alice", 3)]));
    consume_all_within(pipeline.as_ref(), 30).await;
    assert_eq!(*order.lock().unwrap(), vec![1, 2, 3]);
}

fn delay_for(user: &str) -> u64 {
    match user {
        "alice" => 30,
        "bob" => 10,
        "charlie" => 20,
        _ => 0,
    }
}

#[tokio::test(start_paused = true)]
async fn items_in_different_groups_can_process_concurrently() {
    let pipeline = new_chunk_pipeline::<Event, ()>()
        .concurrently_per_group(
            |e: &Event| e.0,
            |group| {
                group.sequentially(|b| {
                    b.pipe(step("variableDelayStep", |e: Event| async move {
                        sleep_ms(delay_for(e.0)).await;
                        Ok(ok(e))
                    }))
                })
            },
            None,
        )
        .build();
    pipeline.feed(events(&[
        ("alice", 1),
        ("bob", 2),
        ("charlie", 3),
        ("alice", 4),
        ("bob", 5),
        ("charlie", 6),
    ]));
    let chunks: Vec<Vec<String>> = collect_chunks(pipeline.as_ref())
        .await
        .into_iter()
        .map(|c| c.into_iter().map(|(u, id)| format!("{u}:{id}")).collect())
        .collect();
    assert_eq!(
        chunks,
        vec![
            vec!["bob:2", "bob:5"],
            vec!["charlie:3", "charlie:6"],
            vec!["alice:1", "alice:4"],
        ]
    );
}

#[tokio::test(start_paused = true)]
async fn complex_group_keys_with_token_and_distinct_id() {
    type IngestionEvent = (&'static str, &'static str, &'static str);
    let groups = shared(HashMap::<String, Vec<&'static str>>::new());
    let g = groups.clone();
    let pipeline = new_chunk_pipeline::<IngestionEvent, ()>()
        .concurrently_per_group(
            |e: &IngestionEvent| format!("{}:{}", e.0, e.1),
            move |group| {
                group.sequentially(move |b| {
                    b.pipe(step("processEventStep", move |e: IngestionEvent| {
                        let g = g.clone();
                        async move {
                            g.lock()
                                .unwrap()
                                .entry(format!("{}:{}", e.0, e.1))
                                .or_default()
                                .push(e.2);
                            sleep_ms(5).await;
                            Ok(ok(e))
                        }
                    }))
                })
            },
            None,
        )
        .build();
    pipeline.feed(items([
        ("token-A", "user-1", "login"),
        ("token-B", "user-1", "signup"),
        ("token-A", "user-2", "pageview"),
        ("token-A", "user-1", "purchase"),
    ]));
    consume_all_within(pipeline.as_ref(), 10).await;
    let groups = groups.lock().unwrap();
    assert_eq!(groups["token-A:user-1"], vec!["login", "purchase"]);
    assert_eq!(groups["token-B:user-1"], vec!["signup"]);
    assert_eq!(groups["token-A:user-2"], vec!["pageview"]);
}
