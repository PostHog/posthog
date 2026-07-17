//! Typed rrweb parse output for offline consumers (feature `typed-parse`).
//!
//! [`parse_scrubbed_event`] scrubs a JSONL line with the same routing as
//! [`crate::anonymize_line`], then hands back a typed [`Event`] — envelope, FullSnapshot DOM tree,
//! Mutation adds/removes/attributes/texts, interaction/input/scroll data — with every `cv`
//! payload (whole-event blobs and per-field Mutation compression, gzip or zstd) transparently
//! decompressed. Scrub-then-parse is one call by design: there is no way to obtain an unscrubbed
//! AST from this module.
//!
//! This is additive and offline-only. Nothing on the scrubbing hot path
//! ([`crate::anonymize_message`], [`crate::snapshot`], [`crate::bytewalk`]) references this
//! module; without the `typed-parse` feature (the Node addon build) it is not even compiled.
//!
//! Payload shapes the renderer does not fold — canvas, stylesheet, plugin, custom, unknown types
//! and sources — pass through as scrubbed generic JSON ([`EventData::Other`] /
//! [`IncrementalData::Other`]) and are *not* cv-decompressed.

use std::collections::BTreeMap;

use anyhow::{Context, Result};
use serde::{Deserialize, Deserializer, Serialize};
use simd_json::borrowed::Value;
use simd_json::StaticNode;

use crate::allow_lists::AllowLists;
use crate::context::Ctx;
use crate::event::{route_event, SOURCE_MUTATION, TYPE_FULL_SNAPSHOT, TYPE_INCREMENTAL, TYPE_META};
use crate::json::{
    as_f64, as_object_mut, as_small_uint, parse_untrusted, reject_if_too_deep, string_value,
};

/// rrweb `EventType` for the envelope's raw `type`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "u8", into = "u8")]
#[repr(u8)]
pub enum EventType {
    DomContentLoaded = 0,
    Load = 1,
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
    Custom = 5,
    Plugin = 6,
}

impl EventType {
    pub const fn from_u8(n: u8) -> Option<Self> {
        Some(match n {
            0 => Self::DomContentLoaded,
            1 => Self::Load,
            2 => Self::FullSnapshot,
            3 => Self::IncrementalSnapshot,
            4 => Self::Meta,
            5 => Self::Custom,
            6 => Self::Plugin,
            _ => return None,
        })
    }
}

/// rrweb `IncrementalSource` for an IncrementalSnapshot's raw `source`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "u8", into = "u8")]
#[repr(u8)]
pub enum IncrementalSource {
    Mutation = 0,
    MouseMove = 1,
    MouseInteraction = 2,
    Scroll = 3,
    ViewportResize = 4,
    Input = 5,
    TouchMove = 6,
    MediaInteraction = 7,
    StyleSheetRule = 8,
    CanvasMutation = 9,
    Font = 10,
    Log = 11,
    Drag = 12,
    StyleDeclaration = 13,
    Selection = 14,
    AdoptedStyleSheet = 15,
    CustomElement = 16,
}

impl IncrementalSource {
    pub const fn from_u8(n: u8) -> Option<Self> {
        Some(match n {
            0 => Self::Mutation,
            1 => Self::MouseMove,
            2 => Self::MouseInteraction,
            3 => Self::Scroll,
            4 => Self::ViewportResize,
            5 => Self::Input,
            6 => Self::TouchMove,
            7 => Self::MediaInteraction,
            8 => Self::StyleSheetRule,
            9 => Self::CanvasMutation,
            10 => Self::Font,
            11 => Self::Log,
            12 => Self::Drag,
            13 => Self::StyleDeclaration,
            14 => Self::Selection,
            15 => Self::AdoptedStyleSheet,
            16 => Self::CustomElement,
            _ => return None,
        })
    }
}

macro_rules! u8_enum_conversions {
    ($($ty:ty),+) => {$(
        impl TryFrom<u8> for $ty {
            type Error = String;
            fn try_from(n: u8) -> Result<Self, String> {
                Self::from_u8(n).ok_or_else(|| {
                    format!(concat!("invalid ", stringify!($ty), " value: {}"), n)
                })
            }
        }
        impl From<$ty> for u8 {
            fn from(v: $ty) -> u8 {
                v as u8
            }
        }
    )+};
}

