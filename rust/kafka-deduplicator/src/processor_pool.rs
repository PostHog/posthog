use crate::kafka::message::{AckableMessage, MessageProcessor};
use rdkafka::Message;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::{error, info};

/// A pool of workers that process messages in parallel
/// Messages with the same key are routed to the same worker to maintain ordering
pub struct ProcessorPool<P: MessageProcessor> {
    /// Receiver for messages from the consumer
    receiver: mpsc::UnboundedReceiver<AckableMessage>,

    /// The processor instances for each worker
    processors: Vec<P>,

    /// Handles for worker tasks
    worker_handles: Vec<JoinHandle<()>>,
}

impl<P: MessageProcessor + Clone + 'static> ProcessorPool<P> {
    /// Create a new processor pool with the specified number of workers
    pub fn new(processor: P, num_workers: usize) -> (mpsc::UnboundedSender<AckableMessage>, Self) {
        let (sender, receiver) = mpsc::unbounded_channel();

        // Clone processor for each worker
        let processors = (0..num_workers).map(|_| processor.clone()).collect();

        let pool = Self {
            receiver,
            processors,
            worker_handles: Vec::with_capacity(num_workers),
        };

        (sender, pool)
    }

    /// Start the worker pool
    pub fn start(mut self) -> Vec<JoinHandle<()>> {
        let num_workers = self.processors.len();
        info!("Starting processor pool with {} workers", num_workers);

        // Create channels for each worker
        let mut worker_senders = Vec::with_capacity(num_workers);
        for i in 0..num_workers {
            let (tx, mut rx) = mpsc::unbounded_channel::<AckableMessage>();
            worker_senders.push(tx);

            let processor = self.processors[i].clone();

            // Spawn worker task
            let handle = tokio::spawn(async move {
                info!("Worker {} started", i);
                while let Some(msg) = rx.recv().await {
                    if let Err(e) = processor.process_message(msg).await {
                        // TODO: Implement Dead Letter Queue (DLQ) handling
                        // Future implementation should:
                        // Retry messages that fail
                        // Send failed messages to a DLQ topic
                        // Allow configuration of error handling strategy (drop/retry/DLQ)
                        // Emit metrics for failed message processing
                        // For now, we just log the error and continue processing
                        error!("Worker {} failed to process message: {}", i, e);
                    }
                }
                info!("Worker {} shutting down", i);
            });

            self.worker_handles.push(handle);
        }

        // Spawn router task that distributes messages to workers
        let router_handle = tokio::spawn(async move {
            info!("Message router started");
            while let Some(msg) = self.receiver.recv().await {
                // Determine which worker should handle this message
                let worker_id = if let Some(key_bytes) = msg.kafka_message().key() {
                    // Hash the key to determine the worker
                    let mut hasher = DefaultHasher::new();
                    key_bytes.hash(&mut hasher);
                    let hash = hasher.finish();
                    (hash as usize) % num_workers
                } else {
                    // No key - use round-robin based on offset
                    (msg.kafka_message().offset() as usize) % num_workers
                };

                // Send to the selected worker
                if let Err(send_error) = worker_senders[worker_id].send(msg) {
                    // Worker channel closed - this means the worker panicked
                    let msg_offset = send_error.0.kafka_message().offset();

                    error!(
                        "CRITICAL: Worker {worker_id} channel closed (worker likely panicked), message offset: {msg_offset}. Shutting down.",
                    );

                    // Don't try to recover - fail fast and let the system restart
                    panic!("Worker {worker_id} died unexpectedly while processing messages");
                }
            }

            // Close all worker channels
            drop(worker_senders);
            info!("Message router shutting down");
        });

        // Add router handle to the list
        self.worker_handles.push(router_handle);
        self.worker_handles
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::message::MessageProcessor;
    use async_trait::async_trait;
    use std::collections::HashMap;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::time::{Duration, Instant};
    use tokio::sync::RwLock;
    use tokio::time::sleep;

    /// Test processor that tracks which worker processed each message
    struct TestProcessor {
        worker_id: usize,
        worker_counts: Arc<RwLock<HashMap<usize, AtomicUsize>>>,
        key_orders: Arc<RwLock<HashMap<Vec<u8>, Vec<i64>>>>,
        processing_delay: Duration,
        concurrent_count: Arc<AtomicUsize>,
        max_concurrent: Arc<AtomicUsize>,
        next_worker_id: Arc<AtomicUsize>, // Per-processor instance counter
    }

    impl Clone for TestProcessor {
        fn clone(&self) -> Self {
            // Each clone gets a unique worker ID from the parent's counter
            Self {
                worker_id: self.next_worker_id.fetch_add(1, Ordering::SeqCst),
                worker_counts: self.worker_counts.clone(),
                key_orders: self.key_orders.clone(),
                processing_delay: self.processing_delay,
                concurrent_count: self.concurrent_count.clone(),
                max_concurrent: self.max_concurrent.clone(),
                next_worker_id: self.next_worker_id.clone(),
            }
        }
    }

    impl TestProcessor {
        fn new(processing_delay: Duration) -> Self {
            Self {
                worker_id: 0, // Initial processor gets ID 0
                worker_counts: Arc::new(RwLock::new(HashMap::new())),
                key_orders: Arc::new(RwLock::new(HashMap::new())),
                processing_delay,
                concurrent_count: Arc::new(AtomicUsize::new(0)),
                max_concurrent: Arc::new(AtomicUsize::new(0)),
                next_worker_id: Arc::new(AtomicUsize::new(1)), // Start at 1 for clones
            }
        }

        async fn get_stats(&self) -> (HashMap<usize, usize>, usize, HashMap<Vec<u8>, Vec<i64>>) {
            let counts = self.worker_counts.read().await;
            let mut worker_counts = HashMap::new();
            for (worker_id, count) in counts.iter() {
                worker_counts.insert(*worker_id, count.load(Ordering::SeqCst));
            }

            let key_orders = self.key_orders.read().await.clone();

            (
                worker_counts,
                self.max_concurrent.load(Ordering::SeqCst),
                key_orders,
            )
        }
    }

    #[async_trait]
    impl MessageProcessor for TestProcessor {
        async fn process_message(&self, message: AckableMessage) -> anyhow::Result<()> {
            let current = self.concurrent_count.fetch_add(1, Ordering::SeqCst) + 1;

            loop {
                let max = self.max_concurrent.load(Ordering::SeqCst);
                if current <= max {
                    break;
                }
                if self
                    .max_concurrent
                    .compare_exchange(max, current, Ordering::SeqCst, Ordering::SeqCst)
                    .is_ok()
                {
                    break;
                }
            }

            // Use the worker ID assigned during clone
            {
                let mut counts = self.worker_counts.write().await;
                counts
                    .entry(self.worker_id)
                    .or_insert_with(|| AtomicUsize::new(0))
                    .fetch_add(1, Ordering::SeqCst);
            }

            if let Some(key) = message.kafka_message().key() {
                let mut orders = self.key_orders.write().await;
                orders
                    .entry(key.to_vec())
                    .or_insert_with(Vec::new)
                    .push(message.kafka_message().offset());
            }

            sleep(self.processing_delay).await;
            message.ack().await;
            self.concurrent_count.fetch_sub(1, Ordering::SeqCst);

            Ok(())
        }
    }

    /// Processor that can fail on specific messages
    #[derive(Clone)]
    struct FailingProcessor {
        fail_on_offset: Option<i64>,
        processed_count: Arc<AtomicUsize>,
        failed_count: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl MessageProcessor for FailingProcessor {
        async fn process_message(&self, message: AckableMessage) -> anyhow::Result<()> {
            let offset = message.kafka_message().offset();

            if let Some(fail_offset) = self.fail_on_offset {
                if offset == fail_offset {
                    self.failed_count.fetch_add(1, Ordering::SeqCst);
                    message.ack().await;
                    return Err(anyhow::anyhow!("Simulated failure at offset {}", offset));
                }
            }

            self.processed_count.fetch_add(1, Ordering::SeqCst);
            message.ack().await;
            Ok(())
        }
    }

    async fn create_test_message(key: Option<&[u8]>, offset: i64) -> AckableMessage {
        use crate::kafka::tracker::InFlightTracker;
        use rdkafka::message::{OwnedHeaders, OwnedMessage};
        use rdkafka::Timestamp;

        let tracker = Arc::new(InFlightTracker::new());
        let permit = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let message = OwnedMessage::new(
            Some(b"test payload".to_vec()),
            key.map(|k| k.to_vec()),
            "test-topic".to_string(),
            Timestamp::NotAvailable,
            0,
            offset,
            Some(OwnedHeaders::new()),
        );

        tracker.track_message(message, 1024, permit).await
    }

    #[tokio::test]
    async fn test_parallel_processing() {
        let processor = TestProcessor::new(Duration::from_millis(50));
        let (sender, pool) = ProcessorPool::new(processor.clone(), 4);

        let handles = pool.start();

        let num_messages = 100;
        for i in 0..num_messages {
            let msg = create_test_message(None, i).await;
            sender.send(msg).unwrap();
        }

        sleep(Duration::from_secs(2)).await;

        let (worker_counts, max_concurrent, _) = processor.get_stats().await;

        assert!(
            worker_counts.len() > 1,
            "Expected multiple workers, got {}",
            worker_counts.len()
        );
        assert!(
            max_concurrent > 1,
            "Expected concurrent processing, max was {max_concurrent}"
        );

        let total_processed: usize = worker_counts.values().sum();
        assert_eq!(total_processed, num_messages as usize);

        drop(sender);
        for handle in handles {
            handle.abort();
        }
    }

    #[tokio::test]
    async fn test_key_based_routing() {
        let processor = TestProcessor::new(Duration::from_millis(10));
        let (sender, pool) = ProcessorPool::new(processor.clone(), 4);

        let handles = pool.start();

        let keys = vec![b"key1", b"key2", b"key3", b"key4"];
        let messages_per_key = 10;

        for (key_idx, key) in keys.iter().enumerate() {
            for i in 0..messages_per_key {
                let offset = (key_idx * messages_per_key + i) as i64;
                let msg = create_test_message(Some(*key), offset).await;
                sender.send(msg).unwrap();
            }
        }

        sleep(Duration::from_secs(1)).await;

        let (_, _, key_orders) = processor.get_stats().await;

        for key in keys {
            let orders = key_orders
                .get(key.as_slice())
                .expect("Key should have been processed");
            let mut sorted_orders = orders.clone();
            sorted_orders.sort();
            assert_eq!(
                orders, &sorted_orders,
                "Messages for key {key:?} were not processed in order: {orders:?}"
            );
        }

        drop(sender);
        for handle in handles {
            handle.abort();
        }
    }

    #[tokio::test]
    async fn test_high_concurrency() {
        let processor = TestProcessor::new(Duration::from_millis(100));
        let num_workers = 8;
        let (sender, pool) = ProcessorPool::new(processor.clone(), num_workers);

        let handles = pool.start();

        let burst_size = 50;
        for i in 0..burst_size {
            let msg = create_test_message(None, i).await;
            sender.send(msg).unwrap();
        }

        sleep(Duration::from_secs(2)).await;

        let (worker_counts, max_concurrent, _) = processor.get_stats().await;

        assert!(
            max_concurrent >= num_workers / 2,
            "Expected at least {} concurrent processing, got {max_concurrent}",
            num_workers / 2
        );

        assert!(
            worker_counts.len() >= num_workers * 3 / 4,
            "Expected at least {} workers to be used, got {}",
            num_workers * 3 / 4,
            worker_counts.len()
        );

        drop(sender);
        for handle in handles {
            handle.abort();
        }
    }

    #[tokio::test]
    async fn test_graceful_shutdown() {
        let processor = TestProcessor::new(Duration::from_millis(10));
        let (sender, pool) = ProcessorPool::new(processor.clone(), 4);

        let handles = pool.start();

        for i in 0..10 {
            let msg = create_test_message(None, i).await;
            sender.send(msg).unwrap();
        }

        sleep(Duration::from_millis(50)).await;

        drop(sender);

        let start = std::time::Instant::now();
        for handle in handles {
            match tokio::time::timeout(Duration::from_secs(1), handle).await {
                Ok(Ok(())) => {}
                Ok(Err(_)) => {}
                Err(_) => panic!("Worker didn't shut down within timeout"),
            }
        }

        assert!(
            start.elapsed() < Duration::from_secs(2),
            "Shutdown took too long: {:?}",
            start.elapsed()
        );
    }

    /// Processor that delays specific keys to test worker independence
    #[derive(Clone)]
    struct SlowKeyProcessor {
        slow_key: Vec<u8>,
        slow_delay: Duration,
        normal_delay: Duration,
        processing_times: Arc<RwLock<HashMap<Vec<u8>, Vec<Instant>>>>,
    }

    #[async_trait]
    impl MessageProcessor for SlowKeyProcessor {
        async fn process_message(&self, message: AckableMessage) -> anyhow::Result<()> {
            let key = message
                .kafka_message()
                .key()
                .map(|k| k.to_vec())
                .unwrap_or_default();

            // Record when we started processing
            {
                let mut times = self.processing_times.write().await;
                times
                    .entry(key.clone())
                    .or_insert_with(Vec::new)
                    .push(Instant::now());
            }

            // Slow down specific key
            if key == self.slow_key {
                sleep(self.slow_delay).await;
            } else {
                sleep(self.normal_delay).await;
            }

            message.ack().await;
            Ok(())
        }
    }

    /// Processor that verifies message ordering for each key
    #[derive(Clone)]
    struct OrderCheckProcessor {
        last_offset_per_key: Arc<RwLock<HashMap<Vec<u8>, i64>>>,
        ordering_violations: Arc<AtomicUsize>,
        processing_delay: Duration,
    }

    #[async_trait]
    impl MessageProcessor for OrderCheckProcessor {
        async fn process_message(&self, message: AckableMessage) -> anyhow::Result<()> {
            if let Some(key) = message.kafka_message().key() {
                let offset = message.kafka_message().offset();

                let mut last_offsets = self.last_offset_per_key.write().await;
                if let Some(&last_offset) = last_offsets.get(key) {
                    if offset <= last_offset {
                        self.ordering_violations.fetch_add(1, Ordering::SeqCst);
                        eprintln!(
                            "Order violation: key {key:?} processed offset {offset} after {last_offset}"
                        );
                    }
                }
                last_offsets.insert(key.to_vec(), offset);
            }

            // Simulate variable processing time
            sleep(self.processing_delay).await;
            message.ack().await;
            Ok(())
        }
    }

    #[tokio::test]
    async fn test_worker_independence() {
        // Test that one slow message doesn't block other workers

        let slow_key = b"slow_key".to_vec();
        let processor = SlowKeyProcessor {
            slow_key: slow_key.clone(),
            slow_delay: Duration::from_millis(500),
            normal_delay: Duration::from_millis(10),
            processing_times: Arc::new(RwLock::new(HashMap::new())),
        };

        let (sender, pool) = ProcessorPool::new(processor.clone(), 4);
        let handles = pool.start();

        // Send slow key messages and fast key messages
        for i in 0..5 {
            // Slow messages
            let msg = create_test_message(Some(&slow_key), i * 2).await;
            sender.send(msg).unwrap();

            // Fast messages with different keys
            let fast_key = format!("fast_{i}").into_bytes();
            let msg = create_test_message(Some(&fast_key), i * 2 + 1).await;
            sender.send(msg).unwrap();
        }

        // Wait for processing
        sleep(Duration::from_secs(3)).await;

        // Verify that fast messages didn't wait for slow ones
        let times = processor.processing_times.read().await;

        // Get the first slow message start time
        let slow_start = times.get(&slow_key).and_then(|t| t.first()).copied();

        // Check that some fast messages completed before the first slow message
        let mut fast_completed_during_slow = 0;
        for (key, timestamps) in times.iter() {
            if key != &slow_key {
                if let Some(slow) = slow_start {
                    for &fast_time in timestamps {
                        // If a fast message started after slow but within the slow processing window
                        if fast_time > slow && fast_time < slow + Duration::from_millis(400) {
                            fast_completed_during_slow += 1;
                        }
                    }
                }
            }
        }

        assert!(
            fast_completed_during_slow > 0,
            "Fast messages should process while slow message is blocking its worker"
        );

        drop(sender);
        for handle in handles {
            handle.abort();
        }
    }

    #[tokio::test]
    async fn test_same_key_ordering_under_load() {
        // Verify ordering is maintained even under high load with delays
        let processor = OrderCheckProcessor {
            last_offset_per_key: Arc::new(RwLock::new(HashMap::new())),
            ordering_violations: Arc::new(AtomicUsize::new(0)),
            processing_delay: Duration::from_millis(5),
        };

        let (sender, pool) = ProcessorPool::new(processor.clone(), 8);
        let handles = pool.start();

        // Send many messages with overlapping keys
        let keys = [b"key_a", b"key_b", b"key_c", b"key_d"];
        for offset in 0..100 {
            let key = keys[offset % keys.len()];
            let msg = create_test_message(Some(key), offset as i64).await;
            sender.send(msg).unwrap();
        }

        // Wait for all processing
        sleep(Duration::from_secs(2)).await;

        // Check no ordering violations occurred
        let violations = processor.ordering_violations.load(Ordering::SeqCst);
        assert_eq!(
            violations, 0,
            "Found {violations} ordering violations - same key messages processed out of order"
        );

        drop(sender);
        for handle in handles {
            handle.abort();
        }
    }

    #[tokio::test]
    async fn test_error_handling() {
        // Test that processor errors don't crash workers
        let processor = FailingProcessor {
            fail_on_offset: Some(5),
            processed_count: Arc::new(AtomicUsize::new(0)),
            failed_count: Arc::new(AtomicUsize::new(0)),
        };

        let (sender, pool) = ProcessorPool::new(processor.clone(), 4);
        let handles = pool.start();

        // Send messages including the failing one
        for i in 0..10 {
            let msg = create_test_message(None, i).await;
            sender.send(msg).unwrap();
        }

        // Wait for processing
        sleep(Duration::from_millis(500)).await;

        // Verify that the error was handled gracefully
        let processed = processor.processed_count.load(Ordering::SeqCst);
        let failed = processor.failed_count.load(Ordering::SeqCst);

        assert_eq!(failed, 1, "Should have failed exactly once");
        assert_eq!(processed, 9, "Should have processed all other messages");

        drop(sender);
        for handle in handles {
            handle.abort();
        }
    }

    #[tokio::test]
    async fn test_worker_failure_causes_panic() {
        // Test that the router panics when a worker dies (fail-fast behavior)
        let processor = TestProcessor::new(Duration::from_millis(10));
        let (sender, pool) = ProcessorPool::new(processor.clone(), 4);
        let mut handles = pool.start();

        // Send some messages to ensure system is working
        for i in 0..5 {
            let msg = create_test_message(None, i).await;
            sender.send(msg).unwrap();
        }

        // Wait for initial messages to be processed
        sleep(Duration::from_millis(100)).await;

        // Abort worker 0 to simulate failure
        handles[0].abort();

        // The router handle is the last one
        let router_handle = handles.pop().unwrap();

        // Send a message that would go to worker 0
        // This should cause the router to panic
        let msg = create_test_message(None, 100).await;
        sender.send(msg).unwrap();

        // Router should panic and exit
        let router_result = tokio::time::timeout(Duration::from_secs(1), router_handle).await;

        // Verify router task panicked or exited
        assert!(
            router_result.is_ok(),
            "Router should have exited after worker failure"
        );

        // Clean up
        drop(sender);
        for handle in handles {
            handle.abort();
        }
    }
}
