//! Whether a recording plays back: full snapshots, the DOM they describe, and mutations against nodes that are not
//! there. The replayer renders such a mutation wrongly or not at all.

use std::collections::{HashMap, HashSet};
use std::ops::Range;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use url::Url;

use crate::bytescan::{self as scan, Span};
use crate::fonts::{bundled_font, is_fetched_font_url};
use crate::url_policy::{is_fetched_image_type, is_remote, needs_redaction, MAX_URL_LEN};

use super::css::{self, CssEditBuilder, CssUrl, Resolver};
use super::edits::{Buffers, Edit, LinkForm, Slot};
use super::events::{field, field_copies, fields, number, text};
use super::rrweb::{
    ADOPTED_STYLE_SHEET, FULL_SNAPSHOT, INCREMENTAL_SNAPSHOT, MUTATION, STYLE_DECLARATION,
    STYLE_SHEET_RULE,
};
use super::srcset::{self, SrcsetSlot};
use super::stats::BlockStats;
use crate::scan::cv::{self, Expansion};
use crate::scan::message::Event;
use crate::scan::tokens::{Token, Tokens};

/// Node ids tracked per window. A larger page stops orphan counting for the window and sets `node_cap_reached`.
pub const MAX_TRACKED_NODES: usize = 200_000;
/// Remote image URLs kept per message, as the v3 collector caps URLs per message.
pub const MAX_IMAGE_URLS: usize = 512;
pub const MAX_FONT_URLS: usize = 512;
/// Attribute changes read per mutation, as many as the nodes tracked. A mutation with more drops its block, because
/// the inspector does not name the URLs in the rest.
pub const MAX_ATTRIBUTE_ITEMS: usize = MAX_TRACKED_NODES;
/// Windows tracked per session. A new window past this evicts the window used least recently.
pub const MAX_WINDOWS: usize = 16;
/// Evicted windows remembered, so that one that comes back is known to have lost its DOM.
const MAX_EVICTED_WINDOWS: usize = 1024;

const TEXT_NODE: f64 = 3.0;

#[derive(Clone, Copy, Default, PartialEq, Eq)]
enum Tag {
    #[default]
    Other,
    Img,
    SvgImage,
    Video,
    Source,
    Picture,
    Style,
    Link,
    Iframe,
    Canvas,
}

const TAGS: [(&str, Tag); 9] = [
    ("img", Tag::Img),
    ("image", Tag::SvgImage),
    ("video", Tag::Video),
    ("source", Tag::Source),
    ("picture", Tag::Picture),
    ("style", Tag::Style),
    ("link", Tag::Link),
    ("iframe", Tag::Iframe),
    ("canvas", Tag::Canvas),
];

fn tag(bytes: &[u8], span: Span) -> Tag {
    scan::unescape(bytes, span).map_or(Tag::Other, |name| {
        TAGS.iter()
            .find(|(known, _)| name.eq_ignore_ascii_case(known))
            .map_or(Tag::Other, |&(_, tag)| tag)
    })
}

/// An element whose attributes v3 fetches an image from (`is_fetchable_image_attr`). An attribute mutation does not
/// name its element's tag, so the window keeps these.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Media {
    Img {
        visibility: Visibility,
    },
    SvgImage,
    Video,
    /// A `source` under a `picture`. Its `type` can name a media type the fetcher does not store, such as AVIF.
    PictureSource {
        unfetched_type: bool,
    },
    /// A `picture`, so that a `source` added under it later is known to be a picture source.
    Picture,
}

/// The remote image URLs of a hidden img, which v3 fetches once the img shows.
#[derive(Clone, Default)]
struct HiddenSources {
    src: Option<String>,
    rr_src: Option<String>,
    fetchable_srcset_candidate: Option<String>,
    srcset_usable: bool,
    srcset_yields_to_img_src: bool,
    has_src: bool,
}

impl HiddenSources {
    fn read(bytes: &[u8], attributes: &Attributes) -> Self {
        let mut sources = Self::default();
        sources.update(bytes, attributes);
        sources
    }

    fn update(&mut self, bytes: &[u8], attributes: &Attributes) {
        let url =
            |span: Span| text(bytes, Some(span)).and_then(|url| fetchable(&url).map(str::to_owned));
        if let Some(span) = attributes.src {
            self.src = url(span);
            self.has_src = is_non_empty_string(bytes, span);
        }
        if let Some(span) = attributes.rr_src {
            self.rr_src = url(span);
        }
        if let Some(span) = attributes.srcset {
            let srcset = text(bytes, Some(span));
            let usable = srcset.as_deref().and_then(srcset::usable_candidate);
            self.srcset_usable = usable.is_some();
            self.srcset_yields_to_img_src = usable.is_some_and(|kept| kept.yields_to_img_src);
            self.fetchable_srcset_candidate =
                usable.and_then(|kept| fetchable(kept.url).map(str::to_owned));
        }
    }

    /// As [`srcset::shown_candidate`] decides, from what the window kept of the srcset and the `src`.
    fn shows_srcset(&self) -> bool {
        self.srcset_usable && !(self.has_src && self.srcset_yields_to_img_src)
    }

    /// Whether the attributes set a source, which an update then changes.
    fn changes(attributes: &Attributes) -> bool {
        attributes.src.is_some() || attributes.rr_src.is_some() || attributes.srcset.is_some()
    }

    fn is_empty(&self) -> bool {
        self.src.is_none() && self.rr_src.is_none() && self.fetchable_srcset_candidate.is_none()
    }

    fn heap_bytes(&self) -> usize {
        let string = |s: &Option<String>| s.as_ref().map_or(0, String::capacity);
        string(&self.src) + string(&self.rr_src) + string(&self.fetchable_srcset_candidate)
    }

    fn push_revealed(mut self, bytes: &[u8], set: &Attributes, walk: &mut Walk) {
        self.update(bytes, set);
        let shows_srcset = self.shows_srcset();
        if !shows_srcset {
            for (url, replaced) in [(self.src, set.src), (self.rr_src, set.rr_src)] {
                if let Some(url) = url.filter(|_| replaced.is_none()) {
                    walk.push_url_text(&url);
                }
            }
        }
        if let Some(url) = self
            .fetchable_srcset_candidate
            .filter(|_| shows_srcset && set.srcset.is_none())
        {
            walk.push_url_text(&url);
        }
    }
}

#[derive(Default)]
struct WindowDom {
    nodes: HashMap<i64, Option<i64>>,
    /// The children of each node. A list keeps a node that moved or went away until the next compaction.
    children: HashMap<i64, Vec<i64>>,
    /// The summed capacity of the child lists, which can exceed their lengths.
    child_capacity: usize,
    stale_children: usize,
    media: HashMap<i64, Media>,
    hidden_sources: HashMap<i64, HiddenSources>,
    hidden_source_bytes: usize,
    /// The text nodes of `style` elements, whose text changes are CSS.
    style_texts: HashSet<i64>,
    has_snapshot: bool,
    /// Orphan counting stopped: the DOM outgrew the node cap, a snapshot did not decode, a node was too deep to walk,
    /// or the window was evicted and came back.
    unverifiable: bool,
    last_used: u64,
    /// From the window's own page URL, because another window of the session can be on another page.
    page_base: Option<Arc<Url>>,
}

/// Why the inspector could not read a block in full. A URL in the part it did not read went unchecked, so the writer drops the block.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UrlLimit {
    AttributeItems,
    NestedBlocks,
    NestedJson,
    Edits,
}

impl UrlLimit {
    /// The outcome of the dropped block in the recorder's metrics.
    pub fn label(self) -> &'static str {
        match self {
            UrlLimit::AttributeItems => "too_many_attribute_items",
            UrlLimit::NestedBlocks => "too_many_nested_blocks",
            UrlLimit::NestedJson => "too_deep_json",
            UrlLimit::Edits => "too_many_edits",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RemoteKind {
    BundledFont(&'static str),
    Font,
    Image,
    /// A URL that no fetch takes, such as a relative one or one in a CSS property that shows no image. The writer keeps
    /// it without its credentials.
    Link,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RemoteUrl {
    pub url: String,
    pub kind: RemoteKind,
}

/// Distinct remote image URLs, at most [`MAX_IMAGE_URLS`] per message.
#[derive(Default)]
struct Urls {
    urls: Vec<String>,
    in_message: HashSet<String>,
    /// Boxed, because the session state counts this struct's size and most messages queue no font file.
    fonts: Option<Box<FontQueue>>,
    limit: Option<UrlLimit>,
    /// Every slot with a remote URL, past the fetch cap and in a hidden img too, because the fetch cap limits only the fetch jobs.
    edits: Vec<Edit>,
    edit_bytes_taken: usize,
    /// A slot the writer could not find again, so that the block must not be stored.
    unplaced: bool,
}

#[derive(Clone, Copy)]
enum CssRead<'p> {
    Sheet,
    /// The value of the property it names.
    Declaration(&'p str),
    /// A text that may not be CSS. See [`css::text_link_urls`].
    Links,
}

#[derive(Default)]
struct FontQueue {
    urls: Vec<String>,
    in_message: HashSet<String>,
}

/// The URL as the fetcher takes it: remote, and no longer than v3 fetches. An inline image is moved out of the block
/// by the image scan instead.
fn fetchable(url: &str) -> Option<&str> {
    let url = url.trim();
    (url.len() <= MAX_URL_LEN && is_remote(url)).then_some(url)
}

impl Urls {
    fn push_fetch(&mut self, url: &str) {
        let Some(url) = fetchable(url) else { return };
        if self.in_message.len() < MAX_IMAGE_URLS && !self.in_message.contains(url) {
            self.in_message.insert(url.to_owned());
            self.urls.push(url.to_owned());
        }
    }

    fn push_font(&mut self, url: &str, family: Option<&str>) {
        let url = url.trim();
        if !is_remote(url) {
            return;
        }
        if family.and_then(bundled_font).is_none() {
            self.queue_font(url);
        }
    }

    fn queue_font(&mut self, url: &str) {
        let Some(url) = fetchable(url).filter(|url| is_fetched_font_url(url)) else {
            return;
        };
        let fonts = self.fonts.get_or_insert_with(Box::default);
        if fonts.in_message.len() < MAX_FONT_URLS && !fonts.in_message.contains(url) {
            fonts.in_message.insert(url.to_owned());
            fonts.urls.push(url.to_owned());
        }
    }

    fn push_css(&mut self, found: CssUrl<'_>) {
        match found {
            CssUrl::Image(url) | CssUrl::Resolved(url) => self.push_fetch(url),
            CssUrl::Unshown(_)
            | CssUrl::Rewrite { .. }
            | CssUrl::Unresolved(_)
            | CssUrl::Link(_) => {}
            CssUrl::Font { url, family } => self.push_font(url, family),
            CssUrl::ResolvedFont(url) => self.queue_font(url),
            CssUrl::NestedTooDeep => self.limit = self.limit.or(Some(UrlLimit::NestedBlocks)),
            CssUrl::Unplaced => self.unplaced = true,
        }
    }

    /// A block past any limit is dropped, so it takes no more of the budget and builds no more edits.
    fn take_edit_bytes(&mut self, budget: Option<&AtomicUsize>, bytes: usize) -> bool {
        if self.limit.is_some() {
            return false;
        }
        let within_budget = budget.is_none_or(|budget| {
            budget
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |left| {
                    left.checked_sub(bytes)
                })
                .is_ok()
        });
        if within_budget {
            self.edit_bytes_taken += bytes;
        } else {
            self.limit = Some(UrlLimit::Edits);
        }
        within_budget
    }

    fn record(
        &mut self,
        buffers: &Buffers,
        (bytes, value): (&[u8], Span),
        slot: Slot,
        edit_budget: Option<&AtomicUsize>,
    ) {
        let Some(source) = buffers.source_of(bytes) else {
            self.unplaced = true;
            return;
        };
        if self.take_edit_bytes(edit_budget, std::mem::size_of::<Edit>()) {
            self.edits.push(Edit {
                source,
                value,
                slot,
            });
        }
    }

    fn read_css(
        &mut self,
        buffers: &Buffers,
        (bytes, value): (&[u8], Span),
        css: &str,
        read: CssRead<'_>,
        resolver: &mut Resolver<'_>,
    ) {
        let edit_budget = resolver.edit_budget();
        let mut edit = Some(CssEditBuilder::new(css));
        let mut found = |found: CssUrl<'_>| {
            if edit.is_some() && !self.take_edit_bytes(edit_budget, found.edit_bytes()) {
                edit = None;
            }
            if let Some(edit) = &mut edit {
                edit.observe(&found);
            }
            self.push_css(found);
        };
        match read {
            CssRead::Sheet => css::urls(css, resolver, &mut found),
            CssRead::Declaration(property) => {
                css::declaration_image_urls(property, css, resolver, &mut found)
            }
            CssRead::Links => css::text_link_urls(css, &mut found),
        }
        match edit.map(CssEditBuilder::finish) {
            Some(Ok(Some(edit))) => {
                self.record(buffers, (bytes, value), Slot::Css(edit), edit_budget)
            }
            Some(Ok(None)) | None => {}
            Some(Err(_)) => self.unplaced = true,
        }
    }

    /// Takes the URLs one walk found.
    fn merge(&mut self, walk: Urls) {
        for url in &walk.urls {
            self.push_fetch(url);
        }
        for url in walk.fonts.iter().flat_map(|fonts| &fonts.urls) {
            self.queue_font(url);
        }
        self.limit = self.limit.or(walk.limit);
        self.edits.extend(walk.edits);
        self.edit_bytes_taken += walk.edit_bytes_taken;
        self.unplaced |= walk.unplaced;
    }
}

/// The budgets that the blocks of one flush share, so that together they hold no more than the flush may.
#[derive(Debug, Clone, Copy, Default)]
pub struct FlushBudgets<'b> {
    pub resolved_bytes: Option<&'b AtomicUsize>,
    pub edit_bytes: Option<&'b AtomicUsize>,
}

/// The DOM state of a session's windows in this process.
#[derive(Default)]
pub struct DomInspector {
    windows: HashMap<String, WindowDom>,
    evicted: HashSet<String>,
    clock: u64,
    /// A full snapshot of any window decoded in this process.
    seen_snapshot: bool,
    /// The session's DOM state was evicted, so any window it opens may have lost its DOM.
    lost: bool,
    urls: Urls,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Observed {
    /// How many nodes a mutation added or removed.
    pub changed: u32,
    /// The event is a full snapshot that decoded.
    pub full_snapshot: bool,
}

/// What one walk over serialized nodes found.
#[derive(Default)]
struct Walk<'p> {
    resolver: Resolver<'p>,
    buffers: Buffers,
    /// Each node and its parent. A root's parent is `None`.
    ids: Vec<(i64, Option<i64>)>,
    /// The walk met more nodes than the node cap, so `ids` stops short.
    truncated: bool,
    media: Vec<(i64, Media)>,
    nodes: u32,
    text_chars: u64,
    remote_stylesheets: u32,
    inline_stylesheets: u32,
    iframes: u32,
    canvases: u32,
    videos: u32,
    shadow_roots: u32,
    style_texts: Vec<i64>,
    image_urls: Urls,
    hidden: Vec<(i64, HiddenSources)>,
    /// `source` elements that are a walk's root, with their srcset. Whether each is a picture source depends on the
    /// parent that the mutation names.
    root_sources: Vec<(Option<i64>, Vec<Span>, Option<Span>)>,
}

impl Walk<'_> {
    fn push_id(&mut self, id: i64, parent: Option<i64>) {
        if self.ids.len() < MAX_TRACKED_NODES {
            self.ids.push((id, parent));
        } else {
            self.truncated = true;
        }
    }

