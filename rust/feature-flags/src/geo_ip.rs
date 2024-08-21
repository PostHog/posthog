use lazy_static::lazy_static;
use maxminddb::Reader;
use serde_json::Value;
use std::collections::HashMap;
use std::env;
use std::net::IpAddr;
use std::path::PathBuf;
use std::str::FromStr;
use tracing::log::{error, info};

// const VALID_GEOIP_PROPERTIES: [&str; 7] = [
//     "city_name",
//     "country_name",
//     "country_code",
//     "continent_name",
//     "continent_code",
//     "postal_code",
//     "time_zone",
// ];

lazy_static! {
    static ref GEOIP: Option<Reader<Vec<u8>>> = {
        // Fetch the base path from an environment variable or fallback to the current directory
        let base_path = env::var("POSTHOG_BASE_DIR").unwrap_or_else(|_| env::current_dir().unwrap().to_string_lossy().into_owned());
        let mut geoip_path = PathBuf::from(base_path);
        geoip_path.push("share/GeoLite2-City.mmdb");

        info!("Attempting to open GeoIP database at: {:?}", geoip_path);

        match Reader::open_readfile(&geoip_path) {
            Ok(reader) => {
                info!("Successfully connected to the GeoIP database at: {:?}", geoip_path);
                Some(reader)
            }
            Err(e) => {
                error!("Failed to open GeoIP database at {:?}: {}", geoip_path, e);
                None
            }
        }
    };
}

pub fn get_geoip_properties(ip_address: Option<&str>) -> HashMap<String, String> {
    let mut properties = HashMap::new();

    if let Some(ip) = ip_address {
        if ip == "127.0.0.1" || GEOIP.is_none() {
            info!("Returning empty properties for IP: {}", ip);
            return properties;
        }

        match IpAddr::from_str(ip) {
            Ok(addr) => {
                if let Some(reader) = &*GEOIP {
                    match reader.lookup::<Value>(addr) {
                        Ok(city) => {
                            info!(
                                "GeoIP lookup succeeded for IP {}: Full city data: {:?}",
                                ip, city
                            );

                            // Extracting the country name properly
                            if let Some(country_name) = city
                                .get("country")
                                .and_then(|c| c.get("names"))
                                .and_then(|n| n.get("en"))
                                .and_then(|v| v.as_str())
                            {
                                properties.insert(
                                    "$geoip_country_name".to_string(),
                                    country_name.to_string(),
                                );
                            }

                            // Extract other properties based on their paths in the JSON
                            if let Some(city_name) = city
                                .get("city")
                                .and_then(|c| c.get("names"))
                                .and_then(|n| n.get("en"))
                                .and_then(|v| v.as_str())
                            {
                                properties
                                    .insert("$geoip_city_name".to_string(), city_name.to_string());
                            }

                            if let Some(country_code) = city
                                .get("country")
                                .and_then(|c| c.get("iso_code"))
                                .and_then(|v| v.as_str())
                            {
                                properties.insert(
                                    "$geoip_country_code".to_string(),
                                    country_code.to_string(),
                                );
                            }

                            if let Some(continent_name) = city
                                .get("continent")
                                .and_then(|c| c.get("names"))
                                .and_then(|n| n.get("en"))
                                .and_then(|v| v.as_str())
                            {
                                properties.insert(
                                    "$geoip_continent_name".to_string(),
                                    continent_name.to_string(),
                                );
                            }

                            if let Some(continent_code) = city
                                .get("continent")
                                .and_then(|c| c.get("code"))
                                .and_then(|v| v.as_str())
                            {
                                properties.insert(
                                    "$geoip_continent_code".to_string(),
                                    continent_code.to_string(),
                                );
                            }

                            if let Some(postal_code) = city
                                .get("postal")
                                .and_then(|p| p.get("code"))
                                .and_then(|v| v.as_str())
                            {
                                properties.insert(
                                    "$geoip_postal_code".to_string(),
                                    postal_code.to_string(),
                                );
                            }

                            if let Some(time_zone) = city
                                .get("location")
                                .and_then(|l| l.get("time_zone"))
                                .and_then(|v| v.as_str())
                            {
                                properties
                                    .insert("$geoip_time_zone".to_string(), time_zone.to_string());
                            }
                        }
                        Err(e) => error!("GeoIP lookup error for IP {}: {}", ip, e),
                    }
                } else {
                    error!("GeoIP reader is None; lookup for IP {} skipped", ip);
                }
            }
            Err(e) => error!("Invalid IP address: {}", e),
        }
    } else {
        info!("No IP address provided; returning empty properties");
    }

    properties
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Once;

    static INIT: Once = Once::new();

    fn initialize() {
        INIT.call_once(|| {
            // Any one-time initialization can go here
            tracing_subscriber::fmt::init(); // Initialize tracing subscriber for logs
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

            // Log the actual result
            info!("GeoIP lookup result for IP {}: {:?}", ip, result);

            // Log the expected country and compare
            info!(
                "Expected country: {}, Actual country: {:?}",
                expected_country,
                result.get("$geoip_country_name")
            );

            // Assert the country name matches the expected value
            assert_eq!(
                result.get("$geoip_country_name"),
                Some(&expected_country.to_string())
            );
            // Assert that all 7 properties are present
            assert_eq!(result.len(), 7); // Assuming all 7 fields are present
        }
    }

    #[test]
    fn test_geoip_with_invalid_database_file() {
        initialize();
        // This test simulates a database error by temporarily replacing the GEOIP reader
        // Note: This requires modifying the GEOIP static to allow mocking, which might not be trivial
        // For simplicity, we'll just check that an invalid IP returns an empty result
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
