use rdkafka::ClientConfig;

/// Kafka consumer configuration builder with sensible defaults for PostHog services.
///
/// Use the factory methods to create a builder for your specific use case:
/// - `for_group_consumer()` - Long-lived consumers that participate in consumer groups
/// - `for_manual_assignment()` - One-shot fetch operations using manual partition assignment
pub struct ConsumerConfigBuilder {
    config: ClientConfig,
}

impl ConsumerConfigBuilder {
    /// Create a consumer config builder for long-lived consumers that participate in consumer groups.
    ///
    /// Includes sensible defaults for group membership, session timeouts, and offset management.
    /// Use this for `BatchConsumer` and other consumers that use `subscribe()`.
    pub fn for_group_consumer(bootstrap_servers: &str, group_id: &str) -> Self {
        let mut config = ClientConfig::new();

        // Required settings
        config
            .set("bootstrap.servers", bootstrap_servers)
            .set("group.id", group_id);

        // PostHog standard defaults for consumer
        config
            .set("enable.auto.offset.store", "false") // Manual store for full control
            .set("enable.auto.commit", "false") // Manual commit for exactly-once semantics
            .set("socket.timeout.ms", "10000")
            .set("session.timeout.ms", "60000")
            .set("heartbeat.interval.ms", "5000")
            .set("max.poll.interval.ms", "300000");

        Self { config }
    }

    /// Create a minimal consumer config builder for one-shot fetch operations.
    ///
    /// Uses a placeholder group.id since rdkafka requires it even for manual assignment.
    /// The group is never actually used for coordination since we use `assign()` instead
    /// of `subscribe()`. Use this for `HeadFetcher` and similar one-shot operations.
    pub fn for_manual_assignment(bootstrap_servers: &str) -> Self {
        let mut config = ClientConfig::new();

        config.set("bootstrap.servers", bootstrap_servers);

        // rdkafka requires group.id even for manual assign() - use placeholder
        config.set("group.id", "manual-assignment-no-group");

        // Minimal defaults for fetch operations
        config
            .set("enable.auto.offset.store", "false")
            .set("enable.auto.commit", "false")
            .set("socket.timeout.ms", "10000");

        Self { config }
    }

    /// Override offset reset policy
    pub fn with_offset_reset(mut self, policy: &str) -> Self {
        self.config.set("auto.offset.reset", policy);
        self
    }

    /// Add any custom configuration
    pub fn set(mut self, key: &str, value: &str) -> Self {
        self.config.set(key, value);
        self
    }

    /// Enable TLS/SSL for Kafka connection
    pub fn with_tls(mut self, enabled: bool) -> Self {
        if enabled {
            self.config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }
        self
    }

    pub fn with_max_partition_fetch_bytes(mut self, bytes: u32) -> Self {
        self.config
            .set("max.partition.fetch.bytes", bytes.to_string());
        self
    }

    pub fn with_topic_metadata_refresh_interval_ms(mut self, ms: u32) -> Self {
        self.config
            .set("topic.metadata.refresh.interval.ms", ms.to_string());
        self
    }

    pub fn with_metadata_max_age_ms(mut self, ms: u32) -> Self {
        self.config.set("metadata.max.age.ms", ms.to_string());
        self
    }

    /// Set minimum bytes to fetch from broker (triggers fetch when buffer has less than this)
    pub fn with_fetch_min_bytes(mut self, bytes: u32) -> Self {
        self.config.set("fetch.min.bytes", bytes.to_string());
        self
    }

    /// Set maximum bytes to fetch from broker in a single request
    pub fn with_fetch_max_bytes(mut self, bytes: u32) -> Self {
        self.config.set("fetch.max.bytes", bytes.to_string());
        self
    }

    /// Set maximum wait time when fetch.min.bytes is not satisfied
    pub fn with_fetch_wait_max_ms(mut self, ms: u32) -> Self {
        self.config.set("fetch.wait.max.ms", ms.to_string());
        self
    }

    /// Set minimum number of messages to queue for prefetching
    pub fn with_queued_min_messages(mut self, messages: u32) -> Self {
        self.config.set("queued.min.messages", messages.to_string());
        self
    }

    /// Set maximum bytes to prefetch across all partitions (in KB)
    pub fn with_queued_max_messages_kbytes(mut self, kbytes: u32) -> Self {
        self.config
            .set("queued.max.messages.kbytes", kbytes.to_string());
        self
    }

    /// Set maximum time between poll() calls before consumer leaves group
    pub fn with_max_poll_interval_ms(mut self, ms: u32) -> Self {
        self.config.set("max.poll.interval.ms", ms.to_string());
        self
    }

    /// Set session timeout: how long broker waits for heartbeats before declaring consumer dead.
    /// With static membership (group.instance.id), broker holds partition assignments for this
    /// duration after a consumer disappears. Should be longer than typical pod restart time.
    pub fn with_session_timeout_ms(mut self, ms: u32) -> Self {
        self.config.set("session.timeout.ms", ms.to_string());
        self
    }

    /// Set heartbeat interval: how often consumer sends heartbeats to broker.
    /// Should be ~1/3 of session.timeout.ms to allow multiple missed heartbeats before timeout.
    pub fn with_heartbeat_interval_ms(mut self, ms: u32) -> Self {
        self.config.set("heartbeat.interval.ms", ms.to_string());
        self
    }

    /// Enable sticky partition assignments based on the kafka client ID supplied.
    /// Always uses cooperative-sticky strategy for consistent behavior across all pods.
    /// When client_id is provided, also enables static membership for truly sticky assignments.
    pub fn with_sticky_partition_assignment(mut self, client_id: Option<&str>) -> Self {
        // Always use cooperative-sticky for consistent behavior across all pods
        self.config
            .set("partition.assignment.strategy", "cooperative-sticky");

        if let Some(found_client_id) = client_id {
            self.config.set("client.id", found_client_id);
            // Enable static membership for truly sticky assignments
            self.config.set("group.instance.id", found_client_id);
        }
        self
    }

    /// Build the final configuration
    pub fn build(self) -> ClientConfig {
        self.config
    }
}
