//! The writer's one pass over an event. It copies the event, and where the inspector read each slot, it writes the
//! slot's references and markers, so it searches the event for no URL. A URL the policy refuses must leave the block
//! wherever it is, so the writer also overwrites each copy of one, which only a block that holds one pays for.

use std::borrow::Cow;
use std::collections::{BTreeMap, HashMap, VecDeque};

use aho_corasick::{AhoCorasick, AhoCorasickKind, MatchKind};
use metrics::counter;
use replay_core_v4::bytescan::{unescape, write_json_string, Span};
use replay_core_v4::inspect::css::{escape_in_identifier, write_css_edit, CssEdit};
use replay_core_v4::inspect::dom::{for_each_srcset_candidate, DeclinedUrl, RemoteKind};
use replay_core_v4::inspect::edits::{Edit, EditSource, EventEdits, Slot};
use replay_core_v4::inspect::srcset::{shown_candidate, SrcsetSlot};
use replay_core_v4::refs::{declined_url_ref, UrlAsset};
use replay_core_v4::seal::image_url_key;
use replay_core_v4::url_policy::is_remote;
use replay_core_v4::v4_image_refs::{bundled_font_ref, ImageDecline, IMAGE_DECLINED_PREFIX};

use crate::urls::url_reference;

fn asset_of(kind: RemoteKind) -> UrlAsset {
    match kind {
        RemoteKind::Image => UrlAsset::Image,
        RemoteKind::Font | RemoteKind::BundledFont(_) => UrlAsset::Font,
    }
}

fn kind_label(kind: RemoteKind) -> &'static str {
    match kind {
        RemoteKind::Image => "image",
        RemoteKind::Font => "font",
        RemoteKind::BundledFont(_) => "bundled_font",
    }
}

fn json_string_contents(text: &str) -> Vec<u8> {
    let mut quoted = Vec::with_capacity(text.len() + 2);
    write_json_string(text, &mut quoted);
    quoted[1..quoted.len() - 1].to_vec()
}

#[derive(Clone)]
struct Named {
    text: String,
    /// The policy's reason, for a URL it declines.
    decline: Option<&'static str>,
}

