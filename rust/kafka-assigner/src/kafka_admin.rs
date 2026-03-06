use std::time::Duration;

use rdkafka::config::ClientConfig;
use rdkafka::consumer::{BaseConsumer, Consumer};

/// Fetch the partition count for a Kafka topic by querying broker metadata.
///
/// Uses a lightweight `BaseConsumer` (no group, no polling) to issue
/// a metadata request. This is cheaper than creating an `AdminClient`.
pub fn fetch_partition_count(
    kafka_hosts: &str,
    tls: bool,
    topic: &str,
    timeout: Duration,
) -> Result<u32, String> {
    let mut config = ClientConfig::new();
    config.set("bootstrap.servers", kafka_hosts);

    if tls {
        config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }

    let consumer: BaseConsumer = config
        .create()
        .map_err(|e| format!("failed to create Kafka client: {e}"))?;

    let metadata = consumer
        .fetch_metadata(Some(topic), timeout)
        .map_err(|e| format!("failed to fetch metadata for topic '{topic}': {e}"))?;

    let topic_metadata = metadata
        .topics()
        .iter()
        .find(|t| t.name() == topic)
        .ok_or_else(|| format!("topic '{topic}' not found in metadata response"))?;

    if let Some(err) = topic_metadata.error() {
        return Err(format!(
            "broker returned error for topic '{topic}': {err:?}"
        ));
    }

    let count = topic_metadata.partitions().len() as u32;
    if count == 0 {
        return Err(format!("topic '{topic}' has 0 partitions"));
    }

    Ok(count)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bad_broker_returns_error() {
        let result = fetch_partition_count(
            "localhost:19092",
            false,
            "nonexistent",
            Duration::from_secs(1),
        );
        assert!(result.is_err());
    }
}
