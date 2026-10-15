//! Whether a recording plays back: full snapshots, the DOM they describe, and mutations against nodes that are not
//! there. The replayer renders such a mutation wrongly or not at all.

use std::collections::{HashMap, HashSet};

use crate::bytescan::{self as scan, Span};

use super::events::{field, number};
use super::rrweb::{FULL_SNAPSHOT, INCREMENTAL_SNAPSHOT, MUTATION};
use super::stats::BlockStats;
use crate::scan::cv::{self, Expansion};
use crate::scan::message::Event;
use crate::scan::tokens::{Token, Tokens};

/// Node ids tracked per window. A larger page stops orphan counting for the window and sets `node_cap_reached`.
pub const MAX_TRACKED_NODES: usize = 200_000;

const TEXT_NODE: f64 = 3.0;

#[derive(Default)]
struct WindowDom {
    nodes: HashSet<i64>,
    has_snapshot: bool,
    cap_reached: bool,
}

/// The DOM state of a session's windows in this process.
#[derive(Default)]
pub struct DomInspector {
    windows: HashMap<String, WindowDom>,
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
    ids: Vec<i64>,
    nodes: u32,
    text_chars: u64,
    remote_stylesheets: u32,
    inline_stylesheets: u32,
    iframes: u32,
    canvases: u32,
    videos: u32,
    shadow_roots: u32,
}

#[derive(Default)]
struct NodeFrame {
    id: Option<i64>,
    is_text: bool,
    tag: Option<Span>,
    text: Option<Span>,
    shadow_host: bool,
    rel_stylesheet: bool,
    href: bool,
    inline_css: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum FrameKind {
    Node,
    ChildNodes,
    Attributes,
    Other,
}

/// Walks the serialized node at `span` and its descendants, reading each byte once.
fn walk_nodes(bytes: &[u8], span: Span, walk: &mut Walk) {
    let mut kinds: Vec<FrameKind> = Vec::new();
    let mut nodes: Vec<NodeFrame> = Vec::new();
    let mut key: Option<Span> = None;
    let mut started = false;
    for token in Tokens::new(bytes, span) {
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
                        finish_node(bytes, node, walk);
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
                        b"tagName" => node.tag = Some(value),
                        b"textContent" => node.text = Some(value),
                        b"isShadowHost" => node.shadow_host = &bytes[value.0..value.1] == b"true",
                        _ => {}
                    }
                }
                (Some(FrameKind::Attributes), Some(name)) => {
                    let Some(node) = nodes.last_mut() else {
                        continue;
                    };
                    match name {
                        b"rel" => {
                            node.rel_stylesheet = attribute_contains(bytes, value, "stylesheet")
                        }
                        b"href" => node.href = true,
                        b"_cssText" => node.inline_css = true,
                        _ => {}
                    }
                }
                _ => {}
            },
        }
    }
}

/// What a full snapshot's data holds.
enum Snapshot {
    /// Its compressed data does not decode.
    Undecoded,
    /// It has no node to walk.
    Empty,
    Walked(Walk),
}

/// Walks the DOM in a full snapshot's data, decoded when the event is compressed.
fn walk_snapshot(inner: &[u8], event: &Event, data: Span) -> Snapshot {
    let expansion;
    let (bytes, root) = if event.compressed && scan::is_string(inner, data) {
        // The decode the message already did, within its budget. An event it skipped is not decoded here.
        expansion = cv::expansion(inner, event);
        let Some(Some(json)) = expansion.json(data) else {
            return Snapshot::Undecoded;
        };
        let Ok(root) = scan::locate_value(json, 0) else {
            return Snapshot::Undecoded;
        };
        (json, root)
    } else {
        (inner, data)
    };
    let Some(node) = field(bytes, root, b"node") else {
        return Snapshot::Empty;
    };
    let mut walk = Walk::default();
    walk_nodes(bytes, node, &mut walk);
    Snapshot::Walked(walk)
}

fn attribute_contains(bytes: &[u8], value: Span, word: &str) -> bool {
    scan::is_string(bytes, value)
        && scan::unescape(bytes, value).is_ok_and(|v| v.to_ascii_lowercase().contains(word))
}

