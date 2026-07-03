// Copied from MLHog prep/labeling/src/scrub/url.rs — bench-only. Adapted: `crate::` import path
// points at `crate::mlhog::`.

//! URL scrub: keep allow-listed path/query/fragment tokens, mask numbers to `$`, redact the rest.
//! `scrub_authority` also strips userinfo/port and rewrites the host to example.com.

use crate::mlhog::context::Ctx;

#[allow(dead_code)]
pub fn scrub(ctx: &Ctx<'_>, input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    scrub_into(ctx, input, &mut out);
    out
}

pub fn scrub_into(ctx: &Ctx<'_>, input: &str, out: &mut String) -> bool {
    scrub_into_opts(ctx, input, out, false)
}

pub fn scrub_into_authority(ctx: &Ctx<'_>, input: &str, out: &mut String) -> bool {
    scrub_into_opts(ctx, input, out, true)
}

fn scrub_into_opts(ctx: &Ctx<'_>, input: &str, out: &mut String, scrub_authority: bool) -> bool {
    let tail_idx = input.find(['?', '#']);
    let base = match tail_idx {
        Some(i) => &input[..i],
        None => input,
    };
    let tail = match tail_idx {
        Some(i) => &input[i..],
        None => "",
    };
    let mut changed = false;

    let (scheme, authority, path) = split_url(base);
    out.push_str(scheme);
    if !authority.is_empty() {
        if scrub_authority {
            let scrubbed = scrub_host(ctx, authority);
            if scrubbed != authority {
                changed = true;
            }
            out.push_str(&scrubbed);
        } else {
            out.push_str(authority);
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
            mask_number_into(raw, out);
            changed = true;
        } else if is_safe_segment(raw) || ctx.allow.url_contains(raw) {
            out.push_str(raw);
        } else {
            out.push_str("[redacted]");
            changed = true;
        }
    }

    let tail_out = scrub_tail(ctx, tail);
    if tail_out != tail {
        changed = true;
    }
    out.push_str(&tail_out);

    changed
}

fn scrub_tail(ctx: &Ctx<'_>, tail: &str) -> String {
    if tail.is_empty() {
        return String::new();
    }
    let (query, frag) = if tail.starts_with('?') {
        match tail.find('#') {
            Some(h) => (&tail[1..h], &tail[h + 1..]),
            None => (&tail[1..], ""),
        }
    } else {
        ("", &tail[1..])
    };

    let mut out = String::new();
    if tail.starts_with('?') {
        let mut kept: Vec<String> = Vec::new();
        for pair in query.split('&') {
            if pair.is_empty() {
                continue;
            }
            match pair.find('=') {
                None => {
                    if is_allowed(ctx, pair) {
                        kept.push(pair.to_string());
                    }
                }
                Some(eq) => {
                    let key = &pair[..eq];
                    let value = &pair[eq + 1..];
                    if !is_allowed(ctx, key) && !(!value.is_empty() && is_allowed(ctx, value)) {
                        continue;
                    }
                    let kr = render_token(ctx, key).unwrap_or_else(|| "[key]".to_string());
                    let vr = if value.is_empty() {
                        String::new()
                    } else {
                        render_token(ctx, value).unwrap_or_else(|| "[value]".to_string())
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
    if !frag.is_empty() && is_allowed(ctx, frag) {
        out.push('#');
        out.push_str(frag);
    }
    out
}

fn scrub_host(ctx: &Ctx<'_>, authority: &str) -> String {
    let mut host = match authority.rfind('@') {
        Some(at) => &authority[at + 1..],
        None => authority,
    };
    if let Some(colon) = host.rfind(':') {
        let port = &host[colon + 1..];
        if !port.is_empty() && port.bytes().all(|b| b.is_ascii_digit()) {
            host = &host[..colon];
        }
    }
    let labels: Vec<&str> = host.split('.').collect();
    let first = labels.first().copied().unwrap_or("");
    if labels.len() > 2 && !first.is_empty() && ctx.allow.url_contains(first) {
        format!("{first}.example.com")
    } else {
        "example.com".to_string()
    }
}

fn split_url(s: &str) -> (&str, &str, &str) {
    let (scheme, rest) = if let Some(scheme_end) = s.find("://") {
        (&s[..scheme_end + 3], &s[scheme_end + 3..])
    } else if let Some(rest) = s.strip_prefix("//") {
        (&s[..2], rest)
    } else {
        return ("", "", s);
    };
    match rest.find('/') {
        None => (scheme, rest, ""),
        Some(path_off) => (scheme, &rest[..path_off], &rest[path_off..]),
    }
}

fn is_simple(t: &str) -> bool {
    t.bytes().all(|b| b.is_ascii_alphanumeric())
}

fn is_numeric(t: &str) -> bool {
    !t.is_empty() && t.bytes().all(|b| b.is_ascii_digit())
}

fn mask_number_into(n: &str, out: &mut String) {
    for _ in 0..n.len() {
        out.push('$');
    }
}

fn mask_number(n: &str) -> String {
    "$".repeat(n.len())
}

fn is_allowed(ctx: &Ctx<'_>, t: &str) -> bool {
    !t.is_empty() && is_simple(t) && !is_numeric(t) && ctx.allow.url_contains(t)
}

fn render_token(ctx: &Ctx<'_>, t: &str) -> Option<String> {
    if is_numeric(t) {
        Some(mask_number(t))
    } else if is_allowed(ctx, t) {
        Some(t.to_string())
    } else {
        None
    }
}

fn is_safe_segment(seg: &str) -> bool {
    matches!(seg, "" | "." | "..")
}
