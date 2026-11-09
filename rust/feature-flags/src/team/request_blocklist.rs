//! A team's blocklist for `/flags` and `/decide` callers, matched by caller host or client IP.
//!
//! Django validates and normalizes both lists on write and puts them in the team metadata
//! cache. This module parses the lists each time a team is deserialized, which happens on
//! every request, so the matchers themselves do no parsing.

use crate::utils::cidr::{parse_cidr, ParsedCidr};
use axum::http::HeaderMap;
use serde::{Deserialize, Serialize};
use std::net::IpAddr;

/// Why the blocklist refused a request. It is a metric label, so the set stays closed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BlockReason {
    Host,
    Ip,
}

impl BlockReason {
    pub fn as_str(self) -> &'static str {
        match self {
            BlockReason::Host => "host",
            BlockReason::Ip => "ip",
        }
    }
}

/// The host of the `Origin` header, or of `Referer` when `Origin` is missing or opaque
/// (browsers send `Origin: null` from sandboxed frames and `file://` pages).
pub fn origin_host(headers: &HeaderMap) -> Option<String> {
    ["origin", "referer"].into_iter().find_map(|name| {
        let value = headers.get(name)?.to_str().ok()?;
        let url = url::Url::parse(value).ok()?;
        let host = url.host_str()?.trim_end_matches('.');
        (!host.is_empty()).then(|| host.to_ascii_lowercase())
    })
}

/// Hostnames. An entry blocks the host itself and all of its subdomains.
#[derive(Clone, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(from = "Vec<String>", into = "Vec<String>")]
pub struct BlockedHosts(Vec<String>);

impl From<Vec<String>> for BlockedHosts {
    fn from(entries: Vec<String>) -> Self {
        Self(
            entries
                .into_iter()
                .map(|entry| entry.trim().trim_end_matches('.').to_ascii_lowercase())
                .filter(|entry| !entry.is_empty())
                .collect(),
        )
    }
}

impl From<BlockedHosts> for Vec<String> {
    fn from(hosts: BlockedHosts) -> Self {
        hosts.0
    }
}

impl BlockedHosts {
    /// `host` must already be lowercase, as [`origin_host`] returns it.
    pub fn matches(&self, host: &str) -> bool {
        self.0.iter().any(|entry| {
            host == entry
                || (host.len() > entry.len()
                    && host.ends_with(entry.as_str())
                    && host.as_bytes()[host.len() - entry.len() - 1] == b'.')
        })
    }
}

/// Single addresses or CIDR ranges. `entries` keeps the stored strings so the team
/// serializes back to the cache shape it came from.
#[derive(Clone, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(from = "Vec<String>", into = "Vec<String>")]
pub struct BlockedIps {
    entries: Vec<String>,
    ranges: Vec<ParsedCidr>,
}

impl From<Vec<String>> for BlockedIps {
    fn from(entries: Vec<String>) -> Self {
        let ranges = entries
            .iter()
            .filter_map(|entry| {
                let parsed = parse_ip_entry(entry.trim());
                if parsed.is_none() {
                    // Django rejects invalid entries on write, so this is a row written by
                    // another path. One bad entry must not disable the rest of the list.
                    // The list is parsed on every request, so a warning would repeat for
                    // every request while the bad entry stays stored.
                    tracing::debug!(entry = %entry, "skipping invalid blocked IP entry");
                }
                parsed
            })
            .collect();
        Self { entries, ranges }
    }
}

impl From<BlockedIps> for Vec<String> {
    fn from(ips: BlockedIps) -> Self {
        ips.entries
    }
}

impl BlockedIps {
    pub fn matches(&self, ip: IpAddr) -> bool {
        self.ranges.iter().any(|range| range.contains(ip))
    }

    /// Consumes `ips` only when the list has a range, so a team without IP entries does
    /// not pay for parsing the caller's addresses.
    pub fn matches_any(&self, ips: impl IntoIterator<Item = IpAddr>) -> bool {
        !self.ranges.is_empty() && ips.into_iter().any(|ip| self.matches(ip))
    }
}

fn parse_ip_entry(entry: &str) -> Option<ParsedCidr> {
    if entry.contains('/') {
        return parse_cidr(entry);
    }
    entry.parse().ok().map(ParsedCidr::single)
}