fn finish_node(bytes: &[u8], node: NodeFrame, walk: &mut Walk) {
    walk.nodes += 1;
    if let Some(id) = node.id {
        walk.ids.push(id);
    }
    if node.is_text {
        if let Some(text) = node.text {
            // The escaped length: close enough to count how much text a page holds, without decoding it.
            walk.text_chars += (text.1 - text.0).saturating_sub(2) as u64;
        }
    }
    walk.shadow_roots += u32::from(node.shadow_host);
    let tag = node
        .tag
        .and_then(|t| scan::unescape(bytes, t).ok())
        .map(|t| t.to_ascii_lowercase());
    match tag.as_deref() {
        Some("link") if node.inline_css => walk.inline_stylesheets += 1,
        Some("link") if node.rel_stylesheet && node.href => walk.remote_stylesheets += 1,
        Some("style") => walk.inline_stylesheets += 1,
        Some("iframe") => walk.iframes += 1,
        Some("canvas") => walk.canvases += 1,
        Some("video") => walk.videos += 1,
        _ => {}
    }
}

impl WindowDom {
    fn insert(&mut self, ids: &[i64]) {
        for &id in ids {
            if self.nodes.len() >= MAX_TRACKED_NODES {
                self.cap_reached = true;
                return;
            }
            self.nodes.insert(id);
        }
    }

    fn knows(&self, id: i64, added: &HashSet<i64>) -> bool {
        self.nodes.contains(&id) || added.contains(&id)
    }
}

impl DomInspector {
    /// Updates the window's DOM with one event and adds what it found to the block.
    pub fn observe(
        &mut self,
        inner: &[u8],
        event: &Event,
        window: &str,
        stats: &mut BlockStats,
    ) -> Observed {
        let dom = self.windows.entry(window.to_owned()).or_default();
        let mut observed = Observed::default();
        match (event.kind, event.source) {
            (Some(FULL_SNAPSHOT), _) => {
                match event
                    .data
                    .map_or(Snapshot::Empty, |data| walk_snapshot(inner, event, data))
                {
                    Snapshot::Walked(walk) => {
                        // A full snapshot replaces the window's DOM.
                        *dom = WindowDom {
                            has_snapshot: true,
                            ..WindowDom::default()
                        };
                        dom.insert(&walk.ids);
                        stats.dom_nodes = stats.dom_nodes.max(walk.nodes);
                        stats.dom_text_chars = stats.dom_text_chars.max(walk.text_chars);
                        stats.remote_stylesheets += walk.remote_stylesheets;
                        stats.inline_stylesheets += walk.inline_stylesheets;
                        stats.iframes += walk.iframes;
                        stats.canvases += walk.canvases;
                        stats.videos += walk.videos;
                        stats.shadow_roots += walk.shadow_roots;
                        observed.full_snapshot = true;
                    }
                    Snapshot::Undecoded => stats.decode_failures += 1,
                    Snapshot::Empty => {}
                }
            }
            (Some(INCREMENTAL_SNAPSHOT), Some(MUTATION))
                if dom.has_snapshot && !dom.cap_reached =>
            {
                if let Some(data) = event.data {
                    let expansion = cv::expansion(inner, event);
                    let (orphans, size, failed) = observe_mutation(inner, data, &expansion, dom);
                    stats.orphan_mutations += orphans;
                    stats.decode_failures += u32::from(failed);
                    observed.changed = size;
                }
            }
            _ => {}
        }
        if !dom.has_snapshot {
            stats.events_before_first_full_snapshot += 1;
        }
        stats.node_cap_reached |= dom.cap_reached;
        observed
    }

    /// Whether any window of the session has a full snapshot in this process.
    pub fn has_snapshot(&self) -> bool {
        self.windows.values().any(|w| w.has_snapshot)
    }
}

/// A mutation list's name and its JSON.
type List<'b> = (&'static [u8], &'b [u8]);

/// The mutation's four lists, decoded when the event is compressed, and whether the event did not decode.
fn mutation_lists<'b>(
    inner: &'b [u8],
    data: Span,
    expansion: &'b Expansion,
) -> (Vec<List<'b>>, bool) {
    if matches!(expansion, Expansion::Failed | Expansion::Skipped) {
        return (Vec::new(), true);
    }
    let mut lists = Vec::new();
    for name in [&b"adds"[..], b"removes", b"texts", b"attributes"] {
        let Some(span) = field(inner, data, name) else {
            continue;
        };
        match expansion.json(span) {
            Some(Some(json)) => lists.push((name, json)),
            // The player reads an empty string or `null` as absent.
            Some(None) => {}
            None => lists.push((name, &inner[span.0..span.1])),
        }
    }
    (lists, false)
}

