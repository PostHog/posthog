//! The fallback for a block whose remote URLs the writer could not all name or replace. Each remote URL token left in
//! the stored bytes becomes [`UNCHECKED_MARKER`], so no URL the policy would refuse is stored, and the block is kept
//! instead of dropped.
//!
//! The scrub reads the bytes one character at a time through their JSON escapes and CSS escapes, so it never splits an
//! escape and the stored JSON stays valid. A URL token ends at whitespace or at the end of its JSON string. A URL that
//! starts after `(`, `'` or `"` also ends at `)`, `'` or `"`, because CSS ends it there. The scrub does not know which
//! slot a token sits in, so it also replaces URLs outside image slots, such as links and text. It runs only on the few
//! blocks that need it.

use std::borrow::Cow;

use aho_corasick::{AhoCorasick, AhoCorasickBuilder, MatchKind};

/// What a scrubbed URL token becomes.
pub const UNCHECKED_MARKER: &str = "imageurl:v4:declined:unchecked";

/// Which URL tokens the scrub replaces.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub enum Scrub {
    #[default]
    Nothing,
    /// Every token that `url_policy::is_remote` reads as remote: `http:` or `https:`, or two slashes or backslashes,
    /// in any letter case and through any escape.
    AllRemote,
    /// Every token that holds one of these hosts, in any letter case. The list is sorted, without duplicates.
    Hosts(Vec<String>),
}

pub struct Scrubber {
    all_remote: bool,
    hosts: Option<AhoCorasick>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Plain,
    /// An unescaped `"`, which ends the JSON string.
    StringEnd,
    /// A character a CSS escape names. It is part of the URL whatever it is.
    CssEscaped,
}

/// One character of the stored bytes and the bytes that spell it.
#[derive(Clone, Copy)]
struct Unit {
    ch: u32,
    len: usize,
    kind: Kind,
}

/// The character that ends a URL besides whitespace and the end of its JSON string.
#[derive(Clone, Copy)]
enum Closer {
    None,
    Paren,
    Apostrophe,
    Quote,
}

enum Start {
    Scheme,
    Slashes,
}

fn is_space(ch: u32) -> bool {
    ch <= u32::from(b' ')
}

fn is_char(ch: u32, byte: u8) -> bool {
    ch == u32::from(byte)
}

/// A character that a relative path or a word can hold, so `//` after it starts no URL.
fn continues_word(ch: u32) -> bool {
    u8::try_from(ch)
        .is_ok_and(|b| b.is_ascii_alphanumeric() || b"-._~/?#@!$&*+=%:;[]\\".contains(&b))
}

/// The character at `at` after its JSON escape, and its length in bytes.
fn json_unit(bytes: &[u8], at: usize) -> (u32, usize) {
    let byte = bytes[at];
    if byte != b'\\' {
        return (u32::from(byte), 1);
    }
    match bytes.get(at + 1) {
        Some(b'u') => bytes
            .get(at + 2..at + 6)
            .and_then(|hex| std::str::from_utf8(hex).ok())
            .and_then(|hex| u32::from_str_radix(hex, 16).ok())
            .map_or((u32::from(byte), 1), |code| (code, 6)),
        Some(&escaped) => {
            let ch = match escaped {
                b'n' => b'\n',
                b'r' => b'\r',
                b't' => b'\t',
                b'b' => 0x08,
                b'f' => 0x0c,
                other => other,
            };
            (u32::from(ch), 2)
        }
        None => (u32::from(byte), 1),
    }
}

/// The character at `at` after its JSON escape and a CSS escape inside it. A CSS hex escape takes the one whitespace
/// after it, as CSS reads it.
fn unit(bytes: &[u8], at: usize) -> Unit {
    let (ch, len) = json_unit(bytes, at);
    if len == 1 && is_char(ch, b'"') {
        return Unit {
            ch,
            len,
            kind: Kind::StringEnd,
        };
    }
    let plain = Unit {
        ch,
        len,
        kind: Kind::Plain,
    };
    if len == 1 || !is_char(ch, b'\\') {
        return plain;
    }
    let mut end = at + len;
    let (mut code, mut digits) = (0u32, 0);
    while digits < 6 && end < bytes.len() {
        let (next, next_len) = json_unit(bytes, end);
        let Some(digit) = char::from_u32(next).and_then(|c| c.to_digit(16)) else {
            break;
        };
        code = code * 16 + digit;
        digits += 1;
        end += next_len;
    }
    if digits > 0 {
        if end < bytes.len() {
            let (next, next_len) = json_unit(bytes, end);
            if is_space(next) {
                end += next_len;
            }
        }
        return Unit {
            ch: code,
            len: end - at,
            kind: Kind::CssEscaped,
        };
    }
    if end >= bytes.len() {
        return plain;
    }
    let (next, next_len) = json_unit(bytes, end);
    if is_space(next) || (next_len == 1 && is_char(next, b'"')) {
        return plain;
    }
    Unit {
        ch: next,
        len: len + next_len,
        kind: Kind::CssEscaped,
    }
}

