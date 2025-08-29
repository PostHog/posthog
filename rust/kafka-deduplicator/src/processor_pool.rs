use rdkafka::Message;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::Arc;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::{error, info};
use crate::kafka::message::{AckableMessage, MessageProcessor};

/// A pool of workers that process messages in parallel
/// Messages with the same key are routed to the same worker to maintain ordering
pub struct ProcessorPool<P: MessageProcessor> {
    /// Receiver for messages from the consumer
    receiver: mpsc::UnboundedReceiver<AckableMessage>,
    
    /// The processor instances for each worker
    processors: Vec<Arc<P>>,
    
    /// Handles for worker tasks
    worker_handles: Vec<JoinHandle<()>>,
}

impl<P: MessageProcessor + Clone + 'static> ProcessorPool<P> {
    /// Create a new processor pool with the specified number of workers
    pub fn new(
        processor: Arc<P>,
        num_workers: usize,
    ) -> (mpsc::UnboundedSender<AckableMessage>, Self) {
        let (sender, receiver) = mpsc::unbounded_channel();
        
        // Clone processor for each worker
        let processors = (0..num_workers)
            .map(|_| processor.clone())
            .collect();
        
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
                if let Err(_) = worker_senders[worker_id].send(msg) {
                    error!("Worker {} channel closed", worker_id);
                    break;
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
