//! Replaces the remote image URLs of a stored block with their `imageurl:v4` references, as v3 replaced them. A URL the
//! policy declines becomes a marker that names the reason, so that no credential, signature or private host stays in
//! the block. The inspector names the URLs: those in image slots, CSS included.

use std::borrow::Cow;

use aho_corasick::{AhoCorasick, AhoCorasickKind, MatchKind};
use metrics::counter;
use replay_core_v4::bytescan::{unescape, write_json_string};
use replay_core_v4::seal::image_url_key;

use crate::urls::url_reference;

/// The bytes with each JSON string that holds an escape `write_json_string` does not write, such as `\/` or `\u0041`,
/// written again as it writes them. Capture writes events that way, but the JSON inside a `cv` payload arrives as the
/// page wrote it, so a URL could hide from the rewrite behind an escape.
pub fn canonical_strings(bytes: &[u8]) -> Cow<'_, [u8]> {
    if !bytes.contains(&b'\\') {
        return Cow::Borrowed(bytes);
    }
    let mut out: Option<Vec<u8>> = None;
    let mut copied_to = 0;
    let mut position = 0;
    while let Some(start) = bytes[position..]
        .iter()
        .position(|&b| b == b'"')
        .map(|at| position + at)
    {
        let mut end = start + 1;
        let mut canonical = true;
        while end < bytes.len() && bytes[end] != b'"' {
            if bytes[end] == b'\\' {
                match bytes.get(end + 1) {
                    Some(b'"' | b'\\' | b'b' | b'f' | b'n' | b'r' | b't') => {}
                    Some(b'u') => canonical &= is_written_escape(bytes.get(end + 2..end + 6)),
                    _ => canonical = false,
                }
                end += 1;
            }
            end += 1;
        }
        if end >= bytes.len() {
            break;
        }
        if !canonical {
            if let Ok(text) = unescape(bytes, (start, end + 1)) {
                let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
                out.extend_from_slice(&bytes[copied_to..start]);
                write_json_string(&text, out);
                copied_to = end + 1;
            }
        }
        position = end + 1;
    }
    match out {
        Some(mut out) => {
            out.extend_from_slice(&bytes[copied_to..]);
            Cow::Owned(out)
        }
        None => Cow::Borrowed(bytes),
    }
}

/// Whether `write_json_string` writes this `\u` escape: a control character without a short escape, in lowercase hex.
fn is_written_escape(hex: Option<&[u8]>) -> bool {
    let Some(&[b'0', b'0', high, low]) = hex else {
        return false;
    };
    let digit = |b: u8| matches!(b, b'0'..=b'9' | b'a'..=b'f');
    digit(high)
        && digit(low)
        && high <= b'1'
        && !matches!((high, low), (b'0', b'8' | b'9' | b'a' | b'c' | b'd'))
}

/// What a declined URL becomes. The reason is the policy's metric label.
pub fn declined_marker(reason: &str) -> String {
    format!("imageurl:v4:declined:{reason}")
}

/// A byte that a URL can go on with. A match next to one is part of a longer URL, so it stays as it is. A comma, a
/// parenthesis or a quote can be in a URL too, but in a srcset or a CSS `url()` it ends one.
fn continues_url(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || b"-._~/?#@!$&*+=%:;[]".contains(&byte)
}

/// Whether the bytes before `at` end with a JSON escape, such as the `\n` of a multi-line srcset. The escape's last
/// letter is not part of the URL that follows it.
fn ends_with_escape(bytes: &[u8], at: usize) -> bool {
    let escaped = |letter: usize| {
        bytes[..letter]
            .iter()
            .rev()
            .take_while(|&&b| b == b'\\')
            .count()
            % 2
            == 1
    };
    let short = at >= 2 && b"\"\\/bfnrt".contains(&bytes[at - 1]) && escaped(at - 1);
    let unicode = at >= 6
        && bytes[at - 5] == b'u'
        && bytes[at - 4..at].iter().all(u8::is_ascii_hexdigit)
        && escaped(at - 5);
    short || unicode
}

struct Target {
    replacement: Vec<u8>,
    /// The policy's reason, for a declined URL.
    declined: Option<&'static str>,
    found: bool,
}

pub struct UrlRewrite {
    matcher: Option<AhoCorasick>,
    /// The declined URLs alone. `apply` passes over a copy inside a longer URL, so the bytes it returns are scanned
    /// again for them.
    declined: Option<AhoCorasick>,
    targets: Vec<Target>,
    /// Bytes that `apply` returned still hold a declined URL.
    declined_kept: bool,
}

