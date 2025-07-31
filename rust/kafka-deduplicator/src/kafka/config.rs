use std::collections::HashMap;
use std::time::Duration;

/// Configuration for the Kafka consumer
#[derive(Debug, Clone)]
pub struct ConsumerConfig {
    /// Kafka broker addresses
    pub brokers: String,
    
    /// Consumer group ID
    pub group_id: String,
    
    /// Topics to consume from
    pub topics: Vec<String>,
    
    /// Maximum number of messages to process concurrently across all partitions
    pub max_in_flight_messages: usize,
    
    /// Maximum number of messages to process concurrently per partition
    pub max_in_flight_messages_per_partition: usize,
    
    /// Maximum memory usage for in-flight messages
    pub max_memory_bytes: usize,
    
    /// Number of worker threads for processing
    pub worker_threads: usize,
    
    /// Timeout for polling messages
    pub poll_timeout: Duration,
    
    /// Timeout for graceful shutdown
    pub shutdown_timeout: Duration,
    
    /// Auto offset reset behavior
    pub auto_offset_reset: String,
    
    /// Additional Kafka configuration
    pub kafka_config: HashMap<String, String>,
}

impl ConsumerConfig {
    pub fn new(brokers: String, group_id: String, topics: Vec<String>) -> Self {
        Self {
            brokers,
            group_id,
            topics,
            max_in_flight_messages: 1000,
            max_in_flight_messages_per_partition: 100,
            max_memory_bytes: 64 * 1024 * 1024, // 64MB
            worker_threads: 4,
            poll_timeout: Duration::from_secs(1),
            shutdown_timeout: Duration::from_secs(30),
            auto_offset_reset: "earliest".to_string(),
            kafka_config: HashMap::new(),
        }
    }
    
    pub fn with_max_in_flight_messages(mut self, max_in_flight_messages: usize) -> Self {
        self.max_in_flight_messages = max_in_flight_messages;
        self
    }
    
    pub fn with_max_in_flight_messages_per_partition(mut self, max_in_flight_messages_per_partition: usize) -> Self {
        self.max_in_flight_messages_per_partition = max_in_flight_messages_per_partition;
        self
    }
    
    pub fn with_max_memory(mut self, max_memory_bytes: usize) -> Self {
        self.max_memory_bytes = max_memory_bytes;
        self
    }
    
    pub fn with_worker_threads(mut self, worker_threads: usize) -> Self {
        self.worker_threads = worker_threads;
        self
    }
    
    pub fn with_poll_timeout(mut self, timeout: Duration) -> Self {
        self.poll_timeout = timeout;
        self
    }
    
    pub fn with_shutdown_timeout(mut self, timeout: Duration) -> Self {
        self.shutdown_timeout = timeout;
        self
    }
    
    pub fn with_kafka_config(mut self, key: String, value: String) -> Self {
        self.kafka_config.insert(key, value);
        self
    }
}

impl Default for ConsumerConfig {
    fn default() -> Self {
        Self::new(
            "localhost:9092".to_string(),
            "default-group".to_string(),
            vec!["default-topic".to_string()],
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_consumer_config_new() {
        let config = ConsumerConfig::new(
            "broker1,broker2".to_string(),
            "test-group".to_string(),
            vec!["topic1".to_string(), "topic2".to_string()],
        );
        
        assert_eq!(config.brokers, "broker1,broker2");
        assert_eq!(config.group_id, "test-group");
        assert_eq!(config.topics, vec!["topic1", "topic2"]);
        assert_eq!(config.max_in_flight_messages, 1000);
        assert_eq!(config.max_in_flight_messages_per_partition, 100);
        assert_eq!(config.max_memory_bytes, 64 * 1024 * 1024);
        assert_eq!(config.worker_threads, 4);
        assert_eq!(config.auto_offset_reset, "earliest");
        assert!(config.kafka_config.is_empty());
    }
    
    #[test]
    fn test_consumer_config_builder() {
        let config = ConsumerConfig::new(
            "localhost:9092".to_string(),
            "builder-group".to_string(),
            vec!["builder-topic".to_string()],
        )
        .with_max_in_flight_messages(2000)
        .with_max_in_flight_messages_per_partition(200)
        .with_max_memory(128 * 1024 * 1024)
        .with_worker_threads(8)
        .with_poll_timeout(Duration::from_millis(500))
        .with_shutdown_timeout(Duration::from_secs(60))
        .with_kafka_config("fetch.min.bytes".to_string(), "10240".to_string())
        .with_kafka_config("fetch.wait.max.ms".to_string(), "100".to_string());
        
        assert_eq!(config.max_in_flight_messages, 2000);
        assert_eq!(config.max_in_flight_messages_per_partition, 200);
        assert_eq!(config.max_memory_bytes, 128 * 1024 * 1024);
        assert_eq!(config.worker_threads, 8);
        assert_eq!(config.poll_timeout, Duration::from_millis(500));
        assert_eq!(config.shutdown_timeout, Duration::from_secs(60));
        assert_eq!(config.kafka_config.len(), 2);
        assert_eq!(config.kafka_config.get("fetch.min.bytes"), Some(&"10240".to_string()));
        assert_eq!(config.kafka_config.get("fetch.wait.max.ms"), Some(&"100".to_string()));
    }
    
    #[test]
    fn test_consumer_config_default() {
        let config = ConsumerConfig::default();
        
        assert_eq!(config.brokers, "localhost:9092");
        assert_eq!(config.group_id, "default-group");
        assert_eq!(config.topics, vec!["default-topic"]);
        assert_eq!(config.max_in_flight_messages, 1000);
        assert_eq!(config.max_in_flight_messages_per_partition, 100);
        assert_eq!(config.max_memory_bytes, 64 * 1024 * 1024);
        assert_eq!(config.worker_threads, 4);
        assert_eq!(config.poll_timeout, Duration::from_secs(1));
        assert_eq!(config.shutdown_timeout, Duration::from_secs(30));
        assert_eq!(config.auto_offset_reset, "earliest");
    }
    
    #[test]
    fn test_kafka_config_chaining() {
        let mut config = ConsumerConfig::default();
        
        config = config
            .with_kafka_config("key1".to_string(), "value1".to_string())
            .with_kafka_config("key2".to_string(), "value2".to_string())
            .with_kafka_config("key1".to_string(), "updated_value1".to_string()); // Override
        
        assert_eq!(config.kafka_config.len(), 2);
        assert_eq!(config.kafka_config.get("key1"), Some(&"updated_value1".to_string()));
        assert_eq!(config.kafka_config.get("key2"), Some(&"value2".to_string()));
    }
    
    #[test]
    fn test_config_values_validation() {
        let config = ConsumerConfig::new(
            "".to_string(), // Empty broker string - should still work
            "".to_string(), // Empty group ID - should still work  
            vec![], // Empty topics - should still work
        );
        
        // Config creation should not fail, even with empty values
        // Validation would happen at the Kafka client level
        assert_eq!(config.brokers, "");
        assert_eq!(config.group_id, "");
        assert!(config.topics.is_empty());
    }
}