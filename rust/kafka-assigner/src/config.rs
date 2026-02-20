use std::time::Duration;

use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // ── etcd ────────────────────────────────────────────────────────
    #[envconfig(default = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[envconfig(default = "/kafka-assigner/")]
    pub etcd_prefix: String,

    // ── gRPC server ─────────────────────────────────────────────────
    #[envconfig(from = "BIND_HOST", default = "0.0.0.0")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "50051")]
    pub port: u16,

    #[envconfig(default = "64")]
    pub stream_channel_size: usize,

    #[envconfig(default = "30")]
    pub consumer_lease_ttl_secs: i64,

    #[envconfig(default = "10")]
    pub consumer_keepalive_interval_secs: u64,

    // ── Assigner / leader election ──────────────────────────────────
    #[envconfig(default = "assigner-0")]
    pub assigner_name: String,

    #[envconfig(default = "15")]
    pub leader_lease_ttl_secs: i64,

    #[envconfig(default = "5")]
    pub leader_keepalive_interval_secs: u64,

    #[envconfig(default = "5")]
    pub election_retry_interval_secs: u64,

    #[envconfig(default = "1")]
    pub rebalance_debounce_interval_secs: u64,

    #[envconfig(default = "300")]
    pub handoff_timeout_secs: u64,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Config::init_from_env()
    }

    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }

    pub fn etcd_endpoint_list(&self) -> Vec<String> {
        self.etcd_endpoints
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }

    pub fn consumer_keepalive_interval(&self) -> Duration {
        Duration::from_secs(self.consumer_keepalive_interval_secs)
    }

    pub fn leader_keepalive_interval(&self) -> Duration {
        Duration::from_secs(self.leader_keepalive_interval_secs)
    }

    pub fn election_retry_interval(&self) -> Duration {
        Duration::from_secs(self.election_retry_interval_secs)
    }

    pub fn rebalance_debounce_interval(&self) -> Duration {
        Duration::from_secs(self.rebalance_debounce_interval_secs)
    }

    pub fn handoff_timeout(&self) -> Duration {
        Duration::from_secs(self.handoff_timeout_secs)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_parses() {
        let config = Config::init_with_defaults().expect("default config should parse");
        assert_eq!(config.stream_channel_size, 64);
        assert_eq!(config.consumer_lease_ttl_secs, 30);
        assert_eq!(config.leader_lease_ttl_secs, 15);
        assert_eq!(config.handoff_timeout_secs, 300);
    }

    #[test]
    fn etcd_endpoint_list_splits_comma_separated() {
        let mut config = Config::init_with_defaults().unwrap();
        config.etcd_endpoints = "http://a:2379, http://b:2379".to_string();
        assert_eq!(
            config.etcd_endpoint_list(),
            vec!["http://a:2379", "http://b:2379"]
        );
    }

    #[test]
    fn etcd_endpoint_list_single() {
        let config = Config::init_with_defaults().unwrap();
        assert_eq!(config.etcd_endpoint_list(), vec!["http://localhost:2379"]);
    }
}
