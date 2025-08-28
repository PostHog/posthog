use maxminddb::Reader;
use serde_json::Value;
use std::net::IpAddr;
use std::str::FromStr;
use std::{collections::HashMap, path::PathBuf};
use thiserror::Error;
use tracing::debug;

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
    pub fn new(db_path: PathBuf) -> Result<Self, GeoIpError> {
        debug!("Attempting to open GeoIP database at: {:?}", db_path);

        let reader = Reader::open_readfile(&db_path)?;
        info!("Successfully opened GeoIP database");

        Ok(GeoIpClient { reader })
    }

    /// Checks if the given IP address is valid.
    fn parse_ip(&self, ip: &str) -> Option<IpAddr> {
        let res = IpAddr::from_str(ip).ok()?;

        if res.is_loopback() {
            None
        } else {
            Some(res)
        }
    }

    /// Returns a dictionary of geoip properties for the given ip address.
    pub fn get_geoip_properties(&self, ip: &str) -> Option<HashMap<String, String>> {
        let ip = self.parse_ip(ip)?;

        self.reader
            .lookup::<Value>(ip)
            .map(|city| extract_properties(&city))
            .ok()
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
    use std::path::Path;

    fn get_db_path() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("share")
            .join("GeoLite2-City.mmdb")
    }

    fn create_test_service() -> GeoIpClient {
        GeoIpClient::new(get_db_path()).expect("Failed to create GeoIpService")
    }

    #[test]
    fn test_geoip_service_creation() {
        let service_result = GeoIpClient::new(get_db_path());
        assert!(service_result.is_ok());
    }

    #[test]
    fn test_geoip_service_creation_failure() {
        let service_result = GeoIpClient::new(PathBuf::from("/non/existant/path"));
        assert!(service_result.is_err());
    }

    #[test]
    fn test_get_geoip_properties_localhost() {
        let service = create_test_service();
        let result = service.get_geoip_properties("127.0.0.1");
        assert!(result.is_none());
    }

    #[test]
    fn test_get_geoip_properties_invalid_ip() {
        let service = create_test_service();
        let result = service.get_geoip_properties("not_an_ip");
        assert!(result.is_none());
    }

    #[test]
    fn test_geoip_results() {
        let service = create_test_service();
        let test_cases = vec![
            ("13.106.122.3", "Australia"),
            ("31.28.64.3", "United Kingdom"),
            ("2600:6c52:7a00:11c:1b6:b7b0:ea19:6365", "United States"),
            ("187.188.10.252", "Mexico"),
        ];

        for (ip, expected_country) in test_cases {
            let result = service.get_geoip_properties(ip).unwrap();
            println!("GeoIP lookup result for IP {ip}: {result:?}");
            println!(
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
        let service = create_test_service();
        let result = service.get_geoip_properties("127.0.0.1");
        assert!(result.is_none());
    }

    #[test]
    fn test_geoip_on_invalid_ip() {
        let service = create_test_service();
        let result = service.get_geoip_properties("999.999.999.999");
        assert!(result.is_none());
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
