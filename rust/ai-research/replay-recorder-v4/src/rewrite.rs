//! Replaces the remote image URLs of a stored block with their `imageurl:v4` references, as v3 replaced them. A URL the
//! policy declines becomes a marker that names the reason, so that no credential, signature or private host stays in
//! the block. The inspector names the URLs: those in image slots, CSS included.
//!
//! A srcset is rebuilt instead: it keeps only the candidate that the inspector fetched, by [`usable_candidate`] in the
//! value the inspector read. It keeps none when that value has no usable candidate, which makes the inspector fetch the
//! img's `src`, or when the candidate is remote in a picture source of a type the fetcher does not store. A browser
//! skips a source with no candidates, so it falls back to a source or an img that can load, where a marker in the list
//! would show a broken image. The writer rebuilds each srcset in the bytes it stores, after escapes were written again
//! and inline images left. Moving an inline image out can change how a srcset parses, so the writer finds the
//! inspector's candidate by its [`CandidatePosition`].

use std::borrow::Cow;
use std::cell::Cell;
use std::collections::{BTreeMap, HashMap};

use aho_corasick::{AhoCorasick, AhoCorasickKind, MatchKind};
use metrics::counter;
use posthog_replay_anonymizer::v4_image_refs::{
    url_declined_marker, ImageDecline, IMAGE_DECLINED_PREFIX,
};
use replay_core_v4::bytescan::{unescape, write_json_string, Span};
use replay_core_v4::inspect::css::{escape_in_identifier, rewrite_functions, CssRewrite};
use replay_core_v4::inspect::dom::{for_each_srcset_candidate, Srcset};
use replay_core_v4::inspect::srcset::usable_candidate;
use replay_core_v4::scan::tokens::{Token, Tokens};
use replay_core_v4::seal::image_url_key;
use replay_core_v4::url_policy::is_remote;

use crate::scrub::{Scrub, Scrubber};
use crate::urls::url_reference;

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

/// Runs a stage of `apply` on bytes that an earlier stage may own, and keeps those bytes when the stage changes nothing.
macro_rules! then_stage {
    ($bytes:expr, $writer:ident . $stage:ident) => {
        match $bytes {
            Cow::Borrowed(bytes) => $writer.$stage(bytes),
            Cow::Owned(owned) => {
                let changed = match $writer.$stage(&owned) {
                    Cow::Owned(changed) => Some(changed),
                    Cow::Borrowed(_) => None,
                };
                Cow::Owned(changed.unwrap_or(owned))
            }
        }
    };
}
/// A CSS-escaped `:/` or `//` as a JSON string holds it, which starts a URL that a selector names. PHP-style JSON holds
/// `:\/\/` too, so a `//` right after a plain colon does not count.
const ESCAPED_URL_STARTS: [&[u8]; 2] = [br"\\:\\/", br"\\/\\/"];

fn holds_escaped_url(starts: &AhoCorasick, bytes: &[u8]) -> bool {
    starts.find_iter(bytes).any(|found| {
        found.pattern().as_usize() == 0 || found.start() == 0 || bytes[found.start() - 1] != b':'
    })
}

/// The block's URLs as a selector holds them. Most events hold none, so these are built when one first does.
struct EscapedMatchers {
    urls: Option<AhoCorasick>,
    declined: Option<AhoCorasick>,
    replacements: Vec<Vec<u8>>,
}

impl EscapedMatchers {
    fn new(targets: &[Target]) -> Self {
        let build = |targets: &mut dyn Iterator<Item = &Target>| {
            let patterns: Vec<Vec<u8>> = targets
                .map(|target| json_string_contents(&escape_in_identifier(&target.url)))
                .collect();
            (!patterns.is_empty())
                .then(|| {
                    AhoCorasick::builder()
                        .kind(Some(AhoCorasickKind::ContiguousNFA))
                        .match_kind(MatchKind::LeftmostLongest)
                        .build(patterns)
                        .ok()
                })
                .flatten()
        };
        Self {
            urls: build(&mut targets.iter()),
            declined: build(&mut targets.iter().filter(|target| target.declined.is_some())),
            replacements: targets
                .iter()
                .map(|target| {
                    json_string_contents(&escape_in_identifier(&String::from_utf8_lossy(
                        &target.replacement,
                    )))
                })
                .collect(),
        }
    }
}

