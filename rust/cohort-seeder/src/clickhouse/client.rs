//! ClickHouse client construction: endpoint precedence, the TLS posture, and the typed
//! `join_algorithm` setting.
//!
//! Depends on `config` for the raw env strings; every value that shapes a ClickHouse query option is
//! parsed here so a misconfiguration fails startup instead of silently degrading query behavior.

use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client as HyperClient;
use hyper_util::rt::TokioExecutor;
use rustls::client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier};
use rustls::crypto::{aws_lc_rs, verify_tls12_signature, verify_tls13_signature, CryptoProvider};
use rustls::pki_types::pem::{self, PemObject};
use rustls::pki_types::{CertificateDer, ServerName, UnixTime};
use rustls::{ClientConfig, DigitallySignedStruct, SignatureScheme};

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

#[derive(Debug, thiserror::Error)]
pub enum ClickHouseClientError {
    #[error(transparent)]
    JoinAlgorithm(#[from] UnknownJoinAlgorithm),
    #[error("building the ClickHouse TLS configuration")]
    Tls(#[from] rustls::Error),
    #[error("reading the ClickHouse CA bundle at {path}")]
    CaBundleUnreadable {
        path: String,
        #[source]
        source: pem::Error,
    },
    #[error("the ClickHouse CA bundle at {path} contains no certificates")]
    CaBundleEmpty { path: String },
}

// Copied from the `clickhouse` crate's own default HTTP client so the unverified-TLS client differs
// from the crate default in certificate verification and nothing else. The idle timeout has to stay
// well under ClickHouse's server-side keep-alive, or the pool hands out sockets the server has closed.
const TCP_KEEPALIVE: Duration = Duration::from_secs(60);
const POOL_IDLE_TIMEOUT: Duration = Duration::from_secs(2);

/// Accepts any server certificate, delegating only the handshake-signature checks to the crypto
/// provider. Selected by `CLICKHOUSE_VERIFY=false`, the posture every Python ClickHouse consumer in
/// the fleet already runs: PostHog's ClickHouse serves certificates from a per-environment internal
/// CA, and no Kubernetes workload carries that trust anchor today, so real chain validation could
/// only ever fail.
///
/// The wire stays encrypted, which is what keeps the ClickHouse password off the network, but the
/// server is *not* authenticated: anything that can redirect traffic on the service network can
/// impersonate ClickHouse, collect the credentials, and serve forged rows. Set `CLICKHOUSE_CA` to
/// the environment's internal CA to close that gap — [`pinned_ca_tls_config`] then takes over and
/// this verifier is never constructed.
#[derive(Debug)]
struct AcceptAnyServerCert(Arc<CryptoProvider>);

impl ServerCertVerifier for AcceptAnyServerCert {
    fn verify_server_cert(
        &self,
        _end_entity: &CertificateDer<'_>,
        _intermediates: &[CertificateDer<'_>],
        _server_name: &ServerName<'_>,
        _ocsp_response: &[u8],
        _now: UnixTime,
    ) -> Result<ServerCertVerified, rustls::Error> {
        Ok(ServerCertVerified::assertion())
    }

    fn verify_tls12_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        verify_tls12_signature(
            message,
            cert,
            dss,
            &self.0.signature_verification_algorithms,
        )
    }

    fn verify_tls13_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        verify_tls13_signature(
            message,
            cert,
            dss,
            &self.0.signature_verification_algorithms,
        )
    }

    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        self.0.signature_verification_algorithms.supported_schemes()
    }
}

/// Validates the server against `ca_path` alone, keeping hostname verification. This is the only
/// mode that authenticates the ClickHouse server, so prefer it wherever the CA reaches the pod.
fn pinned_ca_tls_config(ca_path: &str) -> Result<ClientConfig, ClickHouseClientError> {
    let mut roots = rustls::RootCertStore::empty();
    for certificate in CertificateDer::pem_file_iter(ca_path).map_err(|source| {
        ClickHouseClientError::CaBundleUnreadable {
            path: ca_path.to_string(),
            source,
        }
    })? {
        let certificate =
            certificate.map_err(|source| ClickHouseClientError::CaBundleUnreadable {
                path: ca_path.to_string(),
                source,
            })?;
        roots.add(certificate)?;
    }
    if roots.is_empty() {
        return Err(ClickHouseClientError::CaBundleEmpty {
            path: ca_path.to_string(),
        });
    }

    Ok(
        ClientConfig::builder_with_provider(Arc::new(aws_lc_rs::default_provider()))
            .with_safe_default_protocol_versions()?
            .with_root_certificates(roots)
            .with_no_client_auth(),
    )
}