    fn push_url(&mut self, bytes: &[u8], value: Option<Span>) {
        if let Some((span, url)) = value
            .filter(|&v| scan::is_string(bytes, v))
            .and_then(|v| Some((v, scan::unescape(bytes, v).ok()?)))
        {
            self.record_url(bytes, span, &url);
            self.push_url_text(&url);
        }
    }

    fn record_url(&mut self, bytes: &[u8], value: Span, url: &str) {
        if is_remote(url.trim()) || needs_redaction(url) {
            let edit_budget = self.resolver.edit_budget();
            self.image_urls
                .record(&self.buffers, (bytes, value), Slot::Url, edit_budget);
        }
    }

    fn push_url_text(&mut self, url: &str) {
        self.image_urls.push_fetch(url);
    }

    /// A URL that shows no image is a slot only when it holds a credential, so that the writer leaves the rest alone.
    fn push_link(&mut self, bytes: &[u8], value: Option<Span>, form: LinkForm) {
        let (Some(span), Some(text)) = (value, text(bytes, value)) else {
            return;
        };
        let holds_credential = match form {
            LinkForm::Url => needs_redaction(&text),
            LinkForm::Srcset => {
                let mut holds = false;
                for_each_srcset_candidate(&text, |url, _| holds |= needs_redaction(url));
                holds
            }
            LinkForm::Urls => text.split_ascii_whitespace().any(needs_redaction),
        };
        if holds_credential {
            let edit_budget = self.resolver.edit_budget();
            self.image_urls
                .record(&self.buffers, (bytes, span), Slot::Link(form), edit_budget);
        }
    }

    /// The URL of a slot the fetcher does not take now. The block still holds it, so the writer replaces it.
    fn push_remote(&mut self, bytes: &[u8], value: Option<Span>) {
        if let (Some(span), Some(text)) = (value, text(bytes, value)) {
            self.record_url(bytes, span, &text);
        }
    }

    /// Only the shown candidate gets a fetch job. The block holds the others until the writer drops them, so the writer
    /// needs their URLs too. Returns whether the slot shows a srcset candidate.
    fn push_srcset(&mut self, bytes: &[u8], value: Option<Span>, slot: SrcsetSlot) -> bool {
        let Some(srcset) = text(bytes, value) else {
            return false;
        };
        let shown = srcset::shown_candidate(&srcset, slot);
        if let Some(kept) = shown {
            self.push_url_text(kept.url);
        }
        shown.is_some()
    }

    fn push_srcset_value(&mut self, bytes: &[u8], value: Option<Span>, slot: SrcsetSlot) {
        if let (Some(span), Some(_)) = (value, text(bytes, value)) {
            let edit_budget = self.resolver.edit_budget();
            self.image_urls.record(
                &self.buffers,
                (bytes, span),
                Slot::Srcset(slot),
                edit_budget,
            );
        }
    }

    /// A picture source of a type the fetcher does not store gets no fetch job, and the writer empties its srcset, so
    /// the browser falls back to the next source or the img. `srcsets` holds every copy of the attribute, and only the
    /// last, which the player reads, is fetched.
    fn push_source(&mut self, bytes: &[u8], srcsets: &[Span], unfetched_type: bool) {
        let slot = if unfetched_type {
            SrcsetSlot::UnfetchedTypeSource
        } else {
            SrcsetSlot::Alone
        };
        self.push_srcset(bytes, srcsets.last().copied(), slot);
        for &copy in srcsets {
            self.push_srcset_value(bytes, Some(copy), slot);
        }
    }

    fn push_css_links(&mut self, bytes: &[u8], value: Option<Span>) {
        if let (Some(value), Some(text)) = (value, text(bytes, value)) {
            self.image_urls.read_css(
                &self.buffers,
                (bytes, value),
                &text,
                CssRead::Links,
                &mut self.resolver,
            );
        }
    }

    fn push_css(&mut self, bytes: &[u8], value: Option<Span>) {
        let Some(value) = value else { return };
        if let Some(text) = text(bytes, Some(value)) {
            self.image_urls.read_css(
                &self.buffers,
                (bytes, value),
                &text,
                CssRead::Sheet,
                &mut self.resolver,
            );
        } else if scan::is_object(bytes, value) {
            let Ok(entries) = scan::object_entries(bytes, value) else {
                return;
            };
            for entry in entries.filter_map(Result::ok).filter(|e| !e.key_escaped) {
                let property = std::str::from_utf8(&bytes[entry.key.0..entry.key.1]);
                let declared_at = style_property_value(bytes, entry.value);
                let declared = text(bytes, declared_at);
                if let (Ok(property), Some(at), Some(declared)) = (property, declared_at, declared)
                {
                    self.image_urls.read_css(
                        &self.buffers,
                        (bytes, at),
                        &declared,
                        CssRead::Declaration(property),
                        &mut self.resolver,
                    );
                }
            }
        }
    }
}

/// The candidates of a srcset as (URL, descriptors), parsed as HTML parses one: a URL is a run of non-whitespace, so
/// it can hold a comma. A comma ends a candidate only at the end of its URL or after its descriptors.
pub fn srcset_candidates(srcset: &str) -> Vec<(&str, &str)> {
    let mut candidates = Vec::new();
    for_each_srcset_candidate(srcset, |url, descriptors| {
        candidates.push((url, descriptors))
    });
    candidates
}

/// Streams the candidates of [`srcset_candidates`], so that a message-sized srcset needs no list of them.
pub fn for_each_srcset_candidate<'s>(srcset: &'s str, mut found: impl FnMut(&'s str, &'s str)) {
    let bytes = srcset.as_bytes();
    let mut position = 0;
    loop {
        while bytes
            .get(position)
            .is_some_and(|&b| b.is_ascii_whitespace() || b == b',')
        {
            position += 1;
        }
        if position >= bytes.len() {
            return;
        }
        let start = position;
        while bytes
            .get(position)
            .is_some_and(|b| !b.is_ascii_whitespace())
        {
            position += 1;
        }
        let url = srcset[start..position].trim_end_matches(',');
        if url.len() < position - start {
            found(url, "");
            continue;
        }
        let descriptors = position;
        let mut end = bytes.len();
        let mut in_parens = false;
        while let Some(&byte) = bytes.get(position) {
            position += 1;
            match byte {
                b'(' => in_parens = true,
                b')' => in_parens = false,
                b',' if !in_parens => {
                    end = position - 1;
                    break;
                }
                _ => {}
            }
        }
        found(url, srcset[descriptors..end].trim());
    }
}

fn style_property_value(bytes: &[u8], span: Span) -> Option<Span> {
    if scan::is_array(bytes, span) {
        scan::array_items(bytes, span).ok()?.next()?.ok()
    } else {
        Some(span)
    }
}

/// An attribute that can hold an asset URL.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum AssetAttribute {
    Src,
    RrSrc,
    Srcset,
    Href,
    XlinkHref,
    Poster,
    Style,
    CssText,
}

impl AssetAttribute {
    fn named(name: &[u8]) -> Option<Self> {
        Some(match name {
            b"src" => Self::Src,
            b"rr_src" => Self::RrSrc,
            b"srcset" => Self::Srcset,
            b"href" => Self::Href,
            b"xlink:href" => Self::XlinkHref,
            b"poster" => Self::Poster,
            b"style" => Self::Style,
            b"_cssText" => Self::CssText,
            _ => return None,
        })
    }
}

/// How the walk reads an earlier copy of an attribute, which no fetch takes.
#[derive(Clone, Copy)]
enum EarlierRead {
    /// As an image slot, with a srcset read as this slot.
    Image(SrcsetSlot),
    /// As a URL that shows no image.
    Link,
    Css,
}

/// A repeated attribute takes its last value, as in `JSON.parse`, so that the inspector names the URL the player loads.
/// The block still holds the earlier copies of an asset attribute, so the writer replaces those too.
#[derive(Default)]
struct Attributes {
    earlier: Vec<(AssetAttribute, Span)>,
    rel: Option<Span>,
    href: Option<Span>,
    xlink_href: Option<Span>,
    css_text: Option<Span>,
    style: Option<Span>,
    src: Option<Span>,
    rr_src: Option<Span>,
    srcset: Option<Span>,
    poster: Option<Span>,
    hidden: Option<Span>,
    width: Option<Span>,
    height: Option<Span>,
    source_type: Option<Span>,
    links: Vec<(Span, LinkForm)>,
    css_links: Vec<Span>,
}

/// SVG presentation attributes take a CSS value, and a `url()` in one loads a resource.
fn is_svg_css_attribute(name: &[u8]) -> bool {
    const NAMES: &[&[u8]] = &[
        b"clip-path",
        b"cursor",
        b"fill",
        b"filter",
        b"marker",
        b"marker-end",
        b"marker-mid",
        b"marker-start",
        b"mask",
        b"stroke",
    ];
    NAMES.iter().any(|known| known.eq_ignore_ascii_case(name))
}

/// URL attributes that never hold an image slot, and the `data-` attributes that lazy loaders keep a URL in.
fn link_attribute(name: &[u8]) -> Option<LinkForm> {
    const URLS: &[&[u8]] = &[
        b"action",
        b"formaction",
        b"data",
        b"background",
        b"cite",
        b"longdesc",
        b"manifest",
        b"codebase",
        b"icon",
    ];
    const DATA_URL_SUFFIXES: &[&[u8]] = &[
        b"src",
        b"href",
        b"url",
        b"original",
        b"bg",
        b"background",
        b"poster",
    ];
    if name == b"imagesrcset" {
        return Some(LinkForm::Srcset);
    }
    if name == b"ping" || name == b"attributionsrc" {
        return Some(LinkForm::Urls);
    }
    if URLS.contains(&name) {
        return Some(LinkForm::Url);
    }
    let data = name.strip_prefix(b"data-")?;
    if data.ends_with(b"srcset") {
        return Some(LinkForm::Srcset);
    }
    DATA_URL_SUFFIXES
        .iter()
        .any(|suffix| data.ends_with(suffix))
        .then_some(LinkForm::Url)
}