impl UrlRewrite {
    /// `team_key` is the team's month key for `key_month`, the write month, as for the fetch jobs.
    pub fn new(urls: &[String], team_id: i64, key_month: &str, team_key: &[u8; 32]) -> Self {
        let url_key = image_url_key(team_key);
        let mut patterns = Vec::with_capacity(urls.len());
        let mut targets = Vec::with_capacity(urls.len());
        for url in urls {
            // The block holds the URL as a JSON string holds it.
            let mut escaped = Vec::with_capacity(url.len() + 2);
            write_json_string(url, &mut escaped);
            patterns.push(escaped[1..escaped.len() - 1].to_vec());
            let (replacement, declined) = match url_reference(url, team_id, key_month, &url_key) {
                Ok((_, reference)) => (reference, None),
                Err(decline) => (declined_marker(decline.label()), Some(decline.label())),
            };
            targets.push(Target {
                replacement: replacement.into_bytes(),
                declined,
                found: false,
            });
        }
        let matcher = (!patterns.is_empty())
            .then(|| {
                // A DFA over long URLs can take hundreds of times their bytes. A contiguous NFA takes about ten.
                AhoCorasick::builder()
                    .kind(Some(AhoCorasickKind::ContiguousNFA))
                    .match_kind(MatchKind::LeftmostLongest)
                    .build(&patterns)
                    .ok()
            })
            .flatten();
        let declined: Vec<&[u8]> = patterns
            .iter()
            .zip(&targets)
            .filter(|(_, target)| target.declined.is_some())
            .map(|(pattern, _)| pattern.as_slice())
            .collect();
        let declined = (!declined.is_empty())
            .then(|| {
                AhoCorasick::builder()
                    .kind(Some(AhoCorasickKind::ContiguousNFA))
                    .build(declined)
                    .ok()
            })
            .flatten();
        Self {
            matcher,
            declined,
            targets,
            declined_kept: false,
        }
    }