/// Skips certificate validation entirely. The crate's own `rustls-tls` feature hardwires the bundled
/// Mozilla public roots (`webpki-roots`) and ignores the container trust store, so this is the only
/// way to express verify-off — the posture the rest of the fleet runs against internal ClickHouse.
fn unverified_tls_config() -> Result<ClientConfig, rustls::Error> {
    let provider = Arc::new(aws_lc_rs::default_provider());
    Ok(ClientConfig::builder_with_provider(provider.clone())
        .with_safe_default_protocol_versions()?
        .dangerous()
        .with_custom_certificate_verifier(Arc::new(AcceptAnyServerCert(provider)))
        .with_no_client_auth())
}

fn client_with_tls_config(tls_config: ClientConfig) -> clickhouse::Client {
    let mut http_connector = HttpConnector::new();
    http_connector.set_keepalive(Some(TCP_KEEPALIVE));
    // The connector must pass https:// URLs through to the TLS layer below.
    http_connector.enforce_http(false);

    let connector = hyper_rustls::HttpsConnectorBuilder::new()
        .with_tls_config(tls_config)
        .https_or_http()
        .enable_http1()
        .wrap_connector(http_connector);

    clickhouse::Client::with_http_client(
        HyperClient::builder(TokioExecutor::new())
            .pool_idle_timeout(POOL_IDLE_TIMEOUT)
            .build(connector),
    )
}

pub fn build_client(config: &Config) -> Result<clickhouse::Client, ClickHouseClientError> {
    let join_algorithm = config
        .seeder_ch_join_algorithm
        .parse::<ClickHouseJoinAlgorithm>()?;
    // Ordered most to least trusted: a pinned CA authenticates the server, public roots authenticate
    // it only for publicly-issued certificates, and verify-off authenticates nothing.
    let client = if !config.clickhouse_ca.is_empty() {
        client_with_tls_config(pinned_ca_tls_config(&config.clickhouse_ca)?)
    } else if config.clickhouse_verify {
        clickhouse::Client::default()
    } else {
        client_with_tls_config(unverified_tls_config()?)
    };
    Ok(client
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
        assert!(matches!(
            build_client(&config),
            Err(ClickHouseClientError::JoinAlgorithm(UnknownJoinAlgorithm(algorithm)))
                if algorithm == "grace_hashh"
        ));
    }

    #[test]
    fn build_client_assembles_a_tls_stack_for_both_verify_modes() {
        for verify in [true, false] {
            let mut config = default_config();
            config.clickhouse_secure = true;
            config.clickhouse_verify = verify;
            assert!(
                build_client(&config).is_ok(),
                "failed to build a client with CLICKHOUSE_VERIFY={verify}"
            );
        }
    }

    /// An unusable `CLICKHOUSE_CA` must crash the seeder, never silently degrade to a weaker mode:
    /// the whole point of naming a CA is to authenticate the server.
    #[test]
    fn an_unusable_ca_bundle_fails_startup_rather_than_downgrading() {
        let scratch = tempfile::tempdir().unwrap();
        let empty_bundle = scratch.path().join("empty_ca.pem");
        std::fs::write(&empty_bundle, b"not a certificate\n").unwrap();

        for (ca_path, expected) in [
            (
                "/nonexistent/ca.pem".to_string(),
                "reading the ClickHouse CA bundle",
            ),
            (
                empty_bundle.to_string_lossy().into_owned(),
                "contains no certificates",
            ),
        ] {
            let mut config = default_config();
            // Verify-off must not rescue a broken CA bundle.
            config.clickhouse_verify = false;
            config.clickhouse_ca = ca_path.clone();
            let Err(error) = build_client(&config) else {
                panic!("CA bundle {ca_path:?} unexpectedly produced a working client");
            };
            let error = error.to_string();
            assert!(
                error.contains(expected),
                "CA bundle {ca_path:?} gave {error:?}, expected it to mention {expected:?}"
            );
        }
    }
}
