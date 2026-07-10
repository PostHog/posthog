//! URL scrub. `None` means "unchanged".
//!
//! - Numbers (a bare run of digits) are masked to `$` per digit (length-preserving; `$` rather than
//!   `#` so it doesn't clash with the fragment separator).
//! - Path: keep allow-listed segments; a number -> `$$`; anything else -> `[redacted]`.
//! - Query: a param survives only if its key or value is an allow-listed alphanumeric token.
//! - Fragment: kept only if it is an allow-listed alphanumeric token.
//! - Userinfo (`user:pass@`) is always stripped from the authority.
//! - A scheme without slashes (`mailto:`, `tel:`) is kept; the rest is scrubbed as a path.
//! - With `collapse_host`, or when the host matches the context's first-party host patterns
//!   (the team's recording domains), it additionally drops the port and collapses the host to
//!   `example.com` (keeping a leading allow-listed subdomain label).

use crate::allow_lists::AllowLists;
use crate::context::Ctx;

pub const URL_ALLOWLIST: &[&str] = &["about:blank", "about:srcdoc"];

fn strip_port(host: &mut String) {
    if let Some(ci) = host.rfind(':') {
        let after = &host[ci + 1..];
        if !after.is_empty() && after.bytes().all(|b| b.is_ascii_digit()) {
            host.truncate(ci);
        }
    }
}

fn is_first_party_host(ctx: &Ctx<'_>, host_port: &str) -> bool {
    if ctx.first_party_hosts.is_empty() {
        return false;
    }
    let mut host = host_port.to_ascii_lowercase();
    strip_port(&mut host);
    ctx.first_party_hosts.iter().any(|pattern| {
        host == *pattern
            || (host.len() > pattern.len()
                && host.ends_with(pattern.as_str())
                && host.as_bytes()[host.len() - pattern.len() - 1] == b'.')
    })
}

pub fn scrub_url(ctx: &Ctx<'_>, input: &str) -> Option<String> {
    scrub_url_opts(ctx, input, false)
}

pub fn scrub_url_opts(ctx: &Ctx<'_>, input: &str, collapse_host: bool) -> Option<String> {
    let allow = ctx.allow;
    if URL_ALLOWLIST.contains(&input) {
        return None;
    }
    let tail_idx = input.find(['?', '#']);
    let (base, tail) = match tail_idx {
        Some(i) => (&input[..i], &input[i..]),
        None => (input, ""),
    };
    let mut changed = false;

    let (scheme, authority, path) = split_url(base);
    let mut out = String::with_capacity(input.len());
    out.push_str(scheme);
    if !authority.is_empty() {
        let host_port = match authority.rfind('@') {
            Some(at) => {
                changed = true;
                &authority[at + 1..]
            }
            None => authority,
        };
        if !is_valid_host_port(host_port) {
            // A structurally invalid "host" (e.g. an unencoded `?` in userinfo makes `user:pa`
            // parse as the authority) must not pass through as if it were a hostname.
            out.push_str("[redacted]");
            changed = true;
        } else if collapse_host || is_first_party_host(ctx, host_port) {
            let collapsed = collapsed_host(allow, host_port);
            if collapsed != host_port {
                changed = true;
            }
            out.push_str(&collapsed);
        } else {
            out.push_str(host_port);
        }
    }

    let mut first = true;
    for raw in path.split('/') {
        if first {
            first = false;
        } else {
            out.push('/');
        }
        if raw.is_empty() {
            continue;
        }
        if is_numeric(raw) {
            mask_number_into(raw, &mut out);
            changed = true;
        } else if is_safe_segment(raw) || allow.url_contains(raw) {
            out.push_str(raw);
        } else {
            out.push_str("[redacted]");
            changed = true;
        }
    }

    let tail_out = scrub_tail(allow, tail);
    if tail_out != tail {
        changed = true;
    }
    out.push_str(&tail_out);

    if changed {
        Some(out)
    } else {
        None
    }
}

fn scrub_tail(allow: &AllowLists, tail: &str) -> String {
    if tail.is_empty() {
        return String::new();
    }
    let starts_query = tail.as_bytes()[0] == b'?';
    let (query, frag) = if starts_query {
        match tail[1..].find('#') {
            Some(h) => (&tail[1..1 + h], &tail[1 + h + 1..]),
            None => (&tail[1..], ""),
        }
    } else {
        ("", &tail[1..]) // tail starts with '#'
    };

    let mut out = String::new();
    if starts_query {
        let mut kept: Vec<String> = Vec::new();
        for pair in query.split('&') {
            if pair.is_empty() {
                continue;
            }
            match pair.find('=') {
                None => {
                    if is_allowed(allow, pair) {
                        kept.push(pair.to_string());
                    }
                }
                Some(eq) => {
                    let key = &pair[..eq];
                    let value = &pair[eq + 1..];
                    // A param survives only if its key or (non-empty) value is an allow-listed token.
                    let key_ok = is_allowed(allow, key);
                    let value_ok = !value.is_empty() && is_allowed(allow, value);
                    if !key_ok && !value_ok {
                        continue;
                    }
                    let kr = render_token(allow, key).unwrap_or_else(|| "[key]".to_string());
                    let vr = if value.is_empty() {
                        String::new()
                    } else {
                        render_token(allow, value).unwrap_or_else(|| "[value]".to_string())
                    };
                    kept.push(format!("{kr}={vr}"));
                }
            }
        }
        if !kept.is_empty() {
            out.push('?');
            out.push_str(&kept.join("&"));
        }
    }
    if !frag.is_empty() && is_allowed(allow, frag) {
        out.push('#');
        out.push_str(frag);
    }
    out
}

