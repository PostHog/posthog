//! Replaces the remote image URLs of a stored block with their `imageurl:v4` references, as v3 replaced them. A URL the
//! policy declines becomes a marker that names the reason, so that no credential, signature or private host stays in
//! the block. The inspector names the URLs: those in image slots, CSS included.
//!
//! A srcset is rebuilt instead: a declined candidate leaves the list, and so does each remote candidate of a picture
//! source whose type the fetcher does not store. An inline image, such as an SVG data URI, stays. A browser skips a
//! source with no candidates, so it falls back to a source or an img that can load, where a marker in the list would
//! show a broken image. The writer rebuilds each srcset in the bytes it stores, after inline images left and escapes
//! were written again, so the rebuild never depends on a prediction of those bytes.

use std::borrow::Cow;
use std::collections::{BTreeMap, HashMap, HashSet};

use aho_corasick::{AhoCorasick, AhoCorasickKind, MatchKind};
use metrics::counter;
use replay_core_v4::bytescan::{unescape, write_json_string};
use replay_core_v4::inspect::dom::{for_each_srcset_candidate, Srcset};
use replay_core_v4::scan::images::{extract_images, ImageLimits, ImageSink, AVIF_MARKER};
use replay_core_v4::seal::{image_content_key, image_url_key};
use replay_core_v4::url_policy::is_remote;

use crate::scrub::{Scrub, Scrubber};
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

const SRCSET_KEY: &[u8] = br#""srcset":"#;

struct Target {
    url: String,
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
    srcset_key: AhoCorasick,
    /// Remote URLs that the block names only in picture sources of a type the fetcher does not store.
    unfetched: HashSet<String>,
    /// Each inspected srcset value as the stored block holds it. Only these are rebuilt, so a srcset key outside an
    /// image slot, such as in a custom event's payload, stays as it is.
    stored_srcsets: HashSet<Vec<u8>>,
    url_targets: HashMap<String, usize>,
    team_id: i64,
    key_month: String,
    url_key: [u8; 32],
    fallback: Fallback,
    scrubber: Scrubber,
    scrubbed: u64,
    /// The JSON key whose value held the first declined URL that stayed, for the log. It names the shape without any URL.
    kept_in: Option<String>,
    counters: PassCounters,
}

/// The counter increments of one writer pass. The writer emits them only for the pass whose output it keeps, so a block
/// written twice counts once.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PassCounters {
    srcset_rewrites: BTreeMap<&'static str, u64>,
    url_rewrites: BTreeMap<(&'static str, &'static str), u64>,
    pub removed_avif: u64,
}

impl PassCounters {
    pub fn emit(&self) {
        for (&outcome, &count) in &self.srcset_rewrites {
            counter!("ai_research_v4_recorder_srcset_rewrites_total", "outcome" => outcome)
                .increment(count);
        }
        for (&(outcome, reason), &count) in &self.url_rewrites {
            counter!(
                "ai_research_v4_recorder_image_url_rewrites_total",
                "outcome" => outcome,
                "reason" => reason,
            )
            .increment(count);
        }
        counter!("ai_research_v4_recorder_removed_images_total", "format" => "avif")
            .increment(self.removed_avif);
    }
}

/// How the writer handles what the first pass over a block left unsafe, instead of dropping the block.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Fallback {
    /// Replace a declined URL wherever its bytes are, also inside a longer URL that would otherwise keep it.
    pub overwrite_declined: bool,
    pub scrub: Scrub,
    /// The metric label of why the fallback runs.
    pub reason: Option<&'static str>,
}

/// What `finish` found about a block.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RewriteReport {
    /// No URL the policy declines can stay in the stored bytes.
    pub safe: bool,
    /// A declined URL stayed, as a second copy that the rewrite passed over.
    pub declined_kept: bool,
    /// The hosts of declined URLs the inspector named but the stored bytes do not hold as it read them. `None` when
    /// one of them has no host to look for.
    pub unfound_hosts: Option<Vec<String>>,
    pub scrubbed: u64,
    pub kept_in: Option<String>,
    pub counters: PassCounters,
}

