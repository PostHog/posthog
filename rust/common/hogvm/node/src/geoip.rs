//! GeoIP City lookups shaped like @maxmind/geoip2-node's City model (camelCase keys), which is
//! what the Node VM hands to hog code.

use std::collections::BTreeMap;
use std::net::IpAddr;
use std::sync::OnceLock;

use maxminddb::geoip2;
use serde_json::{json, Map, Value};

static GEOIP: OnceLock<maxminddb::Reader<Vec<u8>>> = OnceLock::new();

/// Open the mmdb once at `init`; later calls are ignored.
pub fn init_geoip(path: &str) -> Result<(), String> {
    if GEOIP.get().is_none() {
        let reader = maxminddb::Reader::open_readfile(path)
            .map_err(|e| format!("failed to open mmdb at {path}: {e}"))?;
        let _ = GEOIP.set(reader);
    }
    Ok(())
}

pub fn is_initialized() -> bool {
    GEOIP.get().is_some()
}

/// City lookup returning the geoip2-node-shaped record, or None the way the Node side returns
/// null (unparsable IP, record not found).
pub fn lookup(ip: &str) -> Option<Value> {
    let reader = GEOIP.get()?;
    let ip = ip.parse::<IpAddr>().ok()?;
    let (city, prefix_len) = reader.lookup_prefix::<geoip2::City>(ip).ok()?;
    Some(city_to_json(&city, ip, prefix_len))
}

// Only fields present in the record are emitted, except `traits`, which geoip2-node always emits
// with false-defaulted flags plus ipAddress/network.
fn city_to_json(city: &geoip2::City, ip: IpAddr, prefix_len: usize) -> Value {
    let mut out = Map::new();

    if let Some(c) = &city.city {
        let mut obj = Map::new();
        insert_some(&mut obj, "geonameId", c.geoname_id.map(|v| json!(v)));
        insert_some(&mut obj, "names", names_to_json(&c.names));
        insert_obj(&mut out, "city", obj);
    }
    if let Some(c) = &city.continent {
        let mut obj = Map::new();
        insert_some(&mut obj, "code", c.code.map(|v| json!(v)));
        insert_some(&mut obj, "geonameId", c.geoname_id.map(|v| json!(v)));
        insert_some(&mut obj, "names", names_to_json(&c.names));
        insert_obj(&mut out, "continent", obj);
    }
    if let Some(c) = &city.country {
        insert_obj(&mut out, "country", country_to_map(c));
    }
    if let Some(c) = &city.registered_country {
        insert_obj(&mut out, "registeredCountry", country_to_map(c));
    }
    if let Some(l) = &city.location {
        let mut obj = Map::new();
        insert_some(
            &mut obj,
            "accuracyRadius",
            l.accuracy_radius.map(|v| json!(v)),
        );
        insert_some(&mut obj, "latitude", l.latitude.map(|v| json!(v)));
        insert_some(&mut obj, "longitude", l.longitude.map(|v| json!(v)));
        insert_some(&mut obj, "metroCode", l.metro_code.map(|v| json!(v)));
        insert_some(&mut obj, "timeZone", l.time_zone.map(|v| json!(v)));
        insert_obj(&mut out, "location", obj);
    }
    if let Some(p) = &city.postal {
        let mut obj = Map::new();
        insert_some(&mut obj, "code", p.code.map(|v| json!(v)));
        insert_obj(&mut out, "postal", obj);
    }
    if let Some(subdivisions) = &city.subdivisions {
        let subs: Vec<Value> = subdivisions
            .iter()
            .map(|s| {
                let mut obj = Map::new();
                insert_some(&mut obj, "geonameId", s.geoname_id.map(|v| json!(v)));
                insert_some(&mut obj, "isoCode", s.iso_code.map(|v| json!(v)));
                insert_some(&mut obj, "names", names_to_json(&s.names));
                Value::Object(obj)
            })
            .collect();
        if !subs.is_empty() {
            out.insert("subdivisions".to_string(), Value::Array(subs));
        }
    }
    out.insert(
        "traits".to_string(),
        traits_to_json(city.traits.as_ref(), ip, prefix_len),
    );

    Value::Object(out)
}

fn traits_to_json(traits: Option<&geoip2::city::Traits>, ip: IpAddr, prefix_len: usize) -> Value {
    let is_anonymous_proxy = traits.and_then(|t| t.is_anonymous_proxy).unwrap_or(false);
    let is_satellite_provider = traits
        .and_then(|t| t.is_satellite_provider)
        .unwrap_or(false);
    json!({
        "isAnonymous": false,
        "isAnonymousProxy": is_anonymous_proxy,
        "isAnonymousVpn": false,
        "isHostingProvider": false,
        "isLegitimateProxy": false,
        "isPublicProxy": false,
        "isResidentialProxy": false,
        "isSatelliteProvider": is_satellite_provider,
        "isTorExitNode": false,
        "ipAddress": ip.to_string(),
        "network": network_string(ip, prefix_len),
    })
}

// The CIDR of the mmdb record that matched the lookup, normalized to the network address the way
// geoip2-node reports it (e.g. "89.160.0.0/17").
fn network_string(ip: IpAddr, prefix_len: usize) -> String {
    let masked = match ip {
        IpAddr::V4(v4) => {
            let bits = u32::from(v4);
            let mask = if prefix_len == 0 {
                0
            } else {
                u32::MAX << (32 - prefix_len as u32)
            };
            IpAddr::V4((bits & mask).into())
        }
        IpAddr::V6(v6) => {
            let bits = u128::from(v6);
            let mask = if prefix_len == 0 {
                0
            } else {
                u128::MAX << (128 - prefix_len as u32)
            };
            IpAddr::V6((bits & mask).into())
        }
    };
    format!("{masked}/{prefix_len}")
}

fn country_to_map(country: &geoip2::city::Country) -> Map<String, Value> {
    let mut obj = Map::new();
    insert_some(&mut obj, "geonameId", country.geoname_id.map(|v| json!(v)));
    insert_some(
        &mut obj,
        "isInEuropeanUnion",
        country.is_in_european_union.map(|v| json!(v)),
    );
    insert_some(&mut obj, "isoCode", country.iso_code.map(|v| json!(v)));
    insert_some(&mut obj, "names", names_to_json(&country.names));
    obj
}

fn names_to_json(names: &Option<BTreeMap<&str, &str>>) -> Option<Value> {
    names.as_ref().map(|names| {
        Value::Object(
            names
                .iter()
                .map(|(locale, name)| (locale.to_string(), json!(name)))
                .collect(),
        )
    })
}

fn insert_some(obj: &mut Map<String, Value>, key: &str, value: Option<Value>) {
    if let Some(value) = value {
        obj.insert(key.to_string(), value);
    }
}

fn insert_obj(out: &mut Map<String, Value>, key: &str, obj: Map<String, Value>) {
    if !obj.is_empty() {
        out.insert(key.to_string(), Value::Object(obj));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn network_string_masks_to_the_record_prefix() {
        assert_eq!(
            network_string("89.160.20.129".parse().unwrap(), 17),
            "89.160.0.0/17"
        );
        assert_eq!(network_string("1.2.3.4".parse().unwrap(), 32), "1.2.3.4/32");
        assert_eq!(network_string("1.2.3.4".parse().unwrap(), 0), "0.0.0.0/0");
        assert_eq!(
            network_string("2001:db8:1234::1".parse().unwrap(), 32),
            "2001:db8::/32"
        );
    }
}
