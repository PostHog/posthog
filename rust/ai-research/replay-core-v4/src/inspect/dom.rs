//! Whether a recording plays back: full snapshots, the DOM they describe, and mutations against nodes that are not
//! there. The replayer renders such a mutation wrongly or not at all.

use std::collections::{HashMap, HashSet};

use posthog_replay_anonymizer::scan::{self, Span};

use super::css;
use super::events::{field, fields, number};
use super::rrweb::{FULL_SNAPSHOT, INCREMENTAL_SNAPSHOT, MUTATION};
use super::stats::BlockStats;
use crate::scan::cv::{self, Expansion};
use crate::scan::message::Event;
use crate::scan::tokens::{Token, Tokens};

/// Node ids tracked per window. A larger page stops orphan counting for the window and sets `node_cap_reached`.
pub const MAX_TRACKED_NODES: usize = 200_000;
/// Remote image URLs kept per message, as the v3 collector caps URLs per message.
pub const MAX_IMAGE_URLS: usize = 512;
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
    Img { hidden: bool },
    SvgImage,
    Video,
    PictureSource,
}

#[derive(Default)]
struct WindowDom {
    nodes: HashMap<i64, Option<i64>>,
    /// The children of each node. A list keeps a node that moved or went away until the next compaction.
    children: HashMap<i64, Vec<i64>>,
    stale_children: usize,
    media: HashMap<i64, Media>,
    has_snapshot: bool,
    /// Orphan counting stopped: the DOM outgrew the node cap, a snapshot or mutation did not decode, or the window was
    /// evicted and came back.
    unverifiable: bool,
    last_used: u64,
}

/// Remote image URLs, at most [`MAX_IMAGE_URLS`] per message.
#[derive(Default)]
struct Urls {
    urls: Vec<String>,
    in_message: usize,
}

impl Urls {
    /// Keeps remote URLs only: an inline image is moved out of the block by the image scan instead.
    fn push(&mut self, url: &str) {
        let url = url.trim();
        if self.in_message < MAX_IMAGE_URLS
            && (url.starts_with("https://") || url.starts_with("http://"))
        {
            self.in_message += 1;
            self.urls.push(url.to_owned());
        }
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
    image_urls: Vec<String>,
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
        if self.image_urls.len() < MAX_IMAGE_URLS {
            self.image_urls.push(url.to_owned());
        }
    }

    /// A srcset is a comma-separated list of `url descriptor` candidates.
    fn push_srcset(&mut self, bytes: &[u8], value: Option<Span>) {
        if let Some(srcset) = value
            .filter(|&v| scan::is_string(bytes, v))
            .and_then(|v| scan::unescape(bytes, v).ok())
        {
            for candidate in srcset.split(',') {
                if let Some(url) = candidate.split_whitespace().next() {
                    self.push_url_text(url);
                }
            }
        }
    }

