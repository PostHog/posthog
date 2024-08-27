use crate::config::Config;
use maxminddb::Reader;
use serde_json::Value;
use std::collections::HashMap;
use std::net::IpAddr;
use std::str::FromStr;
use thiserror::Error;
use tracing::log::{error, info};

#[derive(Error, Debug)]
pub enum GeoIpError {
    #[error("Failed to open GeoIP database: {0}")]
    DatabaseOpenError(#[from] maxminddb::MaxMindDBError),
}

pub struct GeoIpClient {
    reader: Reader<Vec<u8>>,
}

impl GeoIpClient {
    /// Creates a new GeoIpClient instance.
    /// Returns an error if the database can't be loaded.
    pub fn new(config: &Config) -> Result<Self, GeoIpError> {
        let geoip_path = config.get_maxmind_db_path();

        info!("Attempting to open GeoIP database at: {:?}", geoip_path);

        let reader = Reader::open_readfile(&geoip_path)?;
        info!("Successfully opened GeoIP database");

        Ok(GeoIpClient { reader })
    }

    /// Checks if the given IP address is valid.
    fn is_valid_ip(&self, ip: &str) -> bool {
        ip != "127.0.0.1" || ip != "::1"
    }

    /// Looks up the city data for the given IP address.
    /// Returns None if the lookup fails.
    fn lookup_city(&self, ip: &str, addr: IpAddr) -> Option<Value> {
        match self.reader.lookup::<Value>(addr) {
            Ok(city) => {
                info!(
                    "GeoIP lookup succeeded for IP {}: Full city data: {:?}",
                    ip, city
                );
                Some(city)
            }
            Err(e) => {
                error!("GeoIP lookup error for IP {}: {}", ip, e);
                None
            }
        }
    }

    /// Returns a dictionary of geoip properties for the given ip address.
    pub fn get_geoip_properties(&self, ip_address: Option<&str>) -> HashMap<String, String> {
        match ip_address {
            None => {
                info!("No IP address provided; returning empty properties");
                HashMap::new()
            }
            Some(ip) if !self.is_valid_ip(ip) => {
                info!("Returning empty properties for IP: {}", ip);
                HashMap::new()
            }
            Some(ip) => match IpAddr::from_str(ip) {
                Ok(addr) => self
                    .lookup_city(ip, addr)
                    .map(|city| extract_properties(&city))
                    .unwrap_or_default(),
                Err(_) => {
                    error!("Invalid IP address: {}", ip);
                    HashMap::new()
                }
            },
        }
    }
}

const GEOIP_FIELDS: [(&str, &[&str]); 7] = [
    ("$geoip_country_name", &["country", "names", "en"]),
    ("$geoip_city_name", &["city", "names", "en"]),
    ("$geoip_country_code", &["country", "iso_code"]),
    ("$geoip_continent_name", &["continent", "names", "en"]),
    ("$geoip_continent_code", &["continent", "code"]),
    ("$geoip_postal_code", &["postal", "code"]),
    ("$geoip_time_zone", &["location", "time_zone"]),
];

fn get_nested_value<'a>(data: &'a Value, path: &[&str]) -> Option<&'a str> {
    let mut current = data;
    for &key in path {
        current = current.get(key)?;
    }
    current.as_str()
}