impl UrlRewrite {
    /// `team_key` is the team's month key for `key_month`, the write month, as for the fetch jobs.
    pub fn new(
        urls: &[String],
        srcsets: &[Srcset],
        team_id: i64,
        key_month: &str,
        team_key: &[u8; 32],
    ) -> Self {
        let url_key = image_url_key(team_key);
        let mut patterns = Vec::with_capacity(urls.len() + srcsets.len());
        let mut targets = Vec::with_capacity(urls.len() + srcsets.len());
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
                url: url.clone(),
                replacement: replacement.into_bytes(),
                declined,
                found: false,
            });
        }
        let url_targets: HashMap<String, usize> = urls
            .iter()
            .enumerate()
            .map(|(index, url)| (url.clone(), index))
            .collect();
        // A URL that a source of a stored type also names stays, as the inspector merges identical srcset values.
        let mut source_types: HashMap<&str, bool> = HashMap::new();
        for srcset in srcsets {
            for_each_srcset_candidate(&srcset.text, |url, _| {
                if is_remote(url) {
                    *source_types.entry(url).or_insert(true) &= srcset.unfetched_type;
                }
            });
        }
        let unfetched = source_types
            .into_iter()
            .filter(|&(_, unfetched)| unfetched)
            .map(|(url, _)| url.to_owned())
            .collect();
        // The writer takes the inline images out of the raw event and then writes its escapes again, so each value
        // goes through the same two steps.
        let content_key = image_content_key(team_key);
        let stored_srcsets = srcsets
            .iter()
            .map(|srcset| {
                let mut sink =
                    ImageSink::new(&content_key, team_id, key_month, ImageLimits::default());
                let extracted = extract_images(&srcset.raw, &mut sink);
                canonical_strings(&extracted).into_owned()
            })
            .collect();
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
            srcset_key: AhoCorasick::new([SRCSET_KEY]).expect("one literal pattern builds"),
            unfetched,
            stored_srcsets,
            url_targets,
            team_id,
            key_month: key_month.to_owned(),
            url_key,
            fallback: Fallback::default(),
            scrubber: Scrubber::new(&Scrub::Nothing),
            scrubbed: 0,
            kept_in: None,
            counters: PassCounters::default(),
        }
    }

    pub fn with_fallback(mut self, fallback: Fallback) -> Self {
        self.scrubber = Scrubber::new(&fallback.scrub);
        self.fallback = fallback;
        self
    }

    /// The bytes with each srcset that holds a candidate the block cannot keep rebuilt from the candidates it keeps.
    fn rebuild_srcsets<'b>(&mut self, bytes: &'b [u8]) -> Cow<'b, [u8]> {
        let mut out: Option<Vec<u8>> = None;
        let mut copied_to = 0;
        for found in self.srcset_key.find_iter(bytes) {
            let start = found.end();
            if start < copied_to || bytes.get(start) != Some(&b'"') {
                continue;
            }
            let Some(end) = string_end(bytes, start) else {
                continue;
            };
            if !self.stored_srcsets.contains(&bytes[start..end]) {
                continue;
            }
            let Ok(text) = unescape(bytes, (start, end)) else {
                continue;
            };
            let Some((value, outcome, covers)) = rebuilt_srcset(
                &text,
                &self.unfetched,
                &self.url_targets,
                self.team_id,
                &self.key_month,
                &self.url_key,
            ) else {
                continue;
            };
            for url in covers {
                self.targets[url].found = true;
            }
            *self.counters.srcset_rewrites.entry(outcome).or_default() += 1;
            let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
            out.extend_from_slice(&bytes[copied_to..start]);
            write_json_string(&value, out);
            copied_to = end;
        }
        match out {
            Some(mut out) => {
                out.extend_from_slice(&bytes[copied_to..]);
                Cow::Owned(out)
            }
            None => Cow::Borrowed(bytes),
        }
    }

    /// The bytes with each URL replaced, and in a DOM event each inspected srcset rebuilt. Returns the input when it
    /// holds none. Only a full snapshot or a mutation holds image slots, so a srcset in any other event, such as a
    /// custom event's payload with the same value, is left to the rewrite of each URL.
    pub fn apply<'b>(&mut self, bytes: &'b [u8], dom_event: bool) -> Cow<'b, [u8]> {
        let replaced = if !dom_event {
            self.replace_urls(bytes)
        } else {
            match self.rebuild_srcsets(bytes) {
                Cow::Borrowed(bytes) => self.replace_urls(bytes),
                Cow::Owned(rebuilt) => Cow::Owned(self.replace_urls(&rebuilt).into_owned()),
            }
        };
        let (scrubbed, count) = self.scrubber.apply(&replaced);
        if count == 0 {
            return replaced;
        }
        self.scrubbed += count;
        Cow::Owned(scrubbed.into_owned())
    }

    fn replace_urls<'b>(&mut self, bytes: &'b [u8]) -> Cow<'b, [u8]> {
        let Some(matcher) = &self.matcher else {
            return Cow::Borrowed(bytes);
        };
        let mut out: Option<Vec<u8>> = None;
        let mut copied_to = 0;
        for found in matcher.find_iter(bytes) {
            let (start, end) = (found.start(), found.end());
            let index = found.pattern().as_usize();
            // A declined URL inside a longer URL is replaced too when the fallback asks, so that it cannot stay.
            let overwrite =
                self.fallback.overwrite_declined && self.targets[index].declined.is_some();
            if !overwrite
                && (start.checked_sub(1).is_some_and(|before| {
                    continues_url(bytes[before]) && !ends_with_escape(bytes, start)
                }) || bytes.get(end).is_some_and(|&after| continues_url(after)))
            {
                continue;
            }
            let target = &mut self.targets[index];
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
            if let Some(kept) = declined.find(out.as_ref()) {
                self.declined_kept = true;
                if self.kept_in.is_none() {
                    self.kept_in =
                        Some(enclosing_key(&out, kept.start()).unwrap_or("?").to_owned());
                }
            }
        }
        out
    }

    /// Counts the block's URLs. One the block does not hold as the inspector read it, for example with a CSS escape,
    /// stays as it arrived. The block is unsafe when a URL the policy declines can stay, unreplaced or as a second copy
    /// that `apply` passed over, unless the fallback scrubbed every token that could hold it.
    pub fn finish(self) -> RewriteReport {
        let covered = |url: &str| match &self.fallback.scrub {
            Scrub::AllRemote => true,
            Scrub::Hosts(hosts) => {
                url_host(url).is_some_and(|host| hosts.binary_search(&host).is_ok())
            }
            Scrub::Nothing => false,
        };
        let mut unfound_hosts = Some(Vec::new());
        let mut safe = !self.declined_kept;
        for target in &self.targets {
            if !target.found && target.declined.is_some() && !covered(&target.url) {
                safe = false;
                match (url_host(&target.url), &mut unfound_hosts) {
                    (Some(host), Some(hosts)) => hosts.push(host),
                    _ => unfound_hosts = None,
                }
            }
        }
        // Many declined URLs share a host. The second pass binary-searches this list for every target, so it is sorted.
        if let Some(hosts) = &mut unfound_hosts {
            hosts.sort_unstable();
            hosts.dedup();
        }
        let mut counters = self.counters;
        for target in self.targets {
            let outcome = match (target.found, target.declined) {
                (false, _) => "unrewritten",
                (true, None) => "rewritten",
                (true, Some(_)) => "declined",
            };
            *counters
                .url_rewrites
                .entry((outcome, target.declined.unwrap_or("none")))
                .or_default() += 1;
        }
        RewriteReport {
            safe,
            declined_kept: self.declined_kept,
            unfound_hosts,
            scrubbed: self.scrubbed,
            kept_in: self.kept_in,
            counters,
        }
    }
}