// Drop the port and rewrite the host to example.com. Keep a leading *subdomain* label
// (only when there is one, i.e. >=3 labels) if it's url-allow-listed: `us.test.com` -> `us.example.com`.
fn collapsed_host(allow: &AllowLists, host_port: &str) -> String {
    let mut host = host_port;
    if let Some(ci) = host.rfind(':') {
        let after = &host[ci + 1..];
        if !after.is_empty() && after.bytes().all(|b| b.is_ascii_digit()) {
            host = &host[..ci];
        }
    }
    let labels: Vec<&str> = host.split('.').collect();
    let first = labels.first().copied().unwrap_or("");
    if labels.len() > 2 && !first.is_empty() && allow.url_contains(first) {
        format!("{first}.example.com")
    } else {
        "example.com".to_string()
    }
}

// Pinned by `tests/fixtures/url-scheme-allowlist.json` (see `tests/parity.rs`).
pub const URL_SCHEME_ALLOWLIST: &[&str] = &[
    // Web platform
    "about",
    "blob",
    "data",
    "file",
    "ftp",
    "geo",
    "javascript",
    "magnet",
    "mailto",
    "sms",
    "tel",
    "urn",
    "ws",
    "wss", // Microsoft
    "ms-access",
    "ms-excel",
    "ms-outlook",
    "ms-powerpoint",
    "ms-project",
    "ms-publisher",
    "ms-visio",
    "ms-word",
    "msteams",
    "onenote",
    "sip",
    "sips",
    "skype", // Google
    "comgooglemaps",
    "googlechrome",
    "googlegmail",
    "googlemaps", // Apple
    "facetime",
    "facetime-audio",
    "itms",
    "itms-apps",
    "maps",
    "music",
    "shortcuts",
    // Chat and social
    "bluesky",
    "callto",
    "discord",
    "fb",
    "fb-messenger",
    "instagram",
    "irc",
    "line",
    "linkedin",
    "matrix",
    "reddit",
    "sgnl",
    "slack",
    "snapchat",
    "telegram",
    "tg",
    "tiktok",
    "twitter",
    "viber",
    "wechat",
    "weixin",
    "whatsapp",
    "xmpp",
    // Media, payments, and tools
    "bitcoin",
    "bittorrent",
    "figma",
    "notion",
    "obsidian",
    "spotify",
    "steam",
    "vscode",
    "zoommtg",
    "zoomus",
];

fn scheme_without_slashes(s: &str) -> Option<usize> {
    let colon = s.find(':')?;
    let prefix = &s[..colon];
    if URL_SCHEME_ALLOWLIST
        .iter()
        .any(|scheme| prefix.eq_ignore_ascii_case(scheme))
    {
        Some(colon + 1)
    } else {
        None
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

// Split into scheme prefix (incl. `://` or `//`), authority (`[userinfo@]host[:port]`), and path.
fn split_url(s: &str) -> (&str, &str, &str) {
    let (scheme, rest) = if let Some(scheme_end) = s
        .find("://")
        .filter(|&scheme_end| is_valid_scheme(&s[..scheme_end]))
    {
        (&s[..scheme_end + 3], &s[scheme_end + 3..])
    } else if let Some(rest) = s.strip_prefix("//") {
        (&s[..2], rest)
    } else if let Some(end) = scheme_without_slashes(s) {
        // Free text before a colon (or before an embedded `://`) must not pass through as a
        // "scheme"; only allowlisted schemes survive, and only in the slashless form.
        return (&s[..end], "", &s[end..]);
    } else {
        return ("", "", s); // relative URL: all path
    };
    match rest.find('/') {
        None => (scheme, rest, ""),
        Some(path_off) => (scheme, &rest[..path_off], &rest[path_off..]),
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

fn is_safe_segment(seg: &str) -> bool {
    matches!(seg, "" | "." | "..")
}

// `$`, not `#` (the fragment separator).
fn mask_number_into(n: &str, out: &mut String) {
    for _ in 0..n.len() {
        out.push('$');
    }
}

fn is_numeric(t: &str) -> bool {
    !t.is_empty() && t.bytes().all(|b| b.is_ascii_digit())
}

// 100% alphanumeric (empty allowed).
fn is_simple(t: &str) -> bool {
    t.bytes().all(|b| b.is_ascii_alphanumeric())
}

// An allow-listed, alphanumeric, non-number token — the only kind that keeps a query param/fragment
// alive.
fn is_allowed(allow: &AllowLists, t: &str) -> bool {
    !t.is_empty() && is_simple(t) && !is_numeric(t) && allow.url_contains(t)
}

// Rendered form of a surviving token: a number -> `$$`, an allow-listed token -> itself, else None.
fn render_token(allow: &AllowLists, t: &str) -> Option<String> {
    if is_numeric(t) {
        let mut s = String::with_capacity(t.len());
        mask_number_into(t, &mut s);
        Some(s)
    } else if is_allowed(allow, t) {
        Some(t.to_string())
    } else {
        None
    }
}
