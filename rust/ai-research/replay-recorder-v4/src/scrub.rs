//! The fallback for a block whose remote URLs the writer could not all name or replace. Each remote URL token left in
//! the stored bytes becomes [`UNCHECKED_MARKER`], so no URL the policy would refuse is stored, and the block is kept
//! instead of dropped.
//!
//! A token is a run of URL bytes, CSS escapes included, between JSON or CSS delimiters. The scrub does not know which
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
    /// Every token that starts with `http:`, `https:` or `//` and a host, in any letter case.
    AllRemote,
    /// Every token that holds one of these hosts, in any letter case.
    Hosts(Vec<String>),
}

pub struct Scrubber {
    matcher: Option<AhoCorasick>,
    all_remote: bool,
}

/// A byte that a URL token can go on with. A backslash starts a CSS escape, which a browser reads as part of the URL.
fn token_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || b"-._~/?#@!$&*+=%:;[],\\".contains(&byte)
}

/// Whether a JSON escape that ends the token starts at `at`: an escaped quote or line break, not an escaped backslash.
fn json_break_at(bytes: &[u8], at: usize) -> bool {
    bytes.get(at) == Some(&b'\\') && matches!(bytes.get(at + 1), Some(b'"' | b'n' | b'r' | b't'))
}

/// Whether the bytes before `at` end with an escaped quote or line break, which is no part of the token after it.
fn json_break_before(bytes: &[u8], at: usize) -> bool {
    at >= 2
        && matches!(bytes[at - 1], b'"' | b'n' | b'r' | b't')
        && bytes[at - 2] == b'\\'
        && !(at >= 3 && bytes[at - 3] == b'\\')
}

impl Scrubber {
    pub fn new(scrub: &Scrub) -> Self {
        let (patterns, all_remote): (Vec<String>, bool) = match scrub {
            Scrub::Nothing => (Vec::new(), false),
            Scrub::AllRemote => (vec!["http".to_owned(), "//".to_owned()], true),
            Scrub::Hosts(hosts) => (hosts.clone(), false),
        };
        let matcher = (!patterns.is_empty())
            .then(|| {
                AhoCorasickBuilder::new()
                    .ascii_case_insensitive(true)
                    .match_kind(MatchKind::LeftmostFirst)
                    .build(&patterns)
                    .ok()
            })
            .flatten();
        Self {
            matcher,
            all_remote,
        }
    }

    /// The bytes with each URL token replaced, and how many were.
    pub fn apply<'b>(&self, bytes: &'b [u8]) -> (Cow<'b, [u8]>, u64) {
        let Some(matcher) = &self.matcher else {
            return (Cow::Borrowed(bytes), 0);
        };
        let mut out: Option<Vec<u8>> = None;
        let mut copied_to = 0;
        let mut replaced = 0;
        for found in matcher.find_iter(bytes) {
            if found.start() < copied_to {
                continue;
            }
            let Some((start, end)) = self.token(bytes, found.start(), found.end()) else {
                continue;
            };
            if start < copied_to {
                continue;
            }
            let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
            out.extend_from_slice(&bytes[copied_to..start]);
            out.extend_from_slice(UNCHECKED_MARKER.as_bytes());
            copied_to = end;
            replaced += 1;
        }
        match out {
            Some(mut out) => {
                out.extend_from_slice(&bytes[copied_to..]);
                (Cow::Owned(out), replaced)
            }
            None => (Cow::Borrowed(bytes), 0),
        }
    }

    /// The URL token around a match, or `None` when the match does not start a remote URL.
    fn token(&self, bytes: &[u8], start: usize, end: usize) -> Option<(usize, usize)> {
        let mut first = start;
        if self.all_remote {
            // A remote URL starts its token: `http` and `//` inside a longer word or path are no URL start.
            if first > 0 && token_byte(bytes[first - 1]) && !json_break_before(bytes, first) {
                return None;
            }
            let rest = &bytes[end..];
            let starts_url = if bytes[start] == b'/' {
                rest.first().is_some_and(u8::is_ascii_alphanumeric)
            } else {
                let rest = if rest.first().is_some_and(|b| b.eq_ignore_ascii_case(&b's')) {
                    &rest[1..]
                } else {
                    rest
                };
                matches!(rest.first(), Some(b':' | b'\\'))
            };
            if !starts_url {
                return None;
            }
        } else {
            while first > 0 && token_byte(bytes[first - 1]) && !json_break_before(bytes, first) {
                first -= 1;
            }
        }
        let mut last = end;
        while last < bytes.len() && token_byte(bytes[last]) && !json_break_at(bytes, last) {
            last += 1;
        }
        Some((first, last))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scrub(scrub: Scrub, bytes: &str) -> (String, u64) {
        let (out, count) = Scrubber::new(&scrub).apply(bytes.as_bytes());
        (String::from_utf8(out.into_owned()).unwrap(), count)
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
            // A CSS escape is part of the URL a browser loads. The space that ends the escape splits the token, and both
            // parts go.
            (
                r#"{"style":"url(https\\3a //cdn.example.com/a.png)"}"#.to_owned(),
                format!(r#"{{"style":"url({m} {m})"}}"#),
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
        // The space that ends a CSS escape ends the token, so the path after it stays without its host.
        let m = UNCHECKED_MARKER;
        let (out, count) = scrub(
            Scrub::Hosts(vec!["internal.example.com".to_owned()]),
            r#"{"style":"url(https\\3a \\2f \\2f Internal.example.com\\2f a.png)","alt":"other.example.com"}"#,
        );
        assert_eq!(
            out,
            format!(
                r#"{{"style":"url(https\\3a \\2f \\2f {m} a.png)","alt":"other.example.com"}}"#
            )
        );
        assert_eq!(count, 1);
    }
}