fn lower(ch: u32) -> u32 {
    u8::try_from(ch).map_or(ch, |b| u32::from(b.to_ascii_lowercase()))
}

/// Whether a remote URL starts at `at`, and how.
fn remote_start(bytes: &[u8], at: usize) -> Option<Start> {
    let mut chars = [0u32; 6];
    let (mut pos, mut count) = (at, 0);
    while count < chars.len() && pos < bytes.len() {
        let next = unit(bytes, pos);
        if next.kind == Kind::StringEnd {
            break;
        }
        chars[count] = lower(next.ch);
        pos += next.len;
        count += 1;
    }
    let slash = |ch: u32| is_char(ch, b'/') || is_char(ch, b'\\');
    if count >= 2 && slash(chars[0]) && slash(chars[1]) {
        return Some(Start::Slashes);
    }
    // Outside CSS, `\\` is two backslashes rather than one escaped backslash, and a browser reads both as slashes.
    let (first, first_len) = json_unit(bytes, at);
    if slash(first) && at + first_len < bytes.len() && slash(json_unit(bytes, at + first_len).0) {
        return Some(Start::Slashes);
    }
    let http = chars[..4]
        .iter()
        .zip(b"http")
        .all(|(&ch, &b)| is_char(ch, b));
    let colon_at = if is_char(chars[4], b's') { 5 } else { 4 };
    (count > colon_at && http && is_char(chars[colon_at], b':')).then_some(Start::Scheme)
}

fn closer_after(prev: Option<Unit>) -> Closer {
    match prev {
        Some(Unit {
            ch,
            kind: Kind::Plain,
            ..
        }) if is_char(ch, b'(') => Closer::Paren,
        Some(Unit {
            ch,
            kind: Kind::Plain,
            ..
        }) if is_char(ch, b'\'') => Closer::Apostrophe,
        Some(Unit {
            ch,
            kind: Kind::Plain,
            ..
        }) if is_char(ch, b'"') => Closer::Quote,
        _ => Closer::None,
    }
}

fn ends_url(next: Unit, closer: Closer) -> bool {
    match next.kind {
        Kind::StringEnd => true,
        Kind::CssEscaped => false,
        Kind::Plain => {
            is_space(next.ch)
                || match closer {
                    Closer::None => false,
                    Closer::Paren => is_char(next.ch, b')'),
                    Closer::Apostrophe => is_char(next.ch, b'\''),
                    Closer::Quote => is_char(next.ch, b'"'),
                }
        }
    }
}

/// The spans of the remote URL tokens, in order.
fn url_spans(bytes: &[u8]) -> Vec<(usize, usize)> {
    scan(bytes).urls
}

/// The remote URL tokens of the bytes and the insides of their JSON strings, each in order.
struct Scan {
    urls: Vec<(usize, usize)>,
    strings: Vec<(usize, usize)>,
}

fn scan(bytes: &[u8]) -> Scan {
    let mut spans = Vec::new();
    let mut strings = Vec::new();
    let mut string_start: Option<usize> = None;
    let mut prev: Option<Unit> = None;
    let mut at = 0;
    while at < bytes.len() {
        let current = unit(bytes, at);
        if current.kind == Kind::StringEnd {
            match string_start.take() {
                Some(start) => strings.push((start, at)),
                None => string_start = Some(at + 1),
            }
        }
        let first = lower(current.ch);
        let starts = string_start.is_some()
            && current.kind != Kind::StringEnd
            && (is_char(first, b'h') || is_char(first, b'/') || is_char(first, b'\\'))
            && match remote_start(bytes, at) {
                Some(Start::Scheme) => true,
                Some(Start::Slashes) => !prev.is_some_and(|p| continues_word(p.ch)),
                None => false,
            };
        if !starts {
            prev = Some(current);
            at += current.len;
            continue;
        }
        let closer = closer_after(prev);
        let mut end = at;
        while end < bytes.len() {
            let next = unit(bytes, end);
            if ends_url(next, closer) {
                break;
            }
            end += next.len;
        }
        spans.push((at, end));
        prev = None;
        at = end;
    }
    Scan {
        urls: spans,
        strings,
    }
}