impl Attributes {
    fn slot(&mut self, name: &[u8]) -> Option<&mut Option<Span>> {
        Some(match name {
            b"rel" => &mut self.rel,
            b"href" => &mut self.href,
            b"xlink:href" => &mut self.xlink_href,
            b"_cssText" => &mut self.css_text,
            b"style" => &mut self.style,
            b"src" => &mut self.src,
            b"rr_src" => &mut self.rr_src,
            b"srcset" => &mut self.srcset,
            b"poster" => &mut self.poster,
            b"hidden" => &mut self.hidden,
            b"width" => &mut self.width,
            b"height" => &mut self.height,
            b"type" => &mut self.source_type,
            _ => return None,
        })
    }

    fn set(&mut self, name: &[u8], value: Span) {
        if let Some(slot) = self.slot(name) {
            let previous = slot.replace(value);
            if let (Some(previous), Some(attribute)) = (previous, AssetAttribute::named(name)) {
                self.earlier.push((attribute, previous));
            }
        } else if let Some(form) = link_attribute(name) {
            self.links.push((value, form));
        } else if is_svg_css_attribute(name) {
            self.css_links.push(value);
        }
    }

    fn read(bytes: &[u8], object: Span) -> Self {
        let mut attributes = Self::default();
        if let Ok(entries) = scan::object_entries(bytes, object) {
            for entry in entries.filter_map(Result::ok).filter(|e| !e.key_escaped) {
                attributes.set(&bytes[entry.key.0..entry.key.1], entry.value);
            }
        }
        attributes
    }

    fn srcset_copies(&self) -> Vec<Span> {
        self.earlier
            .iter()
            .filter(|(attribute, _)| *attribute == AssetAttribute::Srcset)
            .map(|&(_, span)| span)
            .chain(self.srcset)
            .collect()
    }

    /// The earlier copies of `attributes`, which the player does not read, so they are not fetched. The writer replaces
    /// each one as the last copy's slot reads it.
    fn push_earlier(
        &self,
        bytes: &[u8],
        attributes: &[AssetAttribute],
        read: EarlierRead,
        walk: &mut Walk,
    ) {
        for &(attribute, span) in &self.earlier {
            if !attributes.contains(&attribute) {
                continue;
            }
            let span = Some(span);
            match (attribute, read) {
                (_, EarlierRead::Css) => walk.push_css(bytes, span),
                (AssetAttribute::Srcset, EarlierRead::Image(slot)) => {
                    walk.push_srcset_value(bytes, span, slot)
                }
                (AssetAttribute::Srcset, EarlierRead::Link) => {
                    walk.push_link(bytes, span, LinkForm::Srcset)
                }
                (_, EarlierRead::Image(_)) => walk.push_remote(bytes, span),
                (_, EarlierRead::Link) => walk.push_link(bytes, span, LinkForm::Url),
            }
        }
    }

    /// The sources of a node the window does not know, after a restart, an eviction or the node cap. What the node
    /// shows is not known, so they are not fetched. The block holds them, so the writer replaces them.
    fn push_unknown_sources(&self, bytes: &[u8], walk: &mut Walk) {
        walk.push_remote(bytes, self.src);
        walk.push_remote(bytes, self.rr_src);
        walk.push_srcset_value(bytes, self.srcset, SrcsetSlot::Alone);
        walk.push_remote(bytes, self.href);
        walk.push_remote(bytes, self.xlink_href);
        walk.push_remote(bytes, self.poster);
        let sources = [
            AssetAttribute::Src,
            AssetAttribute::RrSrc,
            AssetAttribute::Srcset,
            AssetAttribute::Href,
            AssetAttribute::XlinkHref,
            AssetAttribute::Poster,
        ];
        let read = EarlierRead::Image(SrcsetSlot::Alone);
        self.push_earlier(bytes, &sources, read, walk);
    }

    /// A mutation that does not set `src` leaves it unknown, so the img's srcset counts as alone.
    fn img_srcset_slot(&self, bytes: &[u8]) -> SrcsetSlot {
        if self
            .src
            .is_some_and(|span| is_non_empty_string(bytes, span))
        {
            SrcsetSlot::BesideImgSrc
        } else {
            SrcsetSlot::Alone
        }
    }

    /// The image URLs v3 fetches from these attributes on an element of this kind, and the URLs in its CSS.
    fn push_urls(&self, bytes: &[u8], media: Option<Media>, walk: &mut Walk) {
        let img_sources = [
            AssetAttribute::Src,
            AssetAttribute::RrSrc,
            AssetAttribute::Srcset,
        ];
        match media {
            Some(Media::Img { visibility }) if !visibility.hides() => {
                let slot = self.img_srcset_slot(bytes);
                if walk.push_srcset(bytes, self.srcset, slot) {
                    walk.push_remote(bytes, self.src);
                    walk.push_remote(bytes, self.rr_src);
                } else {
                    walk.push_url(bytes, self.src);
                    walk.push_url(bytes, self.rr_src);
                }
                walk.push_srcset_value(bytes, self.srcset, slot);
                self.push_earlier(bytes, &img_sources, EarlierRead::Image(slot), walk);
            }
            Some(Media::Img { .. }) => {
                let slot = self.img_srcset_slot(bytes);
                walk.push_remote(bytes, self.src);
                walk.push_remote(bytes, self.rr_src);
                walk.push_srcset_value(bytes, self.srcset, slot);
                self.push_earlier(bytes, &img_sources, EarlierRead::Image(slot), walk);
            }
            Some(Media::SvgImage) => {
                walk.push_url(bytes, self.href);
                walk.push_url(bytes, self.xlink_href);
                let sources = [AssetAttribute::Href, AssetAttribute::XlinkHref];
                let read = EarlierRead::Image(SrcsetSlot::Alone);
                self.push_earlier(bytes, &sources, read, walk);
            }
            Some(Media::Video) => {
                walk.push_url(bytes, self.poster);
                walk.push_link(bytes, self.src, LinkForm::Url);
                let read = EarlierRead::Image(SrcsetSlot::Alone);
                self.push_earlier(bytes, &[AssetAttribute::Poster], read, walk);
                self.push_earlier(bytes, &[AssetAttribute::Src], EarlierRead::Link, walk);
            }
            Some(Media::PictureSource { unfetched_type }) => {
                walk.push_source(bytes, &self.srcset_copies(), unfetched_type);
                walk.push_link(bytes, self.src, LinkForm::Url);
                self.push_earlier(bytes, &[AssetAttribute::Src], EarlierRead::Link, walk);
            }
            Some(Media::Picture) | None => {
                for value in [
                    self.href,
                    self.xlink_href,
                    self.src,
                    self.rr_src,
                    self.poster,
                ] {
                    walk.push_link(bytes, value, LinkForm::Url);
                }
                walk.push_link(bytes, self.srcset, LinkForm::Srcset);
                let links = [
                    AssetAttribute::Href,
                    AssetAttribute::XlinkHref,
                    AssetAttribute::Src,
                    AssetAttribute::RrSrc,
                    AssetAttribute::Poster,
                    AssetAttribute::Srcset,
                ];
                self.push_earlier(bytes, &links, EarlierRead::Link, walk);
            }
        }
        for &(value, form) in &self.links {
            walk.push_link(bytes, Some(value), form);
        }
        for &value in &self.css_links {
            walk.push_css_links(bytes, Some(value));
        }
        walk.push_css(bytes, self.style);
        walk.push_css(bytes, self.css_text);
        let css = [AssetAttribute::Style, AssetAttribute::CssText];
        self.push_earlier(bytes, &css, EarlierRead::Css, walk);
    }
}

fn is_non_empty_string(bytes: &[u8], span: Span) -> bool {
    scan::is_string(bytes, span) && span.1 - span.0 > 2
}

/// An empty `type` gives the browser no hint, as a missing one does.
fn is_unfetched_type(bytes: &[u8], source_type: Option<Span>) -> bool {
    text(bytes, source_type).is_some_and(|t| !t.trim().is_empty() && !is_fetched_image_type(&t))
}

/// A CSS or HTML length read as pixels, as in v3: `1`, `1px` and `1.0` are one pixel, other units are unknown.
fn px_length(text: &str) -> Option<f64> {
    let text = text.trim().to_ascii_lowercase();
    let number = text.strip_suffix("px").map_or(text.as_str(), str::trim);
    number.parse::<f64>().ok()
}

fn is_at_most_one_pixel(length: Option<f64>) -> bool {
    length.is_some_and(|length| (0.0..=1.0).contains(&length))
}

/// What v3 `is_hidden_pixel` reads from an img: the `hidden` attribute, `display: none`, or at most one pixel each way.
/// An attribute mutation names only the attributes it changes, so the window keeps this to judge the img after one.
#[derive(Clone, Copy, Default, PartialEq, Eq)]
struct Visibility {
    hidden: bool,
    display_none: bool,
    /// Whether the width and the height are at most one pixel, by the inline style and by the attributes. The inline
    /// style wins where it declares one.
    style_tiny: [Option<bool>; 2],
    attribute_tiny: [bool; 2],
}

impl Visibility {
    fn hides(&self) -> bool {
        let tiny = |i: usize| self.style_tiny[i].unwrap_or(self.attribute_tiny[i]);
        self.hidden || self.display_none || (tiny(0) && tiny(1))
    }

    fn update(&mut self, bytes: &[u8], attributes: &Attributes) {
        if let Some(hidden) = attributes.hidden {
            self.hidden = !scan::is_null(bytes, hidden);
        }
        for (i, attribute) in [attributes.width, attributes.height]
            .into_iter()
            .enumerate()
        {
            if let Some(span) = attribute {
                self.attribute_tiny[i] = is_at_most_one_pixel(if scan::is_string(bytes, span) {
                    scan::unescape(bytes, span).ok().and_then(|v| px_length(&v))
                } else {
                    scan::parse_number(bytes, span)
                });
            }
        }
        let Some(style) = attributes.style else {
            return;
        };
        if let Some(style) = text(bytes, Some(style)) {
            self.display_none =
                inline_style_declaration(&style, "display").as_deref() == Some("none");
            for (i, name) in ["width", "height"].into_iter().enumerate() {
                self.style_tiny[i] = inline_style_declaration(&style, name)
                    .map(|declared| is_at_most_one_pixel(px_length(&declared)));
            }
        } else if scan::is_object(bytes, style) {
            // rrweb records a change to the style attribute as the properties that changed: a value, a
            // `[value, priority]` pair, or `false` for a property it removed.
            let [display, width, height] = fields(bytes, style, [b"display", b"width", b"height"]);
            let declared = |span: Option<Span>| {
                let value = style_property_value(bytes, span?)?;
                Some(
                    text(bytes, Some(value))
                        .map(|v| without_important(&v.trim().to_ascii_lowercase()).to_owned()),
                )
            };
            if let Some(display) = declared(display) {
                self.display_none = display.as_deref() == Some("none");
            }
            for (i, span) in [width, height].into_iter().enumerate() {
                if let Some(length) = declared(span) {
                    self.style_tiny[i] =
                        length.map(|length| is_at_most_one_pixel(px_length(&length)));
                }
            }
        } else {
            self.display_none = false;
            self.style_tiny = [None; 2];
        }
    }
}

/// The last value an inline style gives one property, lowercased and without `!important`.
fn inline_style_declaration(style: &str, property: &str) -> Option<String> {
    style
        .split(';')
        .filter_map(|declaration| declaration.split_once(':'))
        .filter(|(name, _)| name.trim().eq_ignore_ascii_case(property))
        .map(|(_, value)| without_important(&value.trim().to_ascii_lowercase()).to_owned())
        .next_back()
}

fn without_important(value: &str) -> &str {
    let Some(before_keyword) = value.strip_suffix("important") else {
        return value;
    };
    match before_keyword.trim_end().strip_suffix('!') {
        Some(declared_value) => declared_value.trim_end(),
        None => value,
    }
}