/// The key of the JSON object entry whose string value holds `at`, when it is a plain short key.
fn enclosing_key(bytes: &[u8], at: usize) -> Option<&str> {
    let mut open = at;
    while open > 0 {
        open -= 1;
        if bytes[open] == b'"' && !(open > 0 && bytes[open - 1] == b'\\') {
            break;
        }
    }
    let colon = open.checked_sub(1).filter(|&c| bytes[c] == b':')?;
    let key_end = colon.checked_sub(1).filter(|&e| bytes[e] == b'"')?;
    let key_start = bytes[..key_end].iter().rposition(|&b| b == b'"')? + 1;
    let key = std::str::from_utf8(&bytes[key_start..key_end]).ok()?;
    (key.len() <= 40
        && key
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'$' || b == b'-'))
    .then_some(key)
}

/// The host of a URL the inspector named, in lowercase, protocol-relative and backslash forms included.
fn url_host(url: &str) -> Option<String> {
    let with_scheme;
    let url = if replay_core_v4::url_policy::is_protocol_relative(url) {
        with_scheme = format!("https:{}", url.trim());
        with_scheme.as_str()
    } else {
        url
    };
    url::Url::parse(url)
        .ok()?
        .host_str()
        .map(str::to_ascii_lowercase)
}

/// Where the JSON string that opens at `start` ends, after its closing quote.
fn string_end(bytes: &[u8], start: usize) -> Option<usize> {
    let mut position = start + 1;
    while let Some(&byte) = bytes.get(position) {
        match byte {
            b'\\' => position += 2,
            b'"' => return Some(position + 1),
            _ => position += 1,
        }
    }
    None
}