fn json_string_contents(text: &str) -> Vec<u8> {
    let mut escaped = Vec::with_capacity(text.len() + 2);
    write_json_string(text, &mut escaped);
    escaped.pop();
    escaped.remove(0);
    escaped
}

struct CssTarget {
    /// With its URLs already replaced, so that a long page URL resolved for many short relative URLs never fills memory.
    replacement: String,
    /// The indexes in `targets` of the URLs that the rewrite removes or replaces, which count as found when it applies.
    covers: Vec<usize>,
    kind: &'static str,
    found: bool,
}

/// The keys whose string value is CSS text. Every string under one counts too, such as a declaration in a style diff.
const CSS_KEYS: [&[u8]; 7] = [
    b"_cssText",
    b"style",
    b"textContent",
    b"rule",
    b"replace",
    b"replaceSync",
    b"value",
];

struct CssStrings<'b> {
    bytes: &'b [u8],
    tokens: Tokens<'b>,
    containers_in_css: Vec<bool>,
    key: Option<Span>,
}

impl<'b> CssStrings<'b> {
    fn new(bytes: &'b [u8]) -> Self {
        Self {
            bytes,
            tokens: Tokens::new(bytes, (0, bytes.len())),
            containers_in_css: Vec::new(),
            key: None,
        }
    }
}

impl Iterator for CssStrings<'_> {
    type Item = Span;

    fn next(&mut self) -> Option<Span> {
        for token in self.tokens.by_ref() {
            let in_css = self.containers_in_css.last() == Some(&true)
                || self
                    .key
                    .is_some_and(|key| CSS_KEYS.contains(&&self.bytes[key.0..key.1]));
            match token {
                Token::ObjectStart | Token::ArrayStart => {
                    self.containers_in_css.push(in_css);
                    self.key = None;
                }
                Token::ObjectEnd | Token::ArrayEnd => {
                    self.containers_in_css.pop();
                    self.key = None;
                }
                Token::Key { span, escaped } => self.key = (!escaped).then_some(span),
                Token::Value(span) => {
                    self.key = None;
                    if in_css && self.bytes.get(span.0) == Some(&b'"') {
                        return Some(span);
                    }
                }
            }
        }
        None
    }
}

/// The metric label of a rewrite: the inspector rewrites a whole `url()` only to resolve a relative URL.
fn css_rewrite_kind(text: &str) -> &'static str {
    if text
        .get(..4)
        .is_some_and(|start| start.eq_ignore_ascii_case("url("))
    {
        "relative_url"
    } else {
        "image_set"
    }
}

struct Target {
    url: String,
    replacement: Vec<u8>,
    /// The policy's reason, for a declined URL.
    declined: Option<&'static str>,
    found: Cell<bool>,
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
    escaped_url_starts: AhoCorasick,
    escaped: Option<EscapedMatchers>,
    css_matcher: Option<AhoCorasick>,
    css_targets: Vec<CssTarget>,
    css_texts: HashMap<String, usize>,
    /// The usable candidate of each inspected srcset value, by the [`remote_urls`] of the value. Only a stored srcset with
    /// the same remote URLs is rebuilt, so a srcset key outside an image slot, such as in a custom event's payload, stays
    /// as it is. Values with the same remote URLs share an entry, so each keeps the candidate of every one of them.
    kept_srcset_candidates: HashMap<Vec<String>, Vec<CandidatePosition>>,
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
    css_rewrites: BTreeMap<(&'static str, &'static str), u64>,
    url_rewrites: BTreeMap<(&'static str, &'static str), u64>,
    pub removed_images: [u64; ImageDecline::ALL.len()],
}

