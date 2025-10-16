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
            .set("enable.auto.commit", "false") // Manual commit for exactly-once semantics
            .set("auto.offset.reset", "earliest") // Don't miss data
            .set("session.timeout.ms", "30000")
            .set("heartbeat.interval.ms", "10000")
            .set("max.poll.interval.ms", "300000")
            .set("fetch.min.bytes", "1")
            .set("fetch.wait.max.ms", "500")
            .set("max.partition.fetch.bytes", "1048576"); // 1MB

        Self { config }
    }

    /// Override offset reset policy
    pub fn offset_reset(mut self, policy: &str) -> Self {
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

    /// Enable sticky partition assignments based on the kafka client ID supplied
    pub fn with_sticky_partition_assignment(mut self, client_id: Option<&str>) -> Self {
        if let Some(found_client_id) = client_id {
            self.config.set("client.id", found_client_id);
            self.config
                .set("partition.assignment.strategy", "cooperative-sticky");
        }
        self
    }

    /// Build the final configuration
    pub fn build(self) -> ClientConfig {
        self.config
    }
}
