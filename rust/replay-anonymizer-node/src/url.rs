//! URL scrub. `None` means "unchanged".
//!
//! URLs pass through intact — domain, port, path, query, and fragment are all preserved — with
//! two exceptions:
//!
//! - Userinfo (`user:pass@`) is stripped from the authority. When the authority is structurally
//!   invalid (e.g. an unencoded `?` in userinfo makes `user:pa` parse as the host), the
//!   credentials cannot be safely located, so everything from the authority on is redacted
//!   instead of passed through.
//! - Emails are redacted — the pipeline's guaranteed email pass, same as every other string
//!   position; a `mailto:` href or an email in a query parameter must not pass through verbatim.
//! - A `data:` URI is inlined content, not a location: the payload is redacted, keeping the mime
//!   header. (Data-images on media tags never reach here — they take the blur path.)

use crate::text::redact_emails;

pub fn scrub_url(input: &str) -> Option<String> {
    if let Some(rest) = input.strip_prefix("data:") {
        let header = rest.split(',').next().unwrap_or("");
        return Some(format!("data:{header},[redacted]"));
    }
    let stripped = strip_userinfo(input);
    let text: &str = stripped.as_deref().unwrap_or(input);
    match redact_emails(text) {
        Some(redacted) => Some(redacted),
        None => stripped,
    }
}

/// `Some` when userinfo was removed (or the authority was invalid and redacted); `None` when
/// unchanged. Only `scheme://` and protocol-relative `//` forms carry an authority; everything
/// else (relative paths, `mailto:`, `tel:`, free text) has no credentials position and passes.
fn strip_userinfo(input: &str) -> Option<String> {
    let (scheme, rest) = split_scheme(input)?;
    let authority_end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    let authority = &rest[..authority_end];
    let (host_port, had_userinfo) = match authority.rfind('@') {
        Some(at) => (&authority[at + 1..], true),
        None => (authority, false),
    };
    if !is_valid_host_port(host_port) {
        return Some(format!("{scheme}[redacted]"));
    }
    had_userinfo.then(|| format!("{scheme}{host_port}{}", &rest[authority_end..]))
}

// The scheme prefix (incl. `://` or `//`) and the rest, for inputs that carry an authority.
fn split_scheme(s: &str) -> Option<(&str, &str)> {
    if let Some(scheme_end) = s
        .find("://")
        .filter(|&scheme_end| is_valid_scheme(&s[..scheme_end]))
    {
        Some((&s[..scheme_end + 3], &s[scheme_end + 3..]))
    } else {
        s.strip_prefix("//").map(|rest| (&s[..2], rest))
    }
}

fn is_valid_scheme(prefix: &str) -> bool {
    let bytes = prefix.as_bytes();
    match bytes.split_first() {
        Some((&first, rest)) => {
            first.is_ascii_alphabetic()
                && rest
                    .iter()
                    .all(|&b| b.is_ascii_alphanumeric() || matches!(b, b'+' | b'-' | b'.'))
        }
        None => false,
    }
}

// Host or `[ipv6]`, with an optional `:digits` port.
fn is_valid_host_port(host_port: &str) -> bool {
    let host = match host_port.split_once(':') {
        None => host_port,
        Some(_) if host_port.starts_with('[') => match host_port.rfind(']') {
            Some(close) => {
                let bracketed = &host_port[1..close];
                let port = &host_port[close + 1..];
                let port_ok = port.is_empty()
                    || (port.starts_with(':')
                        && port.len() > 1
                        && port[1..].bytes().all(|b| b.is_ascii_digit()));
                return port_ok
                    && bracketed
                        .bytes()
                        .all(|b| b.is_ascii_hexdigit() || b == b':' || b == b'.');
            }
            None => return false,
        },
        Some((host, port)) => {
            if port.is_empty() || !port.bytes().all(|b| b.is_ascii_digit()) {
                return false;
            }
            host
        }
    };
    host.bytes()
        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
}