/// The token's characters after their JSON and CSS escapes, in lower case, so an escaped host still matches.
fn decoded(bytes: &[u8], (start, end): (usize, usize)) -> String {
    let mut text = String::new();
    let mut at = start;
    while at < end {
        let next = unit(bytes, at);
        text.extend(char::from_u32(lower(next.ch)));
        at += next.len;
    }
    text
}

/// Whether the byte before `at` closes a JSON escape that ends a token, such as `\n`, rather than an escaped backslash.
fn escape_ends_at(bytes: &[u8], at: usize) -> bool {
    at >= 2
        && matches!(bytes[at - 1], b'n' | b'r' | b't' | b'b' | b'f')
        && bytes[..at - 1]
            .iter()
            .rev()
            .take_while(|&&b| b == b'\\')
            .count()
            % 2
            == 1
}

/// The span around a host that no URL token holds, such as a bare host in text. It ends at whitespace and quotes, which
/// never sit inside an escape, so the span keeps every escape whole.
fn bare_span(bytes: &[u8], start: usize, end: usize) -> (usize, usize) {
    let mut first = start;
    while first > 0
        && bytes[first - 1] > b' '
        && bytes[first - 1] != b'"'
        && !escape_ends_at(bytes, first)
    {
        first -= 1;
    }
    let mut last = end;
    while last < bytes.len() && bytes[last] > b' ' && bytes[last] != b'"' {
        if bytes[last] == b'\\' {
            let (ch, len) = json_unit(bytes, last);
            if len > 1 && (is_space(ch) || is_char(ch, b'"')) {
                break;
            }
            last += len;
        } else {
            last += 1;
        }
    }
    (first, last.min(bytes.len()))
}

impl Scrubber {
    pub fn new(scrub: &Scrub) -> Self {
        let hosts = match scrub {
            Scrub::Hosts(hosts) if !hosts.is_empty() => {
                let mut hosts: Vec<String> =
                    hosts.iter().map(|host| host.to_ascii_lowercase()).collect();
                hosts.sort_unstable();
                hosts.dedup();
                AhoCorasickBuilder::new()
                    .ascii_case_insensitive(true)
                    .match_kind(MatchKind::LeftmostFirst)
                    .build(&hosts)
                    .ok()
            }
            _ => None,
        };
        Self {
            all_remote: *scrub == Scrub::AllRemote,
            hosts,
        }
    }

