//! URL scrub. Mirrors `anonymize/url.ts`. `None` means "unchanged".
//!
//! - Numbers (a bare run of digits) are masked to `$` per digit (length-preserving; `$` rather than
//!   `#` so it doesn't clash with the fragment separator).
//! - Path: keep allow-listed segments; a number -> `$$`; anything else -> `[redacted]`.
//! - Query: a param survives only if its key or value is an allow-listed alphanumeric token.
//! - Fragment: kept only if it is an allow-listed alphanumeric token.
//! - Userinfo (`user:pass@`) is always stripped from the authority.
//! - A scheme without slashes (`mailto:`, `tel:`) is kept; the rest is scrubbed as a path.
//! - With `collapse_host` it additionally drops the port and collapses the host to
//!   `example.com` (keeping a leading allow-listed subdomain label).

use crate::allow_lists::AllowLists;

// Spec-defined, entropy-free literals (rrweb's blank/srcdoc iframe placeholders): redacting them
// only costs replay fidelity. Exact matches only.
pub const PASSTHROUGH_URLS: &[&str] = &["about:blank", "about:srcdoc"];

pub fn scrub_url(allow: &AllowLists, input: &str) -> Option<String> {
    scrub_url_opts(allow, input, false)
}

pub fn scrub_url_opts(allow: &AllowLists, input: &str, collapse_host: bool) -> Option<String> {
    if PASSTHROUGH_URLS.contains(&input) {
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
        if collapse_host {
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

// RFC 3986 scheme, e.g. `mailto:`, `tel:`.
fn scheme_without_slashes(s: &str) -> Option<usize> {
    let colon = s.find(':')?;
    let prefix = s[..colon].as_bytes();
    let (&first, rest) = prefix.split_first()?;
    if first.is_ascii_alphabetic()
        && rest
            .iter()
            .all(|&b| b.is_ascii_alphanumeric() || matches!(b, b'+' | b'-' | b'.'))
    {
        Some(colon + 1)
    } else {
        None
    }
}

// Split into scheme prefix (incl. `://` or `//`), authority (`[userinfo@]host[:port]`), and path.
fn split_url(s: &str) -> (&str, &str, &str) {
    let (scheme, rest) = if let Some(scheme_end) = s.find("://") {
        (&s[..scheme_end + 3], &s[scheme_end + 3..])
    } else if let Some(rest) = s.strip_prefix("//") {
        (&s[..2], rest)
    } else if let Some(end) = scheme_without_slashes(s) {
        // No slashes, no authority: everything after the scheme scrubs as a path.
        return (&s[..end], "", &s[end..]);
    } else {
        return ("", "", s); // relative URL: all path
    };
    match rest.find('/') {
        None => (scheme, rest, ""),
        Some(path_off) => (scheme, &rest[..path_off], &rest[path_off..]),
    }
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