fn extract_properties(city: &Value) -> HashMap<String, String> {
    GEOIP_FIELDS
        .iter()
        .filter_map(|&(field, path)| {
            get_nested_value(city, path).map(|value| (field.to_string(), value.to_string()))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::config::Config;
    use std::sync::Once;

    static INIT: Once = Once::new();

    fn initialize() {
        INIT.call_once(|| {
            tracing_subscriber::fmt::init();
        });
    }

    fn create_test_service() -> GeoIpClient {
        let config = Config::default_test_config();
        GeoIpClient::new(&config).expect("Failed to create GeoIpService")
    }

    #[test]
    fn test_geoip_service_creation() {
        initialize();
        let config = Config::default_test_config();
        let service_result = GeoIpClient::new(&config);
        assert!(service_result.is_ok());
    }

    #[test]
    fn test_geoip_service_creation_failure() {
        initialize();
        let mut config = Config::default_test_config();
        config.maxmind_db_path = "/path/to/nonexistent/file".to_string();
        let service_result = GeoIpClient::new(&config);
        assert!(service_result.is_err());
    }

    #[test]
    fn test_get_geoip_properties_none() {
        initialize();
        let service = create_test_service();
        let result = service.get_geoip_properties(None);
        assert!(result.is_empty());
    }

    #[test]
    fn test_get_geoip_properties_localhost() {
        initialize();
        let service = create_test_service();
        let result = service.get_geoip_properties(Some("127.0.0.1"));
        assert!(result.is_empty());
    }

    #[test]
    fn test_get_geoip_properties_invalid_ip() {
        initialize();
        let service = create_test_service();
        let result = service.get_geoip_properties(Some("not_an_ip"));
        assert!(result.is_empty());
    }

    #[test]
    fn test_geoip_results() {
        initialize();
        let service = create_test_service();
        let test_cases = vec![
            ("13.106.122.3", "Australia"),
            ("31.28.64.3", "United Kingdom"),
            ("2600:6c52:7a00:11c:1b6:b7b0:ea19:6365", "United States"),
        ];

        for (ip, expected_country) in test_cases {
            let result = service.get_geoip_properties(Some(ip));
            info!("GeoIP lookup result for IP {}: {:?}", ip, result);
            info!(
                "Expected country: {}, Actual country: {:?}",
                expected_country,
                result.get("$geoip_country_name")
            );
            assert_eq!(
                result.get("$geoip_country_name"),
                Some(&expected_country.to_string())
            );
            assert_eq!(result.len(), 7);
        }
    }

    #[test]
    fn test_geoip_on_local_ip() {
        initialize();
        let service = create_test_service();
        let result = service.get_geoip_properties(Some("127.0.0.1"));
        assert!(result.is_empty());
    }

    #[test]
    fn test_geoip_on_invalid_ip() {
        initialize();
        let service = create_test_service();
        let result = service.get_geoip_properties(Some("999.999.999.999"));
        assert!(result.is_empty());
    }

    #[test]
    fn test_get_nested_value() {
        let data = json!({
            "country": {
                "names": {
                    "en": "United States"
                }
            },
            "city": {
                "names": {
                    "en": "New York"
                }
            },
            "postal": {
                "code": "10001"
            }
        });

        assert_eq!(
            get_nested_value(&data, &["country", "names", "en"]),
            Some("United States")
        );
        assert_eq!(
            get_nested_value(&data, &["city", "names", "en"]),
            Some("New York")
        );
        assert_eq!(get_nested_value(&data, &["postal", "code"]), Some("10001"));
        assert_eq!(get_nested_value(&data, &["country", "code"]), None);
        assert_eq!(get_nested_value(&data, &["nonexistent", "path"]), None);
    }

    #[test]
    fn test_extract_properties() {
        let city_data = json!({
            "country": {
                "names": {
                    "en": "United States"
                },
                "iso_code": "US"
            },
            "city": {
                "names": {
                    "en": "New York"
                }
            },
            "continent": {
                "names": {
                    "en": "North America"
                },
                "code": "NA"
            },
            "postal": {
                "code": "10001"
            },
            "location": {
                "time_zone": "America/New_York"
            }
        });

        let properties = extract_properties(&city_data);

        assert_eq!(
            properties.get("$geoip_country_name"),
            Some(&"United States".to_string())
        );
        assert_eq!(
            properties.get("$geoip_city_name"),
            Some(&"New York".to_string())
        );
        assert_eq!(
            properties.get("$geoip_country_code"),
            Some(&"US".to_string())
        );
        assert_eq!(
            properties.get("$geoip_continent_name"),
            Some(&"North America".to_string())
        );
        assert_eq!(
            properties.get("$geoip_continent_code"),
            Some(&"NA".to_string())
        );
        assert_eq!(
            properties.get("$geoip_postal_code"),
            Some(&"10001".to_string())
        );
        assert_eq!(
            properties.get("$geoip_time_zone"),
            Some(&"America/New_York".to_string())
        );
        assert_eq!(properties.len(), 7);
    }
}