/// Applies a mutation to the window's node set. Returns how many of its changes name a node that is not there, how
/// many nodes it added or removed, and whether a list did not decode.
fn observe_mutation(
    inner: &[u8],
    data: Span,
    expansion: &Expansion,
    dom: &mut WindowDom,
) -> (u32, u32, bool) {
    let (lists, failed) = mutation_lists(inner, data, expansion);
    // rrweb does not order adds parent first, so a parent added anywhere in the same mutation counts as present.
    let mut added = HashSet::new();
    let mut parents = Vec::new();
    for (name, bytes) in &lists {
        if *name != b"adds" {
            continue;
        }
        for item in items(bytes) {
            parents.extend(number(bytes, field(bytes, item, b"parentId")).map(|p| p as i64));
            if let Some(node) = field(bytes, item, b"node") {
                let mut walk = Walk::default();
                walk_nodes(bytes, node, &mut walk);
                added.extend(walk.ids);
            }
        }
    }
    let mut orphans = parents.iter().filter(|&&p| !dom.knows(p, &added)).count() as u32;
    for (name, bytes) in &lists {
        if *name == b"texts" || *name == b"attributes" {
            orphans += items(bytes)
                .filter(|&item| {
                    number(bytes, field(bytes, item, b"id"))
                        .is_some_and(|id| !dom.knows(id as i64, &added))
                })
                .count() as u32;
        }
    }
    let mut removed = 0;
    for (name, bytes) in &lists {
        if *name == b"removes" {
            for item in items(bytes) {
                if let Some(id) = number(bytes, field(bytes, item, b"id")) {
                    dom.nodes.remove(&(id as i64));
                    removed += 1;
                }
            }
        }
    }
    let size = added.len() as u32 + removed;
    dom.insert(&added.into_iter().collect::<Vec<_>>());
    (orphans, size, failed)
}

fn items(bytes: &[u8]) -> impl Iterator<Item = Span> + '_ {
    scan::locate_value(bytes, 0)
        .ok()
        .and_then(|span| scan::array_items(bytes, span).ok())
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
            DomInspector::default().observe(&message.inner, &message.events[0], "w", &mut stats);

            assert_eq!(
                (stats.dom_nodes, stats.dom_text_chars),
                (10, 5),
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
                (1, 1, 0, 1)
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

    #[test]
    fn counts_each_event_that_does_not_decode_once() {
        let message = events(json!([
            {"type": 2, "timestamp": 1, "data": page()},
            {"type": 2, "timestamp": 2, "data": "not gzip", "cv": "2024-10"},
            {"type": 3, "timestamp": 3, "data": {"source": 0, "adds": "not gzip", "removes": [], "texts": "not gzip", "attributes": []}, "cv": "2024-10"},
            {"type": 3, "timestamp": 4, "data": {"source": 0, "adds": sdk_cv(&json!([])), "removes": sdk_cv(&json!([])), "texts": sdk_cv(&json!([])), "attributes": sdk_cv(&json!([]))}, "cv": "2024-10"},
        ]));
        let mut dom = DomInspector::default();
        let mut stats = BlockStats::default();
        for event in &message.events {
            dom.observe(&message.inner, event, "w", &mut stats);
        }
        assert_eq!(stats.decode_failures, 2);

        // An event that the message's decode budget skipped is not decoded again here.
        let mut message = events(json!([
            {"type": 2, "timestamp": 1, "data": sdk_cv(&page()), "cv": "2024-10"},
        ]));
        message.decode_compressed_within(0);
        let mut dom = DomInspector::default();
        let mut stats = BlockStats::default();
        dom.observe(&message.inner, &message.events[0], "w", &mut stats);
        assert_eq!((stats.decode_failures, dom.has_snapshot()), (1, false));
    }

    #[test]
    fn stops_at_hostile_nesting_instead_of_overflowing() {
        let deep = format!("{}{}", "[".repeat(100_000), "]".repeat(100_000));
        let tokens = &mut Tokens::new(deep.as_bytes(), (0, deep.len()));
        assert_eq!(tokens.by_ref().count(), crate::scan::tokens::MAX_DEPTH);
        assert!(tokens.failed);
    }
}