/// The srcset with only the candidates the block keeps, each remote URL as its reference, how it was rebuilt, and the
/// URL targets of the remote URLs it held. `None` when every candidate stays, because the URL targets then replace it.
fn rebuilt_srcset(
    text: &str,
    unfetched: &HashSet<String>,
    url_targets: &HashMap<String, usize>,
    team_id: i64,
    key_month: &str,
    url_key: &[u8; 32],
) -> Option<(String, &'static str, Vec<usize>)> {
    // Streams the candidates into the new value, so that a long srcset holds no list of them.
    let mut value = String::with_capacity(text.len());
    let mut covers = Vec::new();
    let mut removed = false;
    let mut keep = |url: &str, descriptors: &str| {
        if !value.is_empty() {
            value.push_str(", ");
        }
        value.push_str(url);
        if !descriptors.is_empty() {
            value.push(' ');
            value.push_str(descriptors);
        }
    };
    for_each_srcset_candidate(text, |url, descriptors| {
        if url == AVIF_MARKER {
            removed = true;
        } else if !is_remote(url) {
            keep(url, descriptors);
        } else {
            covers.extend(url_targets.get(url));
            match url_reference(url, team_id, key_month, url_key) {
                Ok((_, reference)) if !unfetched.contains(url) => keep(&reference, descriptors),
                _ => removed = true,
            }
        }
    });
    if !removed {
        return None;
    }
    let outcome = if value.is_empty() {
        "emptied"
    } else {
        "trimmed"
    };
    Some((value, outcome, covers))
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEAM_KEY: [u8; 32] = [6; 32];

    fn rewrite(urls: &[&str], bytes: &str) -> String {
        let urls: Vec<String> = urls.iter().map(|u| (*u).to_owned()).collect();
        let mut rewrite = UrlRewrite::new(&urls, &[], 7, "2026-10", &TEAM_KEY);
        String::from_utf8(rewrite.apply(bytes.as_bytes(), true).into_owned()).unwrap()
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
            &[],
            7,
            "2026-10",
            &TEAM_KEY,
        );
        assert_eq!(
            String::from_utf8(rewrite.apply(event.as_bytes(), true).into_owned()).unwrap(),
            format!(
                r#"{{"srcset":"{ra} 1x,\n{rb} 2x,\t{} 3x"}}"#,
                declined_marker("non_public_host")
            )
        );
        assert!(rewrite.finish().safe);
    }

    #[test]
    fn rewrites_a_url_that_a_json_escape_hid() {
        let url = "https://cdn.example.com/a.png?token=secret";
        let hidden = r#"{"src":"https:\/\/cdn.example.com\/a.png?token=secr\u0065t","alt":"a\nb"}"#;
        let canonical = canonical_strings(hidden.as_bytes());
        let mut rewrite = UrlRewrite::new(&[url.to_owned()], &[], 7, "2026-10", &TEAM_KEY);
        assert_eq!(
            String::from_utf8(rewrite.apply(&canonical, true).into_owned()).unwrap(),
            format!(
                r#"{{"src":"{}","alt":"a\nb"}}"#,
                declined_marker("credential")
            )
        );
        assert!(rewrite.finish().safe);
        // An event capture wrote is left as it is.
        let plain = r#"{"text":"a\"b\\c\u0001","n":1}"#;
        assert!(matches!(
            canonical_strings(plain.as_bytes()),
            Cow::Borrowed(_)
        ));
        // A declined URL the block still holds fails the block.
        let rewrite = UrlRewrite::new(&[url.to_owned()], &[], 7, "2026-10", &TEAM_KEY);
        assert!(!rewrite.finish().safe);
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
            ("//user:secret@cdn.example.com/a.png", "credential"),
            ("//10.0.0.7/a.png", "non_public_host"),
            ("https:/user:secret@cdn.example.com/a.png", "credential"),
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
        let mut rewrite = UrlRewrite::new(&[url.to_owned()], &[], 7, "2026-10", &TEAM_KEY);
        rewrite.apply(
            format!(r#"{{"src":"{url}","alt":"x{url}"}}"#).as_bytes(),
            true,
        );
        let report = rewrite.finish();
        assert!(!report.safe);
        // The log names where the copy stayed, without the URL.
        assert_eq!(report.kept_in.as_deref(), Some("alt"));
    }
}
