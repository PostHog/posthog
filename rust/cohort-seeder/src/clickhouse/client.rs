//! ClickHouse client construction: endpoint precedence and the typed `join_algorithm` setting.
//!
//! Depends on `config` for the raw env strings; every value that shapes a ClickHouse query option is
//! parsed here so a misconfiguration fails startup instead of silently degrading query behavior.

use std::str::FromStr;

use crate::config::Config;

/// The resolved ClickHouse HTTP endpoint. Precedence is explicit URL > offline cluster host > host;
/// the scheme comes from `secure`, and a bare host gets the canonical port (8443 secure, 8123 plain).
/// Resolved exactly once by [`ClickHouseEndpoint::resolve`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClickHouseEndpoint(String);

impl ClickHouseEndpoint {
    pub fn resolve(config: &Config) -> Self {
        Self(resolve_endpoint(config))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

fn resolve_endpoint(config: &Config) -> String {
    if !config.clickhouse_url.is_empty() {
        return config.clickhouse_url.clone();
    }
    let host = if config.clickhouse_offline_cluster_host.is_empty() {
        &config.clickhouse_host
    } else {
        &config.clickhouse_offline_cluster_host
    };
    if host.starts_with("http://") || host.starts_with("https://") {
        return host.clone();
    }
    let scheme = if config.clickhouse_secure {
        "https"
    } else {
        "http"
    };
    if has_explicit_port(host) {
        format!("{scheme}://{host}")
    } else {
        let port = if config.clickhouse_secure { 8443 } else { 8123 };
        format!("{scheme}://{host}:{port}")
    }
}

fn has_explicit_port(host: &str) -> bool {
    if let Some(bracket_end) = host.find(']') {
        return host
            .get(bracket_end + 1..)
            .is_some_and(|suffix| suffix.starts_with(':'));
    }
    let Some((_, port)) = host.rsplit_once(':') else {
        return false;
    };
    host.matches(':').count() == 1 && port.parse::<u16>().is_ok()
}

/// The ClickHouse `join_algorithm` query setting. Parsed from config so an unknown value is a startup
/// failure rather than a silent pass-through that would degrade join memory behavior. `as_str` emits
/// the exact ClickHouse token, so the option value is byte-identical to the raw string it parses.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClickHouseJoinAlgorithm {
    Default,
    Auto,
    Hash,
    ParallelHash,
    GraceHash,
    PartialMerge,
    PreferPartialMerge,
    FullSortingMerge,
    Direct,
}

impl ClickHouseJoinAlgorithm {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Default => "default",
            Self::Auto => "auto",
            Self::Hash => "hash",
            Self::ParallelHash => "parallel_hash",
            Self::GraceHash => "grace_hash",
            Self::PartialMerge => "partial_merge",
            Self::PreferPartialMerge => "prefer_partial_merge",
            Self::FullSortingMerge => "full_sorting_merge",
            Self::Direct => "direct",
        }
    }
}

impl FromStr for ClickHouseJoinAlgorithm {
    type Err = UnknownJoinAlgorithm;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "default" => Ok(Self::Default),
            "auto" => Ok(Self::Auto),
            "hash" => Ok(Self::Hash),
            "parallel_hash" => Ok(Self::ParallelHash),
            "grace_hash" => Ok(Self::GraceHash),
            "partial_merge" => Ok(Self::PartialMerge),
            "prefer_partial_merge" => Ok(Self::PreferPartialMerge),
            "full_sorting_merge" => Ok(Self::FullSortingMerge),
            "direct" => Ok(Self::Direct),
            other => Err(UnknownJoinAlgorithm(other.to_string())),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("unknown ClickHouse join algorithm {0:?}")]
pub struct UnknownJoinAlgorithm(pub String);

pub fn build_client(config: &Config) -> Result<clickhouse::Client, UnknownJoinAlgorithm> {
    let join_algorithm = config
        .seeder_ch_join_algorithm
        .parse::<ClickHouseJoinAlgorithm>()?;
    Ok(clickhouse::Client::default()
        .with_url(ClickHouseEndpoint::resolve(config).as_str())
        .with_user(&config.clickhouse_user)
        .with_password(&config.clickhouse_password)
        .with_database(&config.clickhouse_database)
        .with_option(
            "max_execution_time",
            config.seeder_ch_max_execution_time_secs.to_string(),
        )
        .with_option(
            "max_bytes_before_external_group_by",
            config
                .seeder_ch_max_bytes_before_external_group_by
                .to_string(),
        )
        .with_option(
            "max_bytes_before_external_sort",
            config.seeder_ch_max_bytes_before_external_sort.to_string(),
        )
        .with_option("join_algorithm", join_algorithm.as_str()))
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use envconfig::Envconfig;

    use super::*;

    fn default_config() -> Config {
        Config::init_from_hashmap(&HashMap::new()).unwrap()
    }

    fn endpoint(config: &Config) -> String {
        ClickHouseEndpoint::resolve(config).as_str().to_string()
    }

    #[test]
    fn bare_clickhouse_hosts_get_the_canonical_port_for_the_scheme() {
        for (secure, expected) in [
            (false, "http://clickhouse.internal:8123"),
            (true, "https://clickhouse.internal:8443"),
        ] {
            let mut config = default_config();
            config.clickhouse_host = "clickhouse.internal".to_string();
            config.clickhouse_secure = secure;
            assert_eq!(endpoint(&config), expected);
        }

        let mut config = default_config();
        config.clickhouse_host = "fallback.internal".to_string();
        config.clickhouse_offline_cluster_host = "offline.internal".to_string();
        config.clickhouse_secure = true;
        assert_eq!(endpoint(&config), "https://offline.internal:8443");
    }

    #[test]
    fn explicit_clickhouse_urls_and_ports_are_preserved() {
        let mut config = default_config();
        config.clickhouse_url = "https://proxy.example:9440/clickhouse".to_string();
        assert_eq!(endpoint(&config), "https://proxy.example:9440/clickhouse");

        config.clickhouse_url.clear();
        config.clickhouse_host = "clickhouse.internal:9000".to_string();
        config.clickhouse_secure = true;
        assert_eq!(endpoint(&config), "https://clickhouse.internal:9000");
    }

    #[test]
    fn join_algorithm_default_config_parses_and_round_trips() {
        assert_eq!(
            default_config()
                .seeder_ch_join_algorithm
                .parse::<ClickHouseJoinAlgorithm>()
                .unwrap(),
            ClickHouseJoinAlgorithm::GraceHash
        );
        for algorithm in [
            ClickHouseJoinAlgorithm::Default,
            ClickHouseJoinAlgorithm::Auto,
            ClickHouseJoinAlgorithm::Hash,
            ClickHouseJoinAlgorithm::ParallelHash,
            ClickHouseJoinAlgorithm::GraceHash,
            ClickHouseJoinAlgorithm::PartialMerge,
            ClickHouseJoinAlgorithm::PreferPartialMerge,
            ClickHouseJoinAlgorithm::FullSortingMerge,
            ClickHouseJoinAlgorithm::Direct,
        ] {
            assert_eq!(
                algorithm
                    .as_str()
                    .parse::<ClickHouseJoinAlgorithm>()
                    .unwrap(),
                algorithm
            );
        }
    }

    #[test]
    fn build_client_rejects_a_join_algorithm_typo_at_startup() {
        let mut config = default_config();
        config.seeder_ch_join_algorithm = "grace_hashh".to_string();
        assert_eq!(
            build_client(&config).err(),
            Some(UnknownJoinAlgorithm("grace_hashh".to_string()))
        );
    }
}
