use std::{collections::HashMap, sync::Arc, time::Duration};

use property_defs_rs::types::{Event, Update};
use quick_cache::sync::Cache;
use tokio::sync::mpsc::{
    self,
    error::{TryRecvError, TrySendError},
};

// This is a bad hack to just copy the function like this, but I'll refactor later
async fn spawn_producer_loop(
    mut consumer: mpsc::Receiver<Event>,
    channel: mpsc::Sender<Update>,
    shared_cache: Arc<Cache<Update, ()>>,
    skip_threshold: usize,
    compaction_batch_size: usize,
    total_updates_received: Arc<std::sync::atomic::AtomicUsize>,
) {
    let mut batch = ahash::AHashSet::with_capacity(compaction_batch_size);
    let mut last_send = tokio::time::Instant::now();
    loop {
        let event = match consumer.try_recv() {
            Ok(event) => event,
            Err(TryRecvError::Empty) => {
                println!("Empty");
                consumer.recv().await.unwrap()
            }
            Err(TryRecvError::Disconnected) => {
                return;
            }
        };

        let updates = event.into_updates(skip_threshold);
        total_updates_received.fetch_add(updates.len(), std::sync::atomic::Ordering::Relaxed);

        for update in updates {
            if batch.contains(&update) {
                continue;
            }
            batch.insert(update);

            if batch.len() >= compaction_batch_size || last_send.elapsed() > Duration::from_secs(10)
            {
                last_send = tokio::time::Instant::now();
                for update in batch.drain() {
                    if shared_cache.get(&update).is_some() {
                        continue;
                    }
                    shared_cache.insert(update.clone(), ());
                    match channel.try_send(update) {
                        Ok(_) => {}
                        Err(TrySendError::Full(update)) => {
                            println!("Worker blocked");
                            channel.send(update).await.unwrap();
                        }
                        Err(e) => {
                            panic!("Coordinator send failed: {:?}", e);
                        }
                    }
                }
            }
        }
    }
}

const EVENT_COUNT: usize = 1_000_000;
const COMPACTION_BATCH_SIZE: usize = 10_000;
const SKIP_THRESHOLD: usize = 10_000;
const CACHE_SIZE: usize = 5_000_000;
const CHANNEL_SIZE: usize = 50_000;

#[tokio::main]
async fn main() {
    let (in_tx, in_rx) = mpsc::channel(CHANNEL_SIZE);
    let (out_tx, mut out_rx) = mpsc::channel(CHANNEL_SIZE);
    let cache = Arc::new(Cache::new(CACHE_SIZE));
    let total_updates_received = Arc::new(std::sync::atomic::AtomicUsize::new(0));

    let test_handle = tokio::spawn(spawn_producer_loop(
        in_rx,
        out_tx,
        cache.clone(),
        SKIP_THRESHOLD,
        COMPACTION_BATCH_SIZE,
        total_updates_received.clone(),
    ));

    let test_events = (0..EVENT_COUNT)
        .map(generate_test_event)
        .collect::<Vec<_>>();

    let total_updates_issued: Arc<std::sync::atomic::AtomicUsize> =
        Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let total_updates_issued_mv = total_updates_issued.clone();
    let return_handle = tokio::spawn(async move {
        let mut batch = Vec::with_capacity(CHANNEL_SIZE);
        while out_rx.recv_many(&mut batch, CHANNEL_SIZE).await > 0 {
            total_updates_issued_mv.fetch_add(batch.len(), std::sync::atomic::Ordering::Relaxed);
            batch.clear()
        }
    });

    let sender_handle = tokio::spawn(async move {
        for event in test_events {
            in_tx.send(event).await.unwrap();
        }
    });

    // Give that a second to run
    tokio::time::sleep(Duration::from_secs(1)).await;

    let start = tokio::time::Instant::now();
    test_handle.await.unwrap();
    let elapsed = start.elapsed();
    println!(
        "Processed {} events in {}s, {} events/s, issued {} updates, {} total updates ({} ratio)",
        EVENT_COUNT,
        elapsed.as_secs_f64(),
        EVENT_COUNT as f64 / elapsed.as_secs_f64(),
        total_updates_issued.load(std::sync::atomic::Ordering::Relaxed),
        total_updates_received.load(std::sync::atomic::Ordering::Relaxed),
        total_updates_issued.load(std::sync::atomic::Ordering::Relaxed) as f64
            / total_updates_received.load(std::sync::atomic::Ordering::Relaxed) as f64
    );

    sender_handle.await.unwrap();
    return_handle.await.unwrap();
}

// This generates "random" events, in a world where we have N teams, each sending 8 different events, each with 100 properties
// That means we have N * 8 * 100 = N*800 EventProperties, as well as N*8 event definitions and N*100 properties
// in the universe of possible updates to generate. Setting N to 1000 gives 800_000 possible EventProperties,
// 8000 event definitions and 100_000 properties.
fn generate_test_event(seed: usize) -> Event {
    let team_id = (seed % 1000) as i32;
    let event_name = format!("test_event_{}", seed % 8); // Imagine each team sends about 8 different events
    let properties: HashMap<String, String> =
        (0..100) // The average event has 100 properties
            .map(|i| (format!("key_{}", i), format!("val_{}", i)))
            .collect();

    Event {
        team_id,
        event: event_name,
        properties: Some(serde_json::to_string(&properties).unwrap()),
    }
}
