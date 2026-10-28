//! Whether a recording plays back: full snapshots, the DOM they describe, and mutations against nodes that are not
//! there. The replayer renders such a mutation wrongly or not at all.

use std::collections::{HashMap, HashSet};
use std::ops::Range;

use crate::bytescan::{self as scan, Span};
use crate::url_policy::MAX_URL_LEN;

use super::css;
use super::events::{field, fields, number, text};
use super::rrweb::{
    ADOPTED_STYLE_SHEET, FULL_SNAPSHOT, INCREMENTAL_SNAPSHOT, MUTATION, STYLE_DECLARATION,
    STYLE_SHEET_RULE,
};
use super::stats::BlockStats;
use crate::scan::cv::{self, Expansion};
use crate::scan::message::Event;
use crate::scan::tokens::{Token, Tokens};

/// Node ids tracked per window. A larger page stops orphan counting for the window and sets `node_cap_reached`.
pub const MAX_TRACKED_NODES: usize = 200_000;
/// Remote image URLs kept per message, as the v3 collector caps URLs per message.
pub const MAX_IMAGE_URLS: usize = 512;
/// Attribute changes read per mutation, as many as the nodes tracked. A mutation with more drops its block, because
/// the inspector does not name the URLs in the rest.
pub const MAX_ATTRIBUTE_ITEMS: usize = MAX_TRACKED_NODES;
/// The longest remote URL a block may hold in an image slot: four times the longest the fetcher takes.
pub const MAX_REMOTE_URL_BYTES: usize = 8 * 1024;
/// The distinct remote URLs in a block's image slots, and their bytes. The writer builds one matcher over them, and
/// the build takes memory in proportion to their bytes.
pub const MAX_BLOCK_REMOTE_URLS: usize = 10_000;
pub const MAX_BLOCK_REMOTE_URL_BYTES: usize = 2 * 1024 * 1024;
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
    PictureSource,
    /// A `picture`, so that a `source` added under it later is known to be a picture source.
    Picture,
}

/// The remote image URLs of a hidden img, which v3 fetches once the img shows.
#[derive(Clone, Default)]
struct HiddenSources {
    src: Option<String>,
    rr_src: Option<String>,
    srcset: Vec<String>,
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
        }
        if let Some(span) = attributes.rr_src {
            self.rr_src = url(span);
        }
        if let Some(span) = attributes.srcset {
            self.srcset.clear();
            if let Some(srcset) = text(bytes, Some(span)) {
                // One message sends at most MAX_IMAGE_URLS URLs, so the img that shows needs no more.
                srcset_urls(&srcset, &mut |url| {
                    if self.srcset.len() < MAX_IMAGE_URLS {
                        self.srcset.extend(fetchable(url).map(str::to_owned));
                    }
                });
            }
        }
    }

    /// Whether the attributes set a source, which an update then changes.
    fn changes(attributes: &Attributes) -> bool {
        attributes.src.is_some() || attributes.rr_src.is_some() || attributes.srcset.is_some()
    }

    fn is_empty(&self) -> bool {
        self.src.is_none() && self.rr_src.is_none() && self.srcset.is_empty()
    }

    fn heap_bytes(&self) -> usize {
        let string = |s: &Option<String>| s.as_ref().map_or(0, String::capacity);
        string(&self.src)
            + string(&self.rr_src)
            + self.srcset.capacity() * std::mem::size_of::<String>()
            + self.srcset.iter().map(String::capacity).sum::<usize>()
    }

    fn push_revealed(self, set: &Attributes, walk: &mut Walk) {
        for (url, replaced) in [(self.src, set.src), (self.rr_src, set.rr_src)] {
            if let Some(url) = url.filter(|_| replaced.is_none()) {
                walk.push_url_text(&url);
            }
        }
        if set.srcset.is_none() {
            for url in &self.srcset {
                walk.push_url_text(url);
            }
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
}

/// Why the inspector stopped naming a block's remote image URLs. The writer replaces only the URLs it is given, so it
/// drops the block.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UrlLimit {
    UrlLength,
    UrlCount,
    UrlBytes,
    AttributeItems,
}

