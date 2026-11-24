//! A team's request lists for `/flags` and `/decide` callers, matched by caller host or client IP.
//!
//! Django validates and normalizes the lists on write and puts them in the team metadata
//! cache. This module parses the lists each time a team is deserialized, which happens on
//! every request, so the matchers themselves do no parsing.

use crate::utils::cidr::{parse_cidr, ParsedCidr};
use axum::http::{header, HeaderMap};
use serde::{Deserialize, Serialize};
use std::net::IpAddr;

/// Why the request lists refused a request. It is a metric label, so the set stays closed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BlockReason {
    Host,
    Ip,
    HostNotAllowed,
    IpNotAllowed,
    IpUnverified,
}

impl BlockReason {
    pub fn as_str(self) -> &'static str {
        match self {
            BlockReason::Host => "host",
            BlockReason::Ip => "ip",
            BlockReason::HostNotAllowed => "host_not_allowed",
            BlockReason::IpNotAllowed => "ip_not_allowed",
            BlockReason::IpUnverified => "ip_unverified",
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CallerHost<'a> {
    Absent,
    Opaque,
    Named(&'a str),
}

impl<'a> CallerHost<'a> {
    pub fn new(origin_host: Option<&'a str>, headers: &HeaderMap) -> Self {
        match origin_host {
            Some(host) => Self::Named(host),
            None if headers.contains_key(header::ORIGIN)
                || headers.contains_key(header::REFERER) =>
            {
                Self::Opaque
            }
            None => Self::Absent,
        }
    }
}

/// Hostnames. An entry matches the host itself and all of its subdomains.
#[derive(Clone, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(from = "Vec<String>", into = "Vec<String>")]
pub struct HostList(Vec<String>);

impl From<Vec<String>> for HostList {
    fn from(entries: Vec<String>) -> Self {
        Self(
            entries
                .into_iter()
                .map(|entry| entry.trim().trim_end_matches('.').to_ascii_lowercase())
                .collect(),
        )
    }
}

impl From<HostList> for Vec<String> {
    fn from(hosts: HostList) -> Self {
        hosts.0
    }
}

impl HostList {
    /// Counts blank entries, which match no host, so an allowed list of blank entries refuses
    /// every host.
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    /// `host` must already be lowercase, as [`origin_host`] returns it.
    pub fn matches(&self, host: &str) -> bool {
        self.0
            .iter()
            .filter(|entry| !entry.is_empty())
            .any(|entry| {
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
pub struct IpList {
    entries: Vec<String>,
    ranges: Vec<ParsedCidr>,
}

impl From<Vec<String>> for IpList {
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
                    tracing::debug!(entry = %entry, "skipping invalid IP entry");
                }
                parsed
            })
            .collect();
        Self { entries, ranges }
    }
}

impl From<IpList> for Vec<String> {
    fn from(ips: IpList) -> Self {
        ips.entries
    }
}

impl IpList {
    /// Counts the stored entries, not the ones that parsed, so an allowed list of invalid
    /// entries refuses every caller.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

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

pub struct RequestLists<'a> {
    pub blocked_hosts: &'a HostList,
    pub blocked_ips: &'a IpList,
    pub allowed_hosts: &'a HostList,
    pub allowed_ips: &'a IpList,
}

impl RequestLists<'_> {
    /// Blocked entries come first, so a blocked entry wins over an allowed one. Host comes
    /// before IP: when both match, `host` is the more specific answer for support.
    ///
    /// `client_ips` are all the addresses the request carries. The caller can add addresses
    /// but cannot remove the one our edge appended, so a match on any of them blocks.
    pub fn check(
        &self,
        host: CallerHost<'_>,
        client_ips: impl IntoIterator<Item = IpAddr>,
        edge_ip: Option<IpAddr>,
    ) -> Option<BlockReason> {
        if let CallerHost::Named(name) = host {
            if self.blocked_hosts.matches(name) {
                return Some(BlockReason::Host);
            }
        }
        if self.blocked_ips.matches_any(client_ips) {
            return Some(BlockReason::Ip);
        }
        if !self.allows_host(host) {
            return Some(BlockReason::HostNotAllowed);
        }
        self.edge_ip_refusal(edge_ip)
    }

    /// Server-side and mobile SDKs send no `Origin` or `Referer`, so an absent host passes. A
    /// page from any site can send an opaque host, so it fails.
    fn allows_host(&self, host: CallerHost<'_>) -> bool {
        self.allowed_hosts.is_empty()
            || match host {
                CallerHost::Absent => true,
                CallerHost::Opaque => false,
                CallerHost::Named(name) => self.allowed_hosts.matches(name),
            }
    }

    /// Reads only the edge address, because a caller can write an allowed one in
    /// `X-Forwarded-For`.
    fn edge_ip_refusal(&self, edge_ip: Option<IpAddr>) -> Option<BlockReason> {
        if self.allowed_ips.is_empty() {
            return None;
        }
        match edge_ip {
            None => Some(BlockReason::IpUnverified),
            Some(ip) if self.allowed_ips.matches(ip) => None,
            Some(_) => Some(BlockReason::IpNotAllowed),
        }
    }
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

    fn hosts(entries: &[&str]) -> HostList {
        HostList::from(entries.iter().map(|e| e.to_string()).collect::<Vec<_>>())
    }

    fn ips(entries: &[&str]) -> IpList {
        IpList::from(entries.iter().map(|e| e.to_string()).collect::<Vec<_>>())
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
    #[case::blank_hosts(&["", " . "], &[], BlockReason::HostNotAllowed)]
    #[case::invalid_ips(&[], &["not-an-ip"], BlockReason::IpNotAllowed)]
    fn allowed_list_without_a_valid_entry_refuses_the_caller(
        #[case] allowed_hosts: &[&str],
        #[case] allowed_ips: &[&str],
        #[case] expected: BlockReason,
    ) {
        let (no_hosts, no_ips) = (hosts(&[]), ips(&[]));
        let (allowed_hosts, allowed_ips) = (hosts(allowed_hosts), ips(allowed_ips));
        let lists = RequestLists {
            blocked_hosts: &no_hosts,
            blocked_ips: &no_ips,
            allowed_hosts: &allowed_hosts,
            allowed_ips: &allowed_ips,
        };

        let edge_ip = Some("203.0.113.7".parse().unwrap());
        let host = CallerHost::Named("example.com");
        let reason = lists.check(host, std::iter::empty(), edge_ip);

        assert_eq!(reason, Some(expected));
    }

    #[rstest]
    #[case(&[("origin", "https://example.com")], CallerHost::Named("example.com"))]
    #[case(&[("origin", "null")], CallerHost::Opaque)]
    #[case(&[("referer", "not a url")], CallerHost::Opaque)]
    #[case(&[], CallerHost::Absent)]
    fn caller_host_tells_opaque_from_absent(
        #[case] pairs: &[(&'static str, &'static str)],
        #[case] expected: CallerHost<'static>,
    ) {
        let headers = headers(pairs);
        let host = origin_host(&headers);

        assert_eq!(CallerHost::new(host.as_deref(), &headers), expected);
    }

    #[rstest]
    #[case(CallerHost::Named("app.example.com"), &["203.0.113.7"], Some(BlockReason::Host))]
    #[case(CallerHost::Named("example.org"), &["203.0.113.7"], Some(BlockReason::Ip))]
    #[case(CallerHost::Absent, &["203.0.113.7"], Some(BlockReason::Ip))]
    #[case(CallerHost::Opaque, &["192.0.2.1", "203.0.113.7"], Some(BlockReason::Ip))]
    #[case(CallerHost::Named("example.org"), &["198.51.100.1"], None)]
    #[case(CallerHost::Absent, &["198.51.100.1", "192.0.2.1"], None)]
    fn check_reports_host_before_ip(
        #[case] host: CallerHost<'static>,
        #[case] client_ips: &[&str],
        #[case] expected: Option<BlockReason>,
    ) {
        let (blocked_hosts, blocked_ips) = (hosts(&["example.com"]), ips(&["203.0.113.7"]));
        let empty = (hosts(&[]), ips(&[]));
        let lists = RequestLists {
            blocked_hosts: &blocked_hosts,
            blocked_ips: &blocked_ips,
            allowed_hosts: &empty.0,
            allowed_ips: &empty.1,
        };

        let reason = lists.check(host, client_ips.iter().map(|ip| ip.parse().unwrap()), None);

        assert_eq!(reason, expected);
    }

    #[rstest]
    #[case::allowed_subdomain(CallerHost::Named("app.example.com"), None)]
    #[case::other_host(CallerHost::Named("example.org"), Some(BlockReason::HostNotAllowed))]
    #[case::opaque_host(CallerHost::Opaque, Some(BlockReason::HostNotAllowed))]
    #[case::no_host_header(CallerHost::Absent, None)]
    #[case::blocked_wins(CallerHost::Named("blocked.example.com"), Some(BlockReason::Host))]
    fn check_allowed_hosts(
        #[case] host: CallerHost<'static>,
        #[case] expected: Option<BlockReason>,
    ) {
        let (blocked_hosts, allowed_hosts) =
            (hosts(&["blocked.example.com"]), hosts(&["example.com"]));
        let no_ips = ips(&[]);
        let lists = RequestLists {
            blocked_hosts: &blocked_hosts,
            blocked_ips: &no_ips,
            allowed_hosts: &allowed_hosts,
            allowed_ips: &no_ips,
        };

        let reason = lists.check(host, std::iter::empty(), None);

        assert_eq!(reason, expected);
    }

    #[rstest]
    #[case::allowed_edge_ip(&[], Some("203.0.113.7"), None)]
    #[case::other_edge_ip(&[], Some("198.51.100.1"), Some(BlockReason::IpNotAllowed))]
    #[case::no_edge_ip(&["203.0.113.7"], None, Some(BlockReason::IpUnverified))]
    #[case::allowed_ip_only_in_forwarded_for(&["203.0.113.7"], Some("198.51.100.1"), Some(BlockReason::IpNotAllowed))]
    #[case::blocked_wins(&["203.0.113.66"], Some("203.0.113.66"), Some(BlockReason::Ip))]
    fn check_allowed_ips_reads_only_the_edge_ip(
        #[case] client_ips: &[&str],
        #[case] edge_ip: Option<&str>,
        #[case] expected: Option<BlockReason>,
    ) {
        let (blocked_ips, allowed_ips) = (ips(&["203.0.113.66"]), ips(&["203.0.113.0/24"]));
        let no_hosts = hosts(&[]);
        let lists = RequestLists {
            blocked_hosts: &no_hosts,
            blocked_ips: &blocked_ips,
            allowed_hosts: &no_hosts,
            allowed_ips: &allowed_ips,
        };

        let reason = lists.check(
            CallerHost::Absent,
            client_ips.iter().map(|ip| ip.parse().unwrap()),
            edge_ip.map(|ip| ip.parse().unwrap()),
        );

        assert_eq!(reason, expected);
    }
}