/// rrweb `MouseInteractions` for a MouseInteraction's `type`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "u8", into = "u8")]
#[repr(u8)]
pub enum MouseInteractionKind {
    MouseUp = 0,
    MouseDown = 1,
    Click = 2,
    ContextMenu = 3,
    DblClick = 4,
    Focus = 5,
    Blur = 6,
    TouchStart = 7,
    TouchMoveDeparted = 8,
    TouchEnd = 9,
    TouchCancel = 10,
}

impl MouseInteractionKind {
    pub const fn from_u8(n: u8) -> Option<Self> {
        Some(match n {
            0 => Self::MouseUp,
            1 => Self::MouseDown,
            2 => Self::Click,
            3 => Self::ContextMenu,
            4 => Self::DblClick,
            5 => Self::Focus,
            6 => Self::Blur,
            7 => Self::TouchStart,
            8 => Self::TouchMoveDeparted,
            9 => Self::TouchEnd,
            10 => Self::TouchCancel,
            _ => return None,
        })
    }
}

/// rrweb `PointerTypes` for a MouseInteraction's optional `pointerType`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "u8", into = "u8")]
#[repr(u8)]
pub enum PointerType {
    Mouse = 0,
    Pen = 1,
    Touch = 2,
}

impl PointerType {
    pub const fn from_u8(n: u8) -> Option<Self> {
        Some(match n {
            0 => Self::Mouse,
            1 => Self::Pen,
            2 => Self::Touch,
            _ => return None,
        })
    }
}

u8_enum_conversions!(
    EventType,
    IncrementalSource,
    MouseInteractionKind,
    PointerType
);

/// One typed, scrubbed rrweb event. `ty` is the raw envelope `type` (it can exceed the
/// [`EventType`] range for future rrweb versions — those carry [`EventData::Other`]).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Event {
    /// From the PostHog `["window_id", event]` tuple wrapping; `None` for a bare event line.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub window_id: Option<String>,
    #[serde(rename = "type")]
    pub ty: u8,
    /// Epoch milliseconds. rrweb allows fractional timestamps; they truncate here.
    pub timestamp: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub delay: Option<i64>,
    pub data: EventData,
}

impl Event {
    pub const fn event_type(&self) -> Option<EventType> {
        EventType::from_u8(self.ty)
    }
}