impl UrlLimit {
    /// The outcome of the dropped block in the recorder's metrics.
    pub fn label(self) -> &'static str {
        match self {
            UrlLimit::UrlLength => "url_too_long",
            UrlLimit::UrlCount => "too_many_urls",
            UrlLimit::UrlBytes => "too_many_url_bytes",
            UrlLimit::AttributeItems => "too_many_attribute_items",
        }
    }
}

/// Distinct remote image URLs within [`MAX_REMOTE_URL_BYTES`], [`MAX_BLOCK_REMOTE_URLS`] and
/// [`MAX_BLOCK_REMOTE_URL_BYTES`]. Past a limit it keeps no more, and `limit` says why.
#[derive(Debug, Default)]
pub struct RemoteUrls {
    urls: HashSet<String>,
    bytes: usize,
    pub limit: Option<UrlLimit>,
}

impl RemoteUrls {
    fn insert(&mut self, url: &str) {
        if self.limit.is_some() || self.urls.contains(url) {
            return;
        }
        self.limit = if url.len() > MAX_REMOTE_URL_BYTES {
            Some(UrlLimit::UrlLength)
        } else if self.urls.len() >= MAX_BLOCK_REMOTE_URLS {
            Some(UrlLimit::UrlCount)
        } else if self.bytes + url.len() > MAX_BLOCK_REMOTE_URL_BYTES {
            Some(UrlLimit::UrlBytes)
        } else {
            self.bytes += url.len();
            self.urls.insert(url.to_owned());
            None
        };
    }

    pub fn extend(&mut self, other: RemoteUrls) {
        self.limit = self.limit.or(other.limit);
        for url in &other.urls {
            self.insert(url);
        }
    }

    pub fn into_urls(self) -> Vec<String> {
        self.urls.into_iter().collect()
    }
}

/// Distinct remote image URLs, at most [`MAX_IMAGE_URLS`] per message.
#[derive(Default)]
struct Urls {
    urls: Vec<String>,
    in_message: HashSet<String>,
    /// Every remote URL in an image slot, past the fetch cap and in a hidden img too. The writer replaces each one in
    /// the stored block, and the fetch cap limits only the fetch jobs.
    remote: RemoteUrls,
}

/// The URL as the fetcher takes it: remote, and no longer than v3 fetches. An inline image is moved out of the block
/// by the image scan instead.
fn fetchable(url: &str) -> Option<&str> {
    let url = url.trim();
    (url.len() <= MAX_URL_LEN && is_remote(url)).then_some(url)
}

/// A URL scheme is not case sensitive, so `HTTPS://` loads as `https://` does.
fn is_remote(url: &str) -> bool {
    let starts = |prefix: &str| {
        url.get(..prefix.len())
            .is_some_and(|start| start.eq_ignore_ascii_case(prefix))
    };
    starts("https://") || starts("http://")
}

impl Urls {
    fn push(&mut self, url: &str) {
        self.push_remote(url);
        let Some(url) = fetchable(url) else { return };
        if self.in_message.len() < MAX_IMAGE_URLS && !self.in_message.contains(url) {
            self.in_message.insert(url.to_owned());
            self.urls.push(url.to_owned());
        }
    }

    /// Records a URL that the block holds but the fetcher does not take now, such as one of a hidden img.
    fn push_remote(&mut self, url: &str) {
        let url = url.trim();
        if is_remote(url) {
            self.remote.insert(url);
        }
    }