#[derive(Default)]
struct NodeFrame {
    id: Option<i64>,
    is_text: bool,
    is_style_text: bool,
    tag: Tag,
    text: Option<Span>,
    /// The copies of a repeated `textContent` before `text`, which the player reads.
    earlier_texts: Vec<Span>,
    shadow_host: bool,
    attributes: Attributes,
    /// The ids of the children walked so far. A node's id comes after its children, so they wait for it here.
    children: Vec<i64>,
    /// Child text, and child `source` elements with their srcset, which count only under a `style` or a `picture`.
    /// They wait here because the tag can come after the children.
    child_texts: Vec<(Option<i64>, Span)>,
    child_sources: Vec<(Option<i64>, Vec<Span>, Option<Span>)>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum FrameKind {
    Node,
    ChildNodes,
    Attributes,
    Other,
}

/// Walks the serialized node at `span` and its descendants, reading each byte once. Returns false when the input is
/// malformed or nested too deep.
fn walk_nodes(bytes: &[u8], span: Span, walk: &mut Walk) -> bool {
    let mut kinds: Vec<FrameKind> = Vec::new();
    let mut nodes: Vec<NodeFrame> = Vec::new();
    let mut key: Option<Span> = None;
    let mut started = false;
    let mut tokens = Tokens::new(bytes, span);
    for token in tokens.by_ref() {
        let parent = kinds.last().copied();
        let current_key = key.take().map(|k| &bytes[k.0..k.1]);
        match token {
            Token::ObjectStart | Token::ArrayStart => {
                let kind = match (parent, current_key, token) {
                    (None, _, Token::ObjectStart) if !started => FrameKind::Node,
                    (Some(FrameKind::ChildNodes), _, Token::ObjectStart) => FrameKind::Node,
                    (Some(FrameKind::Node), Some(b"childNodes"), Token::ArrayStart) => {
                        FrameKind::ChildNodes
                    }
                    (Some(FrameKind::Node), Some(b"attributes"), Token::ObjectStart) => {
                        FrameKind::Attributes
                    }
                    _ => FrameKind::Other,
                };
                started = true;
                if kind == FrameKind::Node {
                    nodes.push(NodeFrame::default());
                }
                kinds.push(kind);
            }
            Token::ObjectEnd | Token::ArrayEnd => {
                if kinds.pop() == Some(FrameKind::Node) {
                    if let Some(node) = nodes.pop() {
                        finish_node(bytes, node, nodes.last_mut(), walk);
                    }
                }
            }
            Token::Key { span, escaped } => key = (!escaped).then_some(span),
            Token::Value(value) => match (parent, current_key) {
                (Some(FrameKind::Node), Some(name)) => {
                    let Some(node) = nodes.last_mut() else {
                        continue;
                    };
                    match name {
                        b"id" => node.id = scan::parse_number(bytes, value).map(|n| n as i64),
                        b"type" => {
                            node.is_text = scan::parse_number(bytes, value) == Some(TEXT_NODE)
                        }
                        b"tagName" => node.tag = tag(bytes, value),
                        b"textContent" => {
                            if let Some(earlier) = node.text.replace(value) {
                                node.earlier_texts.push(earlier);
                            }
                        }
                        b"isShadowHost" => node.shadow_host = &bytes[value.0..value.1] == b"true",
                        b"isStyle" => node.is_style_text = &bytes[value.0..value.1] == b"true",
                        _ => {}
                    }
                }
                (Some(FrameKind::Attributes), Some(name)) => {
                    if let Some(node) = nodes.last_mut() {
                        node.attributes.set(name, value);
                    }
                }
                _ => {}
            },
        }
    }
    !tokens.failed
}

fn finish_node(bytes: &[u8], node: NodeFrame, parent: Option<&mut NodeFrame>, walk: &mut Walk) {
    walk.nodes += 1;
    let media = match node.tag {
        Tag::Img => {
            let mut visibility = Visibility::default();
            visibility.update(bytes, &node.attributes);
            Some(Media::Img { visibility })
        }
        Tag::SvgImage => Some(Media::SvgImage),
        Tag::Video => Some(Media::Video),
        Tag::Picture => Some(Media::Picture),
        _ => None,
    };
    if node.tag == Tag::Style {
        for &(id, text) in &node.child_texts {
            walk.style_texts.extend(id);
            walk.push_css(bytes, Some(text));
        }
    }
    if node.tag == Tag::Picture {
        for (id, srcsets, source_type) in &node.child_sources {
            let unfetched_type = is_unfetched_type(bytes, *source_type);
            walk.media
                .extend(id.map(|id| (id, Media::PictureSource { unfetched_type })));
            walk.push_source(bytes, srcsets, unfetched_type);
        }
    }
    match node.id {
        Some(id) => {
            for &child in &node.children {
                walk.push_id(child, Some(id));
            }
            if let Some(media) = media {
                walk.media.push((id, media));
            }
            if let Some(Media::Img { visibility }) = media {
                if visibility.hides() && walk.hidden.len() < MAX_TRACKED_NODES {
                    let sources = HiddenSources::read(bytes, &node.attributes);
                    if !sources.is_empty() {
                        walk.hidden.push((id, sources));
                    }
                }
            }
        }
        None => {
            for &child in &node.children {
                walk.push_id(child, None);
            }
        }
    }
    if node.is_text {
        if let Some(text) = node.text {
            // The escaped length: close enough to count how much text a page holds, without decoding it.
            walk.text_chars += (text.1 - text.0).saturating_sub(2) as u64;
            if node.is_style_text {
                walk.style_texts.extend(node.id);
                for &text in node.earlier_texts.iter().chain(&node.text) {
                    walk.push_css(bytes, Some(text));
                }
            }
        }
    }
    walk.shadow_roots += u32::from(node.shadow_host);
    node.attributes.push_urls(bytes, media, walk);
    let attributes = &node.attributes;
    match node.tag {
        Tag::Link if attributes.css_text.is_some() => walk.inline_stylesheets += 1,
        Tag::Link
            if attributes.href.is_some()
                && attributes
                    .rel
                    .is_some_and(|rel| attribute_contains(bytes, rel, "stylesheet")) =>
        {
            walk.remote_stylesheets += 1
        }
        Tag::Style => walk.inline_stylesheets += 1,
        Tag::Iframe => walk.iframes += 1,
        Tag::Canvas => walk.canvases += 1,
        Tag::Video => walk.videos += 1,
        _ => {}
    }
    match parent {
        Some(parent) => {
            parent.children.extend(node.id);
            if node.is_text && !node.is_style_text {
                parent.child_texts.extend(
                    node.earlier_texts
                        .iter()
                        .chain(&node.text)
                        .map(|&text| (node.id, text)),
                );
            }
            if node.tag == Tag::Source {
                parent.child_sources.push((
                    node.id,
                    node.attributes.srcset_copies(),
                    node.attributes.source_type,
                ));
            }
        }
        None => {
            if let Some(id) = node.id {
                walk.push_id(id, None);
            }
            if node.tag == Tag::Source {
                walk.root_sources.push((
                    node.id,
                    node.attributes.srcset_copies(),
                    node.attributes.source_type,
                ));
            }
        }
    }
}

/// What a full snapshot does to its window.
enum Snapshot<'p> {
    /// The player drops it, because its data or its node is not an object.
    Dropped,
    Unreadable,
    /// It nests too deep to walk, and the player may still build a DOM from a payload this deep.
    Unwalked,
    Walked(Box<Walk<'p>>),
}

/// Walks the DOM in a full snapshot's data, decoded when the event is compressed.
fn walk_snapshot<'p>(
    inner: &[u8],
    data: Span,
    expansion: &Expansion,
    resolver: Resolver<'p>,
) -> Snapshot<'p> {
    let (bytes, root) = if scan::is_string(inner, data) {
        match expansion.json(data) {
            Some(Some(json)) => match scan::locate_value(json, 0) {
                Ok(root) => (json, root),
                Err(_) => return Snapshot::Unwalked,
            },
            Some(None) => return Snapshot::Dropped,
            None => return Snapshot::Unreadable,
        }
    } else {
        (inner, data)
    };
    let Some(node) = field(bytes, root, b"node").filter(|&node| scan::is_object(bytes, node))
    else {
        return Snapshot::Dropped;
    };
    let mut walk = Walk {
        resolver,
        buffers: Buffers::new(inner, expansion),
        ..Walk::default()
    };
    if walk_nodes(bytes, node, &mut walk) {
        Snapshot::Walked(Box::new(walk))
    } else {
        Snapshot::Unwalked
    }
}

fn attribute_contains(bytes: &[u8], value: Span, word: &str) -> bool {
    scan::is_string(bytes, value)
        && scan::unescape(bytes, value).is_ok_and(|v| v.to_ascii_lowercase().contains(word))
}

impl WindowDom {
    fn insert(&mut self, id: i64, parent: Option<i64>) {
        if self.nodes.len() >= MAX_TRACKED_NODES && !self.nodes.contains_key(&id) {
            self.unverifiable = true;
            return;
        }
        if let Some(parent) = parent {
            let children = self.children.entry(parent).or_default();
            let capacity = children.capacity();
            children.push(id);
            self.child_capacity += children.capacity() - capacity;
        }
        if self.nodes.insert(id, parent).is_some() {
            self.mark_stale();
        }
    }

    fn add_media(&mut self, media: &[(i64, Media)]) {
        for &(id, kind) in media {
            if self.media.len() < MAX_TRACKED_NODES || self.media.contains_key(&id) {
                self.media.insert(id, kind);
            }
        }
    }

    fn add_hidden_sources(&mut self, hidden: &[(i64, HiddenSources)]) {
        for (id, sources) in hidden {
            if self.hidden_sources.len() < MAX_TRACKED_NODES || self.hidden_sources.contains_key(id)
            {
                self.set_hidden_sources(*id, Some(sources.clone()));
            }
        }
    }

    fn set_hidden_sources(
        &mut self,
        id: i64,
        sources: Option<HiddenSources>,
    ) -> Option<HiddenSources> {
        let sources = sources.filter(|sources| !sources.is_empty());
        self.hidden_source_bytes += sources.as_ref().map_or(0, HiddenSources::heap_bytes);
        let previous = match sources {
            Some(sources) => self.hidden_sources.insert(id, sources),
            None => self.hidden_sources.remove(&id),
        };
        self.hidden_source_bytes -= previous.as_ref().map_or(0, HiddenSources::heap_bytes);
        previous
    }

    fn add_style_texts(&mut self, ids: &[i64]) {
        for &id in ids {
            if self.style_texts.len() < MAX_TRACKED_NODES {
                self.style_texts.insert(id);
            }
        }
    }

    fn knows(&self, id: i64, added: &HashSet<i64>) -> bool {
        self.nodes.contains_key(&id) || added.contains(&id)
    }

    /// Removes a node and every node under it, as the page does. Returns how many nodes went.
    fn remove(&mut self, id: i64) -> u32 {
        let mut removed = 0;
        let mut stack = vec![id];
        while let Some(id) = stack.pop() {
            if self.nodes.remove(&id).is_none() {
                continue;
            }
            removed += 1;
            self.media.remove(&id);
            self.set_hidden_sources(id, None);
            self.style_texts.remove(&id);
            if let Some(children) = self.children.remove(&id) {
                self.child_capacity -= children.capacity();
                // A node that moved away from this parent stays in its list until compaction, so check it.
                stack.extend(
                    children
                        .into_iter()
                        .filter(|c| self.nodes.get(c) == Some(&Some(id))),
                );
            }
        }
        self.mark_stale();
        removed
    }

    fn mark_stale(&mut self) {
        self.stale_children += 1;
        if self.stale_children > self.nodes.len().max(4096) {
            self.compact();
        }
    }

    fn compact(&mut self) {
        let nodes = &self.nodes;
        self.children.retain(|&parent, children| {
            children.retain(|child| nodes.get(child) == Some(&Some(parent)));
            children.sort_unstable();
            children.dedup();
            children.shrink_to_fit();
            !children.is_empty()
        });
        self.child_capacity = self.children.values().map(Vec::capacity).sum();
        self.stale_children = 0;
    }
}

/// The DOM of `name`, created when the session has not seen it, evicting the window used least recently past the cap.
fn window_dom<'d>(
    windows: &'d mut HashMap<String, WindowDom>,
    evicted: &mut HashSet<String>,
    lost: bool,
    clock: u64,
    name: &str,
) -> &'d mut WindowDom {
    if !windows.contains_key(name) {
        if windows.len() >= MAX_WINDOWS {
            let oldest = windows
                .iter()
                .min_by_key(|(_, dom)| dom.last_used)
                .map(|(oldest, dom)| (oldest.clone(), dom.has_snapshot || dom.unverifiable));
            if let Some((oldest, lost_state)) = oldest {
                windows.remove(&oldest);
                if lost_state && evicted.len() < MAX_EVICTED_WINDOWS {
                    evicted.insert(oldest);
                }
            }
        }
        // A window that comes back after eviction lost its DOM, so its mutations go unchecked until its next snapshot.
        let unverifiable = evicted.remove(name) || lost;
        windows.insert(
            name.to_owned(),
            WindowDom {
                unverifiable,
                ..WindowDom::default()
            },
        );
    }
    let dom = windows
        .get_mut(name)
        .expect("the window was inserted above");
    dom.last_used = clock;
    dom
}

/// The heap bytes a hash table of this many slots holds: each slot has an entry and a control byte.
fn table_bytes<T>(capacity: usize) -> usize {
    capacity * (std::mem::size_of::<T>() + 1)
}

impl WindowDom {
    fn retained_bytes(&self) -> usize {
        table_bytes::<(i64, Option<i64>)>(self.nodes.capacity())
            + table_bytes::<(i64, Vec<i64>)>(self.children.capacity())
            + self.child_capacity * std::mem::size_of::<i64>()
            + table_bytes::<(i64, Media)>(self.media.capacity())
            + table_bytes::<(i64, HiddenSources)>(self.hidden_sources.capacity())
            + self.hidden_source_bytes
            + table_bytes::<i64>(self.style_texts.capacity())
            + self
                .page_base
                .as_ref()
                .map_or(0, |base| std::mem::size_of::<Url>() + base.as_str().len())
    }
}

