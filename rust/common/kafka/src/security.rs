use std::{fmt, str::FromStr};

use envconfig::Envconfig;
use rdkafka::{error::KafkaError, ClientConfig};

#[derive(Clone, Default)]
pub struct KafkaCredential(String);

impl FromStr for KafkaCredential {
    type Err = std::convert::Infallible;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Ok(Self(value.to_owned()))
    }
}

impl fmt::Debug for KafkaCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("***")
    }
}

impl KafkaCredential {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Envconfig, Clone, Debug, Default)]
pub struct KafkaSecurityConfig {
    pub kafka_security_protocol: Option<String>,
    pub kafka_sasl_mechanism: Option<String>,
    pub kafka_sasl_user: Option<String>,
    #[envconfig(from = "KAFKA_SASL_PASSWORD")]
    pub kafka_sasl_password: Option<KafkaCredential>,
}

impl KafkaSecurityConfig {
    pub fn apply(&self, config: &mut ClientConfig, tls: bool) {
        if let Some(protocol) = self
            .kafka_security_protocol
            .as_deref()
            .filter(|value| !value.is_empty())
        {
            config.set("security.protocol", protocol.to_ascii_lowercase());
        } else if tls {
            config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }
        let protocol = config.get("security.protocol").unwrap_or("plaintext");
        if !protocol.eq_ignore_ascii_case("sasl_plaintext")
            && !protocol.eq_ignore_ascii_case("sasl_ssl")
        {
            return;
        }
        if let Some(mechanism) = self.kafka_sasl_mechanism.as_deref() {
            config.set("sasl.mechanisms", mechanism.to_ascii_uppercase());
        }
        if let Some(username) = self.kafka_sasl_user.as_deref() {
            config.set("sasl.username", username);
        }
        if let Some(password) = &self.kafka_sasl_password {
            config.set("sasl.password", password.as_str());
        }
    }
}

pub fn validate_security_config(config: &ClientConfig) -> Result<(), KafkaError> {
    let protocol = config.get("security.protocol").unwrap_or("plaintext");
    if !protocol.eq_ignore_ascii_case("sasl_plaintext")
        && !protocol.eq_ignore_ascii_case("sasl_ssl")
    {
        return Ok(());
    }
    let mechanism = config
        .get("sasl.mechanisms")
        .or_else(|| config.get("sasl.mechanism"))
        .unwrap_or("GSSAPI");
    if ["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"]
        .iter()
        .any(|supported| mechanism.eq_ignore_ascii_case(supported))
    {
        for key in ["sasl.username", "sasl.password"] {
            if config.get(key).map_or(true, str::is_empty) {
                return Err(KafkaError::ClientCreation(format!(
                    "{key} is required for username/password Kafka authentication"
                )));
            }
        }
    }
    Ok(())
}

pub fn redacted_config(config: &ClientConfig) -> impl fmt::Debug + '_ {
    config
        .config_map()
        .iter()
        .map(|(key, value)| {
            let sensitive =
                key.contains("password") || key.contains("secret") || key.ends_with(".pem");
            (key, if sensitive { "***" } else { value.as_str() })
        })
        .collect::<std::collections::BTreeMap<_, _>>()
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    #[rstest::rstest]
    #[case("sasl_plaintext", "plain")]
    #[case("SASL_SSL", "PLAIN")]
    #[case("sasl_plaintext", "scram-sha-256")]
    #[case("SASL_SSL", "SCRAM-SHA-256")]
    #[case("sasl_plaintext", "scram-sha-512")]
    #[case("SASL_SSL", "SCRAM-SHA-512")]
    fn authenticated_config_preserves_credentials(#[case] protocol: &str, #[case] mechanism: &str) {
        let env = HashMap::from([
            ("KAFKA_SECURITY_PROTOCOL".to_owned(), protocol.to_owned()),
            ("KAFKA_SASL_MECHANISM".to_owned(), mechanism.to_owned()),
            ("KAFKA_SASL_USER".to_owned(), "00123".to_owned()),
            ("KAFKA_SASL_PASSWORD".to_owned(), " false:$! ".to_owned()),
        ]);
        let security = KafkaSecurityConfig::init_from_hashmap(&env).unwrap();
        let mut config = ClientConfig::new();
        security.apply(&mut config, true);
        validate_security_config(&config).unwrap();
        assert_eq!(
            config.get("security.protocol"),
            Some(protocol.to_ascii_lowercase().as_str())
        );
        assert_eq!(
            config.get("sasl.mechanisms"),
            Some(mechanism.to_ascii_uppercase().as_str())
        );
        assert_eq!(config.get("sasl.username"), Some("00123"));
        assert_eq!(config.get("sasl.password"), Some(" false:$! "));
        assert_ne!(
            config.get("enable.ssl.certificate.verification"),
            Some("false")
        );
        assert!(!format!("{security:?}").contains("false:$!"));
        assert!(!format!("{:?}", redacted_config(&config)).contains("false:$!"));
    }

    #[rstest::rstest]
    #[case("sasl.username")]
    #[case("sasl.password")]
    fn missing_credentials_fail_without_disclosing_values(#[case] missing: &str) {
        let mut config = ClientConfig::new();
        config
            .set("security.protocol", "sasl_ssl")
            .set("sasl.mechanisms", "SCRAM-SHA-512")
            .set("sasl.username", "example-user")
            .set("sasl.password", "fake-kafka-credential")
            .set(missing, "");
        let error = validate_security_config(&config).unwrap_err().to_string();
        assert!(error.contains(missing));
        assert!(!error.contains("fake-kafka-credential"));
    }

    #[rstest::rstest]
    #[case(None, false, None)]
    #[case(None, true, Some("ssl"))]
    #[case(Some("PLAINTEXT"), true, Some("plaintext"))]
    fn legacy_protocol_defaults_remain_unchanged(
        #[case] protocol: Option<&str>,
        #[case] tls: bool,
        #[case] expected: Option<&str>,
    ) {
        let security = KafkaSecurityConfig {
            kafka_security_protocol: protocol.map(str::to_owned),
            kafka_sasl_mechanism: Some("PLAIN".to_owned()),
            kafka_sasl_user: Some("example-user".to_owned()),
            kafka_sasl_password: Some("fake-kafka-credential".parse().unwrap()),
        };
        let mut config = ClientConfig::new();
        security.apply(&mut config, tls);
        validate_security_config(&config).unwrap();
        assert_eq!(config.get("security.protocol"), expected);
        assert_eq!(config.get("sasl.password"), None);
    }
}