    /// Takes the URLs one walk found.
    fn merge(&mut self, walk: Urls) {
        for url in &walk.urls {
            self.push(url);
        }
        self.remote.extend(walk.remote);
    }
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
struct Walk {
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
    root_sources: Vec<(Option<i64>, Option<Span>)>,
}

impl Walk {
    fn push_id(&mut self, id: i64, parent: Option<i64>) {
        if self.ids.len() < MAX_TRACKED_NODES {
            self.ids.push((id, parent));
        } else {
            self.truncated = true;
        }
    }

    fn push_url(&mut self, bytes: &[u8], value: Option<Span>) {
        if let Some(url) = value
            .filter(|&v| scan::is_string(bytes, v))
            .and_then(|v| scan::unescape(bytes, v).ok())
        {
            self.push_url_text(&url);
        }
    }

    fn push_url_text(&mut self, url: &str) {
        self.image_urls.push(url);
    }

    /// The URLs of a slot the fetcher does not take now. The block still holds them, so the writer replaces them.
    fn push_remote(&mut self, bytes: &[u8], value: Option<Span>, srcset: bool) {
        if let Some(text) = text(bytes, value) {
            if srcset {
                srcset_urls(&text, &mut |url| self.image_urls.push_remote(url));
            } else {
                self.image_urls.push_remote(&text);
            }
        }
    }

    fn push_srcset(&mut self, bytes: &[u8], value: Option<Span>) {
        if let Some(srcset) = text(bytes, value) {
            srcset_urls(&srcset, &mut |url| self.push_url_text(url));
        }
    }

    fn push_css(&mut self, bytes: &[u8], value: Option<Span>) {
        let Some(value) = value else { return };
        if let Some(text) = text(bytes, Some(value)) {
            css::image_urls(&text, &mut |url| self.push_url_text(url));
        } else if scan::is_object(bytes, value) {
            let Ok(entries) = scan::object_entries(bytes, value) else {
                return;
            };
            for entry in entries.filter_map(Result::ok).filter(|e| !e.key_escaped) {
                let property = std::str::from_utf8(&bytes[entry.key.0..entry.key.1]);
                let declared = text(bytes, style_property_value(bytes, entry.value));
                if let (Ok(property), Some(declared)) = (property, declared) {
                    css::declaration_image_urls(property, &declared, &mut |url| {
                        self.image_urls.push(url)
                    });
                }
            }
        }
    }
}

/// The URLs of a srcset, parsed as HTML parses one: a URL is a run of non-whitespace, so it can hold a comma. A comma
/// ends a candidate only at the end of its URL or after its descriptors.
fn srcset_urls(srcset: &str, found: &mut impl FnMut(&str)) {
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
        found(url);
        if url.len() < position - start {
            continue;
        }
        let mut in_parens = false;
        while let Some(&byte) = bytes.get(position) {
            position += 1;
            match byte {
                b'(' => in_parens = true,
                b')' => in_parens = false,
                b',' if !in_parens => break,
                _ => {}
            }
        }
    }
}

fn style_property_value(bytes: &[u8], span: Span) -> Option<Span> {
    if scan::is_array(bytes, span) {
        scan::array_items(bytes, span).ok()?.next()?.ok()
    } else {
        Some(span)
    }
}