impl DomInspector {
    /// The state of a session whose DOM state was evicted. A window it opens counts as one that came back after
    /// eviction, until its next full snapshot.
    pub fn after_eviction() -> Self {
        Self {
            lost: true,
            ..Self::default()
        }
    }

    pub fn retained_bytes(&self) -> usize {
        let windows: usize = self
            .windows
            .iter()
            .map(|(name, dom)| name.capacity() + dom.retained_bytes())
            .sum();
        let evicted: usize = self.evicted.iter().map(String::capacity).sum();
        windows
            + table_bytes::<(String, WindowDom)>(self.windows.capacity())
            + evicted
            + table_bytes::<String>(self.evicted.capacity())
    }

    /// Starts a message: the image URL cap counts per message.
    pub fn start_message(&mut self) {
        self.urls.in_message.clear();
        if let Some(fonts) = &mut self.urls.fonts {
            fonts.in_message.clear();
        }
    }

    /// Ends a message. The URLs it saw go, so that they do not stay in memory that [`Self::retained_bytes`] does not
    /// count.
    pub fn finish_message(&mut self) {
        self.urls.in_message = HashSet::new();
        if self
            .urls
            .fonts
            .as_ref()
            .is_some_and(|fonts| fonts.urls.is_empty())
        {
            self.urls.fonts = None;
        }
    }

    /// Updates the window's DOM with one event and adds what it found to the block.
    pub fn observe(
        &mut self,
        inner: &[u8],
        event: &Event,
        window: &str,
        event_page_url: Option<&str>,
        budgets: FlushBudgets<'_>,
        stats: &mut BlockStats,
    ) -> Observed {
        self.clock += 1;
        let dom = window_dom(
            &mut self.windows,
            &mut self.evicted,
            self.lost,
            self.clock,
            window,
        );
        if let Some(page_url) = event_page_url {
            dom.page_base = css::page_base(page_url).map(Arc::new);
        }
        let page_base = dom.page_base.clone();
        let resolver = Resolver::new(page_base.as_deref(), budgets.resolved_bytes)
            .with_edit_budget(budgets.edit_bytes);
        let mut observed = Observed::default();
        match (event.kind, event.source) {
            (Some(FULL_SNAPSHOT), _) => {
                let expansion = cv::expansion(inner, event);
                let last_used = dom.last_used;
                match event.data.map_or(Snapshot::Dropped, |data| {
                    walk_snapshot(inner, data, &expansion, resolver)
                }) {
                    Snapshot::Walked(mut walk) => {
                        // A full snapshot replaces the window's DOM.
                        *dom = WindowDom {
                            has_snapshot: true,
                            unverifiable: walk.truncated,
                            last_used,
                            page_base: page_base.clone(),
                            ..WindowDom::default()
                        };
                        for &(id, parent) in &walk.ids {
                            dom.insert(id, parent);
                        }
                        dom.add_media(&walk.media);
                        dom.add_hidden_sources(&walk.hidden);
                        dom.add_style_texts(&walk.style_texts);
                        stats.full_snapshots += 1;
                        stats.dom_nodes = stats.dom_nodes.max(walk.nodes);
                        stats.dom_text_chars = stats.dom_text_chars.max(walk.text_chars);
                        stats.remote_stylesheets += walk.remote_stylesheets;
                        stats.inline_stylesheets += walk.inline_stylesheets;
                        stats.iframes += walk.iframes;
                        stats.canvases += walk.canvases;
                        stats.videos += walk.videos;
                        stats.shadow_roots += walk.shadow_roots;
                        self.urls.merge(std::mem::take(&mut walk.image_urls));
                        self.seen_snapshot = true;
                        observed.full_snapshot = true;
                    }
                    unread @ (Snapshot::Unreadable | Snapshot::Unwalked) => {
                        if matches!(unread, Snapshot::Unwalked) {
                            self.urls.limit = self.urls.limit.or(Some(UrlLimit::NestedJson));
                        }
                        stats.decode_failures += 1;
                        *dom = WindowDom {
                            unverifiable: true,
                            last_used,
                            page_base: page_base.clone(),
                            ..WindowDom::default()
                        }
                    }
                    // The window keeps the DOM it had, as in the player.
                    Snapshot::Dropped => {}
                }
            }
            (Some(INCREMENTAL_SNAPSHOT), Some(MUTATION)) => {
                if let Some(data) = event.data {
                    let expansion = cv::expansion(inner, event);
                    let (orphans, changed, undecoded) =
                        observe_mutation(inner, data, &expansion, dom, resolver, &mut self.urls);
                    stats.orphan_mutations += orphans;
                    stats.decode_failures += u32::from(undecoded);
                    observed.changed = changed;
                }
            }
            (
                Some(INCREMENTAL_SNAPSHOT),
                Some(STYLE_SHEET_RULE | STYLE_DECLARATION | ADOPTED_STYLE_SHEET),
            ) => {
                if let Some(data) = event.data {
                    let expansion = cv::expansion(inner, event);
                    if matches!(*expansion, Expansion::Failed | Expansion::Skipped) {
                        stats.decode_failures += 1;
                    }
                    style_sheet_urls(
                        inner,
                        data,
                        event.source,
                        &expansion,
                        resolver,
                        &mut self.urls,
                    );
                }
            }
            _ => {}
        }
        if !self.seen_snapshot {
            stats.events_before_first_full_snapshot += 1;
        }
        stats.node_cap_reached |= dom.unverifiable;
        observed
    }

    /// The remote image URLs the DOM referenced since the last call.
    pub fn take_image_urls(&mut self) -> Vec<String> {
        std::mem::take(&mut self.urls.urls)
    }

    pub fn take_font_urls(&mut self) -> Vec<String> {
        self.urls
            .fonts
            .as_mut()
            .map(|fonts| std::mem::take(&mut fonts.urls))
            .unwrap_or_default()
    }

    /// The edits the last event needs, whether it held a slot the writer could not find again, and the bytes its edits took from the flush's edit budget.
    pub fn take_edits(&mut self) -> (Vec<Edit>, bool, usize) {
        (
            std::mem::take(&mut self.urls.edits),
            std::mem::take(&mut self.urls.unplaced),
            std::mem::take(&mut self.urls.edit_bytes_taken),
        )
    }

    pub fn take_url_limit(&mut self) -> Option<UrlLimit> {
        self.urls.limit.take()
    }

    /// Whether a full snapshot of any window of the session decoded in this process.
    pub fn has_snapshot(&self) -> bool {
        self.seen_snapshot
    }
}

#[derive(Clone, Copy)]
struct List<'b> {
    bytes: &'b [u8],
    span: Span,
}

/// A mutation's four lists, decoded when the event is compressed.
#[derive(Default)]
struct Lists<'b> {
    adds: Option<List<'b>>,
    removes: Option<List<'b>>,
    texts: Option<List<'b>>,
    attributes: Option<List<'b>>,
    /// A list is a string that did not decode, so the player drops the whole mutation.
    failed: bool,
    /// A list decoded to JSON that nests too deep to read, which the player still reads.
    too_deep: bool,
}

fn mutation_lists<'b>(inner: &'b [u8], data: Span, expansion: &'b Expansion) -> Lists<'b> {
    let mut lists = Lists::default();
    let names = [&b"adds"[..], b"removes", b"texts", b"attributes"];
    let found = fields(inner, data, names);
    let slots = [
        &mut lists.adds,
        &mut lists.removes,
        &mut lists.texts,
        &mut lists.attributes,
    ];
    let (mut failed, mut too_deep) = (false, false);
    for (slot, span) in slots.into_iter().zip(found) {
        let Some(span) = span else { continue };
        if !scan::is_string(inner, span) {
            *slot = Some(List { bytes: inner, span });
            continue;
        }
        // A list in a string is one the player decompresses, or one it cannot read.
        match expansion.json(span) {
            Some(Some(json)) => match scan::locate_value(json, 0) {
                Ok(span) => *slot = Some(List { bytes: json, span }),
                Err(_) => too_deep = true,
            },
            Some(None) => {}
            None => failed = true,
        }
    }
    lists.failed = failed || too_deep;
    lists.too_deep = too_deep;
    lists
}

struct Add {
    parent: Option<i64>,
    ids: Range<usize>,
}

/// Which additions the player's rrweb applies. It queues an addition whose parent is not in its mirror, retries the
/// queue as the same mutation adds other nodes, and drops what is still waiting. It appends an addition whose `nextId`
/// sibling is not there.
fn applied_adds(adds: &[Add], ids: &[(i64, Option<i64>)], dom: &WindowDom) -> Vec<bool> {
    let mut owner = HashMap::new();
    for (index, add) in adds.iter().enumerate() {
        for &(id, _) in &ids[add.ids.clone()] {
            owner.insert(id, index);
        }
    }
    let mut waiting: HashMap<i64, Vec<usize>> = HashMap::new();
    let mut missing = vec![0_u32; adds.len()];
    let mut ready = Vec::new();
    for (index, add) in adds.iter().enumerate() {
        if let Some(parent) = add.parent.filter(|parent| !dom.nodes.contains_key(parent)) {
            missing[index] += 1;
            if owner.contains_key(&parent) {
                waiting.entry(parent).or_default().push(index);
            }
        }
        if missing[index] == 0 {
            ready.push(index);
        }
    }
    let mut applied = vec![false; adds.len()];
    while let Some(index) = ready.pop() {
        applied[index] = true;
        for &(id, _) in &ids[adds[index].ids.clone()] {
            for waiter in waiting.remove(&id).into_iter().flatten() {
                missing[waiter] -= 1;
                if missing[waiter] == 0 {
                    ready.push(waiter);
                }
            }
        }
    }
    applied
}

