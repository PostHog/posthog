use envconfig::Envconfig;

/// A consumer group and the topic it consumes, as configured via
/// `CONSUMER_TARGETS` (`group=topic` pairs). Groups and topics differ per
/// ingestion lane, so they must be configured together.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConsumerTarget {
    pub group: String,
    pub topic: String,
}

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "0.0.0.0")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3305")]
    pub port: u16,

    #[envconfig(from = "KAFKA_HOSTS", default = "localhost:19092")]
    pub kafka_hosts: String,

    #[envconfig(from = "KAFKA_TLS", default = "false")]
    pub kafka_tls: bool,

    #[envconfig(from = "KAFKA_CLIENT_RACK", default = "")]
    pub kafka_client_rack: String,

    /// Comma-separated `group=topic` pairs, e.g.
    /// `ingestion-analytics-main=ingestion-analytics-main-1024,ingestion-analytics-async=ingestion-analytics-async-8`.
    #[envconfig(
        from = "CONSUMER_TARGETS",
        default = "events-ingestion-consumer=events_plugin_ingestion"
    )]
    pub consumer_targets: String,

    /// Read-replica Postgres URL for token -> team_id resolution. When empty,
    /// resolution is disabled and analyses report `team_id: null`.
    #[envconfig(from = "DATABASE_URL", default = "")]
    pub database_url: String,

    #[envconfig(from = "PG_MAX_CONNECTIONS", default = "2")]
    pub pg_max_connections: u32,

    #[envconfig(from = "ANALYSIS_MESSAGE_COUNT", default = "10000")]
    pub analysis_message_count: u64,

    #[envconfig(from = "ANALYSIS_DEADLINE_SECS", default = "120")]
    pub analysis_deadline_secs: u64,

    /// Kafka transfers full records even though we only analyze headers, so
    /// bound the bytes fetched per analysis. 512 MiB by default.
    #[envconfig(from = "ANALYSIS_MAX_FETCH_BYTES", default = "536870912")]
    pub analysis_max_fetch_bytes: u64,

    #[envconfig(from = "ANALYSIS_MAX_CONCURRENT_JOBS", default = "2")]
    pub analysis_max_concurrent_jobs: usize,

    /// `kubernetes` discovers consumer pods via the K8s API; `static` uses
    /// the fixed `STATIC_PODS` list (local testing, like the
    /// ingestion-consumer's static worker discovery).
    #[envconfig(from = "POD_DISCOVERY_MODE", default = "kubernetes")]
    pub pod_discovery_mode: String,

    /// Comma-separated `name=host:port` entries used by static discovery.
    #[envconfig(from = "STATIC_PODS", default = "local=127.0.0.1:3301")]
    pub static_pods: String,

    #[envconfig(from = "K8S_NAMESPACE", default = "posthog")]
    pub k8s_namespace: String,

    /// Comma-separated pod label selectors, one per consumer deployment.
    #[envconfig(
        from = "POD_LABEL_SELECTORS",
        default = "app=ingestion-analytics-main,app=ingestion-analytics-async"
    )]
    pub pod_label_selectors: String,

    /// Port the ingestion-consumer serves its debug API on.
    #[envconfig(from = "DEBUG_PORT", default = "3301")]
    pub debug_port: u16,

    #[envconfig(from = "KAFKA_METADATA_TIMEOUT_MS", default = "10000")]
    pub kafka_metadata_timeout_ms: u64,

    #[envconfig(from = "KAFKA_FETCH_POLL_TIMEOUT_MS", default = "1000")]
    pub kafka_fetch_poll_timeout_ms: u64,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Self::init_from_env()
    }

    pub fn targets(&self) -> Vec<ConsumerTarget> {
        parse_targets(&self.consumer_targets)
    }

    pub fn target_for_group(&self, group: &str) -> Option<ConsumerTarget> {
        self.targets().into_iter().find(|t| t.group == group)
    }

    pub fn label_selectors(&self) -> Vec<String> {
        self.pod_label_selectors
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from)
            .collect()
    }
}

fn parse_targets(raw: &str) -> Vec<ConsumerTarget> {
    raw.split(',')
        .filter_map(|pair| {
            let (group, topic) = pair.trim().split_once('=')?;
            let (group, topic) = (group.trim(), topic.trim());
            if group.is_empty() || topic.is_empty() {
                return None;
            }
            Some(ConsumerTarget {
                group: group.to_string(),
                topic: topic.to_string(),
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_group_topic_pairs_and_skips_malformed_entries() {
        let targets = parse_targets(
            "ingestion-analytics-main=ingestion-analytics-main-1024, ingestion-analytics-async=ingestion-analytics-async-8,bad-entry,=no-group,no-topic=",
        );
        assert_eq!(
            targets,
            vec![
                ConsumerTarget {
                    group: "ingestion-analytics-main".to_string(),
                    topic: "ingestion-analytics-main-1024".to_string(),
                },
                ConsumerTarget {
                    group: "ingestion-analytics-async".to_string(),
                    topic: "ingestion-analytics-async-8".to_string(),
                },
            ]
        );
    }
}
