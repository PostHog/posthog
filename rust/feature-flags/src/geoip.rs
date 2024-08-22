use maxminddb::Reader;
use once_cell::sync::Lazy;
use serde_json::Value;
use std::net::IpAddr;
use std::str::FromStr;
use std::{collections::HashMap, path::Path};
use tracing::log::{error, info};

static GEOIP: Lazy<Option<Reader<Vec<u8>>>> = Lazy::new(|| {
    // TODO this feels hacky, and should be configurable.  Maybe not worth doing?
    // Let's test it in CI
    let geoip_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("share")
        .join("GeoLite2-City.mmdb");

    info!("Attempting to open GeoIP database at: {:?}", geoip_path);

    match Reader::open_readfile(&geoip_path) {
        Ok(reader) => Some(reader),
        Err(e) => {
            error!("Failed to open GeoIP database at {:?}: {}", geoip_path, e);
            None
        }
    }
});

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

fn is_valid_ip(ip: &str) -> bool {
    // "127.0.0.1" would throw "The address 127.0.0.1 is not in the database."
    ip != "127.0.0.1" && GEOIP.is_some()
}

fn lookup_city(ip: &str, addr: IpAddr) -> Option<Value> {
    GEOIP
        .as_ref()
        .and_then(|reader| match reader.lookup::<Value>(addr) {
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
        })
}

fn extract_properties(city: &Value) -> HashMap<String, String> {
    GEOIP_FIELDS
        .iter()
        .filter_map(|&(field, path)| {
            get_nested_value(city, path).map(|value| (field.to_string(), value.to_string()))
        })
        .collect()
}

/// Returns a dictionary of geoip properties for the given ip address.
///
/// Contains the following:
///    - $geoip_city_name
///    - $geoip_country_name
///    - $geoip_country_code
///    - $geoip_continent_name
///    - $geoip_continent_code
///    - $geoip_postal_code
///    - $geoip_time_zone
pub fn get_geoip_properties(ip_address: Option<&str>) -> HashMap<String, String> {
    match ip_address {
        None => {
            info!("No IP address provided; returning empty properties");
            HashMap::new()
        }
        Some(ip) if !is_valid_ip(ip) => {
            info!("Returning empty properties for IP: {}", ip);
            HashMap::new()
        }
        Some(ip) => match IpAddr::from_str(ip) {
            Ok(addr) => lookup_city(ip, addr)
                .map(|city| extract_properties(&city))
                .unwrap_or_else(|| {
                    error!("GeoIP reader is None; lookup for IP {} skipped", ip);
                    HashMap::new()
                }),
            Err(_) => {
                error!("Invalid IP address: {}", ip);
                HashMap::new()
            }
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Once;

    static INIT: Once = Once::new();

    fn initialize() {
        INIT.call_once(|| {
            tracing_subscriber::fmt::init();
        });
    }

    #[test]
    fn test_get_geoip_properties_none() {
        initialize();
        let result = get_geoip_properties(None);
        assert!(result.is_empty());
    }

    #[test]
    fn test_get_geoip_properties_localhost() {
        initialize();
        let result = get_geoip_properties(Some("127.0.0.1"));
        assert!(result.is_empty());
    }

    #[test]
    fn test_get_geoip_properties_invalid_ip() {
        initialize();
        let result = get_geoip_properties(Some("not_an_ip"));
        assert!(result.is_empty());
    }

    #[test]
    fn test_geoip_results() {
        initialize();
        let test_cases = vec![
            ("13.106.122.3", "Australia"),
            ("31.28.64.3", "United Kingdom"),
            ("2600:6c52:7a00:11c:1b6:b7b0:ea19:6365", "United States"),
        ];

        for (ip, expected_country) in test_cases {
            let result = get_geoip_properties(Some(ip));
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
    fn test_geoip_with_invalid_database_file() {
        initialize();
        let result = get_geoip_properties(Some("0.0.0.0"));
        assert!(result.is_empty());
    }

    #[test]
    fn test_geoip_on_local_ip() {
        initialize();
        let result = get_geoip_properties(Some("127.0.0.1"));
        assert!(result.is_empty());
    }

    #[test]
    fn test_geoip_on_invalid_ip() {
        initialize();
        let result = get_geoip_properties(Some("999.999.999.999"));
        assert!(result.is_empty());
    }
}