/// Applies a mutation to the window's DOM and collects its image URLs. Returns how many of its changes name a node
/// that is not there, how many nodes it added or removed, and whether the recorder could not read all of it. URLs do
/// not depend on the DOM state.
fn observe_mutation(
    inner: &[u8],
    data: Span,
    expansion: &Expansion,
    dom: &mut WindowDom,
    resolver: Resolver<'_>,
    urls: &mut Urls,
) -> (u32, u32, bool) {
    // The recorder did not decode this mutation, so the window's DOM is not known after it.
    if matches!(expansion, Expansion::Skipped) {
        dom.unverifiable = true;
        return (0, 0, true);
    }
    let lists = mutation_lists(inner, data, expansion);
    if lists.too_deep {
        dom.unverifiable = true;
        urls.limit = urls.limit.or(Some(UrlLimit::NestedJson));
    }
    if lists.failed {
        return (0, 0, true);
    }
    let mut undecoded = false;
    let mut walk = Walk {
        resolver,
        buffers: Buffers::new(inner, expansion),
        ..Walk::default()
    };
    let mut adds = Vec::new();
    // The node cap allows a mutation to add 200,000 nodes, so the set of their ids is built once.
    let mut walked: Option<HashSet<i64>> = None;
    if let Some(list) = lists.adds {
        let mut sources = Vec::new();
        for item in items(list) {
            let [parent, node] = fields(list.bytes, item, [b"parentId", b"node"]);
            let parent = number(list.bytes, parent).map(|p| p as i64);
            let first = walk.ids.len();
            if let Some(node) = node {
                let first_source = walk.root_sources.len();
                if !walk_nodes(list.bytes, node, &mut walk) {
                    dom.unverifiable = true;
                    undecoded = true;
                    walk.image_urls.limit = walk.image_urls.limit.or(Some(UrlLimit::NestedJson));
                }
                for entry in &mut walk.ids[first..] {
                    entry.1 = entry.1.or(parent);
                }
                sources.extend(walk.root_sources.drain(first_source..).map(|s| (parent, s)));
            }
            adds.push(Add {
                parent,
                ids: first..walk.ids.len(),
            });
        }
        if !sources.is_empty() {
            let pictures: HashSet<i64> = walk
                .media
                .iter()
                .filter(|(_, media)| *media == Media::Picture)
                .map(|&(id, _)| id)
                .collect();
            let walked = walked.get_or_insert_with(|| walk.ids.iter().map(|&(id, _)| id).collect());
            for (parent, (id, srcsets, source_type)) in sources {
                let Some(parent) = parent else { continue };
                // A parent the window does not know can be a picture, as after a restart.
                if pictures.contains(&parent)
                    || dom.media.get(&parent) == Some(&Media::Picture)
                    || !dom.knows(parent, walked)
                {
                    let unfetched_type = is_unfetched_type(list.bytes, source_type);
                    walk.media
                        .extend(id.map(|id| (id, Media::PictureSource { unfetched_type })));
                    walk.push_source(list.bytes, &srcsets, unfetched_type);
                }
            }
        }
    }
    dom.add_media(&walk.media);
    dom.add_hidden_sources(&walk.hidden);
    dom.add_style_texts(&walk.style_texts);
    let walked = walked.unwrap_or_else(|| walk.ids.iter().map(|&(id, _)| id).collect());
    if let Some(texts) = lists.texts {
        for item in items(texts) {
            let id = field(texts.bytes, item, b"id");
            let Some(id) = number(texts.bytes, id).map(|id| id as i64) else {
                continue;
            };
            for value in field_copies(texts.bytes, item, b"value") {
                if dom.style_texts.contains(&id) {
                    walk.push_css(texts.bytes, Some(value));
                } else if !dom.knows(id, &walked) {
                    // A node the window does not know can be the text of a style element, as after a restart.
                    walk.push_css_links(texts.bytes, Some(value));
                }
            }
        }
    }
    let mut attribute_ids = Vec::new();
    if let Some(attributes) = lists.attributes {
        for (index, item) in items(attributes).enumerate() {
            if index == MAX_ATTRIBUTE_ITEMS {
                walk.image_urls.limit = Some(UrlLimit::AttributeItems);
                break;
            }
            let [id, values] = fields(attributes.bytes, item, [b"id", b"attributes"]);
            let id = number(attributes.bytes, id).map(|id| id as i64);
            attribute_ids.extend(id);
            if let Some(values) = values.filter(|&v| scan::is_object(attributes.bytes, v)) {
                let values = Attributes::read(attributes.bytes, values);
                let mut media = None;
                let mut hidden = None;
                if let Some((id, known)) = id.and_then(|id| dom.media.get_mut(&id).map(|m| (id, m)))
                {
                    if let Media::Img { visibility } = known {
                        let was_hidden = visibility.hides();
                        visibility.update(attributes.bytes, &values);
                        hidden = Some((id, was_hidden, visibility.hides()));
                    }
                    if let (Media::PictureSource { unfetched_type }, Some(_)) =
                        (&mut *known, values.source_type)
                    {
                        *unfetched_type = is_unfetched_type(attributes.bytes, values.source_type);
                    }
                    media = Some(*known);
                }
                match hidden {
                    // The sources move out and back, so an update does not copy them.
                    Some((id, _, true)) if HiddenSources::changes(&values) => {
                        let mut sources = dom.set_hidden_sources(id, None).unwrap_or_default();
                        sources.update(attributes.bytes, &values);
                        dom.set_hidden_sources(id, Some(sources));
                    }
                    Some((id, true, false)) => {
                        if let Some(sources) = dom.set_hidden_sources(id, None) {
                            sources.push_revealed(attributes.bytes, &values, &mut walk);
                        }
                    }
                    _ => {}
                }
                let known =
                    id.is_some_and(|id| dom.nodes.contains_key(&id) || walked.contains(&id));
                if media.is_none() && !known {
                    values.push_unknown_sources(attributes.bytes, &mut walk);
                }
                values.push_urls(attributes.bytes, media, &mut walk);
            }
        }
    }
    urls.merge(std::mem::take(&mut walk.image_urls));
    if walk.truncated {
        dom.unverifiable = true;
    }
    if !dom.has_snapshot || dom.unverifiable {
        // Without the window's DOM, each node an addition names and each removal counts once.
        let removes = lists.removes.map_or(0, |removes| items(removes).count());
        return (0, (walk.ids.len() + removes) as u32, undecoded);
    }

    let applied = applied_adds(&adds, &walk.ids, dom);
    let applied: Vec<&Add> = adds
        .iter()
        .zip(applied)
        .filter(|(_, a)| *a)
        .map(|(add, _)| add)
        .collect();
    let mut orphans = (adds.len() - applied.len()) as u32;
    let added: HashSet<i64> = applied
        .iter()
        .flat_map(|add| &walk.ids[add.ids.clone()])
        .map(|&(id, _)| id)
        .collect();
    orphans += attribute_ids
        .iter()
        .filter(|&&id| !dom.knows(id, &added))
        .count() as u32;
    if let Some(texts) = lists.texts {
        orphans += items(texts)
            .filter(|&item| {
                number(texts.bytes, field(texts.bytes, item, b"id"))
                    .is_some_and(|id| !dom.knows(id as i64, &added))
            })
            .count() as u32;
    }
    let mut removed = 0;
    if let Some(removes) = lists.removes {
        // A node that moves comes as a removal and an add of the same id, so what the adds installed comes back.
        let added_media: Vec<(i64, Media)> = walk
            .media
            .iter()
            .filter_map(|&(id, _)| dom.media.get(&id).map(|&media| (id, media)))
            .collect();
        let added_hidden: Vec<(i64, HiddenSources)> = walk
            .hidden
            .iter()
            .filter_map(|(id, _)| dom.hidden_sources.get(id).map(|s| (*id, s.clone())))
            .collect();
        for item in items(removes) {
            if let Some(id) = number(removes.bytes, field(removes.bytes, item, b"id")) {
                removed += dom.remove(id as i64).max(1);
            }
        }
        dom.add_media(&added_media);
        dom.add_hidden_sources(&added_hidden);
        dom.add_style_texts(&walk.style_texts);
    }
    for add in applied {
        for &(id, parent) in &walk.ids[add.ids.clone()] {
            dom.insert(id, parent);
        }
    }
    (orphans, added.len() as u32 + removed, undecoded)
}

fn style_sheet_urls(
    inner: &[u8],
    data: Span,
    source: Option<u8>,
    expansion: &Expansion,
    mut resolver: Resolver<'_>,
    urls: &mut Urls,
) {
    let buffers = Buffers::new(inner, expansion);
    let resolver = &mut resolver;
    let mut read_rule = |bytes: &[u8], span: Option<Span>, urls: &mut Urls| {
        if let (Some(span), Some(rule)) = (span, text(bytes, span)) {
            urls.read_css(&buffers, (bytes, span), &rule, CssRead::Sheet, resolver);
        }
    };
    match source {
        Some(STYLE_SHEET_RULE) => {
            let adds = field(inner, data, b"adds");
            match adds.map(|adds| decoded_list(inner, adds, expansion)) {
                Some(Ok(Some(adds))) => {
                    for item in items(adds) {
                        for rule in field_copies(adds.bytes, item, b"rule") {
                            read_rule(adds.bytes, Some(rule), urls);
                        }
                    }
                }
                Some(Err(limit)) => urls.limit = urls.limit.or(Some(limit)),
                Some(Ok(None)) | None => {}
            }
            for key in [&b"replace"[..], b"replaceSync"] {
                for sheet in field_copies(inner, data, key) {
                    read_rule(inner, Some(sheet), urls);
                }
            }
        }
        Some(STYLE_DECLARATION) => {
            let set = field(inner, data, b"set");
            let property = set.and_then(|set| text(inner, field(inner, set, b"property")));
            if let (Some(set), Some(property)) = (set, property) {
                for at in field_copies(inner, set, b"value") {
                    if let Some(value) = text(inner, Some(at)) {
                        let read = CssRead::Declaration(&property);
                        urls.read_css(&buffers, (inner, at), &value, read, resolver);
                    }
                }
            }
        }
        Some(ADOPTED_STYLE_SHEET) => {
            let Some(styles) = field(inner, data, b"styles") else {
                return;
            };
            for style in items(List {
                bytes: inner,
                span: styles,
            }) {
                let Some(rules) = field(inner, style, b"rules") else {
                    continue;
                };
                for rule in items(List {
                    bytes: inner,
                    span: rules,
                }) {
                    for text in field_copies(inner, rule, b"rule") {
                        read_rule(inner, Some(text), urls);
                    }
                }
            }
        }
        _ => {}
    }
}

/// A list as the player reads it, decoded when the event compressed it. `None` when it is empty or does not decode.
fn decoded_list<'b>(
    inner: &'b [u8],
    span: Span,
    expansion: &'b Expansion,
) -> Result<Option<List<'b>>, UrlLimit> {
    if !scan::is_string(inner, span) {
        return Ok(Some(List { bytes: inner, span }));
    }
    let Some(Some(json)) = expansion.json(span) else {
        return Ok(None);
    };
    let span = scan::locate_value(json, 0).map_err(|_| UrlLimit::NestedJson)?;
    Ok(Some(List { bytes: json, span }))
}