impl PassCounters {
    pub fn emit(&self) {
        for (&outcome, &count) in &self.srcset_rewrites {
            counter!("ai_research_v4_recorder_srcset_rewrites_total", "outcome" => outcome)
                .increment(count);
        }
        for (&(kind, outcome), &count) in &self.css_rewrites {
            counter!(
                "ai_research_v4_recorder_css_rewrites_total",
                "kind" => kind,
                "outcome" => outcome,
            )
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
        for (reason, &count) in ImageDecline::ALL.iter().zip(&self.removed_images) {
            counter!("ai_research_v4_recorder_removed_images_total", "reason" => reason.label())
                .increment(count);
        }
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
        css_rewrites: &[CssRewrite],
        team_id: i64,
        key_month: &str,
        team_key: &[u8; 32],
    ) -> Self {
        let url_key = image_url_key(team_key);
        let mut patterns = Vec::with_capacity(urls.len() + srcsets.len());
        let mut targets = Vec::with_capacity(urls.len() + srcsets.len());
        for url in urls {
            // The block holds the URL as a JSON string holds it.
            patterns.push(json_string_contents(url));
            let (replacement, declined) = match url_reference(url, team_id, key_month, &url_key) {
                Ok((_, reference)) => (reference, None),
                Err(decline) => (url_declined_marker(decline.into()), Some(decline.label())),
            };
            targets.push(Target {
                url: url.clone(),
                replacement: replacement.into_bytes(),
                declined,
                found: Cell::new(false),
            });
        }
        let url_targets: HashMap<String, usize> = urls
            .iter()
            .enumerate()
            .map(|(index, url)| (url.clone(), index))
            .collect();
        let css_matcher = (!css_rewrites.is_empty())
            .then(|| {
                AhoCorasick::builder()
                    .kind(Some(AhoCorasickKind::ContiguousNFA))
                    .match_kind(MatchKind::LeftmostLongest)
                    .build(
                        css_rewrites
                            .iter()
                            .map(|rewrite| json_string_contents(&rewrite.text)),
                    )
                    .ok()
            })
            .flatten();
        let mut kept_srcset_candidates: HashMap<Vec<String>, Vec<CandidatePosition>> =
            HashMap::new();
        for srcset in srcsets {
            let kept = kept_srcset_candidates
                .entry(remote_urls(&srcset.text))
                .or_default();
            if let Some(position) = usable_position(srcset).filter(|p| !kept.contains(p)) {
                kept.push(position);
            }
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
        let css_targets: Vec<CssTarget> = css_rewrites
            .iter()
            .map(|rewrite| {
                let mut covers = Vec::new();
                let resolved = match &rewrite.resolved {
                    Some(absolute) => {
                        let reference = match url_reference(absolute, team_id, key_month, &url_key)
                        {
                            Ok((_, reference)) => reference,
                            Err(decline) => url_declined_marker(decline.into()),
                        };
                        rewrite.replacement.replacen(
                            &format!("\"{absolute}\""),
                            &format!("\"{reference}\""),
                            1,
                        )
                    }
                    None => rewrite.replacement.clone(),
                };
                let replacement = match &matcher {
                    Some(matcher) => {
                        let quoted =
                            [b"\"".as_slice(), &json_string_contents(&resolved), b"\""].concat();
                        let replaced = replace_targets(
                            matcher,
                            &targets,
                            false,
                            None,
                            &quoted,
                            &mut |index| covers.push(index),
                        );
                        unescape(&replaced, (0, replaced.len()))
                            .map_or_else(|_| resolved.clone(), Cow::into_owned)
                    }
                    None => resolved,
                };
                covers.extend(
                    rewrite
                        .dropped
                        .iter()
                        .filter_map(|url| url_targets.get(url).copied()),
                );
                CssTarget {
                    replacement,
                    covers,
                    kind: css_rewrite_kind(&rewrite.text),
                    found: false,
                }
            })
            .collect();
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
            escaped_url_starts: AhoCorasick::new(ESCAPED_URL_STARTS)
                .expect("two literal patterns build"),
            escaped: None,
            css_matcher,
            css_targets,
            css_texts: css_rewrites
                .iter()
                .enumerate()
                .map(|(index, rewrite)| (rewrite.text.clone(), index))
                .collect(),
            kept_srcset_candidates,
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
            let Ok(text) = unescape(bytes, (start, end)) else {
                continue;
            };
            let Some(kept) = self.kept_srcset_candidates.get(&remote_urls(&text)) else {
                continue;
            };
            let Some((value, outcome, covers)) = rebuilt_srcset(
                &text,
                kept,
                &self.url_targets,
                self.team_id,
                &self.key_month,
                &self.url_key,
            ) else {
                continue;
            };
            for url in covers {
                self.targets[url].found.set(true);
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

    /// Rewrites only whole `url()` and `image-set()` functions inside JSON strings that hold CSS, found as the inspector
    /// finds them. So a class such as `bg-[url(/a.png)]`, a quoted string or a comment keeps its text.
    fn rewrite_css<'b>(&mut self, bytes: &'b [u8]) -> Cow<'b, [u8]> {
        let Some(matcher) = self.css_matcher.clone() else {
            return Cow::Borrowed(bytes);
        };
        let mut css_strings: Option<std::iter::Peekable<CssStrings<'_>>> = None;
        let mut out: Option<Vec<u8>> = None;
        let mut copied_to = 0;
        let mut scanned_to = 0;
        for found in matcher.find_iter(bytes) {
            let start = found.start();
            if start < scanned_to {
                continue;
            }
            let strings = css_strings.get_or_insert_with(|| CssStrings::new(bytes).peekable());
            while strings.next_if(|string| string.1 <= start).is_some() {}
            let Some(&string) = strings.peek().filter(|string| string.0 < start) else {
                continue;
            };
            scanned_to = string.1;
            let Ok(css) = unescape(bytes, string) else {
                continue;
            };
            let rewritten = rewrite_functions(&css, &mut |function| {
                let &index = self.css_texts.get(function)?;
                let target = &mut self.css_targets[index];
                target.found = true;
                for &url in &target.covers {
                    self.targets[url].found.set(true);
                }
                Some(target.replacement.clone())
            });
            if let Some(rewritten) = rewritten {
                let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
                out.extend_from_slice(&bytes[copied_to..string.0]);
                write_json_string(&rewritten, out);
                copied_to = string.1;
            }
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
        let rebuilt = if dom_event {
            self.rebuild_srcsets(bytes)
        } else {
            Cow::Borrowed(bytes)
        };
        let rewritten = then_stage!(rebuilt, self.rewrite_css);
        let replaced = then_stage!(rewritten, self.replace_urls);
        let replaced = if holds_escaped_url(&self.escaped_url_starts, replaced.as_ref()) {
            then_stage!(replaced, self.replace_escaped_urls)
        } else {
            replaced
        };
        let (scrubbed, count) = self.scrubber.apply(&replaced);
        if count == 0 {
            return replaced;
        }
        self.scrubbed += count;
        Cow::Owned(scrubbed.into_owned())
    }

    fn replace_escaped_urls<'b>(&mut self, bytes: &'b [u8]) -> Cow<'b, [u8]> {
        let escaped = self
            .escaped
            .get_or_insert_with(|| EscapedMatchers::new(&self.targets));
        let Some(matcher) = &escaped.urls else {
            return Cow::Borrowed(bytes);
        };
        let targets = &self.targets;
        let out = replace_targets(
            matcher,
            targets,
            self.fallback.overwrite_declined,
            Some(&escaped.replacements),
            bytes,
            &mut |index| targets[index].found.set(true),
        );
        if escaped
            .declined
            .as_ref()
            .is_some_and(|declined| declined.is_match(out.as_ref()))
        {
            self.declined_kept = true;
        }
        out
    }

    fn replace_urls<'b>(&mut self, bytes: &'b [u8]) -> Cow<'b, [u8]> {
        let Some(matcher) = &self.matcher else {
            return Cow::Borrowed(bytes);
        };
        let targets = &self.targets;
        let out = replace_targets(
            matcher,
            targets,
            self.fallback.overwrite_declined,
            None,
            bytes,
            &mut |index| targets[index].found.set(true),
        );
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
            if !target.found.get() && target.declined.is_some() && !covered(&target.url) {
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
        for target in self.css_targets {
            let outcome = if target.found { "rewritten" } else { "unfound" };
            *counters
                .css_rewrites
                .entry((target.kind, outcome))
                .or_default() += 1;
        }
        for target in self.targets {
            let outcome = match (target.found.get(), target.declined) {
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

fn replace_targets<'b>(
    matcher: &AhoCorasick,
    targets: &[Target],
    overwrite_declined: bool,
    escaped_replacements: Option<&[Vec<u8>]>,
    bytes: &'b [u8],
    replaced: &mut dyn FnMut(usize),
) -> Cow<'b, [u8]> {
    let mut out: Option<Vec<u8>> = None;
    let mut copied_to = 0;
    for found in matcher.find_iter(bytes) {
        let (start, end) = (found.start(), found.end());
        let index = found.pattern().as_usize();
        // An escaped URL goes on with an escaped character, which a JSON string holds as `\\` and the character.
        let continues_after = bytes.get(end).is_some_and(|&after| continues_url(after))
            || (escaped_replacements.is_some()
                && bytes.get(end..end + 2) == Some(br"\\")
                && bytes
                    .get(end + 2)
                    .is_some_and(|&after| continues_url(after)));
        // A declined URL inside a longer URL is replaced too when the fallback asks, so that it cannot stay.
        let overwrite = overwrite_declined && targets[index].declined.is_some();
        if !overwrite
            && (start.checked_sub(1).is_some_and(|before| {
                continues_url(bytes[before]) && !ends_with_escape(bytes, start)
            }) || continues_after)
        {
            continue;
        }
        replaced(index);
        let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
        out.extend_from_slice(&bytes[copied_to..start]);
        out.extend_from_slice(match escaped_replacements {
            Some(replacements) => &replacements[index],
            None => &targets[index].replacement,
        });
        copied_to = end;
    }
    let out = match out {
        Some(mut out) => {
            out.extend_from_slice(&bytes[copied_to..]);
            Cow::Owned(out)
        }
        None => Cow::Borrowed(bytes),
    };
    out
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

/// The remote URLs of a srcset, in order. The writer moves only inline images out of a srcset, so these name the
/// srcset the same way in the event the inspector read and in the block the writer stores.
fn remote_urls(srcset: &str) -> Vec<String> {
    let mut urls = Vec::new();
    for_each_srcset_candidate(srcset, |url, _| {
        if is_remote(url) {
            urls.push(url.to_owned());
        }
    });
    urls
}

/// A srcset candidate by its kind and its index among the candidates of that kind. The writer moves only inline images
/// out of a srcset, so a position names the same candidate in the event the inspector read and in the block the writer
/// stores.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CandidatePosition {
    Remote(usize),
    Inline(usize),
}

fn for_each_positioned_candidate<'s>(
    srcset: &'s str,
    mut found: impl FnMut(CandidatePosition, &'s str, &'s str),
) {
    let (mut remote, mut inline) = (0, 0);
    for_each_srcset_candidate(srcset, |url, descriptors| {
        let position = if is_remote(url) {
            remote += 1;
            CandidatePosition::Remote(remote - 1)
        } else {
            inline += 1;
            CandidatePosition::Inline(inline - 1)
        };
        found(position, url, descriptors);
    });
}

fn usable_position(srcset: &Srcset) -> Option<CandidatePosition> {
    // `usable_candidate` reads only a well-formed srcset, whose candidates `for_each_srcset_candidate` reads in the same order.
    let (usable_index, url) = usable_candidate(&srcset.text)?;
    if srcset.unfetched_type && is_remote(url) {
        return None;
    }
    let (mut index, mut usable) = (0, None);
    for_each_positioned_candidate(&srcset.text, |position, _, _| {
        if index == usable_index {
            usable = Some(position);
        }
        index += 1;
    });
    usable
}

/// The srcset with only the candidate the block keeps, a remote URL as its reference, how it was rebuilt, and the URL
/// targets of the remote URLs it held. `None` when the srcset keeps its one candidate, because the URL targets then
/// replace it.
fn rebuilt_srcset(
    text: &str,
    kept: &[CandidatePosition],
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
    for_each_positioned_candidate(text, |position, url, descriptors| {
        let is_kept = kept.contains(&position);
        match position {
            CandidatePosition::Remote(_) => {
                covers.extend(url_targets.get(url));
                match url_reference(url, team_id, key_month, url_key) {
                    Ok((_, reference)) if is_kept => keep(&reference, descriptors),
                    _ => removed = true,
                }
            }
            CandidatePosition::Inline(_) if is_kept && !url.starts_with(IMAGE_DECLINED_PREFIX) => {
                keep(url, descriptors)
            }
            CandidatePosition::Inline(_) => removed = true,
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
    use base64::engine::general_purpose::STANDARD;
    use base64::Engine;
    use replay_core_v4::bytescan::canonical_strings;

    use super::*;

    const TEAM_KEY: [u8; 32] = [6; 32];

    fn rewrite(urls: &[&str], bytes: &str) -> String {
        let urls: Vec<String> = urls.iter().map(|u| (*u).to_owned()).collect();
        let mut rewrite = UrlRewrite::new(&urls, &[], &[], 7, "2026-10", &TEAM_KEY);
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
            &[],
            7,
            "2026-10",
            &TEAM_KEY,
        );
        assert_eq!(
            String::from_utf8(rewrite.apply(event.as_bytes(), true).into_owned()).unwrap(),
            format!(
                r#"{{"srcset":"{ra} 1x,\n{rb} 2x,\timageurl:v4:declined:non_public_host 3x"}}"#
            )
        );
        assert!(rewrite.finish().safe);
    }

    #[test]
    fn keeps_only_the_srcset_candidate_the_inspector_fetched() {
        let png = format!(
            "data:image/png;base64,{}",
            STANDARD.encode(b"\x89PNG\r\n\x1a\nbytes")
        );
        let svg = "data:image/svg+xml,%3Csvg%2F%3E";
        let (a, b, private) = (
            "https://cdn.example.com/a.png",
            "https://cdn.example.com/b.png",
            "https://10.0.0.7/b.png",
        );
        let over_limit = ImageDecline::OverLimit.marker();
        for (inspected, stored, expected) in [
            // A message past its image cap stores the PNG as `over_limit`, where the inspector read a data URI.
            (
                format!("{png} 1x, {svg} 2x"),
                format!("{over_limit} 1x, {svg} 2x"),
                format!("{svg} 2x"),
            ),
            (
                format!("{a} 1x, {b} 2x"),
                format!("{a} 1x, {b} 2x"),
                format!("{} 2x", reference(b)),
            ),
            // The 1x candidate has no fetch job, so it cannot stand in for the declined 2x one.
            (
                format!("{a} 1x, {private} 2x"),
                format!("{a} 1x, {private} 2x"),
                String::new(),
            ),
            (
                format!("{a} 1x, {b} 640w"),
                format!("{a} 1x, {b} 640w"),
                String::new(),
            ),
            // The image scan moves out a data URI in any case, where the inspector read a malformed srcset and fetched
            // the img's `src` instead.
            (
                format!(
                    "DATA:image/png;base64,{} 1x, {b} 2x",
                    STANDARD.encode(b"\x89PNG\r\n\x1a\nbytes")
                ),
                format!("image:v4:7:2026-10:0123abcd 1x, {b} 2x"),
                String::new(),
            ),
        ] {
            let srcset = Srcset {
                raw: serde_json::to_vec(&inspected).unwrap(),
                text: inspected.clone(),
                unfetched_type: false,
            };
            let mut rewrite = UrlRewrite::new(&[], &[srcset], &[], 7, "2026-10", &TEAM_KEY);
            let stored = format!(r#"{{"srcset":"{stored}"}}"#);
            assert_eq!(
                String::from_utf8(rewrite.apply(stored.as_bytes(), true).into_owned()).unwrap(),
                format!(r#"{{"srcset":"{expected}"}}"#),
                "{inspected}"
            );
        }
    }

    #[test]
    fn rewrites_a_url_that_a_json_escape_hid() {
        let url = "https://cdn.example.com/a.png?token=secret";
        let hidden = r#"{"src":"https:\/\/cdn.example.com\/a.png?token=secr\u0065t","alt":"a\nb"}"#;
        let canonical = canonical_strings(hidden.as_bytes());
        let mut rewrite = UrlRewrite::new(&[url.to_owned()], &[], &[], 7, "2026-10", &TEAM_KEY);
        assert_eq!(
            String::from_utf8(rewrite.apply(&canonical, true).into_owned()).unwrap(),
            r#"{"src":"imageurl:v4:declined:credential","alt":"a\nb"}"#
        );
        assert!(rewrite.finish().safe);
        // An event capture wrote is left as it is.
        let plain = r#"{"text":"a\"b\\c\u0001","n":1}"#;
        assert!(matches!(
            canonical_strings(plain.as_bytes()),
            Cow::Borrowed(_)
        ));
        // A declined URL the block still holds fails the block.
        let rewrite = UrlRewrite::new(&[url.to_owned()], &[], &[], 7, "2026-10", &TEAM_KEY);
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
                format!(r#"{{"src":"imageurl:v4:declined:{reason}"}}"#),
                "{url}"
            );
        }
        // A second copy inside a longer URL stays as it is, so the block fails.
        let url = "https://bucket.s3.amazonaws.com/a.png?X-Amz-Signature=abc123";
        let mut rewrite = UrlRewrite::new(&[url.to_owned()], &[], &[], 7, "2026-10", &TEAM_KEY);
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
