//! Addresses in the `X-Forwarded-For` header.
//!
//! Each proxy appends the address of its peer, so the entries on the right come from our
//! edge and the entries on the left come from the caller, who can write any value there.

use axum::http::{HeaderMap, HeaderName};
use std::net::IpAddr;

const X_FORWARDED_FOR: HeaderName = HeaderName::from_static("x-forwarded-for");

/// The chains that reach the flags service have a few entries, and a caller can send any number.
pub const MAX_FORWARDED_ADDRESSES: usize = 20;

/// Parses one entry. An entry can carry a port (`203.0.113.7:8080`, `[2001:db8::1]:8080`),
/// which some gateways (Azure) add.
pub fn parse_entry(entry: &str) -> Option<IpAddr> {
    let trimmed = entry.trim();

    let ip_without_port = if trimmed.starts_with('[') {
        // IPv6 with port (e.g., "[::1]:8080")
        trimmed
            .split(']')
            .next()
            .and_then(|s| s.strip_prefix('['))
            .unwrap_or(trimmed)
    } else if trimmed.contains('.') {
        // Likely IPv4 - check for port after the last dot
        match (trimmed.rfind(':'), trimmed.rfind('.')) {
            // Port comes after the last dot, so this is IPv4:port
            (Some(colon_idx), Some(last_dot_idx)) if colon_idx > last_dot_idx => {
                &trimmed[..colon_idx]
            }
            _ => trimmed,
        }
    } else {
        // No dots and no brackets - assume IPv6 without port
        // IPv6 can have colons as part of the address, so don't strip
        trimmed
    };

    ip_without_port.parse().ok()
}

/// Right to left, so that padding on the left cannot push the entries our edge appended
/// past [`MAX_FORWARDED_ADDRESSES`]. The header lookup waits for the first `next`, so a
/// caller that never reads the addresses pays nothing.
pub fn addresses(headers: &HeaderMap) -> impl Iterator<Item = IpAddr> + '_ {
    std::iter::once_with(|| headers.get_all(X_FORWARDED_FOR))
        .flat_map(|values| values.into_iter().rev())
        // Split the bytes, not a `str`, because a caller can add non-ASCII bytes to the
        // value that our edge appends to, and `to_str` would reject the whole value.
        .flat_map(|value| value.as_bytes().rsplit(|&byte| byte == b','))
        .take(MAX_FORWARDED_ADDRESSES)
        .filter_map(|entry| parse_entry(std::str::from_utf8(entry).ok()?))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;
    use rstest::rstest;

    fn ips(entries: &[&str]) -> Vec<IpAddr> {
        entries.iter().map(|e| e.parse().unwrap()).collect()
    }

    #[rstest]
    #[case::single(&["203.0.113.7"], &["203.0.113.7"])]
    #[case::right_to_left(&["192.0.2.1, 203.0.113.7,10.0.0.1"], &["10.0.0.1", "203.0.113.7", "192.0.2.1"])]
    #[case::later_header_first(&["192.0.2.1", "203.0.113.7"], &["203.0.113.7", "192.0.2.1"])]
    #[case::ports(&["[2001:db8::1]:8080, 203.0.113.7:443"], &["203.0.113.7", "2001:db8::1"])]
    #[case::invalid_entries_skipped(&["junk, , 203.0.113.7"], &["203.0.113.7"])]
    #[case::empty(&[""], &[])]
    fn addresses_reads_entries_from_the_right(
        #[case] values: &[&'static str],
        #[case] expected: &[&str],
    ) {
        let mut headers = HeaderMap::new();
        for value in values {
            headers.append("x-forwarded-for", HeaderValue::from_static(value));
        }

        assert_eq!(addresses(&headers).collect::<Vec<_>>(), ips(expected));
    }

    #[test]
    fn addresses_keeps_appended_entries_when_the_left_side_is_padded() {
        let padding = vec!["192.0.2.1"; 100].join(", ");
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-forwarded-for",
            HeaderValue::from_str(&format!("{padding}, 203.0.113.7,10.0.0.1")).unwrap(),
        );

        let read = addresses(&headers).collect::<Vec<_>>();

        assert_eq!(read.len(), MAX_FORWARDED_ADDRESSES);
        assert_eq!(read[..2], ips(&["10.0.0.1", "203.0.113.7"]));
    }

    #[test]
    fn addresses_reads_entries_next_to_non_ascii_bytes() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-forwarded-for",
            HeaderValue::from_bytes(b"\xff\xfe, 203.0.113.7").unwrap(),
        );

        assert_eq!(
            addresses(&headers).collect::<Vec<_>>(),
            ips(&["203.0.113.7"])
        );
    }
}