#[derive(Debug, Default, PartialEq, Eq)]
pub struct SpliceCounters {
    srcset_rewrites: BTreeMap<&'static str, u64>,
    css_rewrites: BTreeMap<&'static str, u64>,
    url_rewrites: BTreeMap<(&'static str, &'static str, &'static str), u64>,
    pub removed_images: [u64; ImageDecline::ALL.len()],
}

impl SpliceCounters {
    pub fn emit(&self) {
        for (&outcome, &count) in &self.srcset_rewrites {
            counter!("ai_research_v4_recorder_srcset_rewrites_total", "outcome" => outcome)
                .increment(count);
        }
        for (&kind, &count) in &self.css_rewrites {
            counter!(
                "ai_research_v4_recorder_css_rewrites_total",
                "kind" => kind,
                "outcome" => "rewritten",
            )
            .increment(count);
        }
        for (&(kind, outcome, reason), &count) in &self.url_rewrites {
            counter!(
                "ai_research_v4_recorder_image_url_rewrites_total",
                "kind" => kind,
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

/// Refused URLs that hold one another can end many matches at each byte, so a block past this many is dropped.
const MAX_BLOCK_DECLINED_MATCHES: usize = 1_000_000;

/// Overwrites every copy of the block's refused URLs, as a JSON string holds it and as a CSS selector escapes it.
pub struct DeclinedCopies {
    matcher: AhoCorasick,
    markers: Vec<Vec<u8>>,
    longest: usize,
    matches_left: usize,
}

#[derive(Clone, Copy)]
struct Overwrite {
    start: usize,
    end: usize,
    marker: usize,
}

impl DeclinedCopies {
    pub fn new(declined: &[DeclinedUrl]) -> Option<Self> {
        let mut patterns = Vec::new();
        let mut markers = Vec::new();
        for DeclinedUrl { url, kind, decline } in declined {
            let marker = declined_url_ref(asset_of(*kind), *decline);
            // A selector copy takes an escaped marker, so that its colons do not start pseudo-classes.
            for (form, replacement) in [
                (url.clone(), marker.clone()),
                (escape_in_identifier(url), escape_in_identifier(&marker)),
            ] {
                patterns.push(json_string_contents(&form));
                markers.push(json_string_contents(&replacement));
            }
        }
        let matcher = AhoCorasick::builder()
            .kind(Some(AhoCorasickKind::ContiguousNFA))
            .match_kind(MatchKind::Standard)
            .build(&patterns)
            .ok()?;
        let longest = patterns.iter().map(Vec::len).max()?;
        Some(Self {
            matcher,
            markers,
            longest,
            matches_left: MAX_BLOCK_DECLINED_MATCHES,
        })
    }

    /// Copies that overlap share one span, so that a refused URL that starts inside another one is overwritten too.
    pub fn apply<'b>(&mut self, bytes: &'b [u8], overwritten: &mut u64) -> Option<Cow<'b, [u8]>> {
        let mut out = None;
        let mut copied_to = 0;
        let mut pending: VecDeque<Overwrite> = VecDeque::new();
        // Matches come in order of their end, so a later match cannot reach a span that ends `longest` bytes before.
        for found in self.matcher.find_overlapping_iter(bytes) {
            self.matches_left = self.matches_left.checked_sub(1)?;
            let mut span = Overwrite {
                start: found.start(),
                end: found.end(),
                marker: found.pattern().as_usize(),
            };
            while let Some(last) = pending.back().copied().filter(|last| last.end > span.start) {
                pending.pop_back();
                if last.start <= span.start {
                    span.start = last.start;
                    span.marker = last.marker;
                }
            }
            pending.push_back(span);
            while let Some(first) = pending
                .front()
                .copied()
                .filter(|first| first.end + self.longest <= span.end)
            {
                pending.pop_front();
                self.write(bytes, first, &mut out, &mut copied_to);
                *overwritten += 1;
            }
        }
        for span in pending {
            self.write(bytes, span, &mut out, &mut copied_to);
            *overwritten += 1;
        }
        Some(match out {
            Some(mut out) => {
                out.extend_from_slice(&bytes[copied_to..]);
                Cow::Owned(out)
            }
            None => Cow::Borrowed(bytes),
        })
    }

    fn write(
        &self,
        bytes: &[u8],
        span: Overwrite,
        out: &mut Option<Vec<u8>>,
        copied_to: &mut usize,
    ) {
        let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
        out.extend_from_slice(&bytes[*copied_to..span.start]);
        out.extend_from_slice(&self.markers[span.marker]);
        *copied_to = span.end;
    }
}

pub struct Splicer<'b> {
    edits: &'b [EventEdits],
    next: usize,
    team_id: i64,
    key_month: String,
    url_key: [u8; 32],
    named: HashMap<(String, RemoteKind), Named>,
    pub counters: SpliceCounters,
}

impl<'b> Splicer<'b> {
    pub fn new(
        edits: &'b [EventEdits],
        team_id: i64,
        key_month: &str,
        team_key: &[u8; 32],
    ) -> Self {
        Self {
            edits,
            next: 0,
            team_id,
            key_month: key_month.to_owned(),
            url_key: image_url_key(team_key),
            named: HashMap::new(),
            counters: SpliceCounters::default(),
        }
    }

    /// The edits of the block's event at `event`. Events come in order.
    pub fn edits_of(&mut self, event: u32) -> Option<&'b [Edit]> {
        while self.edits.get(self.next).is_some_and(|e| e.event < event) {
            self.next += 1;
        }
        let edits = self.edits.get(self.next).filter(|e| e.event == event)?;
        Some(&edits.edits)
    }

