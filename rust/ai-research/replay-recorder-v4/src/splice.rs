//! The writer's one pass over an event. It copies the event, and where the inspector read each slot, it writes the
//! slot's references, and each URL that gets none without its credentials, so it searches the event for no URL.

use std::collections::{BTreeMap, HashMap};

use metrics::counter;
use replay_core_v4::bytescan::{unescape, write_json_string, Span};
use replay_core_v4::inspect::css::{write_css_edit, CssEdit};
use replay_core_v4::inspect::dom::{for_each_srcset_candidate, RemoteKind};
use replay_core_v4::inspect::edits::{Edit, EditSource, EventEdits, Slot};
use replay_core_v4::inspect::srcset::{shown_candidate, SrcsetSlot};
use replay_core_v4::refs::UrlAsset;
use replay_core_v4::seal::image_url_key;
use replay_core_v4::url_policy::{is_remote, without_credentials};
use replay_core_v4::v4_image_refs::{bundled_font_ref, ImageDecline, IMAGE_DECLINED_PREFIX};

use crate::urls::url_reference;

fn asset_of(kind: RemoteKind) -> UrlAsset {
    match kind {
        RemoteKind::Image | RemoteKind::Link => UrlAsset::Image,
        RemoteKind::Font | RemoteKind::BundledFont(_) => UrlAsset::Font,
    }
}

fn kind_label(kind: RemoteKind) -> &'static str {
    match kind {
        RemoteKind::Image => "image",
        RemoteKind::Font => "font",
        RemoteKind::BundledFont(_) => "bundled_font",
        RemoteKind::Link => "link",
    }
}

/// `url` without its credentials, or as it is when it holds none.
fn kept(url: &str) -> String {
    without_credentials(url).unwrap_or_else(|| url.to_owned())
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
                text: kept(url),
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
                if is_remote(url) {
                    Some(self.named(url, RemoteKind::Image).text)
                } else {
                    without_credentials(text)
                }
            }
            Slot::Srcset(slot) => self.rebuilt_srcset(text, *slot),
            Slot::Css(edit) => Some(self.written_css(text, edit)),
            Slot::Link { srcset: false } => without_credentials(text),
            Slot::Link { srcset: true } => Some(links_without_credentials(text)),
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
        write_css_edit(text, edit, &mut |url| match url.kind {
            RemoteKind::Link => kept(&url.url),
            kind => self.named(&url.url, kind).text,
        })
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
                is_shown.then(|| self.named(url, RemoteKind::Image).text)
            } else if is_shown && !url.starts_with(IMAGE_DECLINED_PREFIX) {
                let written = kept(url);
                remote |= written != url;
                Some(written)
            } else {
                None
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

fn links_without_credentials(srcset: &str) -> String {
    let mut value = String::with_capacity(srcset.len());
    for_each_srcset_candidate(srcset, |url, descriptors| {
        if !value.is_empty() {
            value.push_str(", ");
        }
        value.push_str(&kept(url));
        if !descriptors.is_empty() {
            value.push(' ');
            value.push_str(descriptors);
        }
    });
    value
}