/// The typed payloads the offline renderer folds; everything else passes through as scrubbed
/// generic JSON in `Other`.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(untagged)]
pub enum EventData {
    FullSnapshot(FullSnapshotData),
    Incremental(IncrementalData),
    Meta(MetaData),
    Other(serde_json::Value),
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(untagged)]
pub enum IncrementalData {
    Mutation(MutationData),
    MouseInteraction(MouseInteractionData),
    Scroll(ScrollData),
    Input(InputData),
    Other(serde_json::Value),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FullSnapshotData {
    pub node: SerializedNodeWithId,
    pub initial_offset: InitialOffset,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InitialOffset {
    pub top: f64,
    pub left: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SerializedNodeWithId {
    pub id: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub root_id: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub is_shadow_host: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub is_shadow: Option<bool>,
    #[serde(flatten)]
    pub node: SerializedNode,
}

#[derive(Debug, Clone, PartialEq)]
pub enum SerializedNode {
    Document(DocumentNode),
    DocumentType(DocumentTypeNode),
    Element(ElementNode),
    Text(TextNode),
    Cdata(CdataNode),
    Comment(CommentNode),
}

/// rrweb serialized-node `type`, used only to dispatch [`SerializedNode`]'s (de)serialization.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "u8", into = "u8")]
#[repr(u8)]
enum NodeType {
    Document = 0,
    DocumentType = 1,
    Element = 2,
    Text = 3,
    Cdata = 4,
    Comment = 5,
}

impl NodeType {
    const fn from_u8(n: u8) -> Option<Self> {
        Some(match n {
            0 => Self::Document,
            1 => Self::DocumentType,
            2 => Self::Element,
            3 => Self::Text,
            4 => Self::Cdata,
            5 => Self::Comment,
            _ => return None,
        })
    }
}

u8_enum_conversions!(NodeType);

// Avoids serde's untagged-enum trial-and-error: dispatch on `type`.
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NodeHelper {
    #[serde(rename = "type")]
    ty: NodeType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    tag_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    attributes: Option<BTreeMap<String, AttrValue>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    child_nodes: Option<Vec<SerializedNodeWithId>>,
    #[serde(rename = "isSVG", default, skip_serializing_if = "Option::is_none")]
    is_svg: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    need_block: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    is_custom: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    text_content: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    is_style: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    public_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    system_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    compat_mode: Option<String>,
}

fn empty_helper(ty: NodeType) -> NodeHelper {
    NodeHelper {
        ty,
        tag_name: None,
        attributes: None,
        child_nodes: None,
        is_svg: None,
        need_block: None,
        is_custom: None,
        text_content: None,
        is_style: None,
        name: None,
        public_id: None,
        system_id: None,
        compat_mode: None,
    }
}

impl<'de> Deserialize<'de> for SerializedNode {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let h = NodeHelper::deserialize(d)?;
        Ok(match h.ty {
            NodeType::Document => SerializedNode::Document(DocumentNode {
                child_nodes: h.child_nodes.unwrap_or_default(),
                compat_mode: h.compat_mode,
            }),
            NodeType::DocumentType => SerializedNode::DocumentType(DocumentTypeNode {
                name: h.name.unwrap_or_default(),
                public_id: h.public_id.unwrap_or_default(),
                system_id: h.system_id.unwrap_or_default(),
            }),
            NodeType::Element => SerializedNode::Element(ElementNode {
                tag_name: h.tag_name.unwrap_or_default(),
                attributes: h.attributes.unwrap_or_default(),
                child_nodes: h.child_nodes.unwrap_or_default(),
                is_svg: h.is_svg,
                need_block: h.need_block,
                is_custom: h.is_custom,
            }),
            NodeType::Text => SerializedNode::Text(TextNode {
                text_content: h.text_content.unwrap_or_default(),
                is_style: h.is_style,
            }),
            NodeType::Cdata => SerializedNode::Cdata(CdataNode {
                text_content: h.text_content,
            }),
            NodeType::Comment => SerializedNode::Comment(CommentNode {
                text_content: h.text_content.unwrap_or_default(),
            }),
        })
    }
}

impl Serialize for SerializedNode {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        let h = match self {
            SerializedNode::Document(v) => NodeHelper {
                child_nodes: Some(v.child_nodes.clone()),
                compat_mode: v.compat_mode.clone(),
                ..empty_helper(NodeType::Document)
            },
            SerializedNode::DocumentType(v) => NodeHelper {
                name: Some(v.name.clone()),
                public_id: Some(v.public_id.clone()),
                system_id: Some(v.system_id.clone()),
                ..empty_helper(NodeType::DocumentType)
            },
            SerializedNode::Element(v) => NodeHelper {
                tag_name: Some(v.tag_name.clone()),
                attributes: Some(v.attributes.clone()),
                child_nodes: Some(v.child_nodes.clone()),
                is_svg: v.is_svg,
                need_block: v.need_block,
                is_custom: v.is_custom,
                ..empty_helper(NodeType::Element)
            },
            SerializedNode::Text(v) => NodeHelper {
                text_content: Some(v.text_content.clone()),
                is_style: v.is_style,
                ..empty_helper(NodeType::Text)
            },
            SerializedNode::Cdata(v) => NodeHelper {
                text_content: v.text_content.clone(),
                ..empty_helper(NodeType::Cdata)
            },
            SerializedNode::Comment(v) => NodeHelper {
                text_content: Some(v.text_content.clone()),
                ..empty_helper(NodeType::Comment)
            },
        };
        h.serialize(s)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentNode {
    pub child_nodes: Vec<SerializedNodeWithId>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub compat_mode: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentTypeNode {
    pub name: String,
    pub public_id: String,
    pub system_id: String,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ElementNode {
    pub tag_name: String,
    pub attributes: BTreeMap<String, AttrValue>,
    pub child_nodes: Vec<SerializedNodeWithId>,
    #[serde(rename = "isSVG", skip_serializing_if = "Option::is_none")]
    pub is_svg: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub need_block: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub is_custom: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TextNode {
    pub text_content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub is_style: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CdataNode {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text_content: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CommentNode {
    pub text_content: String,
}

/// An rrweb attribute value: string, number, bool, `null`, or the structured sentinels rrweb uses
/// (e.g. the `rr_captured_*` style objects).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum AttrValue {
    Str(String),
    Num(f64),
    Bool(bool),
    Null,
    Obj(BTreeMap<String, AttrValue>),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MutationData {
    pub source: IncrementalSource, // == Mutation (0)
    #[serde(default)]
    pub texts: Vec<TextMutation>,
    #[serde(default)]
    pub attributes: Vec<AttributeMutation>,
    #[serde(default)]
    pub removes: Vec<RemovedNodeMutation>,
    #[serde(default)]
    pub adds: Vec<AddedNodeMutation>,
    #[serde(
        default,
        rename = "isAttachIframe",
        skip_serializing_if = "Option::is_none"
    )]
    pub is_attach_iframe: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TextMutation {
    pub id: i64,
    pub value: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AttributeMutation {
    pub id: i64,
    pub attributes: BTreeMap<String, AttrValue>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RemovedNodeMutation {
    pub parent_id: i64,
    pub id: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub is_shadow: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AddedNodeMutation {
    pub parent_id: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub previous_id: Option<i64>,
    pub next_id: Option<i64>,
    pub node: SerializedNodeWithId,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MouseInteractionData {
    pub source: IncrementalSource, // == MouseInteraction (2)
    #[serde(rename = "type")]
    pub kind: MouseInteractionKind,
    pub id: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub x: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub y: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pointer_type: Option<PointerType>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScrollData {
    pub source: IncrementalSource, // == Scroll (3)
    pub id: i64,
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct InputData {
    pub source: IncrementalSource, // == Input (5)
    pub id: i64,
    pub text: String,
    pub is_checked: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_triggered: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MetaData {
    pub href: String,
    pub width: u32,
    pub height: u32,
}

/// Typed, scrubbed rrweb event from one JSONL line (bare event or `["window_id", event]` tuple).
/// Offline/non-hot-path only: this parse allocates an AST.
///
/// `Ok(None)` mirrors [`crate::anonymize_line`]'s policy — JSON that parses but is not
/// recognizably an rrweb event (wrong shape, or a missing/non-numeric `type` or `timestamp`).
/// `Err` = the line could not be scrubbed or its typed payload is malformed; fail closed, the
/// caller must drop the line.
pub fn parse_scrubbed_event(allow: &AllowLists, line: &mut [u8]) -> Result<Option<Event>> {
    parse_scrubbed_event_with_ctx(&Ctx::new(allow), line)
}

/// [`parse_scrubbed_event`] with a caller-owned [`Ctx`] — same memo/budget semantics as
/// [`crate::anonymize_line_with_ctx`].
pub fn parse_scrubbed_event_with_ctx(ctx: &Ctx<'_>, line: &mut [u8]) -> Result<Option<Event>> {
    crate::unwind::contain_unwind(
        || {
            reject_if_too_deep(line, "jsonl line")?;
            let root = parse_untrusted(line).context("parse jsonl line")?;
            ctx.reset_cv_budget();
            let (window_id, mut event) = match root {
                event @ Value::Object(_) => (None, event),
                Value::Array(items) => {
                    let mut it = items.into_iter();
                    match (it.next(), it.next(), it.next()) {
                        (Some(Value::String(id)), Some(event @ Value::Object(_)), None) => {
                            (Some(id.into_owned()), event)
                        }
                        _ => return Ok(None),
                    }
                }
                _ => return Ok(None),
            };
            route_event(ctx, &mut event)?;
            build_typed(ctx, window_id, event)
        },
        |msg| anyhow::anyhow!("panic while parsing scrubbed event: {msg}"),
    )
}

fn build_typed(
    ctx: &Ctx<'_>,
    window_id: Option<String>,
    mut event: Value<'_>,
) -> Result<Option<Event>> {
    let obj = as_object_mut(&mut event).expect("caller matched an object");
    let Some(ty) = obj.get("type").and_then(as_small_uint) else {
        return Ok(None);
    };
    let Some(timestamp) = obj.get("timestamp").and_then(as_f64) else {
        return Ok(None);
    };
    let delay = obj.get("delay").and_then(as_f64).map(|d| d as i64);
    let compressed = crate::event::is_compressed_marker(obj.get("cv"));
    let mut data = obj
        .remove("data")
        .unwrap_or(Value::Static(StaticNode::Null));

    let source = crate::json::as_object(&data)
        .and_then(|d| d.get("source"))
        .and_then(as_small_uint);

    if compressed {
        decompress_cv_fields(ctx, ty, source, &mut data)?;
    }

    let typed = match ty {
        TYPE_FULL_SNAPSHOT if crate::json::is_object(&data) => {
            EventData::FullSnapshot(from_value(data).context("typed FullSnapshot data")?)
        }
        TYPE_INCREMENTAL => EventData::Incremental(match source.map(IncrementalSource::from_u8) {
            Some(Some(IncrementalSource::Mutation)) => {
                IncrementalData::Mutation(from_value(data).context("typed Mutation data")?)
            }
            Some(Some(IncrementalSource::MouseInteraction)) => IncrementalData::MouseInteraction(
                from_value(data).context("typed MouseInteraction data")?,
            ),
            Some(Some(IncrementalSource::Scroll)) => {
                IncrementalData::Scroll(from_value(data).context("typed Scroll data")?)
            }
            Some(Some(IncrementalSource::Input)) => {
                IncrementalData::Input(from_value(data).context("typed Input data")?)
            }
            _ => IncrementalData::Other(from_value(data).context("generic incremental data")?),
        }),
        TYPE_META if crate::json::is_object(&data) => {
            EventData::Meta(from_value(data).context("typed Meta data")?)
        }
        _ => EventData::Other(from_value(data).context("generic event data")?),
    };

    Ok(Some(Event {
        window_id,
        ty,
        timestamp: timestamp as i64,
        delay,
        data: typed,
    }))
}

/// Replace compressed `cv` payloads inside `data` with their decoded JSON, so the typed output is
/// transparently decompressed: the whole-blob FullSnapshot string, and each present Mutation
/// sub-field string (`texts`/`attributes`/`removes`/`adds` — `removes` is never re-emitted by the
/// scrub, so it can still be gzip while its siblings are zstd; the magic sniff handles both).
fn decompress_cv_fields(
    ctx: &Ctx<'_>,
    ty: u8,
    source: Option<u8>,
    data: &mut Value<'_>,
) -> Result<()> {
    match (ty, source, &mut *data) {
        (TYPE_FULL_SNAPSHOT, _, Value::String(s)) => {
            *data = decode_cv_string(ctx, s).context("decompress cv FullSnapshot data")?;
        }
        (TYPE_INCREMENTAL, Some(SOURCE_MUTATION), Value::Object(obj)) => {
            for sub_key in ["texts", "attributes", "removes", "adds"] {
                let Some(Value::String(s)) = obj.get(sub_key) else {
                    continue;
                };
                if s.is_empty() {
                    obj.insert(
                        crate::json::key(sub_key),
                        Value::Array(Box::new(Vec::new())),
                    );
                    continue;
                }
                let decoded = decode_cv_string(ctx, s)
                    .with_context(|| format!("decompress cv mutation sub-field `{sub_key}`"))?;
                obj.insert(crate::json::key(sub_key), decoded);
            }
        }
        _ => {}
    }
    Ok(())
}

fn decode_cv_string(ctx: &Ctx<'_>, s: &str) -> Result<Value<'static>> {
    let raw = crate::cv::latin1_to_bytes(s)?;
    let mut decompressed = ctx.decompress_cv(&raw)?;
    reject_if_too_deep(&decompressed, "cv payload")?;
    // Round-trip through owned JSON: the decompressed scratch buffer dies at return, so the
    // borrowed parse cannot escape this function.
    let parsed = parse_untrusted(&mut decompressed).context("parse cv payload")?;
    Ok(string_to_owned_value(parsed))
}

/// Rebuild a borrowed simd-json value as `'static` (owning every string).
fn string_to_owned_value(v: Value<'_>) -> Value<'static> {
    match v {
        Value::Static(s) => Value::Static(s),
        Value::String(s) => string_value(s.into_owned()),
        Value::Array(items) => Value::Array(Box::new(
            items.into_iter().map(string_to_owned_value).collect(),
        )),
        Value::Object(obj) => {
            let mut out = simd_json::borrowed::Object::with_capacity(obj.len());
            for (k, val) in obj.into_iter() {
                out.insert(
                    std::borrow::Cow::Owned(k.into_owned()),
                    string_to_owned_value(val),
                );
            }
            Value::Object(Box::new(out))
        }
    }
}

fn from_value<T: serde::de::DeserializeOwned>(value: Value<'_>) -> Result<T> {
    simd_json::serde::from_borrowed_value(value).map_err(anyhow::Error::from)
}