    /// The bytes with each URL replaced. Returns the input when it holds none.
    pub fn apply<'b>(&mut self, bytes: &'b [u8]) -> Cow<'b, [u8]> {
        let Some(matcher) = &self.matcher else {
            return Cow::Borrowed(bytes);
        };
        let mut out: Option<Vec<u8>> = None;
        let mut copied_to = 0;
        for found in matcher.find_iter(bytes) {
            let (start, end) = (found.start(), found.end());
            if start.checked_sub(1).is_some_and(|before| {
                continues_url(bytes[before]) && !ends_with_escape(bytes, start)
            }) || bytes.get(end).is_some_and(|&after| continues_url(after))
            {
                continue;
            }
            let target = &mut self.targets[found.pattern().as_usize()];
            target.found = true;
            let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
            out.extend_from_slice(&bytes[copied_to..start]);
            out.extend_from_slice(&target.replacement);
            copied_to = end;
        }
        let out = match out {
            Some(mut out) => {
                out.extend_from_slice(&bytes[copied_to..]);
                Cow::Owned(out)
            }
            None => Cow::Borrowed(bytes),
        };
        if let Some(declined) = &self.declined {
            self.declined_kept |= declined.is_match(out.as_ref());
        }
        out
    }

    /// Counts the block's URLs. One the block does not hold as the inspector read it, for example with a CSS escape,
    /// stays as it arrived. Returns false when a URL the policy declines stays, unreplaced or as a second copy that
    /// `apply` passed over, because the block must not be stored then.
    pub fn finish(self) -> bool {
        let mut safe = !self.declined_kept;
        for target in self.targets {
            safe &= target.found || target.declined.is_none();
            let outcome = match (target.found, target.declined) {
                (false, _) => "unrewritten",
                (true, None) => "rewritten",
                (true, Some(_)) => "declined",
            };
            counter!(
                "ai_research_v4_recorder_image_url_rewrites_total",
                "outcome" => outcome,
                "reason" => target.declined.unwrap_or("none"),
            )
            .increment(1);
        }
        safe
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEAM_KEY: [u8; 32] = [6; 32];

    fn rewrite(urls: &[&str], bytes: &str) -> String {
        let urls: Vec<String> = urls.iter().map(|u| (*u).to_owned()).collect();
        let mut rewrite = UrlRewrite::new(&urls, 7, "2026-10", &TEAM_KEY);
        String::from_utf8(rewrite.apply(bytes.as_bytes()).into_owned()).unwrap()
    }

    fn reference(url: &str) -> String {
        url_reference(url, 7, "2026-10", &image_url_key(&TEAM_KEY))
            .unwrap()
            .1
    }

    #[test]
    fn keeps_srcset_and_css_syntax_while_it_replaces_each_url() {
        let (a, b) = (
            "https://cdn.example.com/w_640,q_auto/a.png",
            "https://cdn.example.com/b.png",
        );
        let event = format!(
            r#"{{"srcset":"{a} 640w, {b} 2x","style":"background:url({b}) no-repeat","text":".x{{background:url(\"{a}\")}}","other":"{b}?v=2"}}"#
        );
        let out = rewrite(&[a, b], &event);
        let (ra, rb) = (reference(a), reference(b));
        assert_eq!(
            out,
            format!(
                r#"{{"srcset":"{ra} 640w, {rb} 2x","style":"background:url({rb}) no-repeat","text":".x{{background:url(\"{ra}\")}}","other":"{b}?v=2"}}"#
            )
        );
        assert!(serde_json::from_str::<serde_json::Value>(&out).is_ok());

        // A srcset over several lines holds each URL after an escape, which is no part of the URL.
        let declined = "https://10.0.0.7/c.png";
        let event = format!(r#"{{"srcset":"{a} 1x,\n{b} 2x,\t{declined} 3x"}}"#);
        let mut rewrite = UrlRewrite::new(
            &[a.to_owned(), b.to_owned(), declined.to_owned()],
            7,
            "2026-10",
            &TEAM_KEY,
        );
        assert_eq!(
            String::from_utf8(rewrite.apply(event.as_bytes()).into_owned()).unwrap(),
            format!(
                r#"{{"srcset":"{ra} 1x,\n{rb} 2x,\t{} 3x"}}"#,
                declined_marker("non_public_host")
            )
        );
        assert!(rewrite.finish());
    }

    #[test]
    fn rewrites_a_url_that_a_json_escape_hid() {
        let url = "https://cdn.example.com/a.png?token=secret";
        let hidden = r#"{"src":"https:\/\/cdn.example.com\/a.png?token=secr\u0065t","alt":"a\nb"}"#;
        let canonical = canonical_strings(hidden.as_bytes());
        let mut rewrite = UrlRewrite::new(&[url.to_owned()], 7, "2026-10", &TEAM_KEY);
        assert_eq!(
            String::from_utf8(rewrite.apply(&canonical).into_owned()).unwrap(),
            format!(
                r#"{{"src":"{}","alt":"a\nb"}}"#,
                declined_marker("credential")
            )
        );
        assert!(rewrite.finish());
        // An event capture wrote is left as it is.
        let plain = r#"{"text":"a\"b\\c\u0001","n":1}"#;
        assert!(matches!(
            canonical_strings(plain.as_bytes()),
            Cow::Borrowed(_)
        ));
        // A declined URL the block still holds fails the block.
        let rewrite = UrlRewrite::new(&[url.to_owned()], 7, "2026-10", &TEAM_KEY);
        assert!(!rewrite.finish());
    }

    #[test]
    fn leaves_only_a_marker_where_the_policy_declines_a_url() {
        for (url, reason) in [
            ("https://user:secret@cdn.example.com/a.png", "credential"),
            (
                "https://bucket.s3.amazonaws.com/a.png?X-Amz-Signature=abc123",
                "credential",
            ),
            ("https://10.0.0.7/a.png", "non_public_host"),
            ("http://cdn.example.com/a.png", "bad_scheme"),
        ] {
            let out = rewrite(&[url], &format!(r#"{{"src":"{url}"}}"#));
            assert_eq!(
                out,
                format!(r#"{{"src":"{}"}}"#, declined_marker(reason)),
                "{url}"
            );
        }
        // A second copy inside a longer URL stays as it is, so the block fails.
        let url = "https://bucket.s3.amazonaws.com/a.png?X-Amz-Signature=abc123";
        let mut rewrite = UrlRewrite::new(&[url.to_owned()], 7, "2026-10", &TEAM_KEY);
        rewrite.apply(format!(r#"{{"src":"{url}","alt":"x{url}"}}"#).as_bytes());
        assert!(!rewrite.finish());
    }
}