/// A repeated attribute takes its last value, as in `JSON.parse`, so that the inspector names the URL the player loads.
#[derive(Default)]
struct Attributes {
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
            _ => return None,
        })
    }

    fn read(bytes: &[u8], object: Span) -> Self {
        let mut attributes = Self::default();
        if let Ok(entries) = scan::object_entries(bytes, object) {
            for entry in entries.filter_map(Result::ok).filter(|e| !e.key_escaped) {
                if let Some(slot) = attributes.slot(&bytes[entry.key.0..entry.key.1]) {
                    *slot = Some(entry.value);
                }
            }
        }
        attributes
    }

    /// The sources of a node the window does not know, after a restart, an eviction or the node cap. What the node
    /// shows is not known, so they are not fetched. The block holds them, so the writer replaces them.
    fn push_unknown_sources(&self, bytes: &[u8], walk: &mut Walk) {
        walk.push_remote(bytes, self.src, false);
        walk.push_remote(bytes, self.rr_src, false);
        walk.push_remote(bytes, self.srcset, true);
        walk.push_remote(bytes, self.href, false);
        walk.push_remote(bytes, self.xlink_href, false);
        walk.push_remote(bytes, self.poster, false);
    }

    /// The image URLs v3 fetches from these attributes on an element of this kind, and the URLs in its CSS.
    fn push_urls(&self, bytes: &[u8], media: Option<Media>, walk: &mut Walk) {
        match media {
            Some(Media::Img { visibility }) if !visibility.hides() => {
                walk.push_url(bytes, self.src);
                walk.push_url(bytes, self.rr_src);
                walk.push_srcset(bytes, self.srcset);
            }
            Some(Media::Img { .. }) => {
                walk.push_remote(bytes, self.src, false);
                walk.push_remote(bytes, self.rr_src, false);
                walk.push_remote(bytes, self.srcset, true);
            }
            Some(Media::SvgImage) => {
                walk.push_url(bytes, self.href);
                walk.push_url(bytes, self.xlink_href);
            }
            Some(Media::Video) => walk.push_url(bytes, self.poster),
            Some(Media::PictureSource) => walk.push_srcset(bytes, self.srcset),
            _ => {}
        }
        walk.push_css(bytes, self.style);
        walk.push_css(bytes, self.css_text);
    }
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
    shadow_host: bool,
    attributes: Attributes,
    /// The ids of the children walked so far. A node's id comes after its children, so they wait for it here.
    children: Vec<i64>,
    /// Child text, and child `source` elements with their srcset, which count only under a `style` or a `picture`.
    /// They wait here because the tag can come after the children.
    child_texts: Vec<(Option<i64>, Span)>,
    child_sources: Vec<(Option<i64>, Option<Span>)>,
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
                        b"textContent" => node.text = Some(value),
                        b"isShadowHost" => node.shadow_host = &bytes[value.0..value.1] == b"true",
                        b"isStyle" => node.is_style_text = &bytes[value.0..value.1] == b"true",
                        _ => {}
                    }
                }
                (Some(FrameKind::Attributes), Some(name)) => {
                    if let Some(slot) = nodes.last_mut().and_then(|n| n.attributes.slot(name)) {
                        *slot = Some(value);
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
        for &(id, srcset) in &node.child_sources {
            walk.media.extend(id.map(|id| (id, Media::PictureSource)));
            walk.push_srcset(bytes, srcset);
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
                walk.push_css(bytes, Some(text));
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
                parent
                    .child_texts
                    .extend(node.text.map(|text| (node.id, text)));
            }
            if node.tag == Tag::Source {
                parent.child_sources.push((node.id, node.attributes.srcset));
            }
        }
        None => {
            if let Some(id) = node.id {
                walk.push_id(id, None);
            }
            if node.tag == Tag::Source {
                walk.root_sources.push((node.id, node.attributes.srcset));
            }
        }
    }
}

/// What a full snapshot does to its window.
enum Snapshot {
    /// The player drops it, because its data or its node is not an object.
    Dropped,
    /// It does not decode or is too deep to walk, and the player may still build a DOM from a payload this deep.
    Unreadable,
    Walked(Box<Walk>),
}