/// Host first: when both match, `host` is the more specific answer for support.
/// `client_ips` are all the addresses the request carries. The caller can add addresses
/// but cannot remove the one our edge appended, so a match on any of them blocks.
pub fn check(
    hosts: &BlockedHosts,
    ips: &BlockedIps,
    origin_host: Option<&str>,
    client_ips: impl IntoIterator<Item = IpAddr>,
) -> Option<BlockReason> {
    if origin_host.is_some_and(|host| hosts.matches(host)) {
        return Some(BlockReason::Host);
    }
    if ips.matches_any(client_ips) {
        return Some(BlockReason::Ip);
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;
    use rstest::rstest;

    fn headers(pairs: &[(&'static str, &'static str)]) -> HeaderMap {
        let mut map = HeaderMap::new();
        for (name, value) in pairs {
            map.insert(*name, HeaderValue::from_static(value));
        }
        map
    }

    fn hosts(entries: &[&str]) -> BlockedHosts {
        BlockedHosts::from(entries.iter().map(|e| e.to_string()).collect::<Vec<_>>())
    }

    fn ips(entries: &[&str]) -> BlockedIps {
        BlockedIps::from(entries.iter().map(|e| e.to_string()).collect::<Vec<_>>())
    }

    #[rstest]
    #[case(&[("origin", "https://App.Example.com:8443")], Some("app.example.com"))]
    #[case(&[("origin", "null"), ("referer", "https://example.com/page?q=1")], Some("example.com"))]
    #[case(&[("referer", "https://www.example.org/")], Some("www.example.org"))]
    #[case(&[("origin", "https://example.com"), ("referer", "https://example.org/")], Some("example.com"))]
    #[case(&[("origin", "http://[2001:db8::1]:8000")], Some("[2001:db8::1]"))]
    #[case(&[("origin", "not a url")], None)]
    #[case(&[], None)]
    fn origin_host_reads_origin_then_referer(
        #[case] pairs: &[(&'static str, &'static str)],
        #[case] expected: Option<&str>,
    ) {
        assert_eq!(origin_host(&headers(pairs)).as_deref(), expected);
    }

    #[rstest]
    #[case("example.com", true)]
    #[case("app.example.com", true)]
    #[case("a.b.example.com", true)]
    #[case("notexample.com", false)]
    #[case("example.com.evil.test", false)]
    #[case("example.org", false)]
    fn host_entry_blocks_itself_and_subdomains(#[case] host: &str, #[case] blocked: bool) {
        assert_eq!(hosts(&["Example.com."]).matches(host), blocked);
    }

    #[rstest]
    #[case("203.0.113.7", "203.0.113.7", true)]
    #[case("203.0.113.7", "203.0.113.8", false)]
    #[case("198.51.100.0/24", "198.51.100.255", true)]
    #[case("198.51.100.0/24", "198.51.101.0", false)]
    #[case("2001:db8::1", "2001:db8::1", true)]
    #[case("2001:db8::1", "2001:db8::2", false)]
    #[case("2001:db8:abcd::/48", "2001:db8:abcd:12::1", true)]
    #[case("2001:db8:abcd::/48", "2001:db8:abce::1", false)]
    #[case("203.0.113.7", "::ffff:203.0.113.7", true)]
    #[case("198.51.100.0/24", "2001:db8::1", false)]
    fn ip_entry_matches_addresses_and_ranges(
        #[case] entry: &str,
        #[case] client_ip: &str,
        #[case] blocked: bool,
    ) {
        assert_eq!(ips(&[entry]).matches(client_ip.parse().unwrap()), blocked);
    }

    #[test]
    fn invalid_ip_entry_is_skipped_and_the_rest_still_match() {
        let list = ips(&["not-an-ip", "203.0.113.0/40", "198.51.100.9"]);

        assert!(list.matches("198.51.100.9".parse().unwrap()));
        assert!(!list.matches("203.0.113.1".parse().unwrap()));
    }

    #[rstest]
    #[case(Some("app.example.com"), &["203.0.113.7"], Some(BlockReason::Host))]
    #[case(Some("example.org"), &["203.0.113.7"], Some(BlockReason::Ip))]
    #[case(None, &["203.0.113.7"], Some(BlockReason::Ip))]
    #[case(None, &["192.0.2.1", "203.0.113.7"], Some(BlockReason::Ip))]
    #[case(Some("example.org"), &["198.51.100.1"], None)]
    #[case(None, &["198.51.100.1", "192.0.2.1"], None)]
    fn check_reports_host_before_ip(
        #[case] host: Option<&str>,
        #[case] client_ips: &[&str],
        #[case] expected: Option<BlockReason>,
    ) {
        let reason = check(
            &hosts(&["example.com"]),
            &ips(&["203.0.113.7"]),
            host,
            client_ips.iter().map(|ip| ip.parse().unwrap()),
        );

        assert_eq!(reason, expected);
    }
}