    /// Copies `range` of `bytes`, the bytes that `source` names, into `out`, with each edit inside it written in place.
    pub fn copy(
        &mut self,
        edits: &[Edit],
        source: EditSource,
        bytes: &[u8],
        range: Span,
        out: &mut Vec<u8>,
    ) {
        let mut copied_to = range.0;
        let first = edits.partition_point(|edit| (edit.source, edit.value.0) < (source, range.0));
        for edit in edits[first..]
            .iter()
            .take_while(|edit| edit.source == source && edit.value.0 < range.1)
        {
            if edit.value.0 < copied_to || edit.value.1 > range.1 {
                continue;
            }
            let Ok(text) = unescape(bytes, edit.value) else {
                continue;
            };
            if let Some(replacement) = self.replacement(&edit.slot, &text) {
                out.extend_from_slice(&bytes[copied_to..edit.value.0]);
                write_json_string(&replacement, out);
                copied_to = edit.value.1;
            }
        }
        out.extend_from_slice(&bytes[copied_to..range.1]);
    }

    fn named(&mut self, url: &str, kind: RemoteKind) -> Named {
        if let Some(named) = self.named.get(&(url.to_owned(), kind)) {
            return named.clone();
        }
        let asset = asset_of(kind);
        let named = match (
            kind,
            url_reference(url, asset, self.team_id, &self.key_month, &self.url_key),
        ) {
            (RemoteKind::BundledFont(slug), named) => Named {
                text: bundled_font_ref(slug),
                decline: named.err().map(|decline| decline.label()),
            },
            (_, Ok((_, reference))) => Named {
                text: reference,
                decline: None,
            },
            (_, Err(decline)) => Named {
                text: declined_url_ref(asset, decline),
                decline: Some(decline.label()),
            },
        };
        let outcome = if named.decline.is_some() {
            "declined"
        } else {
            "rewritten"
        };
        *self
            .counters
            .url_rewrites
            .entry((kind_label(kind), outcome, named.decline.unwrap_or("none")))
            .or_default() += 1;
        self.named.insert((url.to_owned(), kind), named.clone());
        named
    }

    fn replacement(&mut self, slot: &Slot, text: &str) -> Option<String> {
        match slot {
            Slot::Url => {
                let url = text.trim();
                is_remote(url).then(|| self.named(url, RemoteKind::Image).text)
            }
            Slot::Srcset(slot) => self.rebuilt_srcset(text, *slot),
            Slot::Css(edit) => Some(self.written_css(text, edit)),
        }
    }

    fn written_css(&mut self, text: &str, edit: &CssEdit) -> String {
        for piece in &edit.pieces {
            if piece.parts.len() > 1 {
                let function = &text[piece.range.clone()];
                let kind = if function
                    .get(..4)
                    .is_some_and(|start| start.eq_ignore_ascii_case("url("))
                {
                    "relative_url"
                } else {
                    "image_set"
                };
                *self.counters.css_rewrites.entry(kind).or_default() += 1;
            }
        }
        write_css_edit(text, edit, &mut |url| self.named(&url.url, url.kind).text)
    }

    /// The srcset with only the candidate it shows, a remote one as its reference. `None` when it has nothing to change.
    fn rebuilt_srcset(&mut self, text: &str, slot: SrcsetSlot) -> Option<String> {
        let shown = shown_candidate(text, slot).map(|kept| kept.index);
        let mut value = String::with_capacity(text.len());
        let (mut removed, mut remote) = (false, false);
        let mut index = 0;
        for_each_srcset_candidate(text, |url, descriptors| {
            let is_shown = shown == Some(index);
            index += 1;
            let written = if is_remote(url) {
                remote = true;
                is_shown
                    .then(|| self.named(url, RemoteKind::Image))
                    .filter(|named| named.decline.is_none())
                    .map(|named| named.text)
            } else {
                (is_shown && !url.starts_with(IMAGE_DECLINED_PREFIX)).then(|| url.to_owned())
            };
            match written {
                Some(written) => {
                    if !value.is_empty() {
                        value.push_str(", ");
                    }
                    value.push_str(&written);
                    if !descriptors.is_empty() {
                        value.push(' ');
                        value.push_str(descriptors);
                    }
                }
                None => removed = true,
            }
        });
        if removed {
            let outcome = if value.is_empty() {
                "emptied"
            } else {
                "trimmed"
            };
            *self.counters.srcset_rewrites.entry(outcome).or_default() += 1;
        }
        (removed || remote).then_some(value)
    }
}
