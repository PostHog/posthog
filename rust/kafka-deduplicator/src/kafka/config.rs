use rdkafka::ClientConfig;

/// Default Kafka consumer configuration builder with sensible defaults for PostHog services
pub struct ConsumerConfigBuilder {
    config: ClientConfig,
}

impl ConsumerConfigBuilder {
    /// Create a new consumer config builder with PostHog defaults
    pub fn new(bootstrap_servers: &str, group_id: &str) -> Self {
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
            .set("session.timeout.ms", "30000")
            .set("heartbeat.interval.ms", "5000")
            .set("max.poll.interval.ms", "300000")
            .set("fetch.min.bytes", "1")
            .set("fetch.wait.max.ms", "500");

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