    /// The bytes with each URL token replaced, and how many were.
    pub fn apply<'b>(&self, bytes: &'b [u8]) -> (Cow<'b, [u8]>, u64) {
        let spans = if self.all_remote {
            url_spans(bytes)
        } else if let Some(hosts) = &self.hosts {
            Self::host_spans(hosts, bytes)
        } else {
            Vec::new()
        };
        if spans.is_empty() {
            return (Cow::Borrowed(bytes), 0);
        }
        let mut out = Vec::with_capacity(bytes.len());
        let mut copied_to = 0;
        let mut replaced = 0;
        for (start, end) in spans {
            if end <= copied_to {
                continue;
            }
            if start >= copied_to {
                out.extend_from_slice(&bytes[copied_to..start]);
                out.extend_from_slice(UNCHECKED_MARKER.as_bytes());
                replaced += 1;
            }
            copied_to = end;
        }
        out.extend_from_slice(&bytes[copied_to..]);
        (Cow::Owned(out), replaced)
    }

    /// The URL tokens that hold a host, and a bare span around each host no URL token holds, by start.
    fn host_spans(hosts: &AhoCorasick, bytes: &[u8]) -> Vec<(usize, usize)> {
        let Scan { urls, strings } = scan(bytes);
        let mut spans: Vec<(usize, usize)> = urls
            .into_iter()
            .filter(|&span| hosts.is_match(decoded(bytes, span).as_bytes()))
            .collect();
        let inside = |list: &[(usize, usize)], (start, end): (usize, usize)| {
            let first = list.partition_point(|&(_, list_end)| list_end < end);
            list.get(first)
                .filter(|&&(list_start, list_end)| list_start <= start && end <= list_end)
                .copied()
        };
        let mut bare = Vec::new();
        let mut covered_to = 0;
        for found in hosts.find_iter(bytes) {
            let host = (found.start(), found.end());
            // A host outside a JSON string is part of a literal such as `null`, and an earlier span may already hold it.
            if host.0 < covered_to || inside(&spans, host).is_some() {
                continue;
            }
            let Some((string_start, string_end)) = inside(&strings, host) else {
                continue;
            };
            let (start, end) = bare_span(bytes, host.0, host.1);
            let span = (start.max(string_start), end.min(string_end));
            covered_to = span.1;
            bare.push(span);
        }
        spans.extend(bare);
        spans.sort_unstable();
        spans
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scrub(scrub: Scrub, bytes: &str) -> (String, u64) {
        let (out, count) = Scrubber::new(&scrub).apply(bytes.as_bytes());
        let out = String::from_utf8(out.into_owned()).unwrap();
        serde_json::from_str::<serde_json::Value>(&out).unwrap_or_else(|e| panic!("{out}: {e}"));
        (out, count)
    }

    #[test]
    fn replaces_every_remote_url_token_and_keeps_the_json_around_it() {
        let m = UNCHECKED_MARKER;
        for (input, expected) in [
            (
                r#"{"src":"https://cdn.example.com/a.png?x=1"}"#.to_owned(),
                format!(r#"{{"src":"{m}"}}"#),
            ),
            (
                r#"{"srcset":"HTTP://a.example.com/a.png 1x,\nhttps://b.example.com/b.png 2x"}"#
                    .to_owned(),
                format!(r#"{{"srcset":"{m} 1x,\n{m} 2x"}}"#),
            ),
            (
                r#"{"style":"background:url(\"//cdn.example.com/a.png\")"}"#.to_owned(),
                format!(r#"{{"style":"background:url(\"{m}\")"}}"#),
            ),
            (
                r#"{"style":"url('https://cdn.example.com/a.png') no-repeat"}"#.to_owned(),
                format!(r#"{{"style":"url('{m}') no-repeat"}}"#),
            ),
            // A CSS escape is part of the URL a browser loads, the whitespace that ends a hex escape included.
            (
                r#"{"style":"url(https\\3a //cdn.example.com/a.png)"}"#.to_owned(),
                format!(r#"{{"style":"url({m})"}}"#),
            ),
            (
                r#"{"style":"url(\\2f\\2f bucket.example.com/a.png?sig=x)"}"#.to_owned(),
                format!(r#"{{"style":"url({m})"}}"#),
            ),
            // A browser reads a backslash as a slash, and the inspector reads any host after two of them as remote.
            (
                r#"{"src":"\\\\10.0.0.7/a.png"}"#.to_owned(),
                format!(r#"{{"src":"{m}"}}"#),
            ),
            (
                r#"{"src":"\/\/[::1]/a.png"}"#.to_owned(),
                format!(r#"{{"src":"{m}"}}"#),
            ),
            // Outside CSS, an apostrophe or a parenthesis is part of the URL, so the query after it goes too.
            (
                r#"{"src":"https://cdn.example.com/a'b(c).png?token=x"}"#.to_owned(),
                format!(r#"{{"src":"{m}"}}"#),
            ),
            // An escaped backslash at the end goes whole, so the quote after it still ends the string.
            (
                r#"{"src":"https://cdn.example.com/a\\"}"#.to_owned(),
                format!(r#"{{"src":"{m}"}}"#),
            ),
            // `http` inside a word, and a path's `//`, start no URL.
            (
                r#"{"text":"httpd at /a//b"}"#.to_owned(),
                r#"{"text":"httpd at /a//b"}"#.to_owned(),
            ),
        ] {
            assert_eq!(scrub(Scrub::AllRemote, &input).0, expected, "{input}");
        }
    }

    #[test]
    fn replaces_the_tokens_that_hold_a_host_in_any_form() {
        let m = UNCHECKED_MARKER;
        let (out, count) = scrub(
            Scrub::Hosts(vec!["internal.example.com".to_owned()]),
            r#"{"style":"url(https\\3a \\2f \\2f Internal.example.com\\2f a.png)","alt":"see internal.example.com/a'b?token=x\nnow","title":"other.example.com"}"#,
        );
        assert_eq!(
            out,
            format!(r#"{{"style":"url({m})","alt":"see {m}\nnow","title":"other.example.com"}}"#)
        );
        assert_eq!(count, 2);
    }

    #[test]
    fn matches_a_host_only_as_the_browser_reads_it_inside_a_string() {
        let m = UNCHECKED_MARKER;
        for (host, input, expected) in [
            (
                "10.0.0.7",
                r#"{"style":"url(https://10\\2e 0.0.7/a.png)"}"#.to_owned(),
                format!(r#"{{"style":"url({m})"}}"#),
            ),
            (
                "null",
                r#"{"src":"https://null/a.png","alt":null}"#.to_owned(),
                format!(r#"{{"src":"{m}","alt":null}}"#),
            ),
        ] {
            assert_eq!(
                scrub(Scrub::Hosts(vec![host.to_owned()]), &input).0,
                expected,
                "{input}"
            );
        }
    }
}