/// Walks the DOM in a full snapshot's data, decoded when the event is compressed.
fn walk_snapshot(inner: &[u8], data: Span, expansion: &Expansion) -> Snapshot {
    let (bytes, root) = if scan::is_string(inner, data) {
        match expansion.json(data) {
            Some(Some(json)) => match scan::locate_value(json, 0) {
                Ok(root) => (json, root),
                Err(_) => return Snapshot::Unreadable,
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
    let mut walk = Walk::default();
    if walk_nodes(bytes, node, &mut walk) {
        Snapshot::Walked(Box::new(walk))
    } else {
        Snapshot::Unreadable
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
    }

    /// Ends a message. The URLs it saw go, so that they do not stay in memory that [`Self::retained_bytes`] does not
    /// count.
    pub fn finish_message(&mut self) {
        self.urls.in_message = HashSet::new();
    }

    /// Updates the window's DOM with one event and adds what it found to the block.
    pub fn observe(
        &mut self,
        inner: &[u8],
        event: &Event,
        window: &str,
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
        let mut observed = Observed::default();
        match (event.kind, event.source) {
            (Some(FULL_SNAPSHOT), _) => {
                let expansion = cv::expansion(inner, event);
                let last_used = dom.last_used;
                match event.data.map_or(Snapshot::Dropped, |data| {
                    walk_snapshot(inner, data, &expansion)
                }) {
                    Snapshot::Walked(mut walk) => {
                        // A full snapshot replaces the window's DOM.
                        *dom = WindowDom {
                            has_snapshot: true,
                            unverifiable: walk.truncated,
                            last_used,
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
                    Snapshot::Unreadable => {
                        stats.decode_failures += 1;
                        *dom = WindowDom {
                            unverifiable: true,
                            last_used,
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
                        observe_mutation(inner, data, &expansion, dom, &mut self.urls);
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
                    style_sheet_urls(inner, data, event.source, &expansion, &mut self.urls);
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

    /// Every remote image URL the events since the last call hold, for the writer to replace.
    pub fn take_remote_urls(&mut self) -> RemoteUrls {
        std::mem::take(&mut self.urls.remote)
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
    let mut failed = false;
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
                Err(_) => failed = true,
            },
            Some(None) => {}
            None => failed = true,
        }
    }
    lists.failed = failed;
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
    urls: &mut Urls,
) -> (u32, u32, bool) {
    // The recorder did not decode this mutation, so the window's DOM is not known after it.
    if matches!(expansion, Expansion::Skipped) {
        dom.unverifiable = true;
        return (0, 0, true);
    }
    let lists = mutation_lists(inner, data, expansion);
    if lists.failed {
        return (0, 0, true);
    }
    let mut undecoded = false;
    let mut walk = Walk::default();
    let mut adds = Vec::new();
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
            for (parent, (id, srcset)) in sources {
                let Some(parent) = parent else { continue };
                if pictures.contains(&parent) || dom.media.get(&parent) == Some(&Media::Picture) {
                    walk.media.extend(id.map(|id| (id, Media::PictureSource)));
                    walk.push_srcset(list.bytes, srcset);
                }
            }
        }
    }
    dom.add_media(&walk.media);
    dom.add_hidden_sources(&walk.hidden);
    dom.add_style_texts(&walk.style_texts);
    if let Some(texts) = lists.texts {
        for item in items(texts) {
            let [id, value] = fields(texts.bytes, item, [b"id", b"value"]);
            if number(texts.bytes, id).is_some_and(|id| dom.style_texts.contains(&(id as i64))) {
                walk.push_css(texts.bytes, value);
            }
        }
    }
    let mut attribute_ids = Vec::new();
    if let Some(attributes) = lists.attributes {
        let walked: HashSet<i64> = walk.ids.iter().map(|&(id, _)| id).collect();
        for (index, item) in items(attributes).enumerate() {
            if index == MAX_ATTRIBUTE_ITEMS {
                walk.image_urls.remote.limit = Some(UrlLimit::AttributeItems);
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
                            sources.push_revealed(&values, &mut walk);
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
    urls: &mut Urls,
) {
    let mut push = |url: &str| urls.push(url);
    match source {
        Some(STYLE_SHEET_RULE) => {
            let [adds, replace, replace_sync] =
                fields(inner, data, [b"adds", b"replace", b"replaceSync"]);
            if let Some(adds) = adds.and_then(|adds| decoded_list(inner, adds, expansion)) {
                for item in items(adds) {
                    if let Some(rule) = text(adds.bytes, field(adds.bytes, item, b"rule")) {
                        css::image_urls(&rule, &mut push);
                    }
                }
            }
            for sheet in [replace, replace_sync] {
                if let Some(sheet) = text(inner, sheet) {
                    css::image_urls(&sheet, &mut push);
                }
            }
        }
        Some(STYLE_DECLARATION) => {
            let set = field(inner, data, b"set");
            let [property, value] =
                set.map_or([None; 2], |set| fields(inner, set, [b"property", b"value"]));
            if let (Some(property), Some(value)) = (text(inner, property), text(inner, value)) {
                css::declaration_image_urls(&property, &value, &mut push);
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
                    if let Some(rule) = text(inner, field(inner, rule, b"rule")) {
                        css::image_urls(&rule, &mut push);
                    }
                }
            }
        }
        _ => {}
    }
}

/// A list as the player reads it, decoded when the event compressed it. `None` when it is empty or does not decode.
fn decoded_list<'b>(inner: &'b [u8], span: Span, expansion: &'b Expansion) -> Option<List<'b>> {
    if !scan::is_string(inner, span) {
        return Some(List { bytes: inner, span });
    }
    let json = expansion.json(span)??;
    Some(List {
        bytes: json,
        span: scan::locate_value(json, 0).ok()?,
    })
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
                element(12, "video", json!({"poster": "https://cdn.example.com/p.jpg"}), json!([])),
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
            dom.observe(&message.inner, &message.events[0], "w", &mut stats);
            // Remote image URLs go to the fetcher. The inline image in the srcset is the image scan's to move.
            assert_eq!(
                dom.take_image_urls(),
                [
                    "https://cdn.example.com/a.png",
                    "https://cdn.example.com/a@2x.png",
                    "https://cdn.example.com/p.jpg"
                ]
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
            dom.observe(&message.inner, event, "w", &mut stats);
        }
        assert_eq!(stats.events_before_first_full_snapshot, 1);
        assert_eq!(stats.orphan_mutations, 2);
    }

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
            dom.observe(&message.inner, event, window, &mut stats);
        }
        (dom, stats)
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
            element(20, "img", json!({"src": url("shown-later"), "srcset": format!("{} 2x", url("shown-later-2x")), "hidden": ""}), json!([])),
            element(21, "img", json!({"src": format!("https://cdn.example.com/{}.png", "a".repeat(MAX_URL_LEN))}), json!([])),
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
            mutation(json!([]), json!([]), json!([]), json!([{"id": 6, "attributes": {"style": {"background-image": [format!("url({})", url("style-object")), "important"], "background": format!("url({})", url("style-object-plain")), "color": "red", "mask-image": false}}}])),
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
            {"type": 3, "timestamp": 3, "cv": "2024-10", "data": {"source": 8, "id": 3, "adds": sdk_cv(&json!([{"rule": format!(".c{{background:url({})}}", url("sheet-rule")), "index": 0}]))}},
            {"type": 3, "timestamp": 3, "data": {"source": 8, "id": 3, "replaceSync": format!(".r{{cursor:url({}),auto}}", url("sheet-replace"))}},
            {"type": 3, "timestamp": 3, "data": {"source": 13, "id": 3, "index": [0], "set": {"property": "background-image", "value": format!("url({})", url("declaration"))}}},
            {"type": 3, "timestamp": 3, "data": {"source": 13, "id": 3, "index": [0], "set": {"property": "--x", "value": format!("url({})", url("custom-declaration"))}}},
            {"type": 3, "timestamp": 3, "data": {"source": 15, "id": 1, "styleIds": [1], "styles": [{"styleId": 1, "rules": [{"rule": format!(".d{{background:url({})}}", url("adopted"))}]}]}},
        ]));
        let (mut dom, _) = observe_all(&message, "w");
        // A hidden or one-pixel img is not fetched, but the block holds its URL, so the writer replaces it too.
        let remote = dom.take_remote_urls().into_urls();
        for name in ["hidden", "display-none", "pixel", "shown-later", "lazy"] {
            assert!(remote.contains(&url(name)), "{name}");
        }
        let mut found = dom.take_image_urls();
        found.sort();
        let mut expected: Vec<String> = [
            "before-snapshot",
            "style-text",
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
            "adopted",
            "w_640,q_auto/srcset-comma",
            "srcset-second",
            "shown-later",
            "shown-later-2x",
            "style-object",
            "style-object-plain",
            "lone-source",
            "same-mutation-source",
            "source-srcset-change",
        ]
        .into_iter()
        .map(url)
        .collect();
        expected.sort();
        assert_eq!(found, expected);
    }

    #[test]
    fn caps_the_sources_a_hidden_img_keeps() {
        let srcset = |count: usize| {
            (0..count)
                .map(|i| format!("https://cdn.example.com/{i}.png {}w", i + 1))
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
        assert!(retained(1) < retained(MAX_IMAGE_URLS));
        assert_eq!(retained(MAX_IMAGE_URLS), retained(10 * MAX_IMAGE_URLS));
    }

    #[test]
    fn stops_naming_remote_urls_past_a_block_limit() {
        let url = |i: usize, len: usize| {
            let mut url = format!("https://cdn.example.com/{i}/");
            url.extend(std::iter::repeat_n('a', len - url.len()));
            url
        };
        let limit = |urls: &mut dyn Iterator<Item = String>| {
            let mut remote = RemoteUrls::default();
            urls.for_each(|u| remote.insert(&u));
            remote.limit
        };
        let longest = MAX_REMOTE_URL_BYTES;
        let most_long = MAX_BLOCK_REMOTE_URL_BYTES / longest;
        for (urls, expected) in [
            (vec![url(0, longest)], None),
            (vec![url(0, longest + 1)], Some(UrlLimit::UrlLength)),
            (
                (0..MAX_BLOCK_REMOTE_URLS).map(|i| url(i, 40)).collect(),
                None,
            ),
            (
                (0..=MAX_BLOCK_REMOTE_URLS).map(|i| url(i, 40)).collect(),
                Some(UrlLimit::UrlCount),
            ),
            ((0..most_long).map(|i| url(i, longest)).collect(), None),
            (
                (0..=most_long).map(|i| url(i, longest)).collect(),
                Some(UrlLimit::UrlBytes),
            ),
        ] {
            assert_eq!(limit(&mut urls.into_iter()), expected);
        }

        // A mutation past the attribute cap is not read to its end.
        let attributes = |count: usize| {
            let items = vec![r#"{"id":1,"attributes":{}}"#; count].join(",");
            let inner = format!(
                r#"{{"properties":{{"$session_id":"s","$snapshot_items":[{{"type":3,"timestamp":2,"data":{{"source":0,"attributes":[{items}]}}}}]}}}}"#
            );
            let message = read_message(json!({ "data": inner }).to_string().into_bytes()).unwrap();
            observe_all(&message, "w").0.take_remote_urls().limit
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
        // The cap limits the fetch jobs only. The writer replaces every remote URL in the block.
        assert_eq!(dom.take_remote_urls().into_urls().len(), 601);
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
                &mut stats,
            );
        }
        assert!(!stats.node_cap_reached);
        dom.observe(&message.inner, &message.events[1], "0", &mut stats);
        assert!(stats.node_cap_reached);

        for window in 0..MAX_WINDOWS {
            let other = format!("other-{window}");
            dom.observe(&message.inner, &message.events[1], &other, &mut stats);
        }
        let mut stats = BlockStats::default();
        dom.observe(&message.inner, &message.events[1], "0", &mut stats);
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