    fn push_css(&mut self, bytes: &[u8], value: Option<Span>) {
        if let Some(text) = value
            .filter(|&v| scan::is_string(bytes, v))
            .and_then(|v| scan::unescape(bytes, v).ok())
        {
            css::image_urls(&text, &mut |url| self.push_url_text(url));
        }
    }
}

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
                    slot.get_or_insert(entry.value);
                }
            }
        }
        attributes
    }

    /// v3 `is_hidden_pixel`: hidden by the `hidden` attribute or `display: none`, or at most one pixel each way.
    fn hide_pixel(&self, bytes: &[u8]) -> bool {
        if self.hidden.is_some_and(|h| !scan::is_null(bytes, h)) {
            return true;
        }
        let style = self
            .style
            .filter(|&s| scan::is_string(bytes, s))
            .and_then(|s| scan::unescape(bytes, s).ok());
        let style = style.as_deref();
        if style
            .and_then(|s| inline_style_declaration(s, "display"))
            .as_deref()
            == Some("none")
        {
            return true;
        }
        is_at_most_one_pixel(
            dimension_px(bytes, style, self.width, "width"),
            dimension_px(bytes, style, self.height, "height"),
        )
    }

    /// The image URLs v3 fetches from these attributes on an element of this kind, and the URLs in its CSS.
    fn push_urls(&self, bytes: &[u8], media: Option<Media>, walk: &mut Walk) {
        match media {
            Some(Media::Img { hidden }) if !hidden && !self.hide_pixel(bytes) => {
                walk.push_url(bytes, self.src);
                walk.push_url(bytes, self.rr_src);
                walk.push_srcset(bytes, self.srcset);
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

fn is_at_most_one_pixel(width: Option<f64>, height: Option<f64>) -> bool {
    let at_most_one = |length: f64| (0.0..=1.0).contains(&length);
    matches!((width, height), (Some(width), Some(height)) if at_most_one(width) && at_most_one(height))
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

/// The inline style wins over the attribute, as in the browser.
fn dimension_px(
    bytes: &[u8],
    style: Option<&str>,
    attribute: Option<Span>,
    name: &str,
) -> Option<f64> {
    if let Some(declared) = style.and_then(|style| inline_style_declaration(style, name)) {
        return px_length(&declared);
    }
    let attribute = attribute?;
    if scan::is_string(bytes, attribute) {
        return px_length(&scan::unescape(bytes, attribute).ok()?);
    }
    scan::parse_number(bytes, attribute)
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
    child_texts: Vec<Span>,
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
                        slot.get_or_insert(value);
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
        Tag::Img => Some(Media::Img {
            hidden: node.attributes.hide_pixel(bytes),
        }),
        Tag::SvgImage => Some(Media::SvgImage),
        Tag::Video => Some(Media::Video),
        _ => None,
    };
    if node.tag == Tag::Style {
        for &text in &node.child_texts {
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
                parent.child_texts.extend(node.text);
            }
            if node.tag == Tag::Source {
                parent.child_sources.push((node.id, node.attributes.srcset));
            }
        }
        None => {
            if let Some(id) = node.id {
                walk.push_id(id, None);
            }
        }
    }
}

/// Walks the DOM in a full snapshot's data, decoded when the event is compressed. `None` when it does not decode.
fn walk_snapshot(inner: &[u8], data: Span, expansion: &Expansion) -> Option<Walk> {
    let (bytes, root) = if scan::is_string(inner, data) {
        let json = expansion.json(data)??;
        (json, scan::locate_value(json, 0).ok()?)
    } else {
        (inner, data)
    };
    let node = field(bytes, root, b"node")?;
    let mut walk = Walk::default();
    walk_nodes(bytes, node, &mut walk).then_some(walk)
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
            self.children.entry(parent).or_default().push(id);
        }
        if self.nodes.insert(id, parent).is_some() {
            self.stale_children += 1;
        }
    }

    fn add_media(&mut self, media: &[(i64, Media)]) {
        for &(id, kind) in media {
            if self.media.len() < MAX_TRACKED_NODES || self.media.contains_key(&id) {
                self.media.insert(id, kind);
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
            if let Some(children) = self.children.remove(&id) {
                // A node that moved away from this parent stays in its list until compaction, so check it.
                stack.extend(
                    children
                        .into_iter()
                        .filter(|c| self.nodes.get(c) == Some(&Some(id))),
                );
            }
        }
        self.stale_children += 1;
        if self.stale_children > self.nodes.len().max(4096) {
            self.compact();
        }
        removed
    }

    fn compact(&mut self) {
        let nodes = &self.nodes;
        self.children.retain(|&parent, children| {
            children.retain(|child| nodes.get(child) == Some(&Some(parent)));
            children.sort_unstable();
            children.dedup();
            !children.is_empty()
        });
        self.stale_children = 0;
    }
}

/// The DOM of `name`, created when the session has not seen it, evicting the window used least recently past the cap.
fn window_dom<'d>(
    windows: &'d mut HashMap<String, WindowDom>,
    evicted: &mut HashSet<String>,
    clock: u64,
    name: &str,
) -> &'d mut WindowDom {
    if !windows.contains_key(name) {
        if windows.len() >= MAX_WINDOWS {
            let oldest = windows
                .iter()
                .min_by_key(|(_, dom)| dom.last_used)
                .map(|(oldest, dom)| (oldest.clone(), dom.has_snapshot));
            if let Some((oldest, had_snapshot)) = oldest {
                windows.remove(&oldest);
                if had_snapshot && evicted.len() < MAX_EVICTED_WINDOWS {
                    evicted.insert(oldest);
                }
            }
        }
        // A window that comes back after eviction lost its DOM, so its mutations go unchecked until its next snapshot.
        let unverifiable = evicted.remove(name);
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

impl DomInspector {
    /// Starts a message: the image URL cap counts per message.
    pub fn start_message(&mut self) {
        self.urls.in_message = 0;
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
        let dom = window_dom(&mut self.windows, &mut self.evicted, self.clock, window);
        let mut observed = Observed::default();
        match (event.kind, event.source) {
            (Some(FULL_SNAPSHOT), _) => {
                let expansion = cv::expansion(inner, event);
                let last_used = dom.last_used;
                match event
                    .data
                    .and_then(|data| walk_snapshot(inner, data, &expansion))
                {
                    Some(walk) => {
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
                        stats.full_snapshots += 1;
                        stats.dom_nodes = stats.dom_nodes.max(walk.nodes);
                        stats.dom_text_chars = stats.dom_text_chars.max(walk.text_chars);
                        stats.remote_stylesheets += walk.remote_stylesheets;
                        stats.inline_stylesheets += walk.inline_stylesheets;
                        stats.iframes += walk.iframes;
                        stats.canvases += walk.canvases;
                        stats.videos += walk.videos;
                        stats.shadow_roots += walk.shadow_roots;
                        for url in &walk.image_urls {
                            self.urls.push(url);
                        }
                        self.seen_snapshot = true;
                        observed.full_snapshot = true;
                    }
                    // The replayer cannot build a DOM from it, so the window's mutations cannot be checked.
                    None => {
                        *dom = WindowDom {
                            unverifiable: true,
                            last_used,
                            ..WindowDom::default()
                        }
                    }
                }
            }
            (Some(INCREMENTAL_SNAPSHOT), Some(MUTATION)) => {
                if let Some(data) = event.data {
                    let expansion = cv::expansion(inner, event);
                    let (orphans, changed) =
                        observe_mutation(inner, data, &expansion, dom, &mut self.urls);
                    stats.orphan_mutations += orphans;
                    observed.changed = changed;
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
    /// A list did not decode, so the mutation cannot be checked.
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

/// Applies a mutation to the window's DOM and collects its image URLs. Returns how many of its changes name a node
/// that is not there, and how many nodes it added or removed. URLs do not depend on the DOM state.
fn observe_mutation(
    inner: &[u8],
    data: Span,
    expansion: &Expansion,
    dom: &mut WindowDom,
    urls: &mut Urls,
) -> (u32, u32) {
    let lists = mutation_lists(inner, data, expansion);
    if lists.failed {
        dom.unverifiable = true;
    }
    let mut walk = Walk::default();
    let mut parents = Vec::new();
    if let Some(adds) = lists.adds {
        for item in items(adds) {
            let [parent, node] = fields(adds.bytes, item, [b"parentId", b"node"]);
            let parent = number(adds.bytes, parent).map(|p| p as i64);
            parents.extend(parent);
            if let Some(node) = node {
                let first = walk.ids.len();
                if !walk_nodes(adds.bytes, node, &mut walk) {
                    dom.unverifiable = true;
                }
                for entry in &mut walk.ids[first..] {
                    entry.1 = entry.1.or(parent);
                }
            }
        }
    }
    dom.add_media(&walk.media);
    let mut attribute_ids = Vec::new();
    if let Some(attributes) = lists.attributes {
        for item in items(attributes) {
            let [id, values] = fields(attributes.bytes, item, [b"id", b"attributes"]);
            let id = number(attributes.bytes, id).map(|id| id as i64);
            attribute_ids.extend(id);
            if let Some(values) = values.filter(|&v| scan::is_object(attributes.bytes, v)) {
                let media = id.and_then(|id| dom.media.get(&id).copied());
                Attributes::read(attributes.bytes, values).push_urls(
                    attributes.bytes,
                    media,
                    &mut walk,
                );
            }
        }
    }
    for url in &walk.image_urls {
        urls.push(url);
    }
    if walk.truncated {
        dom.unverifiable = true;
    }
    if !dom.has_snapshot || dom.unverifiable {
        return (0, 0);
    }

    // rrweb does not order adds parent first, so a parent added anywhere in the same mutation counts as present.
    let added: HashSet<i64> = walk.ids.iter().map(|&(id, _)| id).collect();
    let mut orphans = parents.iter().filter(|&&p| !dom.knows(p, &added)).count() as u32;
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
        for item in items(removes) {
            if let Some(id) = number(removes.bytes, field(removes.bytes, item, b"id")) {
                removed += dom.remove(id as i64).max(1);
            }
        }
    }
    for &(id, parent) in &walk.ids {
        dom.insert(id, parent);
    }
    (orphans, added.len() as u32 + removed)
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
    use posthog_replay_anonymizer::compression;
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
    fn stops_checking_a_window_whose_events_do_not_decode() {
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
        let cases = [
            // A snapshot that does not decode is not a full snapshot, so the replay still waits for one.
            (
                json!([{"type": 2, "timestamp": 1, "data": "not gzip", "cv": "2024-10"}]),
                0,
            ),
            (
                json!([{"type": 2, "timestamp": 1, "data": deep, "cv": "2024-10"}]),
                0,
            ),
            (
                json!([
                    {"type": 2, "timestamp": 1, "data": page()},
                    {"type": 3, "timestamp": 2, "cv": "2024-10", "data": {"source": 0, "adds": sdk_cv(&json!([{"parentId": 500, "node": {"type": 3, "id": 501}}])),
                        "removes": "not gzip", "texts": sdk_cv(&json!([])), "attributes": sdk_cv(&json!([]))}},
                ]),
                1,
            ),
        ];
        for (items, full_snapshots) in cases {
            let message = events(items);
            let (_, stats) = observe_all(&message, "w");
            assert_eq!(stats.full_snapshots, full_snapshots);
            assert_eq!(stats.events_before_first_full_snapshot, 1 - full_snapshots);
            assert_eq!(stats.orphan_mutations, 0);
            assert!(stats.node_cap_reached, "an unchecked window is flagged");
        }
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
        ]))], "id": 1}});
        let message = events(json!([
            // URLs do not wait for the first full snapshot.
            mutation(json!([{"parentId": 1, "node": element(30, "img", json!({"src": url("before-snapshot")}), json!([]))}]), json!([]), json!([]), json!([])),
            {"type": 2, "timestamp": 1, "data": snapshot},
            // A lazy loader sets `src` later. The iframe is not an image.
            mutation(json!([]), json!([]), json!([]), json!([{"id": 17, "attributes": {"src": url("lazy")}}, {"id": 18, "attributes": {"src": url("frame")}}, {"id": 6, "attributes": {"style": format!("background-image:url({})", url("style-mutation"))}}])),
        ]));
        let (mut dom, _) = observe_all(&message, "w");
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
        ]
        .into_iter()
        .map(url)
        .collect();
        expected.sort();
        assert_eq!(found, expected);
    }

    #[test]
    fn caps_image_urls_per_message() {
        let adds: Vec<Value> = (0..600)
            .map(|i| json!({"parentId": 1, "node": element(100 + i, "img", json!({"src": format!("https://cdn.example.com/{i}.png")}), json!([]))}))
            .collect();
        let message = events(json!([
            mutation(json!(adds[..300]), json!([]), json!([]), json!([])),
            mutation(json!(adds[300..]), json!([]), json!([]), json!([])),
        ]));
        let (mut dom, _) = observe_all(&message, "w");
        assert_eq!(dom.take_image_urls().len(), MAX_IMAGE_URLS);
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
    }

    #[test]
    fn stops_at_hostile_nesting_instead_of_overflowing() {
        let deep = format!("{}{}", "[".repeat(100_000), "]".repeat(100_000));
        let tokens = &mut Tokens::new(deep.as_bytes(), (0, deep.len()));
        assert_eq!(tokens.by_ref().count(), crate::scan::tokens::MAX_DEPTH);
        assert!(tokens.failed);
    }
}