fn items(list: List<'_>) -> impl Iterator<Item = Span> + '_ {
    scan::array_items(list.bytes, list.span)
        .ok()
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
}

#[cfg(test)]
mod tests {
    use crate::compression;
    use serde_json::{json, Value};

    use super::*;
    use crate::scan::message::read_message;

    fn events(items: Value) -> crate::scan::message::Message {
        let inner = json!({"event": "$snapshot_items", "properties": {"$session_id": "s", "$snapshot_items": items}});
        read_message(
            json!({"distinct_id": "d", "data": inner.to_string()})
                .to_string()
                .into_bytes(),
        )
        .unwrap()
    }

    fn sdk_cv(value: &Value) -> String {
        compression::gzip(value.to_string().as_bytes())
            .unwrap()
            .iter()
            .map(|&b| char::from(b))
            .collect()
    }

    fn element(id: i64, tag: &str, attributes: Value, children: Value) -> Value {
        json!({"type": 2, "tagName": tag, "attributes": attributes, "childNodes": children, "id": id})
    }

    fn page() -> Value {
        json!({"node": {"type": 0, "childNodes": [element(2, "html", json!({}), json!([
            element(3, "head", json!({}), json!([
                element(4, "link", json!({"rel": "stylesheet", "href": "https://cdn.example.com/a.css"}), json!([])),
                element(5, "link", json!({"rel": "stylesheet", "href": "/b.css", "_cssText": ".b{}"}), json!([])),
            ])),
            element(6, "body", json!({}), json!([
                {"type": 3, "textContent": "hello", "id": 7},
                element(8, "iframe", json!({}), json!([])),
                element(9, "canvas", json!({}), json!([])),
                element(11, "img", json!({"src": "https://cdn.example.com/a.png", "srcset": "https://cdn.example.com/a@2x.png 2x, data:image/png;base64,AA 3x"}), json!([])),
                element(12, "video", json!({"poster": "//cdn.example.com/p.jpg"}), json!([])),
                {"type": 2, "tagName": "div", "attributes": {}, "childNodes": [], "isShadowHost": true, "id": 10},
            ])),
        ]))], "id": 1}})
    }

    #[test]
    fn reads_a_full_snapshot_plain_or_compressed() {
        for compressed in [false, true] {
            let event = if compressed {
                json!({"type": 2, "timestamp": 1, "data": sdk_cv(&page()), "cv": "2024-10"})
            } else {
                json!({"type": 2, "timestamp": 1, "data": page()})
            };
            let message = events(json!([event]));
            let mut stats = BlockStats::default();
            let mut dom = DomInspector::default();
            dom.observe(
                &message.inner,
                &message.events[0],
                "w",
                None,
                FlushBudgets::default(),
                &mut stats,
            );
            // The srcset has no 1x candidate, so the img shows its `src`, which HTML adds as one.
            assert_eq!(
                dom.take_image_urls(),
                ["https://cdn.example.com/a.png", "//cdn.example.com/p.jpg"]
            );

            assert_eq!(
                (stats.dom_nodes, stats.dom_text_chars),
                (12, 5),
                "compressed: {compressed}"
            );
            assert_eq!((stats.remote_stylesheets, stats.inline_stylesheets), (1, 1));
            assert_eq!(
                (
                    stats.iframes,
                    stats.canvases,
                    stats.videos,
                    stats.shadow_roots
                ),
                (1, 1, 1, 1)
            );
            assert_eq!(stats.events_before_first_full_snapshot, 0);
        }
    }

    #[test]
    fn counts_mutations_against_nodes_that_are_not_there() {
        let mutation = |adds: Value, removes: Value, texts: Value| json!({"type": 3, "timestamp": 2, "data": {"source": 0, "adds": adds, "removes": removes, "texts": texts, "attributes": []}});
        let message = events(json!([
            // Before the first full snapshot nothing is known, so this counts as waiting, not as an orphan.
            mutation(json!([{"parentId": 99, "node": {"type": 3, "id": 100}}]), json!([]), json!([])),
            {"type": 2, "timestamp": 1, "data": page()},
            // A known parent, and a parent the same mutation adds after its child.
            mutation(json!([{"parentId": 21, "node": {"type": 3, "id": 22}}, {"parentId": 6, "node": element(21, "p", json!({}), json!([]))}]), json!([]), json!([])),
            // An unknown parent, and a text change on a node removed by the same mutation's remove list later.
            mutation(json!([{"parentId": 500, "node": {"type": 3, "id": 501}}]), json!([{"parentId": 6, "id": 7}]), json!([])),
            mutation(json!([]), json!([]), json!([{"id": 7, "value": "gone"}, {"id": 22, "value": "kept"}])),
            // The player's rrweb appends an addition whose next sibling is not there.
            mutation(json!([{"parentId": 6, "nextId": 900, "node": {"type": 3, "id": 31}}, {"parentId": 6, "nextId": 33, "node": {"type": 3, "id": 32}}, {"parentId": 6, "nextId": -1, "node": {"type": 3, "id": 33}}]), json!([]), json!([])),
            mutation(json!([]), json!([]), json!([{"id": 31, "value": "appended"}, {"id": 32, "value": "kept"}])),
        ]));
        let mut dom = DomInspector::default();
        let mut stats = BlockStats::default();
        for event in &message.events {
            dom.observe(
                &message.inner,
                event,
                "w",
                None,
                FlushBudgets::default(),
                &mut stats,
            );
        }
        assert_eq!(stats.events_before_first_full_snapshot, 1);
        assert_eq!(stats.orphan_mutations, 2);
    }

    const PAGE_URL: &str = "http://app.example.com/shop/item";

    fn mutation(adds: Value, removes: Value, texts: Value, attributes: Value) -> Value {
        json!({"type": 3, "timestamp": 2, "data": {"source": 0, "adds": adds, "removes": removes, "texts": texts, "attributes": attributes}})
    }

    fn observe_all(
        message: &crate::scan::message::Message,
        window: &str,
    ) -> (DomInspector, BlockStats) {
        let mut dom = DomInspector::default();
        let mut stats = BlockStats::default();
        dom.start_message();
        for event in &message.events {
            dom.observe(
                &message.inner,
                event,
                window,
                Some(PAGE_URL),
                FlushBudgets::default(),
                &mut stats,
            );
        }
        (dom, stats)
    }

    /// What the writer replaces, read back from the edits: each URL with its kind, and each function a rewrite replaces whole.
    #[derive(Default)]
    struct Named {
        urls: Vec<(String, RemoteKind)>,
        rewrites: Vec<(String, Vec<RemoteUrl>)>,
    }

    fn named(dom: &mut DomInspector, message: &crate::scan::message::Message) -> Named {
        let (edits, unplaced, _) = dom.take_edits();
        assert!(!unplaced);
        let mut named = Named::default();
        for edit in edits {
            let bytes = match edit.source {
                super::super::edits::EditSource::Payload => message.inner.clone(),
                super::super::edits::EditSource::Field(span) => message
                    .events
                    .iter()
                    .find_map(|event| {
                        cv::expansion(&message.inner, event)
                            .json(span)
                            .flatten()
                            .map(<[u8]>::to_vec)
                    })
                    .unwrap(),
            };
            let text = scan::unescape(&bytes, edit.value).unwrap();
            match edit.slot {
                Slot::Url => named.urls.push((text.trim().to_owned(), RemoteKind::Image)),
                Slot::Srcset(_) => for_each_srcset_candidate(&text, |url, _| {
                    if is_remote(url) {
                        named.urls.push((url.to_owned(), RemoteKind::Image));
                    }
                }),
                Slot::Link(_) => {}
                Slot::Css(edit) => {
                    for piece in edit.pieces {
                        let urls = piece.parts.iter().filter_map(|part| match part {
                            css::CssPart::Url(url) => Some(url.clone()),
                            css::CssPart::Text(_) => None,
                        });
                        if piece.parts.len() == 1 {
                            named.urls.extend(urls.map(|url| (url.url, url.kind)));
                        } else {
                            let urls = urls.collect();
                            named.rewrites.push((text[piece.range].to_owned(), urls));
                        }
                    }
                }
            }
        }
        named
    }

    #[test]
    fn removes_a_whole_subtree_and_follows_a_move() {
        let message = events(json!([
            {"type": 2, "timestamp": 1, "data": page()},
            // Moves the img under the head, then removes the body with everything left under it.
            mutation(json!([{"parentId": 3, "node": element(11, "img", json!({}), json!([]))}]), json!([{"parentId": 6, "id": 11}]), json!([]), json!([])),
            mutation(json!([]), json!([{"parentId": 2, "id": 6}]), json!([]), json!([])),
            mutation(json!([]), json!([]), json!([{"id": 7, "value": "gone"}]), json!([{"id": 11, "attributes": {"alt": "moved"}}, {"id": 9, "attributes": {"width": "1"}}])),
        ]));
        let (_, stats) = observe_all(&message, "w");
        // The text node 7 and the canvas 9 went with the body. The img moved out of it first.
        assert_eq!(stats.orphan_mutations, 2);
        assert!(!stats.node_cap_reached);
    }

    #[test]
    fn stops_checking_a_window_whose_snapshot_does_not_decode() {
        let deep = format!(
            r#"{{"node":{{"type":0,"childNodes":[{}{}],"id":1}}}}"#,
            "[".repeat(1100),
            "]".repeat(1100)
        );
        let deep: String = compression::gzip(deep.as_bytes())
            .unwrap()
            .iter()
            .map(|&b| char::from(b))
            .collect();
        for data in [json!("not gzip"), json!(deep)] {
            let message =
                events(json!([{"type": 2, "timestamp": 1, "data": data, "cv": "2024-10"}]));
            let (_, stats) = observe_all(&message, "w");
            // A snapshot that does not decode is not a full snapshot, so the replay still waits for one.
            assert_eq!(
                (
                    stats.full_snapshots,
                    stats.events_before_first_full_snapshot
                ),
                (0, 1)
            );
            assert!(stats.node_cap_reached, "an unchecked window is flagged");
        }
    }

    #[test]
    fn counts_each_event_that_does_not_decode_once() {
        let message = events(json!([
            {"type": 2, "timestamp": 1, "data": page()},
            {"type": 2, "timestamp": 2, "data": "not gzip", "cv": "2024-10"},
            {"type": 3, "timestamp": 3, "data": {"source": 0, "adds": "not gzip", "removes": [], "texts": "not gzip", "attributes": []}, "cv": "2024-10"},
            {"type": 3, "timestamp": 4, "data": {"source": 8, "adds": "not gzip", "removes": []}, "cv": "2024-10"},
            {"type": 3, "timestamp": 5, "data": {"source": 0, "adds": sdk_cv(&json!([])), "removes": sdk_cv(&json!([])), "texts": sdk_cv(&json!([])), "attributes": sdk_cv(&json!([]))}, "cv": "2024-10"},
        ]));
        let (_, stats) = observe_all(&message, "w");
        assert_eq!(stats.decode_failures, 3);
    }

    #[test]
    fn ignores_events_the_player_drops() {
        let text = |id: i64| {
            mutation(
                json!([]),
                json!([]),
                json!([{"id": id, "value": "x"}]),
                json!([]),
            )
        };
        let dropped = [
            json!({"type": 2, "timestamp": 2, "data": {"node": null}}),
            json!({"type": 3, "timestamp": 2, "cv": "2024-10", "data": {"source": 0, "adds": sdk_cv(&json!([{"parentId": 6, "node": {"type": 3, "id": 501}}])),
                "removes": "not gzip", "texts": sdk_cv(&json!([])), "attributes": sdk_cv(&json!([]))}}),
        ];
        for event in dropped {
            let (_, stats) = observe_all(&events(json!([event, text(7)])), "w");
            assert_eq!(
                (
                    stats.full_snapshots,
                    stats.events_before_first_full_snapshot
                ),
                (0, 2),
                "{event}"
            );
            let (_, stats) = observe_all(
                &events(
                    json!([{"type": 2, "timestamp": 1, "data": page()}, event, text(7), text(501)]),
                ),
                "w",
            );
            assert_eq!(
                (
                    stats.full_snapshots,
                    stats.orphan_mutations,
                    stats.node_cap_reached
                ),
                (1, 1, false),
                "{event}"
            );
        }
    }

    #[test]
    fn flags_a_window_whose_mutation_the_recorder_did_not_decode() {
        let mut message = events(json!([
            {"type": 2, "timestamp": 1, "data": page()},
            {"type": 3, "timestamp": 2, "cv": "2024-10", "data": {"source": 0, "adds": sdk_cv(&json!([{"parentId": 6, "node": {"type": 3, "id": 501}}])),
                "removes": sdk_cv(&json!([])), "texts": sdk_cv(&json!([])), "attributes": sdk_cv(&json!([]))}},
        ]));
        message.events[1].expansion = Some(Expansion::Skipped);
        let (_, stats) = observe_all(&message, "w");
        assert!(stats.node_cap_reached);
    }

    #[test]
    fn collects_remote_image_urls_wherever_the_page_references_them() {
        let url = |name: &str| format!("https://cdn.example.com/{name}.png");
        let snapshot = json!({"node": {"type": 0, "childNodes": [element(2, "html", json!({}), json!([
            element(3, "style", json!({}), json!([{"type": 3, "textContent": format!(".a{{background:url(\"{}\")}} :root{{--x:url({})}}", url("style-text"), url("custom-property")), "id": 4}])),
            element(5, "link", json!({"rel": "stylesheet", "_cssText": format!(".b{{background-image:image-set(url({}) 1x, url({}) 2x)}}", url("set-1x"), url("set-2x"))}), json!([])),
            element(6, "div", json!({"style": format!("background: url('{}') no-repeat; color: red", url("style-attribute"))}), json!([])),
            element(7, "svg", json!({}), json!([element(8, "image", json!({"href": url("svg-href"), "xlink:href": url("svg-xlink")}), json!([]))])),
            element(9, "img", json!({"rr_src": url("rr-src")}), json!([])),
            element(10, "img", json!({"src": url("pixel"), "width": "1", "height": 1}), json!([])),
            element(11, "img", json!({"src": url("display-none"), "style": "display: none !important"}), json!([])),
            element(12, "img", json!({"src": url("hidden"), "hidden": ""}), json!([])),
            element(13, "picture", json!({}), json!([element(14, "source", json!({"srcset": format!("{} 2x", url("picture-source"))}), json!([]))])),
            element(15, "video", json!({}), json!([element(16, "source", json!({"src": url("video-source")}), json!([]))])),
            element(17, "img", json!({"data-src": url("lazy")}), json!([])),
            element(18, "iframe", json!({"src": "https://example.com/frame"}), json!([])),
            element(19, "img", json!({"srcset": format!("{} 640w,{} 2x", url("w_640,q_auto/srcset-comma"), url("srcset-second"))}), json!([])),
            element(20, "img", json!({"src": url("shown-later"), "srcset": format!("{} 1x, {} 2x", url("shown-later-1x"), url("shown-later-2x")), "hidden": ""}), json!([])),
            element(21, "img", json!({"src": format!("https://cdn.example.com/{}.png", "a".repeat(MAX_URL_LEN))}), json!([])),
            element(22, "img", json!({"src": url("srcset-removed"), "srcset": format!("{} 1x", url("removed-1x")), "hidden": ""}), json!([])),
            element(23, "img", json!({"src": url("src-over-2x"), "srcset": format!("{} 2x", url("yields-2x")), "hidden": ""}), json!([])),
            element(24, "img", json!({"src": url("src-under-1x"), "srcset": format!("{} 1x, {} 2x", url("srcset-1x"), url("srcset-2x"))}), json!([])),
        ]))], "id": 1}});
        let message = events(json!([
            // URLs do not wait for the first full snapshot.
            mutation(json!([{"parentId": 1, "node": element(30, "img", json!({"src": url("before-snapshot")}), json!([]))}]), json!([]), json!([]), json!([])),
            {"type": 2, "timestamp": 1, "data": snapshot},
            // A lazy loader sets `src` later. The iframe is not an image.
            mutation(json!([]), json!([]), json!([]), json!([{"id": 17, "attributes": {"src": url("lazy")}}, {"id": 18, "attributes": {"src": url("frame")}}, {"id": 6, "attributes": {"style": format!("background-image:url({})", url("style-mutation"))}}])),
            // Hidden imgs that a mutation reveals while it sets `src`. The pixel stays a pixel.
            mutation(json!([]), json!([]), json!([]), json!([{"id": 11, "attributes": {"style": {"display": false}, "src": url("revealed")}}, {"id": 12, "attributes": {"hidden": null, "src": url("unhidden")}}, {"id": 10, "attributes": {"src": url("still-pixel")}}])),
            // An update that sets no source keeps the hidden img's sources.
            mutation(json!([]), json!([]), json!([]), json!([{"id": 20, "attributes": {"alt": "x"}}])),
            mutation(json!([]), json!([]), json!([]), json!([{"id": 20, "attributes": {"hidden": null}}])),
            // The srcset leaves as the img shows, so the img shows its `src`.
            mutation(json!([]), json!([]), json!([]), json!([{"id": 22, "attributes": {"hidden": null, "srcset": null}}])),
            // A srcset with no 1x candidate loses to the img's `src`, which HTML adds as one.
            mutation(json!([]), json!([]), json!([]), json!([{"id": 23, "attributes": {"hidden": null}}])),
            mutation(json!([]), json!([]), json!([]), json!([{"id": 6, "attributes": {"style": {"background-image": [format!("url({})", url("style-object")), "important"], "background": format!("url({})", url("style-object-plain")), "color": "red", "mask-image": false}}}])),
            mutation(json!([]), json!([]), json!([]), json!([{"id": 6, "attributes": {"style": {"background-image": "url(\"/img/relative-style.png\")"}}}])),
            // A `source` added on its own under a `picture`, one the page has or one the same mutation adds.
            mutation(json!([{"parentId": 13, "node": element(40, "source", json!({"srcset": format!("{} 2x", url("lone-source"))}), json!([]))},
                {"parentId": 41, "node": element(42, "source", json!({"srcset": url("same-mutation-source")}), json!([]))},
                {"parentId": 6, "node": element(41, "picture", json!({}), json!([]))}]), json!([]), json!([]), json!([])),
            mutation(json!([]), json!([]), json!([]), json!([{"id": 42, "attributes": {"srcset": url("source-srcset-change")}}])),
            // An img that moves keeps what it is, so a later `src` counts.
            mutation(json!([{"parentId": 3, "node": element(9, "img", json!({}), json!([]))}]), json!([{"parentId": 2, "id": 9}]), json!([]), json!([])),
            mutation(json!([]), json!([]), json!([]), json!([{"id": 9, "attributes": {"src": url("moved")}}])),
            // New text in a `style` is CSS. Text elsewhere is not.
            mutation(json!([]), json!([]), json!([{"id": 4, "value": format!(".a{{background:url({})}}", url("style-text-change"))}, {"id": 6, "value": format!("background:url({})", url("not-css"))}]), json!([])),
            // Rules and declarations that a page sets through CSSOM, compressed or not.
            {"type": 3, "timestamp": 3, "cv": "2024-10", "data": {"source": 8, "id": 3, "adds": sdk_cv(&json!([{"rule": format!(".c{{background:url({})}} .e{{background:url(/img/relative-rule.png)}}", url("sheet-rule")), "index": 0}]))}},
            {"type": 3, "timestamp": 3, "data": {"source": 8, "id": 3, "replaceSync": format!(".r{{cursor:url({}),auto}}", url("sheet-replace"))}},
            {"type": 3, "timestamp": 3, "data": {"source": 13, "id": 3, "index": [0], "set": {"property": "background-image", "value": format!("url({})", url("declaration"))}}},
            {"type": 3, "timestamp": 3, "data": {"source": 13, "id": 3, "index": [0], "set": {"property": "--x", "value": format!("url({})", url("custom-declaration"))}}},
            {"type": 3, "timestamp": 3, "data": {"source": 15, "id": 1, "styleIds": [1], "styles": [{"styleId": 1, "rules": [{"rule": format!(".d{{background:url({})}}", url("adopted"))}]}]}},
        ]));
        let (mut dom, _) = observe_all(&message, "w");
        // A hidden or one-pixel img is not fetched, but the block holds its URL, so the writer replaces it too.
        let named = named(&mut dom, &message);
        let mut rewrites: Vec<String> = named.rewrites.into_iter().map(|(text, _)| text).collect();
        let remote: Vec<String> = named.urls.into_iter().map(|(url, _)| url).collect();
        for name in [
            "hidden",
            "display-none",
            "pixel",
            "shown-later",
            "lazy",
            "w_640,q_auto/srcset-comma",
            "srcset-second",
        ] {
            assert!(remote.contains(&url(name)), "{name}");
        }
        assert!(!remote
            .iter()
            .any(|url| url.ends_with("/img/relative-style.png")));
        rewrites.sort();
        assert_eq!(
            rewrites,
            [
                format!(
                    "image-set(url({}) 1x, url({}) 2x)",
                    url("set-1x"),
                    url("set-2x")
                ),
                "url(\"/img/relative-style.png\")".to_owned(),
                "url(/img/relative-rule.png)".to_owned(),
            ]
        );
        let mut found = dom.take_image_urls();
        found.sort();
        let mut expected: Vec<String> = [
            "before-snapshot",
            "style-text",
            "custom-property",
            "set-2x",
            "style-attribute",
            "svg-href",
            "svg-xlink",
            "rr-src",
            "picture-source",
            "lazy",
            "style-mutation",
            "revealed",
            "unhidden",
            "moved",
            "style-text-change",
            "sheet-rule",
            "sheet-replace",
            "declaration",
            "custom-declaration",
            "adopted",
            "shown-later-1x",
            "srcset-removed",
            "src-over-2x",
            "srcset-1x",
            "style-object",
            "style-object-plain",
            "lone-source",
            "same-mutation-source",
            "source-srcset-change",
        ]
        .into_iter()
        .map(url)
        .chain([
            "https://app.example.com/img/relative-style.png".to_owned(),
            "https://app.example.com/img/relative-rule.png".to_owned(),
        ])
        .collect();
        expected.sort();
        assert_eq!(found, expected);
    }

    #[test]
    fn names_font_face_urls_and_fetches_only_unbundled_loadable_ones() {
        let font = |name: &str| format!("https://fonts.example.com/{name}");
        let face =
            |family: &str, src: &str| format!("@font-face{{font-family:{family};src:{src}}}");
        let style = [
            face(
                "'Brand Sans'",
                &format!(
                    "url({}) format('woff2'),url({}) format('embedded-opentype')",
                    font("brand.woff2"),
                    font("brand.eot?#iefix")
                ),
            ),
            face(
                "\"Open Sans\"",
                &format!("url({})", font("open-sans.woff2")),
            ),
            face("Inter", &format!("url({})", font("shared.woff2"))),
            face("Brand Inter", &format!("url({})", font("shared.woff2"))),
            format!(".logo{{background:url({})}}", font("logo.png")),
            face("Logo", &format!("url({})", font("logo.png"))),
            face("Brand Serif", "url(/fonts/serif.woff2)"),
            face("Roboto", "url(/fonts/roboto.woff2)"),
        ]
        .concat();
        let snapshot = json!({"node": {"type": 0, "childNodes": [element(2, "html", json!({}), json!([
            element(3, "style", json!({}), json!([{"type": 3, "textContent": style, "id": 4}])),
        ]))], "id": 1}});
        let message = events(json!([
            {"type": 2, "timestamp": 1, "data": snapshot},
            {"type": 3, "timestamp": 2, "data": {"source": 8, "id": 3, "adds": [{"rule": face("Icons", &format!("url({})", font("icons.woff"))), "index": 0}]}},
        ]));
        let (mut dom, _) = observe_all(&message, "w");
        let mut fetched = dom.take_font_urls();
        fetched.sort();
        let mut expected = ["brand.woff2", "icons.woff", "logo.png", "shared.woff2"]
            .map(font)
            .to_vec();
        expected.insert(0, "https://app.example.com/fonts/serif.woff2".to_owned());
        assert_eq!(fetched, expected);
        let named = named(&mut dom, &message);
        let mut resolved: Vec<RemoteUrl> = named
            .rewrites
            .into_iter()
            .flat_map(|(_, urls)| urls)
            .collect();
        resolved.sort_by(|a, b| a.url.cmp(&b.url));
        assert_eq!(
            resolved,
            [
                RemoteUrl {
                    url: "https://app.example.com/fonts/roboto.woff2".to_owned(),
                    kind: RemoteKind::BundledFont("roboto"),
                },
                RemoteUrl {
                    url: "https://app.example.com/fonts/serif.woff2".to_owned(),
                    kind: RemoteKind::Font,
                },
            ]
        );
        // Each slot names its URL by its own kind, so a URL in two slots has two references.
        let mut remote = named.urls;
        remote.sort();
        assert_eq!(
            remote,
            [
                (font("brand.eot?#iefix"), RemoteKind::Font),
                (font("brand.woff2"), RemoteKind::Font),
                (font("icons.woff"), RemoteKind::Font),
                (font("logo.png"), RemoteKind::Font),
                (font("logo.png"), RemoteKind::Image),
                (
                    font("open-sans.woff2"),
                    RemoteKind::BundledFont("open-sans")
                ),
                (font("shared.woff2"), RemoteKind::BundledFont("inter")),
                (font("shared.woff2"), RemoteKind::Font),
            ]
        );
    }

    #[test]
    fn keeps_one_srcset_candidate_of_a_hidden_img() {
        let srcset = |count: usize| {
            (0..count)
                .map(|i| format!("https://cdn.example.com/{i:05}.png {}w", i + 1))
                .collect::<Vec<_>>()
                .join(", ")
        };
        let retained = |count: usize| {
            let snapshot = json!({"node": {"type": 0, "childNodes": [element(2, "img", json!({"srcset": srcset(count), "hidden": ""}), json!([]))], "id": 1}});
            let (dom, _) = observe_all(
                &events(json!([{"type": 2, "timestamp": 1, "data": snapshot}])),
                "w",
            );
            dom.retained_bytes()
        };
        assert_eq!(retained(1), retained(10 * MAX_IMAGE_URLS));
    }

    #[test]
    fn stops_reading_a_mutation_past_the_attribute_cap() {
        let attributes = |count: usize| {
            let items = vec![r#"{"id":1,"attributes":{}}"#; count].join(",");
            let inner = format!(
                r#"{{"properties":{{"$session_id":"s","$snapshot_items":[{{"type":3,"timestamp":2,"data":{{"source":0,"attributes":[{items}]}}}}]}}}}"#
            );
            let message = read_message(json!({ "data": inner }).to_string().into_bytes()).unwrap();
            observe_all(&message, "w").0.take_url_limit()
        };
        assert_eq!(attributes(MAX_ATTRIBUTE_ITEMS), None);
        assert_eq!(
            attributes(MAX_ATTRIBUTE_ITEMS + 1),
            Some(UrlLimit::AttributeItems)
        );
    }

    #[test]
    fn caps_distinct_remote_image_urls_per_message() {
        let img = |i: i64, src: String| json!({"parentId": 1, "node": element(i, "img", json!({"src": src}), json!([]))});
        // Repeats and inline images come first and do not use up the cap.
        let mut adds: Vec<Value> = (0..600)
            .map(|i| img(i, "https://cdn.example.com/icon.png".to_owned()))
            .chain((600..1200).map(|i| img(i, "data:image/png;base64,AA".to_owned())))
            .collect();
        adds.extend((0..600).map(|i| img(2000 + i, format!("https://cdn.example.com/{i}.png"))));
        let message = events(json!([
            mutation(json!(adds[..1500]), json!([]), json!([]), json!([])),
            mutation(json!(adds[1500..]), json!([]), json!([]), json!([])),
        ]));
        let (mut dom, _) = observe_all(&message, "w");
        let found = dom.take_image_urls();
        assert_eq!(found.len(), MAX_IMAGE_URLS);
        // The cap limits the fetch jobs only. The writer replaces the URL of every remote slot in the block.
        assert_eq!(named(&mut dom, &message).urls.len(), 1200);
        assert_eq!(
            found[..2],
            [
                "https://cdn.example.com/icon.png",
                "https://cdn.example.com/0.png"
            ]
        );
    }

    #[test]
    fn compacts_the_child_lists_that_repeated_adds_grow() {
        let mut dom = WindowDom::default();
        for _ in 0..100_000 {
            dom.insert(2, Some(1));
        }
        assert!(dom.children[&1].len() <= 4097);
        let capacity: usize = dom.children.values().map(Vec::capacity).sum();
        assert!(dom.retained_bytes() >= capacity * std::mem::size_of::<i64>());
    }

    #[test]
    fn flags_a_window_that_returns_after_eviction() {
        let snapshot = json!({"type": 2, "timestamp": 1, "data": page()});
        let mut dom = DomInspector::default();
        let mut stats = BlockStats::default();
        let message = events(json!([
            snapshot,
            mutation(
                json!([]),
                json!([]),
                json!([{"id": 7, "value": "x"}]),
                json!([])
            )
        ]));
        for window in 0..=MAX_WINDOWS {
            dom.observe(
                &message.inner,
                &message.events[0],
                &window.to_string(),
                None,
                FlushBudgets::default(),
                &mut stats,
            );
        }
        assert!(!stats.node_cap_reached);
        dom.observe(
            &message.inner,
            &message.events[1],
            "0",
            None,
            FlushBudgets::default(),
            &mut stats,
        );
        assert!(stats.node_cap_reached);

        for window in 0..MAX_WINDOWS {
            let other = format!("other-{window}");
            dom.observe(
                &message.inner,
                &message.events[1],
                &other,
                None,
                FlushBudgets::default(),
                &mut stats,
            );
        }
        let mut stats = BlockStats::default();
        dom.observe(
            &message.inner,
            &message.events[1],
            "0",
            None,
            FlushBudgets::default(),
            &mut stats,
        );
        assert!(stats.node_cap_reached);
    }

    #[test]
    fn stops_at_hostile_nesting_instead_of_overflowing() {
        let deep = format!("{}{}", "[".repeat(100_000), "]".repeat(100_000));
        let tokens = &mut Tokens::new(deep.as_bytes(), (0, deep.len()));
        assert_eq!(tokens.by_ref().count(), crate::scan::tokens::MAX_DEPTH);
        assert!(tokens.failed);
    }
}
