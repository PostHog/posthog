use std::{
    borrow::Cow,
    collections::HashMap,
    ops::Range,
    sync::{Arc, Mutex, OnceLock},
};

use gpui::{
    AnyElement, App, Axis, Bounds, DefiniteLength, Div, Element, ElementId, FontStyle, FontWeight,
    GlobalElementId, HighlightStyle, Hsla, Image, ImageFormat, ImageSource, InspectorElementId,
    InteractiveElement as _, IntoElement, IsZero as _, LayoutId, ObjectFit, Overflow,
    ParentElement, Pixels, Point, Refineable as _, Rems, ScrollHandle, SharedString, SharedUri,
    StatefulInteractiveElement, StyleRefinement, Styled, StyledImage as _, TextStyleRefinement,
    WhiteSpace, Window, div, img, prelude::FluentBuilder as _, px, relative, rems,
};
use markdown::mdast;

use crate::{
    GlobalState, ScrollableMask, Scrollbar, StyledExt, h_flex,
    scrollable_mask::horizontal_scroll_area,
    text::{
        CodeBlockActionsFn, CodeBlockHighlighterFn, LinkClickHandlerFn, MarkdownExtensions,
        MarkdownNode, TableActionsFn,
        document::{NodeRenderOptions, PrevBlock, flow_position},
        inline::{
            Inline, InlineHighlight, InlineState, code_insets, combine_highlights, fade_highlights,
            point_in_text_selection, text_runs, text_size_ranges,
        },
        inline_flow::{InlineFlow, InlineFlowItem, slice_ranges},
        range_highlight::{RangeHighlightFrame, RevealAt, RevealRequest},
        stream_fade::{StreamFadeFrame, TextLeafKey},
        text_view::handle_link_click,
    },
    theme::ActiveTheme as _,
};

use super::{
    SelectionFormat, TextViewStyle,
    utils::{data_url_image, list_item_prefix, ordered_list_ordinal},
};

const CHECK_SVG_LIGHT: &[u8] = br#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none"><path d="m3.25 8.25 3 3 6.5-7" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>"#;
const CHECK_SVG_DARK: &[u8] = br#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none"><path d="m3.25 8.25 3 3 6.5-7" stroke="black" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>"#;

/// The block-level nodes.
///
/// This is the document tree TextView renders. Together with
/// [`editor_host`](super::editor_host) it is also the hand-over type for
/// external editors: they build the tree, render it with
/// [`BlockNode::render`] and read geometry back per leaf.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub enum BlockNode {
    /// Something like a Div container in HTML.
    Root {
        children: Vec<BlockNode>,
        span: Option<Span>,
    },
    Paragraph(Paragraph),
    Heading {
        level: u8,
        children: Paragraph,
        span: Option<Span>,
    },
    Blockquote {
        children: Vec<BlockNode>,
        span: Option<Span>,
    },
    List {
        /// Only contains ListItem, others will be ignored
        children: Vec<BlockNode>,
        ordered: bool,
        /// The first ordinal for an ordered list. HTML lists leave this unset.
        start: Option<u32>,
        span: Option<Span>,
    },
    ListItem {
        children: Vec<BlockNode>,
        spread: bool,
        /// Whether the list item is checked, if None, it's not a checkbox
        checked: Option<bool>,
        span: Option<Span>,
    },
    CodeBlock(CodeBlock),
    /// A custom Markdown node produced by [`MarkdownExtensions`].
    Custom {
        node: MarkdownNode,
        state: BlockState,
    },
    Table(Table),
    Break {
        html: bool,
        span: Option<Span>,
    },
    HorizontalRule {
        span: Option<Span>,
    },
    /// Use for to_markdown get raw definition
    Definition {
        identifier: SharedString,
        url: SharedString,
        title: Option<SharedString>,
        span: Option<Span>,
    },
    Unknown,
}

/// Retained block interaction state, shared with its rendered element.
///
/// Opaque: build one with `BlockState::default()` for a
/// [`BlockNode::Custom`].
#[derive(Debug, Clone, Default)]
pub struct BlockState {
    // None is unobserved, allowing virtualized copy to include enclosed blocks.
    selection: Arc<Mutex<Option<BlockSelection>>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BlockSelection {
    Empty,
    Full,
}

impl BlockState {
    fn selection(&self) -> Option<BlockSelection> {
        self.selection.lock().ok().and_then(|selection| *selection)
    }

    fn set_selection(&self, value: Option<BlockSelection>) {
        if let Ok(mut selection) = self.selection.lock() {
            *selection = value;
        }
    }

    fn is_selected(&self) -> bool {
        self.selection() == Some(BlockSelection::Full)
    }

    fn has_selection_observation(&self) -> bool {
        self.selection().is_some()
    }

    fn clear_selection(&self) {
        self.set_selection(None);
    }
}

impl PartialEq for BlockState {
    fn eq(&self, _: &Self) -> bool {
        // Runtime selection does not change parsed document identity.
        true
    }
}

pub(super) struct CustomBlockSelectionProjection {
    state: BlockState,
    bounds: Bounds<Pixels>,
}

impl CustomBlockSelectionProjection {
    pub(super) fn project(&self, start: Point<Pixels>, end: Point<Pixels>) {
        self.state
            .set_selection(custom_block_selection(self.bounds, start, end));
    }

    pub(super) fn deselect(&self) {
        self.state.set_selection(None);
    }
}

fn custom_block_selection(
    bounds: Bounds<Pixels>,
    start: Point<Pixels>,
    end: Point<Pixels>,
) -> Option<BlockSelection> {
    if bounds.size.width <= Pixels::ZERO
        || bounds.size.height <= Pixels::ZERO
        || bounds.bottom() <= start.y.min(end.y)
        || bounds.top() > start.y.max(end.y)
    {
        return None;
    }
    Some(if custom_block_is_selected(bounds, start, end) {
        BlockSelection::Full
    } else {
        BlockSelection::Empty
    })
}

/// A table cell, laid out as its content. Text painted inside it knows its
/// cell, so a drag that starts in the cell selects only in that cell.
struct TableCellElement(AnyElement);

impl IntoElement for TableCellElement {
    type Element = Self;

    fn into_element(self) -> Self {
        self
    }
}

impl Element for TableCellElement {
    type RequestLayoutState = ();
    type PrepaintState = ();

    fn id(&self) -> Option<ElementId> {
        None
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, ()) {
        (self.0.request_layout(window, cx), ())
    }

    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) {
        // Prepaint runs for the whole window before any text paints, so the
        // cell that holds the anchor is known to all text, in every view.
        if let Some(view) = GlobalState::global(cx).text_view_state() {
            view.read(cx)
                .selection_adapter
                .record_table_cell(bounds, cx);
        }
        GlobalState::global(cx).push_table_cell(bounds);
        self.0.prepaint(window, cx);
        GlobalState::global(cx).pop_table_cell();
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut (),
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) {
        GlobalState::global(cx).push_table_cell(bounds);
        self.0.paint(window, cx);
        GlobalState::global(cx).pop_table_cell();
    }
}

/// Observe the plugin's own bounds without changing its layout or listeners.
struct CustomBlockElement {
    content: AnyElement,
    state: BlockState,
}

impl IntoElement for CustomBlockElement {
    type Element = Self;

    fn into_element(self) -> Self {
        self
    }
}

impl Element for CustomBlockElement {
    type RequestLayoutState = ();
    type PrepaintState = ();

    fn id(&self) -> Option<ElementId> {
        None
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, ()) {
        (self.content.request_layout(window, cx), ())
    }

    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) {
        self.content.prepaint(window, cx);
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut (),
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) {
        let view = GlobalState::global(cx).text_view_state();
        let selection = view.as_ref().and_then(|view| {
            let state = view.read(cx);
            if !state.is_selectable() {
                return None;
            }
            if state.is_all_selected() {
                return Some(BlockSelection::Full);
            }
            if state.preserve_inline_selection {
                return self.state.selection();
            }
            let (start, end) = state.painted_selection_points(cx)?;
            custom_block_selection(bounds, start, end)
        });
        self.state.set_selection(selection);
        if let Some(view) = &view {
            if view.read(cx).is_selectable() {
                view.read(cx).selection_adapter.register_copy_projection(
                    super::selection_adapter::CopyProjection::CustomBlock(
                        CustomBlockSelectionProjection {
                            state: self.state.clone(),
                            bounds,
                        },
                    ),
                    cx,
                );
            }
            let visible = bounds.intersect(&window.content_mask().bounds);
            if view.read(cx).is_selectable()
                && visible.size.width > Pixels::ZERO
                && visible.size.height > Pixels::ZERO
            {
                view.read(cx)
                    .selection_adapter
                    .register_inline(vec![visible]);
            }
        }
        self.content.paint(window, cx);
        if selection == Some(BlockSelection::Full) {
            let color = view.as_ref().unwrap().read(cx).text_view_style.selection();
            window.paint_quad(gpui::fill(bounds, color));
        }
    }
}

/// A block is atomic: the selection takes it whole once it crosses the block's
/// edge, and never from a gesture that stays inside it. A press and release
/// within one block is a click on its content — often an interactive card —
/// and the pointer commonly travels a few pixels during a quick click, so
/// counting that travel as a drag would paint the whole block as selected.
fn custom_block_is_selected(
    bounds: Bounds<Pixels>,
    start: Point<Pixels>,
    end: Point<Pixels>,
) -> bool {
    let (start_inside, end_inside) = (bounds.contains(&start), bounds.contains(&end));
    start != end
        && !(start_inside && end_inside)
        && (start_inside
            || end_inside
            || point_in_text_selection(
                bounds.origin,
                bounds.size.width,
                start,
                end,
                bounds.size.height,
            ))
}

/// How many styles a selection takes in, which decides whether
/// [`SelectionFormat::SourceAcrossStyles`] copies the rendered text or the
/// source.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum SelectionStyles {
    None,
    One,
    Mixed,
}

impl SelectionStyles {
    /// Combine two separately selected parts. They are two styles even when
    /// their marks match, because they sit in different blocks or cells.
    fn merge(&mut self, other: Self) {
        *self = match (*self, other) {
            (Self::None, other) | (other, Self::None) => other,
            _ => Self::Mixed,
        };
    }
}

#[derive(Clone, Copy)]
enum BlockTextKind {
    All,
    Selected,
    /// Like `Selected`, but reconstructs Markdown source for the selection
    /// instead of the rendered plain text.
    SelectedSource,
}

impl BlockNode {
    pub(super) fn is_list_item(&self) -> bool {
        matches!(self, Self::ListItem { .. })
    }

    /// Combine all children, omitting the empt parent nodes.
    pub(super) fn compact(self) -> BlockNode {
        match self {
            Self::Root { mut children, .. } if children.len() == 1 => children.remove(0).compact(),
            _ => self,
        }
    }

    /// Get the span of the node.
    pub fn span(&self) -> Option<Span> {
        match self {
            BlockNode::Root { span, .. } => *span,
            BlockNode::Paragraph(paragraph) => paragraph.span,
            BlockNode::Heading { span, .. } => *span,
            BlockNode::Blockquote { span, .. } => *span,
            BlockNode::List { span, .. } => *span,
            BlockNode::ListItem { span, .. } => *span,
            BlockNode::CodeBlock(code_block) => code_block.span,
            BlockNode::Custom { node, .. } => node.span,
            BlockNode::Table(table) => table.span,
            BlockNode::Break { span, .. } => *span,
            BlockNode::HorizontalRule { span, .. } => *span,
            BlockNode::Definition { span, .. } => *span,
            BlockNode::Unknown { .. } => None,
        }
    }

    pub(super) fn text(&self) -> String {
        self.text_by_kind(BlockTextKind::All)
    }

    /// The selected text within this block, in `format`.
    ///
    /// [`SelectionFormat::Source`] reconstructs the Markdown source of the
    /// selection instead of the rendered text.
    pub(super) fn selected_text(&self, format: SelectionFormat) -> String {
        self.text_by_kind(match format {
            SelectionFormat::Plain => BlockTextKind::Selected,
            SelectionFormat::Source | SelectionFormat::SourceAcrossStyles => {
                BlockTextKind::SelectedSource
            }
        })
    }

    /// How many styles the selection within this block takes in.
    pub(super) fn selection_styles(&self) -> SelectionStyles {
        let mut styles = SelectionStyles::None;
        match self {
            BlockNode::Root { children, .. }
            | BlockNode::Blockquote { children, .. }
            | BlockNode::List { children, .. }
            | BlockNode::ListItem { children, .. } => {
                for child in children {
                    styles.merge(child.selection_styles());
                }
            }
            BlockNode::Paragraph(paragraph) => styles = paragraph.selection_styles(),
            BlockNode::Heading { children, .. } => styles = children.selection_styles(),
            BlockNode::Table(table) => {
                for row in &table.children {
                    for cell in &row.children {
                        styles.merge(cell.children.selection_styles());
                    }
                }
            }
            BlockNode::CodeBlock(code_block) => {
                if code_block.has_selection() {
                    styles = SelectionStyles::One;
                }
            }
            // A plugin's text stands in for content its source spells out.
            BlockNode::Custom { state, .. } => {
                if state.is_selected() {
                    styles = SelectionStyles::Mixed;
                }
            }
            BlockNode::Definition { .. }
            | BlockNode::Break { .. }
            | BlockNode::HorizontalRule { .. }
            | BlockNode::Unknown => {}
        }
        styles
    }

    pub(super) fn selected_source_range(&self) -> SourceRangeSelection {
        let mut selected = SourceRangeSelection::Unselected;
        match self {
            BlockNode::Root { children, .. }
            | BlockNode::Blockquote { children, .. }
            | BlockNode::List { children, .. }
            | BlockNode::ListItem { children, .. } => {
                for child in children {
                    selected.merge(child.selected_source_range());
                }
            }
            BlockNode::Paragraph(paragraph) => selected = paragraph.selected_source_range(),
            BlockNode::Heading { children, .. } => selected = children.selected_source_range(),
            BlockNode::Table(table) => {
                for row in &table.children {
                    for cell in &row.children {
                        selected.merge(cell.children.selected_source_range());
                    }
                }
            }
            BlockNode::CodeBlock(code_block) => selected = code_block.selected_source_range(),
            BlockNode::Custom { node, state } => {
                if state.is_selected() {
                    selected = node
                        .source_range()
                        .map_or(SourceRangeSelection::Unmapped, SourceRangeSelection::Mapped);
                }
            }
            BlockNode::Definition { .. }
            | BlockNode::Break { .. }
            | BlockNode::HorizontalRule { .. }
            | BlockNode::Unknown => {}
        }
        selected
    }

    fn text_by_kind(&self, kind: BlockTextKind) -> String {
        let mut text = String::new();
        match self {
            BlockNode::Root { children, .. } => {
                let block_text = Self::children_text(children, kind);
                if !block_text.is_empty() {
                    text.push_str(&block_text);
                    text.push('\n');
                }
            }
            BlockNode::Paragraph(paragraph) => {
                let block_text = match kind {
                    BlockTextKind::All => paragraph.text(),
                    BlockTextKind::Selected => paragraph.selected_text(),
                    BlockTextKind::SelectedSource => paragraph.selected_source(),
                };
                if !block_text.is_empty() {
                    text.push_str(&block_text);
                    text.push('\n');
                }
            }
            BlockNode::Heading {
                level, children, ..
            } => {
                let block_text = match kind {
                    BlockTextKind::All => children.text(),
                    BlockTextKind::Selected => children.selected_text(),
                    BlockTextKind::SelectedSource => children.selected_source(),
                };
                if !block_text.is_empty() {
                    // In source mode, prefix the heading marker so a selected
                    // heading round-trips as Markdown (e.g. `## Title`).
                    if matches!(kind, BlockTextKind::SelectedSource) {
                        text.push_str(&"#".repeat(*level as usize));
                        text.push(' ');
                    }
                    text.push_str(&block_text);
                    text.push('\n');
                }
            }
            BlockNode::List {
                children,
                ordered,
                start,
                ..
            } => {
                if matches!(kind, BlockTextKind::SelectedSource) {
                    // Reconstruct the list source, indenting nested lists and
                    // restoring list markers and task-list checkboxes.
                    text.push_str(&list_selected_source(children, *ordered, *start, ""));
                } else {
                    text.push_str(&Self::children_text(children, kind));
                }
            }
            BlockNode::ListItem { children, .. } => {
                text.push_str(&Self::children_text(children, kind));
            }
            BlockNode::Blockquote { children, .. } => {
                let block_text = Self::children_text(children, kind);

                if !block_text.is_empty() {
                    if matches!(kind, BlockTextKind::SelectedSource) {
                        // Prefix every line with `> ` so a selected blockquote
                        // round-trips as Markdown.
                        let quoted = block_text
                            .trim_end_matches('\n')
                            .lines()
                            .map(|line| {
                                if line.is_empty() {
                                    ">".to_string()
                                } else {
                                    format!("> {}", line)
                                }
                            })
                            .collect::<Vec<_>>()
                            .join("\n");
                        text.push_str(&quoted);
                    } else {
                        text.push_str(&block_text);
                    }
                    text.push('\n');
                }
            }
            BlockNode::Table(table) => {
                if matches!(kind, BlockTextKind::SelectedSource) {
                    let block_text = table_selected_source(table);
                    if !block_text.is_empty() {
                        text.push_str(&block_text);
                        text.push('\n');
                    }
                } else {
                    let mut block_text = String::new();
                    for row in table.children.iter() {
                        let mut row_texts = vec![];
                        for cell in row.children.iter() {
                            match kind {
                                BlockTextKind::All => row_texts.push(cell.children.text()),
                                // Source is handled above; only Selected reaches
                                // here. A cell with nothing selected adds nothing,
                                // so a selection in one cell copies only its text.
                                _ => {
                                    let selected = cell.children.selected_text();
                                    if !selected.is_empty() {
                                        row_texts.push(selected);
                                    }
                                }
                            }
                        }
                        if !row_texts.is_empty() {
                            block_text.push_str(&row_texts.join(" "));
                            block_text.push('\n');
                        }
                    }

                    if !block_text.is_empty() {
                        text.push_str(&block_text);
                        text.push('\n');
                    }
                }
            }
            BlockNode::CodeBlock(code_block) => {
                let block_text = match kind {
                    BlockTextKind::All => code_block.text(),
                    BlockTextKind::Selected => code_block.selected_text(),
                    BlockTextKind::SelectedSource => code_block.selected_source(),
                };
                if !block_text.is_empty() {
                    text.push_str(&block_text);
                    text.push('\n');
                }
            }
            BlockNode::Custom { node, state } => {
                if matches!(kind, BlockTextKind::All) || state.is_selected() {
                    let content = match kind {
                        BlockTextKind::SelectedSource => Cow::Owned(node.to_markdown()),
                        _ => Cow::Borrowed(node.as_text()),
                    };
                    if !content.is_empty() {
                        text.push_str(&content);
                        text.push('\n');
                    }
                }
            }
            BlockNode::Definition { .. }
            | BlockNode::Break { .. }
            | BlockNode::HorizontalRule { .. }
            | BlockNode::Unknown { .. } => {}
        }

        text
    }

    fn children_text(children: &[BlockNode], kind: BlockTextKind) -> String {
        let mut text = String::new();
        for child in children.iter() {
            text.push_str(&child.text_by_kind(kind));
        }

        text
    }

    /// Synchronously clear the selection stored in every inline state.
    ///
    /// Mirrors the [`selected_text`](Self::selected_text) traversal so the
    /// selection can be cleared without relying on a repaint.
    /// Whether this block carries a selection, even an empty one.
    ///
    /// A block only learns its selection when it is painted, so this doubles as
    /// "this block was on screen while the selection was made". An empty
    /// selection is the caret left by the press that started the drag, which is
    /// why it counts (see [`ParsedDocument::selected_text`]).
    pub(super) fn has_selection(&self) -> bool {
        match self {
            BlockNode::Root { children, .. }
            | BlockNode::Blockquote { children, .. }
            | BlockNode::List { children, .. }
            | BlockNode::ListItem { children, .. } => {
                children.iter().any(|child| child.has_selection())
            }
            BlockNode::Paragraph(paragraph) => paragraph.has_selection(),
            BlockNode::Heading { children, .. } => children.has_selection(),
            BlockNode::Table(table) => table.children.iter().any(|row| {
                row.children
                    .iter()
                    .any(|cell| cell.children.has_selection())
            }),
            BlockNode::CodeBlock(code_block) => code_block.has_selection(),
            BlockNode::Custom { state, .. } => {
                // An observed empty endpoint must suppress virtualized copy fallback.
                state.has_selection_observation()
            }
            BlockNode::Definition { .. }
            | BlockNode::Break { .. }
            | BlockNode::HorizontalRule { .. }
            | BlockNode::Unknown { .. } => false,
        }
    }

    pub(super) fn clear_selection(&self) {
        match self {
            BlockNode::Root { children, .. }
            | BlockNode::Blockquote { children, .. }
            | BlockNode::List { children, .. }
            | BlockNode::ListItem { children, .. } => {
                for child in children.iter() {
                    child.clear_selection();
                }
            }
            BlockNode::Paragraph(paragraph) => paragraph.clear_selection(),
            BlockNode::Heading { children, .. } => children.clear_selection(),
            BlockNode::Table(table) => {
                for row in table.children.iter() {
                    for cell in row.children.iter() {
                        cell.children.clear_selection();
                    }
                }
            }
            BlockNode::CodeBlock(code_block) => code_block.clear_selection(),
            BlockNode::Custom { state, .. } => {
                state.clear_selection();
            }
            BlockNode::Definition { .. }
            | BlockNode::Break { .. }
            | BlockNode::HorizontalRule { .. }
            | BlockNode::Unknown { .. } => {}
        }
    }
}

#[allow(unused)]
#[derive(Debug, Default, Clone, PartialEq)]
pub struct LinkMark {
    pub url: SharedString,
    /// Optional identifier for footnotes.
    pub identifier: Option<SharedString>,
    pub title: Option<SharedString>,
}

#[derive(Debug, Default, Clone, PartialEq)]
pub struct TextMark {
    pub bold: bool,
    pub italic: bool,
    pub strikethrough: bool,
    pub underline: bool,
    pub code: bool,
    /// Highlight (`<mark>`) the text with this background color.
    ///
    /// `None` means the text is not highlighted.
    pub highlight: Option<Hsla>,
    pub link: Option<LinkMark>,
}

impl TextMark {
    pub fn bold(mut self) -> Self {
        self.bold = true;
        self
    }

    pub fn italic(mut self) -> Self {
        self.italic = true;
        self
    }

    pub fn strikethrough(mut self) -> Self {
        self.strikethrough = true;
        self
    }

    pub fn underline(mut self) -> Self {
        self.underline = true;
        self
    }

    pub fn code(mut self) -> Self {
        self.code = true;
        self
    }

    /// Mark the text as highlighted (`<mark>`) with the given background color.
    pub fn highlight(mut self, color: Hsla) -> Self {
        self.highlight = Some(color);
        self
    }

    pub fn link(mut self, link: impl Into<LinkMark>) -> Self {
        self.link = Some(link.into());
        self
    }

    pub fn merge(&mut self, other: TextMark) {
        self.bold |= other.bold;
        self.italic |= other.italic;
        self.strikethrough |= other.strikethrough;
        self.underline |= other.underline;
        self.code |= other.code;
        if other.highlight.is_some() {
            self.highlight = other.highlight;
        }
        if let Some(link) = other.link {
            self.link = Some(link);
        }
    }
}

/// The bytes
#[derive(Debug, Default, Copy, Clone, PartialEq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
}

#[allow(unused)]
#[derive(Default, Clone)]
pub struct ImageNode {
    pub url: SharedUri,
    pub link: Option<LinkMark>,
    pub title: Option<SharedString>,
    pub alt: Option<SharedString>,
    pub width: Option<DefiniteLength>,
    pub height: Option<DefiniteLength>,
    pub(crate) span: Option<Span>,
    /// The image a `data:` URL carries, decoded on first render and kept for
    /// the node's lifetime so it is not decoded again every frame.
    pub(super) embedded: OnceLock<Option<Arc<Image>>>,
}

impl ImageNode {
    pub fn title(&self) -> String {
        self.title
            .clone()
            .unwrap_or_else(|| self.alt.clone().unwrap_or_default())
            .to_string()
    }

    /// The [`ImageSource`] to render, without granting implicit filesystem
    /// access.
    ///
    /// A `data:` URL carries its image inline, so it is decoded here rather
    /// than handed to GPUI's resource loader, which only fetches over HTTP.
    /// Every other document-provided value remains URI-backed, including
    /// `file://` and scheme-less strings.
    pub(super) fn source(&self) -> ImageSource {
        match self.embedded.get_or_init(|| data_url_image(&self.url)) {
            Some(image) => ImageSource::Image(image.clone()),
            None => self.url.clone().into(),
        }
    }
}

impl std::fmt::Debug for ImageNode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ImageNode")
            .field("url", &self.url)
            .field("link", &self.link)
            .field("title", &self.title)
            .field("alt", &self.alt)
            .field("width", &self.width)
            .field("height", &self.height)
            .field("span", &self.span)
            .finish()
    }
}

impl PartialEq for ImageNode {
    fn eq(&self, other: &Self) -> bool {
        self.url == other.url
            && self.link == other.link
            && self.title == other.title
            && self.alt == other.alt
            && self.width == other.width
            && self.height == other.height
            && self.span == other.span
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct SourceSegment {
    pub(crate) rendered: Range<usize>,
    pub(crate) source: Range<usize>,
    /// Whether each rendered character came from a source character of the
    /// same length, so that part of the segment maps to part of its source.
    /// A decoded entity or an escape maps only as a whole, even an entity
    /// whose characters take as many bytes as its source, like `&acE;`.
    pub(crate) linear: bool,
}

pub(crate) enum SourceRangeSelection {
    Unselected,
    Mapped(Range<usize>),
    Unmapped,
}

impl SourceRangeSelection {
    pub(crate) fn merge(&mut self, other: Self) {
        match (&mut *self, other) {
            (_, Self::Unselected) => {}
            (_, Self::Unmapped) => *self = Self::Unmapped,
            (Self::Unselected, mapped @ Self::Mapped(_)) => *self = mapped,
            (Self::Mapped(selected), Self::Mapped(range)) => {
                selected.start = selected.start.min(range.start);
                selected.end = selected.end.max(range.end);
            }
            (Self::Unmapped, Self::Mapped(_)) => {}
        }
    }

    pub(crate) fn into_range(self) -> Option<Range<usize>> {
        match self {
            Self::Mapped(range) => Some(range),
            Self::Unselected | Self::Unmapped => None,
        }
    }
}

fn source_range_for_segments(
    segments: &[SourceSegment],
    selection: Range<usize>,
) -> Option<Range<usize>> {
    fn mapped_source_start(segment: &SourceSegment, rendered_start: usize) -> usize {
        if segment.linear {
            segment.source.start + rendered_start.saturating_sub(segment.rendered.start)
        } else {
            segment.source.start
        }
    }

    fn mapped_source_end(segment: &SourceSegment, rendered_end: usize) -> usize {
        if segment.linear {
            segment.source.start
                + rendered_end
                    .min(segment.rendered.end)
                    .saturating_sub(segment.rendered.start)
        } else {
            segment.source.end
        }
    }

    if selection.start >= selection.end {
        return None;
    }

    let mut overlapping = segments.iter().filter(|segment| {
        segment.rendered.start < selection.end && segment.rendered.end > selection.start
    });
    let first = overlapping.next()?;
    if first.rendered.start > selection.start {
        return None;
    }
    let mut rendered_end = first.rendered.end;
    let source_start = mapped_source_start(first, selection.start);
    let mut source_end = mapped_source_end(first, selection.end);
    for segment in overlapping {
        if segment.rendered.start > rendered_end {
            return None;
        }
        rendered_end = rendered_end.max(segment.rendered.end);
        source_end = mapped_source_end(segment, selection.end);
    }
    (rendered_end >= selection.end).then_some(source_start..source_end)
}

/// One run of inline content in a [`Paragraph`]: marked text, an image or a
/// custom inline node.
#[derive(Default, Clone, Debug)]
pub struct InlineNode {
    /// The text content.
    pub(crate) text: SharedString,
    pub(crate) image: Option<ImageNode>,
    pub(crate) custom: Option<MarkdownNode>,
    custom_selection: Arc<Mutex<bool>>,
    /// The text styles, each tuple contains the range of the text and the style.
    pub(crate) marks: Vec<(Range<usize>, TextMark)>,
    /// Rendered UTF-8 byte spans paired with their exact Markdown source spans.
    pub(crate) source_segments: Vec<SourceSegment>,

    pub(super) state: Arc<Mutex<InlineState>>,
}

impl PartialEq for InlineNode {
    fn eq(&self, other: &Self) -> bool {
        self.text == other.text
            && self.image == other.image
            && self.custom == other.custom
            && self.marks == other.marks
            && self.source_segments == other.source_segments
    }
}

fn set_leaf_key(state: &mut Arc<Mutex<InlineState>>, key: u64) {
    let text = state
        .lock()
        .map(|state| state.text.clone())
        .unwrap_or_default();
    // Rekeying creates a new rendered identity. Do not mutate the state of
    // another AST clone (or carry its transient selection into this instance).
    *state = Arc::new(Mutex::new(InlineState {
        text,
        editor_key: Some(key),
        cleanup_senders: Vec::new(),
        ..Default::default()
    }));
}

/// Wrap `text` with the Markdown syntax implied by `mark`.
///
/// This mirrors the per-mark formatting in [`Paragraph::to_markdown`] but
/// operates on an already-sliced run, so it can reconstruct the Markdown
/// source for a *partial* text selection. Applied inside-out (innermost markup
/// first) so nested emphasis like `**_x_**` round-trips.
pub(crate) fn wrap_with_mark(text: &str, mark: &TextMark) -> String {
    if text.is_empty() {
        return String::new();
    }

    let mut out = text.to_string();
    if mark.code {
        out = format!("`{}`", out);
    }
    if mark.italic {
        out = format!("*{}*", out);
    }
    if mark.bold {
        out = format!("**{}**", out);
    }
    if mark.strikethrough {
        out = format!("~~{}~~", out);
    }
    if mark.underline {
        // Markdown has no underline syntax, and `__` reads as bold to most
        // parsers, so fall back to the inline HTML `<u>` parses from.
        out = format!("<u>{}</u>", out);
    }
    if mark.highlight.is_some() {
        out = format!("=={}==", out);
    }
    if let Some(link) = &mark.link {
        out = match &link.title {
            Some(title) => format!("[{}]({} \"{}\")", out, link.url, title),
            None => format!("[{}]({})", out, link.url),
        };
    }
    out
}

/// Keep syntax and marks separate until all selected runs and atomic objects
/// have been collected. Wrapping every run independently creates adjacent `*`
/// delimiters that can turn italic formulas into bold ones when pasted.
#[derive(Default)]
struct MarkdownSource {
    pieces: Vec<(String, Vec<TextMark>)>,
    /// Whether an inline object or image was emitted, whose rendered text
    /// stands in for source that spells out more.
    has_objects: bool,
}

impl MarkdownSource {
    fn push_str(&mut self, source: &str) {
        self.push_marked(source, &TextMark::default());
    }

    fn push_marked(&mut self, source: &str, mark: &TextMark) {
        if source.is_empty() {
            return;
        }
        // Outer-to-inner order for equally extensive marks. When a mark spans
        // more neighboring pieces, serialize it outside the shorter marks.
        let mut layers = Vec::new();
        if let Some(link) = &mark.link {
            layers.push(TextMark {
                link: Some(link.clone()),
                ..Default::default()
            });
        }
        if let Some(highlight) = mark.highlight {
            layers.push(TextMark {
                highlight: Some(highlight),
                ..Default::default()
            });
        }
        if mark.underline {
            layers.push(TextMark::default().underline());
        }
        if mark.strikethrough {
            layers.push(TextMark::default().strikethrough());
        }
        if mark.bold {
            layers.push(TextMark::default().bold());
        }
        if mark.italic {
            layers.push(TextMark::default().italic());
        }
        if mark.code {
            layers.push(TextMark::default().code());
        }
        self.pieces.push((source.to_string(), layers));
    }

    fn push_text(
        &mut self,
        text: &str,
        marks: &[(Range<usize>, TextMark)],
        selection: Range<usize>,
    ) {
        let start = selection.start.min(text.len());
        let end = selection.end.min(text.len());
        if start >= end {
            return;
        }
        let mut cursor = start;
        for (range, mark) in marks {
            let lo = range.start.max(start);
            let hi = range.end.min(end);
            if lo >= hi {
                continue;
            }
            if cursor < lo {
                self.push_str(&text[cursor..lo]);
            }
            self.push_marked(&text[lo..hi], mark);
            cursor = hi;
        }
        if cursor < end {
            self.push_str(&text[cursor..end]);
        }
    }

    fn push_images(&mut self, images: &[String]) {
        if images.is_empty() {
            return;
        }
        self.has_objects = true;
        self.push_str(&images.join(""));
    }

    fn push_object(&mut self, node: &InlineNode) {
        self.has_objects = true;
        let mut mark = TextMark::default();
        for (_, layer) in &node.marks {
            mark.merge(layer.clone());
        }
        self.push_marked(&node.custom.as_ref().unwrap().to_markdown(), &mark);
    }

    fn is_empty(&self) -> bool {
        self.pieces.is_empty()
    }

    fn styles(&self) -> SelectionStyles {
        if self.is_empty() {
            SelectionStyles::None
        } else if !self.has_objects && self.pieces.windows(2).all(|pair| pair[0].1 == pair[1].1) {
            SelectionStyles::One
        } else {
            SelectionStyles::Mixed
        }
    }

    fn finish(mut self) -> String {
        fn write(pieces: &mut [(String, Vec<TextMark>)]) -> String {
            let mut out = String::new();
            let mut offset = 0;
            while offset < pieces.len() {
                let Some((mark, count)) = pieces[offset]
                    .1
                    .iter()
                    .map(|mark| {
                        let count = pieces[offset..]
                            .iter()
                            .take_while(|(_, layers)| layers.contains(mark))
                            .count();
                        (mark.clone(), count)
                    })
                    .reduce(|best, candidate| {
                        if candidate.1 > best.1 {
                            candidate
                        } else {
                            best
                        }
                    })
                else {
                    out.push_str(&pieces[offset].0);
                    offset += 1;
                    continue;
                };
                let group = &mut pieces[offset..offset + count];
                for (_, layers) in group.iter_mut() {
                    layers.retain(|layer| layer != &mark);
                }
                let content = write(group);
                out.push_str(&wrap_with_mark(&content, &mark));
                offset += count;
            }
            out
        }
        write(&mut self.pieces)
    }
}

/// How a selection covers one rendered run, so the caller can tell whether it
/// continues into an adjacent inline image.
#[derive(Default)]
struct RunSelection {
    emitted: bool,
    at_start: bool,
    at_end: bool,
}

/// Emit the selected part of one rendered run, preceded by the images the
/// selection has run into. `run` holds the run's children with their offset
/// into the run's concatenated text.
fn emit_run(
    state: &Arc<Mutex<InlineState>>,
    run: &[(usize, &InlineNode)],
    pending_images: &mut Vec<String>,
    out: &mut MarkdownSource,
) -> RunSelection {
    let mut selected = RunSelection::default();
    let Ok(state) = state.lock() else {
        return selected;
    };
    let Some(selection) = &state.selection else {
        return selected;
    };
    if selection.start >= selection.end {
        return selected;
    }

    selected.at_start = selection.start == 0;
    selected.at_end = selection.end >= state.text.len();

    for (start, child) in run {
        let end = start + child.text.len();
        let lo = selection.start.max(*start);
        let hi = selection.end.min(end);
        if lo >= hi {
            continue;
        }

        if !selected.emitted {
            if selected.at_start {
                out.push_images(pending_images);
            }
            pending_images.clear();
        }
        selected.emitted = true;

        out.push_text(&child.text, &child.marks, (lo - start)..(hi - start));
    }

    selected
}

/// The Markdown source for an inline image, e.g. `![alt](url "title")`.
fn image_markdown(image: &ImageNode) -> String {
    let alt = image.alt.clone().unwrap_or_default();
    let title = image
        .title
        .clone()
        .map_or(String::new(), |title| format!(" \"{}\"", title));
    format!("![{}]({}{})", alt, image.url, title)
}

/// Reconstruct the Markdown source for the `selection` sub-range of a text run
/// carrying `marks`.
///
/// `selection` is a byte range into `text`. For each mark that overlaps the
/// selection, the overlapping slice is wrapped in the mark's Markdown syntax
/// (see [`wrap_with_mark`]); slices not covered by any mark are emitted
/// verbatim. This lets a rendered-offset selection be copied back as Markdown
/// source (e.g. selecting inside a `**bold**` run yields `**bold**`).
#[cfg(test)]
pub(crate) fn reconstruct_markdown(
    text: &str,
    marks: &[(Range<usize>, TextMark)],
    selection: Range<usize>,
) -> String {
    let mut source = MarkdownSource::default();
    source.push_text(text, marks, selection);
    source.finish()
}

/// Reconstruct the Markdown source of the selected cells of `table`.
///
/// Cells emit their own selected source; rows are piped (`| a | b |`) and the
/// delimiter/alignment row is inserted after the first row, so a selected
/// table round-trips as a Markdown table. A selection in one cell (a drag that
/// started in a cell stays in it) is that cell's source alone. Returns an empty
/// string when no cell is selected.
fn table_selected_source(table: &Table) -> String {
    let cell_source = |cell: &TableCell| cell.children.selected_source().replace('\n', " ");

    let mut selected = table
        .children
        .iter()
        .flat_map(|row| row.children.iter())
        .map(cell_source)
        .filter(|source| !source.trim().is_empty());
    match (selected.next(), selected.next()) {
        (None, _) => return String::new(),
        (Some(only), None) => return only.trim().to_string(),
        _ => {}
    }

    let mut lines: Vec<String> = Vec::new();
    for (row_ix, row) in table.children.iter().enumerate() {
        let cells: Vec<String> = row
            .children
            .iter()
            .map(|cell| cell_source(cell).trim().to_string())
            .collect();
        lines.push(format!("| {} |", cells.join(" | ")));

        // The Markdown delimiter row carries the column alignments and must
        // follow the header row.
        if row_ix == 0 {
            let aligns: Vec<String> = (0..row.children.len())
                .map(|ix| {
                    match table.column_align(ix) {
                        ColumnumnAlign::None | ColumnumnAlign::Left => ":--",
                        ColumnumnAlign::Center => ":-:",
                        ColumnumnAlign::Right => "--:",
                    }
                    .to_string()
                })
                .collect();
            lines.push(format!("| {} |", aligns.join(" | ")));
        }
    }

    lines.join("\n")
}

/// Reconstruct the Markdown source of the selected items of a list.
///
/// Restores the list marker (`- ` / `N. `) and task-list checkbox (`[x] ` /
/// `[ ] `) of each item, and recurses into nested lists with a deeper `indent`
/// so nesting is preserved. `indent` is the leading whitespace for this level;
/// nested levels are indented by the width of the parent marker so continuation
/// and sub-list lines align under the item text. Items with no selected content
/// are skipped but still consume an ordered number, so the remaining items keep
/// their original numbering.
fn list_selected_source(
    children: &[BlockNode],
    ordered: bool,
    start: Option<u32>,
    indent: &str,
) -> String {
    let mut out = String::new();
    let mut item_ix = 0usize;

    for child in children {
        let BlockNode::ListItem {
            children: item_children,
            checked,
            ..
        } = child
        else {
            continue;
        };

        let marker = if ordered {
            format!("{}. ", ordered_list_ordinal(start, item_ix))
        } else {
            "- ".to_string()
        };
        let checkbox = match checked {
            Some(true) => "[x] ",
            Some(false) => "[ ] ",
            None => "",
        };
        let child_indent = format!("{}{}", indent, " ".repeat(marker.len()));

        // Split the item into its own content and any nested lists, so the
        // nested lists can be indented under the content.
        let mut content = String::new();
        let mut nested = String::new();
        for sub in item_children {
            if let BlockNode::List {
                children: sub_children,
                ordered: sub_ordered,
                start: sub_start,
                ..
            } = sub
            {
                nested.push_str(&list_selected_source(
                    sub_children,
                    *sub_ordered,
                    *sub_start,
                    &child_indent,
                ));
            } else {
                content.push_str(&sub.text_by_kind(BlockTextKind::SelectedSource));
            }
        }
        let content = content.trim_end_matches('\n');

        if content.is_empty() && nested.is_empty() {
            item_ix += 1;
            continue;
        }

        if content.is_empty() {
            // An item whose only selected content is a nested list.
            out.push_str(indent);
            out.push_str(&marker);
            out.push_str(checkbox.trim_end());
            out.push('\n');
        } else {
            // The first line carries the marker and checkbox; continuation
            // lines are indented to align under the item text.
            let mut lines = content.lines();
            if let Some(first) = lines.next() {
                out.push_str(indent);
                out.push_str(&marker);
                out.push_str(checkbox);
                out.push_str(first);
                out.push('\n');
            }
            for line in lines {
                out.push_str(&child_indent);
                out.push_str(line);
                out.push('\n');
            }
        }
        out.push_str(&nested);
        item_ix += 1;
    }

    out
}

impl InlineNode {
    /// A run of text with no marks.
    pub fn new(text: impl Into<SharedString>) -> Self {
        Self {
            text: text.into(),
            image: None,
            custom: None,
            custom_selection: Arc::default(),
            marks: vec![],
            source_segments: vec![],
            state: Arc::new(Mutex::new(InlineState::default())),
        }
    }

    /// A custom inline node, an atomic object in the flow.
    pub fn custom(node: MarkdownNode) -> Self {
        let mut this = Self::new(node.as_text().to_string());
        this.custom = Some(node);
        this
    }

    /// An inline image, an atomic object in the flow.
    pub fn image(image: ImageNode) -> Self {
        let mut this = Self::new("");
        this.image = Some(image);
        this
    }

    /// Sets the marks, each a byte range of the text and its style.
    pub fn marks(mut self, marks: Vec<(Range<usize>, TextMark)>) -> Self {
        self.marks = marks;
        self
    }

    /// The text of the run (the fallback text of a custom node, empty for an image).
    pub fn text(&self) -> &str {
        &self.text
    }

    /// The image, when this run is an image.
    pub fn as_image(&self) -> Option<&ImageNode> {
        self.image.as_ref()
    }

    /// The custom node, when this run is one.
    pub fn as_custom(&self) -> Option<&MarkdownNode> {
        self.custom.as_ref()
    }

    /// The marks, each a byte range of the text and its style.
    pub fn mark_runs(&self) -> &[(Range<usize>, TextMark)] {
        &self.marks
    }

    pub(crate) fn source_segments(mut self, source_segments: Vec<SourceSegment>) -> Self {
        self.source_segments = source_segments;
        self
    }

    fn selected_source_range(&self, selection: Range<usize>) -> Option<Range<usize>> {
        source_range_for_segments(&self.source_segments, selection)
    }
}

/// The paragraph element, contains multiple text nodes.
///
/// Unlike other Element, this is cloneable, because it is used in the Node AST.
/// We are keep the selection state inside this AST Nodes.
#[derive(Debug, Clone, Default)]
pub struct Paragraph {
    pub(super) span: Option<Span>,
    pub(super) children: Vec<InlineNode>,
    /// The link references in this paragraph, used for reference links.
    ///
    /// The key is the identifier, the value is the url.
    pub(super) link_refs: HashMap<SharedString, SharedString>,

    pub(crate) state: Arc<Mutex<InlineState>>,
    /// What the plain (text-only) render path derives from `children`, kept
    /// between frames; see [`ParagraphRender`].
    pub(super) render_cache: ParagraphRenderCache,
}

/// Derived state, invisible to `Debug` and equality.
///
/// A clone carries what was cached so far: the cached value is a pure
/// function of the children and the style it is keyed on, a clone has the
/// same children, and every mutation of the children replaces the cache
/// (`invalidate_render_cache`). Streaming reparses deep-clone the document on
/// every append, and an empty clone made every paragraph rebuild.
#[derive(Default)]
pub(super) struct ParagraphRenderCache(Mutex<Option<Arc<ParagraphRender>>>);

impl Clone for ParagraphRenderCache {
    fn clone(&self) -> Self {
        let cached = self.0.lock().ok().and_then(|cache| cache.clone());
        Self(Mutex::new(cached))
    }
}

impl std::fmt::Debug for ParagraphRenderCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("ParagraphRenderCache")
    }
}

/// The text, highlights and links a text-only paragraph renders with.
///
/// They are a pure function of the paragraph's children and the style they
/// are rendered under, yet every frame rebuilt them: the paragraph's text was
/// re-concatenated and copied into a fresh `SharedString`, and its marks
/// merged into highlights through `combine_highlights` once per child. On a
/// scroll that was ~8% of the frame for nothing. Streamed fades change every
/// frame and are layered on afterwards; reference links are resolved
/// afterwards too, since a definition can arrive later in the document.
struct ParagraphRender {
    style: Arc<TextViewStyle>,
    mono_font: SharedString,
    background: Hsla,
    text: SharedString,
    highlights: Vec<(Range<usize>, InlineHighlight)>,
    /// Links as written, before reference resolution.
    links: Vec<(Range<usize>, LinkMark)>,
}

impl PartialEq for Paragraph {
    fn eq(&self, other: &Self) -> bool {
        self.span == other.span
            && self.children == other.children
            && self.link_refs == other.link_refs
    }
}

impl Paragraph {
    pub(crate) fn new(text: String) -> Self {
        Self {
            span: None,
            children: vec![InlineNode::new(&text)],
            link_refs: HashMap::new(),
            state: Arc::new(Mutex::new(InlineState::default())),
            render_cache: ParagraphRenderCache::default(),
        }
    }

    /// The text, highlights and (unresolved) links of a text-only paragraph,
    /// from the cache when the style has not changed since they were built.
    fn plain_render(
        &self,
        node_cx: &NodeContext,
        cx: &App,
    ) -> (
        SharedString,
        Vec<(Range<usize>, InlineHighlight)>,
        Vec<(Range<usize>, LinkMark)>,
    ) {
        let mono_font = cx.theme().tokens.typography.mono.clone();
        let background = cx.theme().tokens.colors.background;
        if let Ok(cache) = self.render_cache.0.lock()
            && let Some(cached) = cache.as_ref()
            && (Arc::ptr_eq(&cached.style, &node_cx.style) || *cached.style == *node_cx.style)
            && cached.mono_font == mono_font
            && cached.background == background
        {
            return (
                cached.text.clone(),
                cached.highlights.clone(),
                cached.links.clone(),
            );
        }

        let mut text = String::new();
        let mut highlights: Vec<(Range<usize>, InlineHighlight)> = vec![];
        let mut links: Vec<(Range<usize>, LinkMark)> = vec![];
        let mut offset = 0;
        for inline_node in &self.children {
            let text_len = inline_node.text.len();
            text.push_str(&inline_node.text);
            let mut node_highlights = vec![];
            for (range, style) in &inline_node.marks {
                let inner_range = (offset + range.start)..(offset + range.end);
                let mut highlight = mark_highlight(style, node_cx, cx);
                if let Some(link_mark) = style.link.clone() {
                    highlight.style.color = Some(node_cx.style.link());
                    highlight.style.underline = Some(link_underline(&node_cx.style));
                    links.push((inner_range.clone(), link_mark));
                }
                node_highlights.push((inner_range, highlight));
            }
            highlights = combine_highlights(highlights, node_highlights);
            offset += text_len;
        }
        let text = SharedString::from(text);
        if let Ok(mut cache) = self.render_cache.0.lock() {
            *cache = Some(Arc::new(ParagraphRender {
                style: node_cx.style.clone(),
                mono_font,
                background,
                text: text.clone(),
                highlights: highlights.clone(),
                links: links.clone(),
            }));
        }
        (text, highlights, links)
    }

    pub(super) fn selected_text(&self) -> String {
        let mut text = String::new();

        for c in self.children.iter() {
            let Ok(state) = c.state.lock() else {
                continue;
            };
            if let Some(selection) = &state.selection {
                text.push_str(&state.text[selection.start..selection.end]);
            }
            if let Some(custom) = &c.custom
                && c.custom_selection.lock().is_ok_and(|selected| *selected)
            {
                text.push_str(custom.as_text());
            }
        }

        if let Ok(state) = self.state.lock()
            && let Some(selection) = &state.selection
        {
            text.push_str(&state.text[selection.start..selection.end]);
        }

        text
    }

    /// Map the current rendered selection to its exact Markdown source range.
    pub(super) fn selected_source_range(&self) -> SourceRangeSelection {
        let mut selected = SourceRangeSelection::Unselected;
        let mut run: Vec<(usize, &InlineNode)> = Vec::new();
        let mut offset = 0;
        let mut pending_images: Vec<Option<Span>> = Vec::new();
        let mut enters_image = true;

        let include_run = |state: &Arc<Mutex<InlineState>>,
                           run: &[(usize, &InlineNode)]|
         -> (SourceRangeSelection, RunSelection) {
            let Ok(state) = state.lock() else {
                return (SourceRangeSelection::Unmapped, RunSelection::default());
            };
            let Some(selection) = state.selection else {
                return (SourceRangeSelection::Unselected, RunSelection::default());
            };
            if selection.start >= selection.end {
                return (SourceRangeSelection::Unselected, RunSelection::default());
            }

            let mut run_selection = RunSelection {
                at_start: selection.start == 0,
                at_end: selection.end >= state.text.len(),
                ..Default::default()
            };
            let mut mapped = SourceRangeSelection::Unselected;
            let mut rendered_end = selection.start;
            for (start, child) in run {
                let end = start + child.text.len();
                let lo = selection.start.max(*start);
                let hi = selection.end.min(end);
                if lo >= hi {
                    continue;
                }
                run_selection.emitted = true;
                if lo > rendered_end {
                    return (SourceRangeSelection::Unmapped, run_selection);
                }
                let Some(range) = child.selected_source_range((lo - start)..(hi - start)) else {
                    return (SourceRangeSelection::Unmapped, run_selection);
                };
                mapped.merge(SourceRangeSelection::Mapped(range));
                rendered_end = rendered_end.max(hi);
            }
            if rendered_end < selection.end {
                (SourceRangeSelection::Unmapped, run_selection)
            } else {
                (mapped, run_selection)
            }
        };

        let merge_images = |selected: &mut SourceRangeSelection, images: &mut Vec<Option<Span>>| {
            for span in images.drain(..) {
                selected.merge(
                    span.map(|span| SourceRangeSelection::Mapped(span.start..span.end))
                        .unwrap_or(SourceRangeSelection::Unmapped),
                );
            }
        };

        for child in &self.children {
            if child.custom.is_some() {
                let (run_range, run_selection) = include_run(&child.state, &run);
                if run_selection.emitted && run_selection.at_start {
                    merge_images(&mut selected, &mut pending_images);
                }
                selected.merge(run_range);

                match child.custom_selection.lock() {
                    Ok(value) if *value => {
                        if run.is_empty() || (run_selection.emitted && run_selection.at_end) {
                            merge_images(&mut selected, &mut pending_images);
                        }
                        selected.merge(
                            child
                                .custom
                                .as_ref()
                                .and_then(MarkdownNode::source_range)
                                .map(SourceRangeSelection::Mapped)
                                .unwrap_or(SourceRangeSelection::Unmapped),
                        );
                        enters_image = true;
                    }
                    Ok(_) => enters_image = false,
                    Err(_) => {
                        selected.merge(SourceRangeSelection::Unmapped);
                        enters_image = false;
                    }
                }
                pending_images.clear();
                run.clear();
                offset = 0;
                continue;
            }
            if let Some(image) = &child.image {
                let run_before = !run.is_empty();
                let (run_range, run_selection) = include_run(&child.state, &run);
                if run_selection.emitted && run_selection.at_start {
                    merge_images(&mut selected, &mut pending_images);
                }
                selected.merge(run_range);
                if run_before {
                    enters_image = run_selection.emitted && run_selection.at_end;
                }
                if enters_image {
                    pending_images.push(image.span);
                } else {
                    pending_images.clear();
                }
                run.clear();
                offset = 0;
                continue;
            }
            run.push((offset, child));
            offset += child.text.len();
        }

        let (trailing_range, trailing) = include_run(&self.state, &run);
        if trailing.emitted && trailing.at_start {
            merge_images(&mut selected, &mut pending_images);
        }
        selected.merge(trailing_range);
        if !trailing.emitted
            && enters_image
            && !matches!(selected, SourceRangeSelection::Unselected)
        {
            merge_images(&mut selected, &mut pending_images);
        }
        selected
    }

    /// Reconstruct the Markdown source for the current selection.
    ///
    /// Mirrors [`selected_text`](Self::selected_text), but emits Markdown
    /// instead of the rendered text, using each inline node's `marks` (see
    /// [`reconstruct_markdown`]).
    ///
    /// Selection offsets index an `InlineState.text`, and one such state spans
    /// *several* children: [`Paragraph::render`] concatenates children until it
    /// hits an inline image, stores that run in the image child's state, then
    /// starts over; whatever follows the last image is stored in `self.state`.
    /// So walk the children in the same runs and map each selected byte back to
    /// the child it was rendered from — mapping against a single child's text
    /// would attribute the same offsets to children in other runs.
    ///
    /// An image has no selection of its own, so it is emitted when the
    /// selection runs into it: reaching the end of the run before it, and
    /// starting at the beginning of the run after it. A paragraph that begins
    /// or ends with an image has no run on that side, which counts as reaching
    /// it.
    pub(super) fn selected_source(&self) -> String {
        self.selected_markdown().finish()
    }

    /// How many styles the selection within this paragraph takes in.
    pub(super) fn selection_styles(&self) -> SelectionStyles {
        self.selected_markdown().styles()
    }

    /// The selection as Markdown pieces, before their marks are serialized;
    /// see [`selected_source`](Self::selected_source).
    fn selected_markdown(&self) -> MarkdownSource {
        let mut source = MarkdownSource::default();
        let mut pending_images: Vec<String> = Vec::new();
        let mut run: Vec<(usize, &InlineNode)> = Vec::new();
        let mut offset = 0;
        let mut enters_image = true;

        for child in self.children.iter() {
            if child.custom.is_some() {
                let selected = emit_run(&child.state, &run, &mut pending_images, &mut source);
                let object_selected = child
                    .custom_selection
                    .lock()
                    .is_ok_and(|selected| *selected);
                if object_selected {
                    if run.is_empty() || (selected.emitted && selected.at_end) {
                        source.push_images(&pending_images);
                    }
                    source.push_object(child);
                }
                pending_images.clear();
                enters_image = object_selected;
                run.clear();
                offset = 0;
                continue;
            }
            let Some(image) = &child.image else {
                run.push((offset, child));
                offset += child.text.len();
                continue;
            };

            // The run before an image is stored in that image's own state.
            let run_before = !run.is_empty();
            let selected = emit_run(&child.state, &run, &mut pending_images, &mut source);
            if run_before {
                enters_image = selected.emitted && selected.at_end;
            }
            if enters_image {
                pending_images.push(image_markdown(image));
            } else {
                pending_images.clear();
            }

            run.clear();
            offset = 0;
        }

        let trailing = emit_run(&self.state, &run, &mut pending_images, &mut source);
        // Trailing images have no run after them to flush them.
        if !trailing.emitted && enters_image && !source.is_empty() {
            source.push_images(&pending_images);
        }

        source
    }

    pub(super) fn text(&self) -> String {
        let mut text = String::new();
        for node in self.children.iter() {
            text.push_str(&node.text);
        }
        text
    }

    /// Synchronously clear the selection stored in every inline state.
    ///
    /// Mirrors the [`selected_text`](Self::selected_text) traversal.
    pub(super) fn has_selection(&self) -> bool {
        self.children.iter().any(|c| {
            c.state.lock().is_ok_and(|state| state.selection.is_some())
                || c.custom_selection.lock().is_ok_and(|selected| *selected)
        }) || self
            .state
            .lock()
            .is_ok_and(|state| state.selection.is_some())
    }

    pub(super) fn clear_selection(&self) {
        for c in self.children.iter() {
            if let Ok(mut selected) = c.custom_selection.lock() {
                *selected = false;
            }
            if let Ok(mut state) = c.state.lock() {
                state.selection = None;
            }
        }

        if let Ok(mut state) = self.state.lock() {
            state.selection = None;
        }
    }
}

/// A table: rows of cell paragraphs and per-column alignment.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Table {
    pub(crate) children: Vec<TableRow>,
    pub(crate) column_aligns: Vec<ColumnumnAlign>,
    pub(crate) span: Option<Span>,
    /// The [`TableData`] handed to the `table_actions` hook, kept between
    /// frames; see [`Table::cached_table_data`].
    pub(crate) table_data_cache: TableDataCache,
    pub(crate) column_widths_cache: TableColumnWidthsCache,
}

/// Derived state, invisible to `Debug` and equality.
///
/// A clone carries what was cached so far: a parsed table does not change
/// after parsing (cell mutations only touch selection state, which
/// [`TableData`] does not read), so a clone has the same data. Streaming
/// reparses deep-clone the document on every append, and an empty clone made
/// every table rebuild.
#[derive(Default)]
pub(crate) struct TableDataCache(Mutex<Option<Arc<TableData>>>);

impl Clone for TableDataCache {
    fn clone(&self) -> Self {
        let cached = self.0.lock().ok().and_then(|cache| cache.clone());
        Self(Mutex::new(cached))
    }
}

impl PartialEq for TableDataCache {
    fn eq(&self, _: &Self) -> bool {
        true
    }
}

impl std::fmt::Debug for TableDataCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("TableDataCache")
    }
}

/// Like `TableDataCache`, derived widths survive clones of an unchanged
/// parsed table. A newly parsed table starts with an empty cache.
#[derive(Default)]
pub(crate) struct TableColumnWidthsCache(Mutex<Option<Arc<TableColumnWidths>>>);

impl Clone for TableColumnWidthsCache {
    fn clone(&self) -> Self {
        let cached = self.0.lock().ok().and_then(|cache| cache.clone());
        Self(Mutex::new(cached))
    }
}

impl PartialEq for TableColumnWidthsCache {
    fn eq(&self, _: &Self) -> bool {
        true
    }
}

impl std::fmt::Debug for TableColumnWidthsCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("TableColumnWidthsCache")
    }
}

fn text_system_id(window: &Window) -> usize {
    std::rc::Rc::as_ptr(window.text_system()) as usize
}

struct TableColumnWidths {
    /// Identity of the window text system the widths were measured with.
    /// `WindowTextSystem` is `Rc`-shared and the cache must stay `Send`, so
    /// only its address is kept.
    text_system: usize,
    /// The styles the header row and the body rows render with.
    text_styles: TableTextStyles,
    rem_size: Pixels,
    mono_family: SharedString,
    inline_code: HighlightStyle,
    /// Maxima from ordinary text only. Custom cells may shrink after an update.
    widths: Vec<f32>,
    custom_cells: Vec<(usize, usize)>,
}

/// The text styles table rows render with: the window's, refined by
/// `style.table` on the frame, `style.table_head` on the header row and
/// `style.table_cell` on every cell, in the order the elements apply them.
#[derive(Clone, PartialEq)]
struct TableTextStyles {
    head: gpui::TextStyle,
    body: gpui::TextStyle,
    head_refinement: TextStyleRefinement,
    body_refinement: TextStyleRefinement,
}

impl TableTextStyles {
    fn new(style: &TextViewStyle, window: &Window) -> Self {
        let mut body_refinement = style.table().text.clone();
        let mut head_refinement = body_refinement.clone();
        head_refinement.refine(&style.table_head().text);
        head_refinement.refine(&style.table_cell().text);
        body_refinement.refine(&style.table_cell().text);
        let mut head = window.text_style();
        let mut body = head.clone();
        head.refine(&head_refinement);
        body.refine(&body_refinement);
        Self {
            head,
            body,
            head_refinement,
            body_refinement,
        }
    }

    fn row(&self, row_ix: usize) -> &gpui::TextStyle {
        if row_ix == 0 { &self.head } else { &self.body }
    }

    fn row_refinement(&self, row_ix: usize) -> &TextStyleRefinement {
        if row_ix == 0 {
            &self.head_refinement
        } else {
            &self.body_refinement
        }
    }
}

/// Plain snapshot of a rendered Markdown table, passed to the
/// [`crate::text::TextView::table_actions`] hook.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct TableData {
    /// First table row (header cells) as plain text.
    pub headers: Vec<String>,
    /// Rows after the header as plain text cells. May be ragged while
    /// a table is still streaming in.
    pub rows: Vec<Vec<String>>,
    /// The table serialized back to GFM pipe-table Markdown, alignments kept.
    pub markdown: String,
    /// Byte range of the table in the Markdown source, for callers that need
    /// to map the table back to the document.
    ///
    /// Not needed to keep element ids apart: the actions row is wrapped in its
    /// own identified element, so plain ids like `"copy"` are already scoped
    /// per table.
    pub span: Option<Range<usize>>,
}

impl Table {
    /// A table of `rows` (one paragraph per cell) with the column alignments.
    pub fn new(rows: Vec<Vec<Paragraph>>, column_aligns: Vec<ColumnumnAlign>) -> Self {
        Self {
            children: rows
                .into_iter()
                .map(|row| TableRow {
                    children: row
                        .into_iter()
                        .map(|children| TableCell {
                            children,
                            width: None,
                        })
                        .collect(),
                })
                .collect(),
            column_aligns,
            ..Default::default()
        }
    }

    /// The rows, each an iterator over its cells' paragraphs.
    pub fn rows(&self) -> impl Iterator<Item = impl Iterator<Item = &Paragraph>> {
        self.children
            .iter()
            .map(|row| row.children.iter().map(|cell| &cell.children))
    }

    /// The alignment of each column.
    pub fn column_aligns(&self) -> &[ColumnumnAlign] {
        &self.column_aligns
    }

    pub(crate) fn column_align(&self, index: usize) -> ColumnumnAlign {
        self.column_aligns.get(index).copied().unwrap_or_default()
    }

    /// Serialize the table back to GFM pipe-table Markdown (`| a | b |`),
    /// preserving column alignments. Cell newlines collapse to spaces and
    /// `|` is escaped so rows stay intact.
    ///
    /// Mirrors [`table_selected_source`], which does the same for the selected
    /// cells only.
    pub(crate) fn to_markdown(&self) -> String {
        let mut lines: Vec<String> = Vec::with_capacity(self.children.len() + 1);

        for (row_ix, row) in self.children.iter().enumerate() {
            let cells: Vec<String> = row
                .children
                .iter()
                .map(|cell| {
                    cell.children
                        .to_markdown()
                        .trim()
                        .replace('\n', " ")
                        .replace('|', "\\|")
                })
                .collect();
            lines.push(format!("| {} |", cells.join(" | ")));

            // The Markdown delimiter row carries the column alignments and must
            // follow the header row.
            if row_ix == 0 {
                let aligns: Vec<String> = (0..row.children.len())
                    .map(|ix| {
                        match self.column_align(ix) {
                            ColumnumnAlign::None | ColumnumnAlign::Left => ":--",
                            ColumnumnAlign::Center => ":-:",
                            ColumnumnAlign::Right => "--:",
                        }
                        .to_string()
                    })
                    .collect();
                lines.push(format!("| {} |", aligns.join(" | ")));
            }
        }

        lines.join("\n")
    }

    /// Snapshot of this table for the [`crate::text::TextView::table_actions`]
    /// hook.
    pub(crate) fn table_data(&self) -> TableData {
        let row_text = |row: &TableRow| {
            row.children
                .iter()
                .map(|cell| cell.children.text().trim().to_string())
                .collect::<Vec<_>>()
        };

        TableData {
            headers: self.children.first().map(row_text).unwrap_or_default(),
            rows: self.children.iter().skip(1).map(row_text).collect(),
            markdown: self.to_markdown(),
            span: self.span.map(|span| span.start..span.end),
        }
    }

    /// [`Self::table_data`], built on the first render and reused by later
    /// ones: serializing every cell and the whole table back to Markdown on
    /// every scroll or stream frame is wasted work, and a parsed table does
    /// not change after parsing (a reparse builds a new one).
    fn cached_table_data(&self) -> Arc<TableData> {
        if let Ok(cache) = self.table_data_cache.0.lock()
            && let Some(cached) = cache.as_ref()
        {
            return cached.clone();
        }

        let data = Arc::new(self.table_data());
        if let Ok(mut cache) = self.table_data_cache.0.lock() {
            *cache = Some(data.clone());
        }
        data
    }
}

/// The alignment of a table column.
#[derive(Debug, Default, Copy, Clone, PartialEq)]
pub enum ColumnumnAlign {
    /// No alignment in the delimiter row (`---`); renders like `Left`.
    #[default]
    None,
    Left,
    Center,
    Right,
}

impl From<mdast::AlignKind> for ColumnumnAlign {
    fn from(value: mdast::AlignKind) -> Self {
        match value {
            mdast::AlignKind::None => ColumnumnAlign::None,
            mdast::AlignKind::Left => ColumnumnAlign::Left,
            mdast::AlignKind::Center => ColumnumnAlign::Center,
            mdast::AlignKind::Right => ColumnumnAlign::Right,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub(crate) struct TableRow {
    pub children: Vec<TableCell>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub(crate) struct TableCell {
    pub children: Paragraph,
    pub width: Option<DefiniteLength>,
}

impl Paragraph {
    pub(crate) fn take(&mut self) -> Paragraph {
        std::mem::replace(
            self,
            Paragraph {
                span: None,
                children: vec![],
                link_refs: Default::default(),
                state: Arc::new(Mutex::new(InlineState::default())),
                render_cache: ParagraphRenderCache::default(),
            },
        )
    }

    pub(crate) fn is_image(&self) -> bool {
        false
    }

    pub(crate) fn set_span(&mut self, span: Span) {
        self.span = Some(span);
    }

    pub(crate) fn push_str(&mut self, text: &str) {
        self.children.push(
            InlineNode::new(text.to_string()).marks(vec![(0..text.len(), TextMark::default())]),
        );
        self.invalidate_render_cache();
    }

    /// Appends an inline run.
    pub fn push(&mut self, text: InlineNode) {
        self.children.push(text);
        self.invalidate_render_cache();
    }

    /// The inline runs.
    pub fn children(&self) -> &[InlineNode] {
        &self.children
    }

    /// Marks this paragraph as a leaf of an external editor: while a
    /// [`collect_leaf_geometry`](super::editor_host::collect_leaf_geometry)
    /// scope is active, it reports its geometry under `key` and paints the
    /// decorations given for `key`. Rekeying detaches runtime state from clones.
    pub fn with_leaf_key(mut self, key: u64) -> Self {
        set_leaf_key(&mut self.state, key);
        self
    }

    pub(crate) fn push_image(&mut self, image: ImageNode) {
        self.children.push(InlineNode::image(image));
        self.invalidate_render_cache();
    }

    /// The children changed, so what was derived from them is stale.
    fn invalidate_render_cache(&mut self) {
        self.render_cache = ParagraphRenderCache::default();
    }

    pub(crate) fn is_empty(&self) -> bool {
        self.children.is_empty()
            || self
                .children
                .iter()
                .all(|node| node.text.is_empty() && node.image.is_none())
    }

    /// Return length of children text.
    pub(crate) fn text_len(&self) -> usize {
        self.children
            .iter()
            .map(|node| node.text.len())
            .sum::<usize>()
    }

    pub(crate) fn merge(&mut self, other: Self) {
        self.children.extend(other.children);
        self.invalidate_render_cache();
    }
}

#[derive(Debug, Clone)]
pub struct CodeBlock {
    lang: Option<SharedString>,
    meta: Option<SharedString>,
    state: Arc<Mutex<InlineState>>,
    highlight_cache: Arc<Mutex<Option<CachedCodeBlockHighlights>>>,
    /// Rendered UTF-8 byte spans of the code paired with their exact Markdown
    /// source spans.
    pub(crate) source_segments: Vec<SourceSegment>,
    pub span: Option<Span>,
}

struct CachedCodeBlockHighlights {
    highlighter: Arc<CodeBlockHighlighterFn>,
    styles: Vec<(Range<usize>, HighlightStyle)>,
}

impl std::fmt::Debug for CachedCodeBlockHighlights {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("CachedCodeBlockHighlights")
            .field("styles", &self.styles)
            .finish_non_exhaustive()
    }
}

impl PartialEq for CodeBlock {
    fn eq(&self, other: &Self) -> bool {
        self.lang == other.lang
            && self.meta == other.meta
            && self.code() == other.code()
            && self.span == other.span
    }
}

impl CodeBlock {
    /// Get the language of the code block.
    pub fn lang(&self) -> Option<SharedString> {
        self.lang.clone()
    }

    /// The rest of the fence's info string after the language, when any.
    pub fn meta(&self) -> Option<SharedString> {
        self.meta.clone()
    }

    /// Sets the fence's info string after the language. It is kept for
    /// round trips and is not rendered.
    pub fn with_meta(mut self, meta: Option<SharedString>) -> Self {
        self.meta = meta;
        self
    }

    /// Marks this code block as a leaf of an external editor, like
    /// [`Paragraph::with_leaf_key`]. Rekeying detaches runtime state from clones.
    pub fn with_leaf_key(mut self, key: u64) -> Self {
        set_leaf_key(&mut self.state, key);
        self
    }

    /// Get the code content of the code block.
    pub fn code(&self) -> SharedString {
        self.state
            .lock()
            .map(|state| state.text.clone())
            .unwrap_or_default()
    }

    /// Builds a code block that is not tied to a parsed document.
    ///
    /// [`crate::TextView::code_block_highlighter`] hands a `&CodeBlock` to the
    /// highlighter it is given, so anyone writing one needs a way to build a
    /// block to exercise it against.
    pub fn from_code(code: impl Into<SharedString>, lang: Option<impl Into<SharedString>>) -> Self {
        Self::new(code.into(), lang.map(Into::into), None::<Span>)
    }

    /// A code block of `code` in `lang`.
    pub fn new(
        code: SharedString,
        lang: Option<SharedString>,
        span: Option<impl Into<Span>>,
    ) -> Self {
        let state = Arc::new(Mutex::new(InlineState::default()));
        if let Ok(mut state) = state.lock() {
            state.set_text(code);
        }

        Self {
            lang,
            meta: None,
            state,
            highlight_cache: Arc::new(Mutex::new(None)),
            source_segments: vec![],
            span: span.map(|s| s.into()),
        }
    }

    pub(crate) fn source_segments(mut self, source_segments: Vec<SourceSegment>) -> Self {
        self.source_segments = source_segments;
        self
    }

    #[cfg(test)]
    pub(crate) fn set_selection(&self, selection: Range<usize>) {
        if let Ok(mut state) = self.state.lock() {
            state.selection = Some(selection.into());
        }
    }

    pub(super) fn selected_source_range(&self) -> SourceRangeSelection {
        let Ok(state) = self.state.lock() else {
            return SourceRangeSelection::Unmapped;
        };
        let Some(selection) = state.selection else {
            return SourceRangeSelection::Unselected;
        };
        if selection.start >= selection.end {
            return SourceRangeSelection::Unselected;
        }
        source_range_for_segments(&self.source_segments, selection.start..selection.end)
            .map(SourceRangeSelection::Mapped)
            .unwrap_or(SourceRangeSelection::Unmapped)
    }

    fn highlighted_styles(
        &self,
        highlighter: &Arc<CodeBlockHighlighterFn>,
    ) -> Vec<(Range<usize>, HighlightStyle)> {
        if let Ok(cache) = self.highlight_cache.lock()
            && let Some(cache) = cache.as_ref()
            && Arc::ptr_eq(&cache.highlighter, highlighter)
        {
            return cache.styles.clone();
        }

        let code_len = self.code().len();
        let styles = highlighter(self)
            .into_iter()
            .filter(|(range, _)| range.start <= range.end && range.end <= code_len)
            .collect::<Vec<_>>();
        if let Ok(mut cache) = self.highlight_cache.lock() {
            *cache = Some(CachedCodeBlockHighlights {
                highlighter: highlighter.clone(),
                styles: styles.clone(),
            });
        }
        styles
    }

    pub(super) fn selected_text(&self) -> String {
        let mut text = String::new();
        if let Ok(state) = self.state.lock()
            && let Some(selection) = &state.selection
        {
            text.push_str(&state.text[selection.start..selection.end]);
        }
        text
    }

    /// Markdown source for the current selection.
    ///
    /// The selected code is wrapped in a fenced code block carrying the block's
    /// language, so a selected code block round-trips as Markdown (e.g.
    /// ```` ```rust\n…\n``` ````) instead of pasting as bare, unfenced text.
    /// A partial selection is still emitted as a valid fenced block.
    pub(super) fn selected_source(&self) -> String {
        let code = self.selected_text();
        if code.is_empty() {
            return String::new();
        }
        let lang = self.lang.clone().unwrap_or_default();
        // Trim trailing newlines so the closing fence sits on its own line
        // directly after the last code line (no blank line before it).
        let code = code.trim_end_matches('\n');
        format!("```{}\n{}\n```", lang, code)
    }

    pub(super) fn text(&self) -> String {
        self.state
            .lock()
            .map(|state| state.text.to_string())
            .unwrap_or_default()
    }

    /// Synchronously clear the selection stored in the inline state.
    ///
    /// Mirrors the [`selected_text`](Self::selected_text) traversal.
    pub(super) fn has_selection(&self) -> bool {
        self.state
            .lock()
            .is_ok_and(|state| state.selection.is_some())
    }

    pub(super) fn clear_selection(&self) {
        if let Ok(mut state) = self.state.lock() {
            state.selection = None;
        }
    }

    fn render(
        &self,
        options: &NodeRenderOptions,
        node_cx: &NodeContext,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let style = &node_cx.style;
        let leaf_key = self.span.map(|span| TextLeafKey::block(span.start));
        // The language sits quietly in the top-right corner, where custom
        // actions go instead when the caller provides them; the top padding
        // keeps the first line clear of it. Like the actions, it stays out of
        // the scrolled content so it holds its corner.
        let lang_label = self
            .lang()
            .filter(|lang| !lang.is_empty() && node_cx.code_block_actions.is_none())
            .map(|lang| {
                div()
                    .absolute()
                    .top(px(7.))
                    .right_3()
                    .font_family(cx.theme().tokens.typography.sans.clone())
                    .text_size(cx.theme().tokens.typography.xs.size)
                    .line_height(px(16.))
                    .text_color(style.muted_foreground())
                    .child(lang)
            });

        let block = div()
            .w_full()
            .min_w_0()
            .px_4()
            .pt(if lang_label.is_some() {
                px(28.)
            } else {
                px(14.)
            })
            .pb(px(14.))
            .bg(style.code_background())
            .border_1()
            .border_color(style.border())
            .font_family(cx.theme().tokens.typography.mono.clone())
            .text_size(cx.theme().tokens.typography.mono_md.size)
            .line_height(relative(1.6))
            .relative()
            .refine_style(&style.code_block())
            .child(
                Inline::new(
                    self.state.clone(),
                    vec![],
                    fade_highlights(
                        node_cx
                            .code_block_highlighter
                            .as_ref()
                            .map(|highlighter| self.highlighted_styles(highlighter))
                            .unwrap_or_default()
                            .into_iter()
                            .map(|(range, style)| (range, InlineHighlight::from(style)))
                            .collect(),
                        node_cx.stream_fades(leaf_key),
                    ),
                    node_cx.link_click_handler.clone(),
                )
                .range_backgrounds(node_cx.range_backgrounds(leaf_key).to_vec())
                .reveal(node_cx.reveal_at(leaf_key, 0, self.code().len())),
            );
        let actions = node_cx.code_block_actions.clone().map(|actions| {
            div()
                .id("actions")
                .absolute()
                .top_2()
                .right_2()
                .bg(style.code_background())
                .rounded(cx.theme().tokens.radius.md)
                .child(actions(&self, window, cx))
        });
        // The id scopes the caller's action ids per code block, so plain ids
        // like `"copy"` don't collide across blocks.
        let id = block_element_id("codeblock", self.span, options.ix);
        let block = if matches!(style.code_block().overflow.y, Some(Overflow::Scroll)) {
            let scroll_handle = window
                .use_keyed_state(
                    block_element_id("codeblock-scroll", self.span, options.ix),
                    cx,
                    |_, _| ScrollHandle::default(),
                )
                .read(cx)
                .clone();
            // Scroll mode is opted in by setting `style.code_block`'s
            // `overflow.y` to `Overflow::Scroll`.
            // The mask consumes the wheel in the capture phase, so an ancestor
            // `gpui::list` doesn't scroll on the same event. Mask, scrollbar
            // and actions are siblings of the scrolled block, so they stay
            // pinned to the viewport instead of moving with the code.
            div()
                .id(id.clone())
                .w_full()
                .min_w_0()
                .relative()
                .child(block.id("scroll").track_scroll(&scroll_handle))
                .child(ScrollableMask::new(Axis::Vertical, &scroll_handle).id(id))
                .child(
                    div()
                        .absolute()
                        .inset_0()
                        .child(Scrollbar::vertical(&scroll_handle)),
                )
                .children(actions)
                .children(lang_label)
                .into_any_element()
        } else {
            // Without actions nothing under the block needs element state.
            match actions {
                Some(actions) => block.id(id).child(actions).into_any_element(),
                None => block.children(lang_label).into_any_element(),
            }
        };

        gapped(
            block,
            if options.is_last {
                rems(0.)
            } else {
                style.paragraph_gap()
            },
        )
    }
}

/// A context for rendering nodes, contains link references.
#[derive(Default, Clone)]
pub(crate) struct NodeContext {
    /// The byte offset of the node in the original markdown text.
    /// Used for incremental updates.
    pub(crate) offset: usize,
    pub(crate) link_refs: HashMap<SharedString, LinkMark>,
    pub(crate) style: Arc<TextViewStyle>,
    pub(crate) code_block_actions: Option<Arc<CodeBlockActionsFn>>,
    pub(crate) code_block_highlighter: Option<Arc<CodeBlockHighlighterFn>>,
    pub(crate) table_actions: Option<Arc<TableActionsFn>>,
    pub(crate) image_source: Option<Arc<super::text_view::ImageSourceFn>>,
    pub(crate) link_click_handler: Option<Arc<LinkClickHandlerFn>>,
    pub(crate) markdown_extensions: Arc<MarkdownExtensions>,
    /// This frame's streamed fade-in, when any text is still fading.
    pub(crate) stream_fade: Option<Arc<StreamFadeFrame>>,
    /// The application's range highlights, when there are any.
    pub(crate) range_highlights: Option<Arc<RangeHighlightFrame>>,
    /// The line being scrolled into view, when there is one.
    pub(crate) reveal: Option<RevealRequest>,
    /// The font size the text view inherits this frame, or zero when not
    /// resolved; read it through `body_font_size`.
    pub(crate) body_font_size: Pixels,
}

impl NodeContext {
    fn image_source(&self, image: &ImageNode) -> ImageSource {
        match &self.image_source {
            Some(resolve) => resolve(&image.url),
            None => image.source(),
        }
    }

    pub(super) fn add_ref(&mut self, identifier: SharedString, link: LinkMark) {
        self.link_refs.insert(identifier, link);
    }

    /// The fade ranges of the text leaf `key`, in its rendered byte space.
    fn stream_fades(&self, key: Option<TextLeafKey>) -> &[(Range<usize>, f32)] {
        match (&self.stream_fade, key) {
            (Some(frame), Some(key)) => frame.fades(key).unwrap_or_default(),
            _ => &[],
        }
    }

    /// The range highlight backgrounds of the text leaf `key`, in its
    /// rendered byte space.
    fn range_backgrounds(&self, key: Option<TextLeafKey>) -> &[(Range<usize>, Hsla)] {
        match (&self.range_highlights, key) {
            (Some(frame), Some(key)) => frame.backgrounds(key),
            _ => &[],
        }
    }

    /// The pending reveal, when it starts in the text leaf `key` between
    /// `start` and `end`, rebased to `start`.
    fn reveal_at(&self, key: Option<TextLeafKey>, start: usize, end: usize) -> Option<RevealAt> {
        self.reveal.as_ref()?.at(key, start, end)
    }
}

impl PartialEq for NodeContext {
    fn eq(&self, other: &Self) -> bool {
        self.link_refs == other.link_refs && self.style == other.style
        // Note: code_block_actions, table_actions and markdown_extensions are
        // intentionally not compared (closures can't be compared)
    }
}

/// The text color with more contrast against a highlight composited over the
/// theme background (WCAG relative luminance).
fn mark_text_color(highlight: Hsla, background: Hsla) -> Hsla {
    fn channel(value: f32) -> f32 {
        if value <= 0.04045 {
            value / 12.92
        } else {
            ((value + 0.055) / 1.055).powf(2.4)
        }
    }
    let rgb = background.to_rgb().blend(highlight.to_rgb());
    let luminance = 0.2126 * channel(rgb.r) + 0.7152 * channel(rgb.g) + 0.0722 * channel(rgb.b);
    // Contrast with black is (L + 0.05) / 0.05 and with white 1.05 / (L + 0.05);
    // they are equal where (L + 0.05)^2 = 0.0525.
    if (luminance + 0.05) * (luminance + 0.05) > 0.0525 {
        gpui::black()
    } else {
        gpui::white()
    }
}

/// The highlight a text mark renders with. The link decoration is applied by
/// the caller, which also has to record the link range.
fn mark_highlight(mark: &TextMark, node_cx: &NodeContext, cx: &App) -> InlineHighlight {
    let mut highlight = HighlightStyle::default();
    if mark.bold {
        highlight.font_weight = Some(FontWeight::BOLD);
    }
    if mark.italic {
        highlight.font_style = Some(FontStyle::Italic);
    }
    if mark.strikethrough {
        highlight.strikethrough = Some(gpui::StrikethroughStyle {
            thickness: gpui::px(1.),
            ..Default::default()
        });
    }
    if mark.underline {
        highlight.underline = Some(gpui::UnderlineStyle {
            thickness: gpui::px(1.),
            ..Default::default()
        });
    }
    let mut font_family = None;
    if mark.code {
        highlight = highlight.highlight(node_cx.style.inline_code_highlight());
        let style = node_cx.style.inline_code_style();
        highlight = highlight.highlight(HighlightStyle {
            color: style.text.color,
            font_weight: style.text.font_weight,
            font_style: style.text.font_style,
            underline: style.text.underline,
            strikethrough: style.text.strikethrough,
            ..Default::default()
        });
        font_family = Some(
            style
                .text
                .font_family
                .clone()
                .unwrap_or_else(|| cx.theme().tokens.typography.mono.clone()),
        );
    }
    if let Some(color) = mark.highlight {
        highlight.background_color = Some(color);
        // Set the text color with the background, as the HTML standard's
        // `mark { background: yellow; color: black }` does, so a light
        // highlight stays readable in a dark theme.
        // A transparent mark leaves the underlying surface unchanged. Keep
        // its inherited foreground, including on custom-colored surfaces.
        if color.a > 0.0 {
            highlight.color = Some(mark_text_color(color, cx.theme().tokens.colors.background));
        }
    }
    InlineHighlight {
        style: highlight,
        font_family,
        font_size_scale: mark.code.then_some(0.875),
        code_style: mark.code.then(|| node_cx.style.inline_code_style().clone()),
    }
}

impl Paragraph {
    /// The highlights over [`Self::text`], for measuring the paragraph with
    /// the runs it renders with. Link colors are left out: they do not move
    /// glyphs.
    fn inline_highlights(
        &self,
        node_cx: &NodeContext,
        cx: &App,
    ) -> Vec<(Range<usize>, InlineHighlight)> {
        let mut highlights = vec![];
        let mut offset = 0;
        for inline_node in &self.children {
            let node_highlights = inline_node
                .marks
                .iter()
                .map(|(range, mark)| {
                    (
                        (offset + range.start)..(offset + range.end),
                        mark_highlight(mark, node_cx, cx),
                    )
                })
                .collect::<Vec<_>>();
            highlights = combine_highlights(highlights, node_highlights);
            offset += inline_node.text.len();
        }
        highlights
    }

    /// `fade_key` names this paragraph's text for the streamed fade-in and
    /// for range highlights; the owning block supplies it because a heading
    /// or table cell paragraph carries no span of its own.
    fn render(
        &self,
        fade_key: Option<TextLeafKey>,
        node_cx: &NodeContext,
        _window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let children = &self.children;
        let fades = node_cx.stream_fades(fade_key);
        let backgrounds = node_cx.range_backgrounds(fade_key);

        if self.should_render_inline_flow() {
            return InlineFlow::new(
                leaf_element_id(fade_key),
                self.inline_flow_items(fade_key, fades, backgrounds, node_cx, cx),
                node_cx.link_click_handler.clone(),
            )
            .editor_key(self.leaf_key())
            .into_any_element();
        }

        let has_image = children.iter().any(|child| child.image.is_some());
        // Text alone is one `Inline`, which needs no box of its own, and its
        // text, highlights and links are cached across frames.
        if !has_image {
            let (text, highlights, mut links) = self.plain_render(node_cx, cx);
            // An editor leaf is laid out even when empty, so the editor gets
            // a line box for the caret.
            if text.is_empty() && self.leaf_key().is_none() {
                return div().into_any_element();
            }
            for (_, link_mark) in &mut links {
                if let Some(identifier) = link_mark.identifier.as_ref()
                    && let Some(mark) = node_cx.link_refs.get(identifier)
                {
                    *link_mark = mark.clone();
                }
            }
            let highlights = fade_highlights(highlights, &slice_fades(fades, 0, text.len()));
            let backgrounds = slice_backgrounds(backgrounds, 0, text.len());
            let reveal = node_cx.reveal_at(fade_key, 0, text.len());
            if let Ok(mut state) = self.state.lock() {
                state.set_text(text);
            }
            return Inline::new(
                self.state.clone(),
                links,
                highlights,
                node_cx.link_click_handler.clone(),
            )
            .range_backgrounds(backgrounds)
            .reveal(reveal)
            .into_any_element();
        }

        let mut child_nodes: Vec<AnyElement> = vec![];

        let mut text = String::new();
        let mut highlights: Vec<(Range<usize>, InlineHighlight)> = vec![];
        let mut links: Vec<(Range<usize>, LinkMark)> = vec![];
        let mut offset = 0;
        // Where `text` starts in the paragraph's whole rendered text, which
        // is the byte space the fade ranges use.
        let mut consumed = 0;

        for (ix, inline_node) in children.iter().enumerate() {
            let text_len = inline_node.text.len();
            text.push_str(&inline_node.text);

            if let Some(image) = &inline_node.image {
                if text.len() > 0 {
                    if let Ok(mut state) = inline_node.state.lock() {
                        state.set_text(text.clone().into());
                    }
                    child_nodes.push(
                        Inline::new(
                            inline_node.state.clone(),
                            links.clone(),
                            fade_highlights(
                                highlights.clone(),
                                &slice_fades(fades, consumed, consumed + text.len()),
                            ),
                            node_cx.link_click_handler.clone(),
                        )
                        .range_backgrounds(slice_backgrounds(
                            backgrounds,
                            consumed,
                            consumed + text.len(),
                        ))
                        .reveal(node_cx.reveal_at(fade_key, consumed, consumed + text.len()))
                        .into_any_element(),
                    );
                }
                let link_click_handler = node_cx.link_click_handler.clone();
                child_nodes.push(
                    img(node_cx.image_source(image))
                        .id(ix)
                        .object_fit(ObjectFit::Contain)
                        .max_w(relative(1.))
                        .when_some(image.width, |this, width| this.w(width))
                        .when_some(image.link.clone(), |this, link| {
                            let link_click_handler = link_click_handler.clone();
                            let aux_link = link.clone();
                            let aux_link_click_handler = link_click_handler.clone();
                            this.cursor_pointer()
                                .on_click(move |event, window, cx| {
                                    crate::TextSelection::end(window, cx);
                                    cx.stop_propagation();
                                    handle_link_click(
                                        &link_click_handler,
                                        link.url.clone(),
                                        event.clone(),
                                        window,
                                        cx,
                                    );
                                })
                                .on_aux_click(move |event, window, cx| {
                                    crate::TextSelection::end(window, cx);
                                    cx.stop_propagation();
                                    handle_link_click(
                                        &aux_link_click_handler,
                                        aux_link.url.clone(),
                                        event.clone(),
                                        window,
                                        cx,
                                    );
                                })
                        })
                        .into_any_element(),
                );

                consumed += text.len();
                text.clear();
                links.clear();
                highlights.clear();
                offset = 0;
            } else {
                let mut node_highlights = vec![];
                for (range, style) in &inline_node.marks {
                    let inner_range = (offset + range.start)..(offset + range.end);
                    let mut highlight = mark_highlight(style, node_cx, cx);

                    if let Some(mut link_mark) = style.link.clone() {
                        highlight.style.color = Some(node_cx.style.link());
                        highlight.style.underline = Some(link_underline(&node_cx.style));

                        // convert link references, replace link
                        if let Some(identifier) = link_mark.identifier.as_ref() {
                            if let Some(mark) = node_cx.link_refs.get(identifier) {
                                link_mark = mark.clone();
                            }
                        }

                        links.push((inner_range.clone(), link_mark));
                    }

                    node_highlights.push((inner_range, highlight));
                }

                highlights = combine_highlights(highlights, node_highlights);
                offset += text_len;
            }
        }

        // Add the last text node
        if text.len() > 0 {
            let text_end = consumed + text.len();
            let highlights = fade_highlights(highlights, &slice_fades(fades, consumed, text_end));
            if let Ok(mut state) = self.state.lock() {
                state.set_text(text.into());
            }
            child_nodes.push(
                Inline::new(
                    self.state.clone(),
                    links,
                    highlights,
                    node_cx.link_click_handler.clone(),
                )
                .range_backgrounds(slice_backgrounds(backgrounds, consumed, text_end))
                .reveal(node_cx.reveal_at(fade_key, consumed, text_end))
                .into_any_element(),
            );
        }

        // Text alone is one `Inline`, which needs no box of its own. Images
        // keep an identified box: an image's element state is its animation,
        // and the box scopes that state per paragraph.
        if !has_image {
            return child_nodes
                .pop()
                .unwrap_or_else(|| div().into_any_element());
        }

        div()
            .id(leaf_element_id(fade_key))
            .children(child_nodes)
            .into_any_element()
    }

    /// The key an external editor gave this leaf, if any.
    fn leaf_key(&self) -> Option<u64> {
        self.state.lock().ok().and_then(|state| state.editor_key)
    }

    fn should_render_inline_flow(&self) -> bool {
        let has_image = self.children.iter().any(|child| child.image.is_some());
        let has_text = self.children.iter().any(|child| !child.text.is_empty());
        // An editor leaf with an image always uses the flow, which reports
        // its pieces to the editor (an image-only paragraph would otherwise
        // take the plain image path, which reports nothing).
        if has_image && self.leaf_key().is_some() {
            return true;
        }
        self.children.iter().any(|child| child.custom.is_some())
            || (has_image && has_text)
            || self
                .children
                .iter()
                .any(|child| child.marks.iter().any(|(_, mark)| mark.code))
    }

    fn inline_flow_items(
        &self,
        leaf_key: Option<TextLeafKey>,
        fades: &[(Range<usize>, f32)],
        backgrounds: &[(Range<usize>, Hsla)],
        node_cx: &NodeContext,
        cx: &mut App,
    ) -> Vec<InlineFlowItem> {
        let mut items = Vec::new();
        let mut text = String::new();
        let mut highlights: Vec<(Range<usize>, InlineHighlight)> = vec![];
        let mut links: Vec<(Range<usize>, LinkMark)> = vec![];
        let mut offset = 0;
        // Where `text` starts in the paragraph's whole rendered text, which
        // is the byte space the fade and background ranges use.
        let mut consumed = 0;

        for inline_node in &self.children {
            if let Some(node) = &inline_node.custom {
                if let Ok(mut state) = inline_node.state.lock() {
                    state.set_text(text.clone().into());
                }
                if !text.is_empty() {
                    let item_fades = slice_fades(fades, consumed, consumed + text.len());
                    let item_backgrounds =
                        slice_backgrounds(backgrounds, consumed, consumed + text.len());
                    let item_reveal = node_cx.reveal_at(leaf_key, consumed, consumed + text.len());
                    consumed += text.len();
                    items.push(InlineFlowItem::Text {
                        state: inline_node.state.clone(),
                        text: std::mem::take(&mut text).into(),
                        links: std::mem::take(&mut links),
                        highlights: fade_highlights(std::mem::take(&mut highlights), &item_fades),
                        backgrounds: item_backgrounds,
                        reveal: item_reveal,
                    });
                }
                let mut object_style = HighlightStyle::default();
                let mut object_link = None;
                for (_, mark) in &inline_node.marks {
                    object_style = object_style.highlight(mark_highlight(mark, node_cx, cx).style);
                    if let Some(link) = &mark.link {
                        object_link = Some(
                            link.identifier
                                .as_ref()
                                .and_then(|id| node_cx.link_refs.get(id))
                                .unwrap_or(link)
                                .clone(),
                        );
                        object_style.color = Some(node_cx.style.link());
                        object_style.underline = Some(link_underline(&node_cx.style));
                    }
                }
                let rendered_node = node.clone();
                let extensions = node_cx.markdown_extensions.clone();
                items.push(InlineFlowItem::Object {
                    text: node.shared_text(),
                    accessibility_label: node.shared_accessibility_name(),
                    id: node.source_range().map_or(items.len(), |range| range.start),
                    renderer: Arc::new(move |context, window, cx| {
                        extensions.render_inline(&rendered_node, context, window, cx)
                    }),
                    selected: inline_node.custom_selection.clone(),
                    style: object_style,
                    link: object_link,
                });
                consumed += inline_node.text.len();
                offset = 0;
                continue;
            }
            let text_len = inline_node.text.len();
            text.push_str(&inline_node.text);

            if let Some(image) = &inline_node.image {
                if !text.is_empty() {
                    if let Ok(mut state) = inline_node.state.lock() {
                        state.set_text(text.clone().into());
                    }
                    items.push(InlineFlowItem::Text {
                        state: inline_node.state.clone(),
                        text: text.clone().into(),
                        links: links.clone(),
                        highlights: fade_highlights(
                            highlights.clone(),
                            &slice_fades(fades, consumed, consumed + text.len()),
                        ),
                        backgrounds: slice_backgrounds(
                            backgrounds,
                            consumed,
                            consumed + text.len(),
                        ),
                        reveal: node_cx.reveal_at(leaf_key, consumed, consumed + text.len()),
                    });
                }

                items.push(InlineFlowItem::Image {
                    source: node_cx.image_source(image),
                    link: image.link.clone(),
                    title: image.title(),
                    width: image.width,
                    height: image.height,
                });

                consumed += text.len();
                text.clear();
                links.clear();
                highlights.clear();
                offset = 0;
            } else {
                let mut node_highlights = vec![];
                for (range, style) in &inline_node.marks {
                    let inner_range = (offset + range.start)..(offset + range.end);
                    let mut highlight = mark_highlight(style, node_cx, cx);

                    if let Some(mut link_mark) = style.link.clone() {
                        highlight.style.color = Some(node_cx.style.link());
                        highlight.style.underline = Some(link_underline(&node_cx.style));

                        if let Some(identifier) = link_mark.identifier.as_ref()
                            && let Some(mark) = node_cx.link_refs.get(identifier)
                        {
                            link_mark = mark.clone();
                        }

                        links.push((inner_range.clone(), link_mark));
                    }

                    node_highlights.push((inner_range, highlight));
                }

                highlights = combine_highlights(highlights, node_highlights);
                offset += text_len;
            }
        }

        if !text.is_empty() {
            if let Ok(mut state) = self.state.lock() {
                state.set_text(text.clone().into());
            }
            let highlights = fade_highlights(
                highlights,
                &slice_fades(fades, consumed, consumed + text.len()),
            );
            let backgrounds = slice_backgrounds(backgrounds, consumed, consumed + text.len());
            let reveal = node_cx.reveal_at(leaf_key, consumed, consumed + text.len());
            items.push(InlineFlowItem::Text {
                state: self.state.clone(),
                text: text.into(),
                links,
                highlights,
                backgrounds,
                reveal,
            });
        }

        items
    }
}

/// The element id of a block that needs one, from `kind` and the block's
/// source start, which is unique across a parsed Markdown document. The HTML
/// parser records no spans, so its blocks fall back to their index among
/// their siblings: unique among them, though not across nesting levels.
fn block_element_id(kind: &'static str, span: Option<Span>, ix: usize) -> ElementId {
    (kind, span.map_or(ix, |span| span.start)).into()
}

/// The element id of a paragraph that needs one: an inline flow, whose
/// objects are accessibility nodes, or an image, whose element state is its
/// animation. The leaf key is unique per paragraph in a parsed Markdown
/// document; the HTML parser records no spans, so its paragraphs share one.
fn leaf_element_id(fade_key: Option<TextLeafKey>) -> ElementId {
    fade_key.map_or_else(|| ElementId::from("p"), ElementId::from)
}

/// A link's underline: a hairline in a translucent link color, so a run of
/// links reads as text first and as links second.
fn link_underline(style: &TextViewStyle) -> gpui::UnderlineStyle {
    gpui::UnderlineStyle {
        thickness: px(1.),
        color: Some(style.link().opacity(0.4)),
        ..Default::default()
    }
}

/// The font size the blocks inherit, which heading sizes and the spacing of
/// lists, tables and rules are proportional to (like CSS `em`), so a compact
/// 14px view and a 16px document keep the same rhythm.
///
/// Resolved once per frame into the context; a context built without it
/// (as in tests) resolves it from the window.
fn body_font_size(node_cx: &NodeContext, window: &Window) -> Pixels {
    if node_cx.body_font_size > Pixels::ZERO {
        node_cx.body_font_size
    } else {
        window.text_style().font_size.to_pixels(window.rem_size())
    }
}

/// A heading's `(size scale, line height, section gap)`, the size relative to
/// the body text and the gap above it relative to the heading itself.
/// Hierarchy comes from weight rather than size: every level is semibold and
/// the sizes step down gently from the body.
fn heading_metrics(level: u8) -> (f32, f32, f32) {
    match level {
        1 => (1.8, 1.25, 1.1),
        2 => (4. / 3., 1.35, 1.6),
        3 => (17. / 15., 1.35, 1.4),
        4 => (1., 1.35, 1.4),
        5 => (14. / 15., 1.35, 1.4),
        _ => (13. / 15., 1.35, 1.4),
    }
}

/// The gap below a heading, relative to the heading's size.
const HEADING_BOTTOM_GAP: f32 = 0.35;

/// The size a heading renders at, including one a caller's heading
/// refinement pins, which its gaps follow.
fn heading_size(level: u8, node_cx: &NodeContext, window: &Window) -> Pixels {
    node_cx.style.heading(level).text.font_size.map_or_else(
        || body_font_size(node_cx, window) * heading_metrics(level).0,
        |size| size.to_pixels(window.rem_size()),
    )
}

/// The room above and below a horizontal rule.
fn rule_space(body_font_size: Pixels) -> Pixels {
    body_font_size * 1.6
}

/// The gap below a block: a paragraph gap, unless nothing follows it.
fn block_gap(options: &NodeRenderOptions, style: &TextViewStyle) -> Rems {
    if options.in_list || options.is_last {
        rems(0.)
    } else {
        style.paragraph_gap()
    }
}

/// `block` with `gap` below it. The box only exists to hold the padding,
/// so a block with no gap below it is returned as is.
fn gapped(block: AnyElement, gap: Rems) -> AnyElement {
    if gap.is_zero() {
        block
    } else {
        div().pb(gap).child(block).into_any_element()
    }
}

/// The fade ranges overlapping `start..end`, rebased to start at `start`.
fn slice_fades(
    fades: &[(Range<usize>, f32)],
    start: usize,
    end: usize,
) -> Vec<(Range<usize>, f32)> {
    slice_ranges(fades, start, end, |range, fade_out| (range, *fade_out))
}

/// The range highlight backgrounds overlapping `start..end`, rebased to
/// start at `start`.
fn slice_backgrounds(
    backgrounds: &[(Range<usize>, Hsla)],
    start: usize,
    end: usize,
) -> Vec<(Range<usize>, Hsla)> {
    slice_ranges(backgrounds, start, end, |range, color| (range, *color))
}

/// A table column's cell widths for layout, excluding the divider after it.
struct TableColumn {
    /// The width that fits the content on its widest line.
    max: f32,
    /// The width below which the column stops shrinking.
    min: f32,
    divider: f32,
}

/// Horizontal padding of a table cell: `px_3` unless `style.table_cell`
/// sets it.
fn table_cell_padding_x(style: &TextViewStyle, rem_size: Pixels) -> f32 {
    let padding = &style.table_cell().padding;
    let side = |length: Option<DefiniteLength>| match length {
        Some(DefiniteLength::Absolute(length)) => f32::from(length.to_pixels(rem_size)),
        _ => CELL_PAD_PX / 2.,
    };
    side(padding.left) + side(padding.right)
}

const CELL_PAD_PX: f32 = 24.0; // px_3 horizontal padding
const CELL_MIN_PX: f32 = 48.0;
const CELL_BORDER_PX: f32 = 1.0; // border_r_1 drawn by every column but the last

/// The max-content width of every table column: the widest cell line,
/// shaped with the runs the cell renders with, plus the cell's padding and
/// border. Never capped: a cap would clip overflowing text *and* leave it
/// outside the scrollable width, making it unreachable.
fn measure_table_columns(
    table: &Table,
    col_count: usize,
    node_cx: &NodeContext,
    window: &mut Window,
    cx: &mut App,
) -> Vec<f32> {
    let text_styles = TableTextStyles::new(&node_cx.style, window);
    let rem_size = window.rem_size();
    let mono_family = cx.theme().tokens.typography.mono.clone();
    let inline_code = node_cx.style.inline_code_highlight();
    let cached = table.column_widths_cache.0.lock().ok().and_then(|cache| {
        cache
            .as_ref()
            .filter(|cached| {
                cached.widths.len() == col_count
                    && cached.text_styles == text_styles
                    && cached.rem_size == rem_size
                    && cached.mono_family == mono_family
                    && cached.inline_code == inline_code
                    && cached.text_system == text_system_id(window)
            })
            .cloned()
    });
    let measured = cached.unwrap_or_else(|| {
        let (widths, custom_cells) =
            measure_table_text_columns(table, col_count, &text_styles, node_cx, window, cx);
        let measured = Arc::new(TableColumnWidths {
            text_system: text_system_id(window),
            text_styles: text_styles.clone(),
            rem_size,
            mono_family,
            inline_code,
            widths,
            custom_cells,
        });
        if let Ok(mut cache) = table.column_widths_cache.0.lock() {
            *cache = Some(measured.clone());
        }
        measured
    });

    // Resource-backed cells must be measured again, even when their text is
    // unchanged. Keep callbacks outside the cache lock and do not retain their
    // widths: a loaded image or a plugin can get narrower as well as wider.
    let mut col_w = measured.widths.clone();
    for &(row_ix, ix) in &measured.custom_cells {
        let cell = &table.children[row_ix].children[ix];
        let items = cell.children.inline_flow_items(None, &[], &[], node_cx, cx);
        let style = text_styles.row_refinement(row_ix).clone();
        let width = window.with_text_style(Some(style), |window| {
            super::inline_flow::intrinsic_width(&items, window, cx)
        });
        let border = if ix + 1 < col_count {
            CELL_BORDER_PX
        } else {
            0.
        };
        col_w[ix] = col_w[ix].max(f32::from(width) + CELL_PAD_PX + border);
    }
    col_w
}

// The first measurement still visits all ordinary cells. This cache avoids
// repeating that work; it is not a budget for the initial table layout.
fn measure_table_text_columns(
    table: &Table,
    col_count: usize,
    text_styles: &TableTextStyles,
    node_cx: &NodeContext,
    window: &mut Window,
    cx: &mut App,
) -> (Vec<f32>, Vec<(usize, usize)>) {
    let mut col_w = vec![CELL_MIN_PX; col_count];
    let mut custom_cells = Vec::new();
    for (row_ix, row) in table.children.iter().enumerate() {
        let text_style = text_styles.row(row_ix);
        let font_size = text_style.font_size.to_pixels(window.rem_size());
        for (ix, cell) in row.children.iter().enumerate() {
            let Some(slot) = col_w.get_mut(ix) else {
                continue;
            };
            if cell
                .children
                .children
                .iter()
                .any(|node| node.custom.is_some())
            {
                custom_cells.push((row_ix, ix));
                continue;
            }
            let text = cell.children.text();
            let highlights = cell.children.inline_highlights(node_cx, cx);
            let mut w = 0.0_f32;
            let mut line_start = 0;
            for line in text.split('\n') {
                let start = line_start + (line.len() - line.trim_start().len());
                let line_end = line_start + line.len();
                line_start = line_end + 1;
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }
                let end = start + line.len();
                let line_highlights = highlights
                    .iter()
                    .filter_map(|(range, highlight)| {
                        let clipped = range.start.max(start)..range.end.min(end);
                        (clipped.start < clipped.end).then(|| {
                            (
                                clipped.start - start..clipped.end - start,
                                highlight.clone(),
                            )
                        })
                    })
                    .collect::<Vec<_>>();
                let mut line_w = gpui::Pixels::ZERO;
                for (range, scale) in
                    text_size_ranges(line.len(), &line_highlights, font_size, window.rem_size())
                {
                    let highlights = slice_ranges(
                        &line_highlights,
                        range.start,
                        range.end,
                        |range, highlight| (range, highlight.clone()),
                    );
                    let insets = code_insets(&highlights, font_size * scale, window.rem_size());
                    line_w += insets.left + insets.right;
                    let runs = text_runs(range.len(), text_style, &highlights);
                    line_w += window
                        .text_system()
                        .layout_line(&line[range], font_size * scale, &runs, None)
                        .width;
                }
                w = w.max(f32::from(line_w));
            }
            // Border-box widths, so the padding and border the cell draws
            // must leave the measured text its full width.
            let border = if ix + 1 < col_count {
                CELL_BORDER_PX
            } else {
                0.
            };
            *slot = slot.max(w + CELL_PAD_PX + border);
        }
    }
    (col_w, custom_cells)
}

impl Paragraph {
    fn to_markdown(&self) -> String {
        if self.children.iter().any(|node| node.custom.is_some()) {
            let mut source = MarkdownSource::default();
            for node in &self.children {
                if node.custom.is_some() {
                    source.push_object(node);
                } else {
                    source.push_text(&node.text, &node.marks, 0..node.text.len());
                    if let Some(image) = &node.image {
                        source.push_str(&image_markdown(image));
                    }
                }
            }
            let mut text = source.finish();
            text.push_str("\n\n");
            return text;
        }
        let mut text = self
            .children
            .iter()
            .map(|text_node| {
                let mut text = text_node.text.to_string();
                for (range, style) in &text_node.marks {
                    if style.bold {
                        text = format!("**{}**", &text_node.text[range.clone()]);
                    }
                    if style.italic {
                        text = format!("*{}*", &text_node.text[range.clone()]);
                    }
                    if style.strikethrough {
                        text = format!("~~{}~~", &text_node.text[range.clone()]);
                    }
                    if style.code {
                        text = format!("`{}`", &text_node.text[range.clone()]);
                    }
                    if style.highlight.is_some() {
                        text = format!("=={}==", &text_node.text[range.clone()]);
                    }
                    if let Some(link) = &style.link {
                        text = format!("[{}]({})", &text_node.text[range.clone()], link.url);
                    }
                }

                if let Some(image) = &text_node.image {
                    let alt = image.alt.clone().unwrap_or_default();
                    let title = image
                        .title
                        .clone()
                        .map_or(String::new(), |t| format!(" \"{}\"", t));
                    text.push_str(&format!("![{}]({}{})", alt, image.url, title))
                }

                text
            })
            .collect::<Vec<_>>()
            .join("");

        text.push_str("\n\n");
        text
    }
}

impl BlockNode {
    /// Converts the node to markdown format.
    ///
    /// This is used to generate markdown for test.
    #[allow(dead_code)]
    pub(crate) fn to_markdown(&self) -> String {
        match self {
            BlockNode::Root { children, .. } => children
                .iter()
                .map(|child| child.to_markdown())
                .collect::<Vec<_>>()
                .join("\n\n"),
            BlockNode::Paragraph(paragraph) => paragraph.to_markdown(),
            BlockNode::Heading {
                level, children, ..
            } => {
                let hashes = "#".repeat(*level as usize);
                format!("{} {}", hashes, children.to_markdown())
            }
            BlockNode::Blockquote { children, .. } => {
                let content = children
                    .iter()
                    .map(|child| child.to_markdown())
                    .collect::<Vec<_>>()
                    .join("\n\n");

                content
                    .lines()
                    .map(|line| format!("> {}", line))
                    .collect::<Vec<_>>()
                    .join("\n")
            }
            BlockNode::List {
                children,
                ordered,
                start,
                ..
            } => children
                .iter()
                .enumerate()
                .map(|(i, child)| {
                    let prefix = if *ordered {
                        format!("{}. ", ordered_list_ordinal(*start, i))
                    } else {
                        "- ".to_string()
                    };
                    format!("{}{}", prefix, child.to_markdown())
                })
                .collect::<Vec<_>>()
                .join("\n"),
            BlockNode::ListItem {
                children, checked, ..
            } => {
                let checkbox = if let Some(checked) = checked {
                    if *checked { "[x] " } else { "[ ] " }
                } else {
                    ""
                };
                format!(
                    "{}{}",
                    checkbox,
                    children
                        .iter()
                        .map(|child| child.to_markdown())
                        .collect::<Vec<_>>()
                        .join("\n")
                )
            }
            BlockNode::CodeBlock(code_block) => {
                format!(
                    "```{}\n{}\n```",
                    code_block.lang.clone().unwrap_or_default(),
                    code_block.code()
                )
            }
            BlockNode::Table(table) => table.to_markdown(),
            BlockNode::Break { html, .. } => {
                if *html {
                    "<br>".to_string()
                } else {
                    "\n".to_string()
                }
            }
            BlockNode::HorizontalRule { .. } => "---".to_string(),
            BlockNode::Custom { node, .. } => node.to_markdown(),
            BlockNode::Definition {
                identifier,
                url,
                title,
                ..
            } => {
                if let Some(title) = title {
                    format!("[{}]: {} \"{}\"", identifier, url, title)
                } else {
                    format!("[{}]: {}", identifier, url)
                }
            }
            BlockNode::Unknown { .. } => "".to_string(),
        }
        .trim()
        .to_string()
    }
}

impl BlockNode {
    fn render_list_item_row(
        content: AnyElement,
        ix: usize,
        options: NodeRenderOptions,
        checked: Option<bool>,
        style: &TextViewStyle,
        line_height: Pixels,
        indent: Pixels,
    ) -> Div {
        h_flex()
            .w_full()
            .min_w_0()
            .relative()
            .items_start()
            .content_start()
            .when(!options.todo && checked.is_none(), |this| {
                // The marker hangs in an indent column, right-aligned against
                // the text like an outside list marker, and steps back in
                // color so the item text leads.
                this.child(
                    div()
                        .flex_none()
                        .min_w(indent)
                        .pr(indent * 0.3)
                        .text_right()
                        .text_color(style.muted_foreground())
                        .refine_style(style.list_style())
                        .child(
                            list_item_prefix(
                                ix,
                                options.list_start,
                                options.ordered,
                                options.depth,
                            )
                            .trim_end()
                            .to_string(),
                        ),
                )
            })
            .when_some(checked, |this, checked| {
                // Todo list checkbox
                let check_svg = if style.is_dark() {
                    CHECK_SVG_DARK
                } else {
                    CHECK_SVG_LIGHT
                };
                this.child(
                    div()
                        .flex()
                        .mr_2()
                        .h(line_height)
                        .flex_none()
                        .items_center()
                        .justify_center()
                        .child(
                            div()
                                .flex()
                                .size(rems(0.9375))
                                .items_center()
                                .justify_center()
                                .rounded(px(4.))
                                .border(px(1.5))
                                .border_color(
                                    style
                                        .list_style()
                                        .text
                                        .color
                                        .unwrap_or(style.muted_foreground()),
                                )
                                .when(checked, |this| {
                                    this.bg(style.link()).border_color(style.link()).child(
                                        img(Arc::new(Image::from_bytes(
                                            ImageFormat::Svg,
                                            check_svg.to_vec(),
                                        )))
                                        .size(rems(0.75)),
                                    )
                                }),
                        ),
                )
            })
            .child(
                div()
                    // Include the body in intrinsic width measurement, while
                    // still letting it shrink and wrap in a constrained row.
                    .flex_auto()
                    .min_w_0()
                    .overflow_hidden()
                    // A done task steps back so the open ones stand out.
                    .when(checked == Some(true), |this| {
                        this.text_color(style.muted_foreground())
                    })
                    .child(content),
            )
    }

    fn render_list_item(
        item: &BlockNode,
        ix: usize,
        options: NodeRenderOptions,
        node_cx: &NodeContext,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        match item {
            BlockNode::ListItem {
                children,
                spread,
                checked,
                ..
            } => {
                let body = body_font_size(node_cx, window);
                let indent = body * 1.4;
                div()
                    .w_full()
                    .min_w_0()
                    // Items breathe a little apart, less than paragraphs do.
                    .when(ix > 0, |this| this.pt(body * 0.25))
                    .when(*spread, |this| this.child(div()))
                    .children({
                        let mut items: Vec<Div> = Vec::with_capacity(children.len());

                        for (child_ix, child) in children.iter().enumerate() {
                            match child {
                                BlockNode::Paragraph { .. } => {
                                    let last_not_list = child_ix > 0
                                        && !matches!(
                                            children[child_ix - 1],
                                            BlockNode::List { .. }
                                        );

                                    let text = child.render_block(
                                        NodeRenderOptions {
                                            depth: options.depth + 1,
                                            todo: checked.is_some(),
                                            is_last: true,
                                            ..options
                                        },
                                        node_cx,
                                        window,
                                        cx,
                                    );

                                    // Continuation paragraph — stack vertically below
                                    // the previous row, indented to align with the text
                                    // column (past bullet/number prefix).
                                    if last_not_list {
                                        if let Some(preceding_row) = items.pop() {
                                            items.push(
                                                div().child(preceding_row).child(
                                                    div()
                                                        .w_full()
                                                        .pl(indent)
                                                        .overflow_hidden()
                                                        .child(text),
                                                ),
                                            );
                                            continue;
                                        }
                                    }

                                    items.push(Self::render_list_item_row(
                                        text,
                                        ix,
                                        options,
                                        *checked,
                                        &node_cx.style,
                                        window.line_height(),
                                        indent,
                                    ));
                                }
                                BlockNode::List { .. } => {
                                    items.push(div().ml(indent).child(child.render_block(
                                        NodeRenderOptions {
                                            depth: options.depth + 1,
                                            todo: checked.is_some(),
                                            is_last: true,
                                            ..options
                                        },
                                        node_cx,
                                        window,
                                        cx,
                                    )));
                                }
                                BlockNode::Root { .. }
                                | BlockNode::Heading { .. }
                                | BlockNode::Blockquote { .. }
                                | BlockNode::CodeBlock(_)
                                | BlockNode::Custom { .. }
                                | BlockNode::Table(_)
                                | BlockNode::HorizontalRule { .. } => {
                                    let block = child.render_block(
                                        NodeRenderOptions {
                                            depth: options.depth + 1,
                                            todo: checked.is_some(),
                                            is_last: true,
                                            ..options
                                        },
                                        node_cx,
                                        window,
                                        cx,
                                    );

                                    if child_ix == 0 {
                                        items.push(Self::render_list_item_row(
                                            block,
                                            ix,
                                            options,
                                            *checked,
                                            &node_cx.style,
                                            window.line_height(),
                                            indent,
                                        ));
                                    } else {
                                        // Indent continuation blocks to align with a
                                        // nested sub-list (`ml(indent)`) and with
                                        // continuation paragraphs.
                                        items.push(
                                            div()
                                                .w_full()
                                                .min_w_0()
                                                .pl(indent)
                                                .overflow_hidden()
                                                .child(block),
                                        );
                                    }
                                }
                                BlockNode::ListItem { .. }
                                | BlockNode::Break { .. }
                                | BlockNode::Definition { .. }
                                | BlockNode::Unknown => {}
                            }
                        }
                        items
                    })
                    .into_any_element()
            }
            _ => div().into_any_element(),
        }
    }

    /// Render a Markdown table.
    ///
    /// Columns are sized from the measured max-content width of their cells,
    /// so they line up and fit their content on proportional fonts and mixed
    /// scripts alike. The layout adapts to the frame:
    ///
    /// - Wider than the content: every column fits its content and the spare
    ///   width is shared in proportion to it.
    /// - Narrower: the narrow columns keep their full content width and only
    ///   the widest ones shrink and wrap, all down to one common width (see
    ///   [`Self::render_table_rows`]). Shrinking every column by the same
    ///   ratio would wrap the last word or character of a column that nearly
    ///   fits onto a line of its own.
    /// - Narrower than the column floors: the default layout clips, while
    ///   `style.table` overflow-x: scroll keeps the floors and scrolls
    ///   horizontally, so no content ever becomes unreachable.
    ///
    /// `white_space: nowrap` on `style.table_cell` composes like in CSS: the
    /// refinement keeps cell text on a single line, and the scroll layout
    /// raises the floors to the full content widths so the single-line
    /// columns never shrink.
    fn render_table(
        item: &BlockNode,
        options: &NodeRenderOptions,
        node_cx: &NodeContext,
        text_size: Pixels,
        window: &mut Window,
        cx: &mut App,
    ) -> impl IntoElement {
        // A scrolling column stops shrinking (and the table starts to scroll)
        // at a floor scaled to its content: roughly the width at which the
        // text wraps to `CELL_WRAP_MAX_LINES` lines, clamped between the two
        // bounds so moderate columns can still wrap meaningfully while one
        // huge column cannot push the scroll threshold arbitrarily high.
        const CELL_WRAP_MAX_LINES: f32 = 2.0;
        const CELL_WRAP_MIN_PX: f32 = 160.0;
        const CELL_WRAP_MAX_PX: f32 = 480.0;
        const TABLE_BORDER_PX: f32 = 2.0; // the frame's border_1, left + right

        let table = match item {
            BlockNode::Table(table) => table,
            _ => return div().into_any_element(),
        };

        let style = &node_cx.style;
        let col_count = table
            .children
            .iter()
            .map(|row| row.children.len())
            .max()
            .unwrap_or(0);
        let col_w = measure_table_columns(table, col_count, node_cx, window, cx);
        let scroll = matches!(style.table().overflow.x, Some(Overflow::Scroll));
        let nowrap = style.table_cell().text.white_space == Some(WhiteSpace::Nowrap);
        let rem_size = window.rem_size();
        let wrap_min_px = f32::from(rems(4.).to_pixels(rem_size));
        // Widths were measured with the default cell padding.
        let padding_delta = table_cell_padding_x(style, rem_size) - CELL_PAD_PX;
        // Lengths are rounded to device pixels for layout. Round the content
        // widths up, or a column can lose the fraction of a pixel that keeps
        // its text on one line.
        let scale_factor = window.scale_factor();
        let device_ceil = |width: f32| (width * scale_factor).ceil() / scale_factor;
        let columns: Vec<TableColumn> = col_w
            .iter()
            .enumerate()
            .map(|(ix, &w)| {
                let w = w + padding_delta;
                let floor = if scroll && nowrap {
                    w
                } else if scroll {
                    (w / CELL_WRAP_MAX_LINES)
                        .clamp(CELL_WRAP_MIN_PX, CELL_WRAP_MAX_PX)
                        .min(w)
                } else {
                    w.min(wrap_min_px)
                };
                let divider = if ix + 1 < col_count {
                    CELL_BORDER_PX
                } else {
                    0.
                };
                let max = device_ceil(w - divider);
                TableColumn {
                    min: device_ceil(floor - divider).min(max),
                    max,
                    divider,
                }
            })
            .collect();

        let rows = Self::render_table_rows(table, &columns, node_cx, window, cx);
        let frame = StyleRefinement::default()
            .text_size(text_size)
            .bg(style
                .table_background()
                .unwrap_or(cx.theme().tokens.colors.surface))
            .border_1()
            .border_color(style.border())
            .refine_style(style.table());
        let body = if scroll {
            let scroll_handle = window
                .use_keyed_state(
                    block_element_id("table-scroll", table.span, options.ix),
                    cx,
                    |_, _| ScrollHandle::default(),
                )
                .read(cx)
                .clone();
            let min_total_w = columns
                .iter()
                .map(|column| column.min + column.divider)
                .sum::<f32>()
                + TABLE_BORDER_PX;
            // Scroll viewport owns the visible frame, including any
            // caller-provided radius. Keeping the border here makes the
            // rounded frame stable while the wider row track moves below it.
            //
            // `horizontal_scroll_area` clips with `overflow_hidden` and
            // delegates the wheel to a sibling `ScrollableMask`, so the
            // gesture is locked to its starting axis and a horizontal swipe
            // is consumed before an ancestor scroller (`gpui::list` under
            // `TextView::scrollable`) can take its vertical component.
            horizontal_scroll_area(
                block_element_id("table", table.span, options.ix),
                &scroll_handle,
                &frame,
                // Row track sized to `max(viewport, column floors)`:
                // `min_w_full` fills the frame while the columns can still
                // shrink-to-fit (their text wrapping), the definite
                // `w(min_total_w)` keeps the floors once they are reached,
                // letting the track exceed the viewport and scroll.
                div().min_w_full().w(px(min_total_w)).children(rows),
            )
            .into_any_element()
        } else {
            div()
                .w_full()
                .overflow_hidden()
                .refine_style(&frame)
                .children(rows)
                .into_any_element()
        };

        div()
            .pb(block_gap(options, style))
            .w_full()
            .child(body)
            // Custom actions row (e.g. copy / download) rendered below the
            // table. The hook's element spans full width; alignment is up to
            // the caller (e.g. `h_flex().justify_end()`). The gap keeps hover
            // backgrounds of the action buttons off the table border, and the
            // id scopes the caller's element ids per table, so plain ids like
            // `"copy"` don't collide across tables (same as code blocks).
            .children(node_cx.table_actions.clone().map(|f| {
                div()
                    .id(block_element_id("table-actions", table.span, options.ix))
                    .mt_1()
                    .child(f(&table.cached_table_data(), window, cx))
            }))
            .into_any_element()
    }

    /// Corner radii for the first and last table rows, derived from the
    /// frame radius in `style.table()`.
    ///
    /// GPUI clips children with a rectangular content mask, so a square row
    /// background (e.g. the header fill) pokes out of a rounded table frame
    /// at the corners. Rounding the first row's top and the last row's
    /// bottom corners to the frame radius — inset by the frame's 1px border
    /// sitting between frame and rows — keeps the row fills inside the
    /// frame. (A horizontally scrolled track can still meet the viewport
    /// corner with a square edge mid-scroll; only a rounded content mask
    /// could clip that, and gpui masks are rectangular.)
    fn table_row_corner_radii(style: &TextViewStyle, window: &Window) -> [Option<Pixels>; 4] {
        let rem_size = window.rem_size();
        let inset = |radius: Option<gpui::AbsoluteLength>| {
            radius.map(|radius| (radius.to_pixels(rem_size) - px(1.)).max(px(0.)))
        };
        let radii = &style.table().corner_radii;
        [
            inset(radii.top_left),
            inset(radii.top_right),
            inset(radii.bottom_left),
            inset(radii.bottom_right),
        ]
    }

    /// The table rows, each a flex row laid out on the same column grid.
    ///
    /// Every column is a cell plus slack beside it. A cell grows from zero up
    /// to its content width `max` and never below its floor `min`:
    /// flex layout grows all cells equally and freezes each one that reaches
    /// its content width, so the narrow columns fit their content and the
    /// widest ones share what is left. The slack grows only after every cell
    /// is frozen, so a frame wider than the content spreads the extra width
    /// in proportion to the columns, placed after, around or before the cell
    /// to follow the column alignment.
    ///
    /// A row with fewer cells than the table keeps empty cells in their
    /// place, so its columns line up with the other rows.
    fn render_table_rows(
        table: &Table,
        columns: &[TableColumn],
        node_cx: &NodeContext,
        window: &mut Window,
        cx: &mut App,
    ) -> Vec<AnyElement> {
        // The slack's share of the frame while any cell is still growing is
        // `SLACK_GROW / (cells * CELL_GROW)`, a negligible fraction of a
        // pixel. The slack factors still add up to `SLACK_GROW`: flex layout
        // hands out only that fraction of the free space when the factors
        // sum to less than one, and the slack must take all of it.
        const CELL_GROW: f32 = 1e6;
        const SLACK_GROW: f32 = 1.0;

        let style = &node_cx.style;
        let col_count = columns.len();
        let total_w = columns.iter().map(|column| column.max).sum::<f32>().max(1.);
        // The slack is part of the column, so it carries the cell's fill and
        // the column divider in the cell's border color.
        let mut slack_style = StyleRefinement::default();
        slack_style.background = style.table_cell().background.clone();
        slack_style.border_color = style.table_cell().border_color;
        let slack = |grow: f32| {
            div()
                .flex_basis(px(0.))
                .flex_grow(grow)
                .flex_shrink(0.)
                .border_color(style.border())
                .refine_style(&slack_style)
        };

        let row_count = table.children.len();
        let [top_left, top_right, bottom_left, bottom_right] =
            Self::table_row_corner_radii(style, window);
        let mut rows = Vec::with_capacity(row_count);
        let mut cell_ordinal = 0;
        for (row_ix, row) in table.children.iter().enumerate() {
            let mut cells = Vec::with_capacity(col_count * 2);
            for (ix, column) in columns.iter().enumerate() {
                let is_last_col = ix + 1 == col_count;
                let align = table.column_align(ix);
                let content = row.children.get(ix).map(|cell| {
                    let fade_key = table
                        .span
                        .map(|span| TextLeafKey::table_cell(span.start, cell_ordinal));
                    cell_ordinal += 1;
                    cell.children.render(fade_key, node_cx, window, cx)
                });

                let grow = SLACK_GROW * column.max / total_w;
                let (lead, trail) = match align {
                    ColumnumnAlign::None | ColumnumnAlign::Left => (0., grow),
                    ColumnumnAlign::Center => (grow / 2., grow / 2.),
                    ColumnumnAlign::Right => (grow, 0.),
                };
                if lead > 0. {
                    cells.push(slack(lead).into_any_element());
                }
                cells.push(
                    TableCellElement(
                        div()
                            .flex_basis(px(0.))
                            .flex_grow(CELL_GROW)
                            .min_w(px(column.min))
                            .max_w(px(column.max))
                            .overflow_hidden()
                            .when(align == ColumnumnAlign::Center, |this| this.text_center())
                            .when(align == ColumnumnAlign::Right, |this| this.text_right())
                            .px_3()
                            .py(px(7.))
                            .refine_style(&style.table_cell())
                            .children(content)
                            .into_any_element(),
                    )
                    .into_any_element(),
                );
                if trail > 0. || !is_last_col {
                    cells.push(
                        slack(trail)
                            .when(!is_last_col, |this| this.border_r_1())
                            .into_any_element(),
                    );
                }
            }
            rows.push(
                div()
                    .w_full()
                    .when(row_ix < row_count - 1, |this| this.border_b_1())
                    .border_color(style.border())
                    .flex()
                    .flex_row()
                    // The first row is the header, as everywhere else that
                    // reads a table (`table_data`, `to_markdown`). The
                    // refinement comes last so it can override the defaults.
                    .when(row_ix == 0, |this| {
                        this.bg(style.code_background())
                            .text_color(style.foreground())
                            .when_some(top_left, |this, radius| this.rounded_tl(radius))
                            .when_some(top_right, |this, radius| this.rounded_tr(radius))
                            .refine_style(&style.table_head())
                    })
                    .when(row_ix + 1 == row_count, |this| {
                        this.when_some(bottom_left, |this, radius| this.rounded_bl(radius))
                            .when_some(bottom_right, |this, radius| this.rounded_br(radius))
                    })
                    .children(cells)
                    .into_any_element(),
            );
        }
        rows
    }

    pub(crate) fn render_block(
        &self,
        options: NodeRenderOptions,
        node_cx: &NodeContext,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let mb = block_gap(&options, &node_cx.style);

        match self {
            BlockNode::Root { children, .. } => div()
                .children(children.into_iter().enumerate().map(move |(ix, node)| {
                    // A nested root (an HTML block container) continues the
                    // flow around it: until it shows a block of its own, it
                    // stands where the container stands.
                    let (is_first, prev) = match flow_position(children, ix) {
                        (true, _) => (options.is_first, options.prev),
                        (false, prev) => (false, prev),
                    };
                    node.render_block(
                        NodeRenderOptions {
                            ix,
                            is_first,
                            prev,
                            is_last: options.is_last && ix + 1 == children.len(),
                            ..options
                        },
                        node_cx,
                        window,
                        cx,
                    )
                }))
                .into_any_element(),
            BlockNode::Paragraph(paragraph) => gapped(
                paragraph.render(
                    paragraph.span.map(|span| TextLeafKey::block(span.start)),
                    node_cx,
                    window,
                    cx,
                ),
                mb,
            ),
            BlockNode::Heading {
                level,
                children,
                span,
            } => {
                let (_, line_height, section_gap) = heading_metrics(*level);
                let refinement = node_cx.style.heading(*level);
                let text_size = heading_size(*level, node_cx, window);
                // The previous block already leaves a gap below itself, so
                // only the rest of the section gap is added here -- the two
                // collapse like CSS margins. A heading right after another one
                // belongs to the same section and stays close. Nested in a
                // list item, a heading sits flush with the item.
                let top = if options.is_first || options.depth > 0 {
                    px(0.)
                } else {
                    match options.prev {
                        PrevBlock::Heading(_) => text_size * 0.25,
                        PrevBlock::Rule => (text_size * section_gap
                            - rule_space(body_font_size(node_cx, window)))
                        .max(px(0.)),
                        PrevBlock::Other => (text_size * section_gap
                            - node_cx.style.paragraph_gap().to_pixels(window.rem_size()))
                        .max(px(0.)),
                    }
                };
                let bottom = if options.is_last {
                    px(0.)
                } else {
                    text_size * HEADING_BOTTOM_GAP
                };

                div()
                    .pt(top)
                    .pb(bottom)
                    .whitespace_normal()
                    .text_size(text_size)
                    .line_height(relative(line_height))
                    .font_weight(FontWeight::SEMIBOLD)
                    .when(*level >= 6, |this| {
                        this.text_color(node_cx.style.muted_foreground())
                    })
                    .refine_style(&refinement)
                    .child(children.render(
                        span.map(|span| TextLeafKey::block(span.start)),
                        node_cx,
                        window,
                        cx,
                    ))
                    .into_any_element()
            }
            BlockNode::Blockquote { children, .. } => gapped(
                div()
                    .w_full()
                    .text_color(node_cx.style.muted_foreground())
                    .border_l_2()
                    .border_color(node_cx.style.border())
                    .pl(body_font_size(node_cx, window) * 0.9)
                    .refine_style(node_cx.style.blockquote_style())
                    // Nested tables measure while rendering, before this div applies its text style.
                    .children({
                        let children_len = children.len();
                        children.into_iter().enumerate().map(move |(index, c)| {
                            let is_last = index == children_len - 1;
                            let (is_first, prev) = flow_position(children, index);
                            window.with_text_style(
                                Some(node_cx.style.blockquote_style().text.clone()),
                                |window| {
                                    c.render_block(
                                        NodeRenderOptions {
                                            is_first,
                                            prev,
                                            ..options.is_last(is_last)
                                        },
                                        node_cx,
                                        window,
                                        cx,
                                    )
                                },
                            )
                        })
                    })
                    .into_any_element(),
                mb,
            ),
            BlockNode::List {
                children,
                ordered,
                start,
                ..
            } => div()
                .w_full()
                .min_w_0()
                .pb(mb)
                .children({
                    let mut items = Vec::with_capacity(children.len());
                    let mut item_index = 0;
                    for (ix, item) in children.into_iter().enumerate() {
                        let is_item = item.is_list_item();

                        items.push(Self::render_list_item(
                            item,
                            item_index,
                            NodeRenderOptions {
                                ix,
                                ordered: *ordered,
                                list_start: *start,
                                ..options
                            },
                            node_cx,
                            window,
                            cx,
                        ));

                        if is_item {
                            item_index += 1;
                        }
                    }
                    items
                })
                .into_any_element(),
            BlockNode::CodeBlock(code_block) => code_block.render(&options, node_cx, window, cx),
            BlockNode::Custom { node, state } => {
                let inner = match node_cx.markdown_extensions.render_block(node, window, cx) {
                    Some(rendered) => rendered,
                    None => div().child(node.as_text().to_string()).into_any_element(),
                };

                div()
                    .pb(mb)
                    .child(CustomBlockElement {
                        content: inner,
                        state: state.clone(),
                    })
                    .into_any_element()
            }
            BlockNode::Table { .. } => {
                // Tables are data and read a step denser than the body. The
                // columns are measured while rendering, so they are measured
                // at the same size the cells are laid out with; the actions
                // row below keeps the body size.
                let text_size = body_font_size(node_cx, window) * (14. / 15.);
                window.with_text_style(
                    Some(TextStyleRefinement {
                        font_size: Some(text_size.into()),
                        ..Default::default()
                    }),
                    |window| {
                        Self::render_table(self, &options, node_cx, text_size, window, cx)
                            .into_any_element()
                    },
                )
            }
            BlockNode::HorizontalRule { .. } => {
                // A section break: a hairline with more room around it than
                // a paragraph gap. The previous block's own gap counts toward
                // the space above, as with headings.
                let space = rule_space(body_font_size(node_cx, window));
                let top = if options.is_first || options.depth > 0 {
                    px(0.)
                } else {
                    let above = match options.prev {
                        PrevBlock::Rule => space,
                        PrevBlock::Heading(level) => {
                            heading_size(level, node_cx, window) * HEADING_BOTTOM_GAP
                        }
                        PrevBlock::Other => {
                            node_cx.style.paragraph_gap().to_pixels(window.rem_size())
                        }
                    };
                    (space - above).max(px(0.))
                };
                div()
                    .pt(top)
                    .when(!options.is_last, |this| this.pb(space))
                    .child(div().bg(node_cx.style.border()).h(px(1.)))
                    .into_any_element()
            }
            BlockNode::Break { .. } => div().into_any_element(),
            BlockNode::Unknown { .. } | BlockNode::Definition { .. } => div().into_any_element(),
            _ => {
                if cfg!(debug_assertions) {
                    tracing::warn!("unknown implementation: {:?}", self);
                }

                div().into_any_element()
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn block_plugin_selection_copies_both_formats_and_clears_synchronously() {
        let source = "$$\nx\n$$";
        let mut node = MarkdownNode::new("math", ()).text("x").markdown(source);
        node.set_span(Some(Span {
            start: 0,
            end: source.len(),
        }));
        let state = BlockState::default();
        let same_content = BlockNode::Custom {
            node: node.clone(),
            state: BlockState::default(),
        };
        let block = BlockNode::Custom {
            node,
            state: state.clone(),
        };
        let document = crate::text::document::ParsedDocument {
            source: source.into(),
            blocks: Arc::new(vec![block.clone()]),
        };
        assert!(!block.has_selection());
        state.set_selection(Some(BlockSelection::Full));
        // Runtime selection does not affect parsed content equality.
        assert_eq!(block, same_content);
        for blocks in [None, Some(0..=0)] {
            assert_eq!(
                document.selected_text(SelectionFormat::Plain, blocks.clone()),
                "x\n"
            );
            assert_eq!(
                document.selected_text(SelectionFormat::Source, blocks),
                source
            );
        }
        assert_eq!(document.selected_source_range(), Some(0..source.len()));

        // A clone shares the retained state, including clearing before repaint.
        block.clear_selection();
        assert!(!document.blocks[0].has_selection());
        assert_eq!(
            document.selected_text(SelectionFormat::Plain, Some(0..=0)),
            ""
        );
        assert_eq!(document.selected_source_range(), None);
    }

    #[test]
    fn block_plugin_empty_endpoint_suppresses_virtualized_copy_fallback() {
        let state = BlockState::default();
        let block = BlockNode::Custom {
            node: MarkdownNode::new("math", ())
                .text("formula")
                .markdown("$$formula$$"),
            state: state.clone(),
        };
        let after = CodeBlock::from_code("after", None::<SharedString>);
        after.set_selection(0..5);
        let document = crate::text::document::ParsedDocument {
            blocks: Arc::new(vec![block, BlockNode::CodeBlock(after)]),
            ..Default::default()
        };
        assert!(
            document
                .selected_text(SelectionFormat::Plain, Some(0..=1))
                .contains("formula")
        );
        state.set_selection(Some(BlockSelection::Empty));
        assert!(document.blocks[0].has_selection());
        for format in [SelectionFormat::Plain, SelectionFormat::Source] {
            let text = document.selected_text(format, Some(0..=1));
            assert!(text.contains("after"));
            assert!(!text.contains("formula"));
        }
    }

    #[test]
    fn block_plugin_geometry_selects_whole_blocks_in_both_drag_directions() {
        let bounds = Bounds::new(gpui::point(px(10.), px(20.)), gpui::size(px(100.), px(40.)));
        let inside = bounds.center();
        let above = gpui::point(px(0.), px(0.));
        let below = gpui::point(px(0.), px(80.));
        for (start, end) in [(above, inside), (inside, below), (above, below)] {
            assert!(custom_block_is_selected(bounds, start, end));
            assert!(custom_block_is_selected(bounds, end, start));
        }
        assert!(!custom_block_is_selected(bounds, inside, inside));
        // Pointer travel during a click, and any drag that never leaves the
        // block, select nothing.
        for (start, end) in [
            (inside, inside + gpui::point(px(1.), px(0.))),
            (
                bounds.origin,
                bounds.bottom_right() - gpui::point(px(1.), px(1.)),
            ),
        ] {
            assert!(!custom_block_is_selected(bounds, start, end));
            assert!(!custom_block_is_selected(bounds, end, start));
        }
        assert!(!custom_block_is_selected(
            bounds,
            gpui::point(px(150.), px(30.)),
            gpui::point(px(160.), px(40.))
        ));
    }

    #[test]
    fn selected_inline_objects_coalesce_surrounding_emphasis() {
        for (object_mark, expected) in [
            (TextMark::default().italic(), "*fore $x$ aft*"),
            (TextMark::default().italic().bold(), "*fore **$x$** aft*"),
        ] {
            let italic = TextMark::default().italic();
            let before = InlineNode::new("before ").marks(vec![(0..7, italic.clone())]);
            let formula =
                InlineNode::custom(MarkdownNode::new("math", ()).text("x").markdown("$x$"))
                    .marks(vec![(0..1, object_mark)]);
            let after = InlineNode::new(" after").marks(vec![(0..6, italic)]);
            {
                let mut state = formula.state.lock().unwrap();
                state.text = "before ".into();
                state.selection = Some((2..7).into());
            }
            *formula.custom_selection.lock().unwrap() = true;
            let paragraph = Paragraph {
                children: vec![before, formula, after],
                ..Default::default()
            };
            {
                let mut state = paragraph.state.lock().unwrap();
                state.text = " after".into();
                state.selection = Some((0..4).into());
            }
            assert_eq!(paragraph.selected_source(), expected);
        }
    }

    #[test]
    fn consecutive_inline_objects_copy_atomically_without_neighboring_text() {
        let first =
            InlineNode::custom(MarkdownNode::new("math", ()).text("甲²").markdown("$甲^2$"));
        let second = InlineNode::custom(MarkdownNode::new("math", ()).text("b").markdown("$b$"));
        *first.custom_selection.lock().unwrap() = true;
        *second.custom_selection.lock().unwrap() = true;
        let paragraph = Paragraph {
            children: vec![first, second],
            ..Default::default()
        };
        assert_eq!(paragraph.selected_text(), "甲²b");
        assert_eq!(paragraph.selected_source(), "$甲^2$$b$");
        assert!(paragraph.has_selection());
        paragraph.clear_selection();
        assert_eq!(paragraph.selected_text(), "");
        assert_eq!(paragraph.selected_source(), "");
        assert!(!paragraph.has_selection());
    }

    #[test]
    fn selected_inline_object_interleaves_runs_and_preserves_enclosing_mark() {
        let before = InlineNode::new("中文 ");
        let formula =
            InlineNode::custom(MarkdownNode::new("math", ()).text("x²").markdown("$x^2$"))
                .marks(vec![(0..3, TextMark::default().bold())]);
        let after = InlineNode::new(" English");
        {
            let mut preceding = formula.state.lock().unwrap();
            preceding.text = "中文 ".into();
            preceding.selection = Some((3..7).into());
        }
        *formula.custom_selection.lock().unwrap() = true;
        let paragraph = Paragraph {
            children: vec![before, formula, after],
            ..Default::default()
        };
        {
            let mut trailing = paragraph.state.lock().unwrap();
            trailing.text = " English".into();
            trailing.selection = Some((0..4).into());
        }
        assert_eq!(paragraph.selected_text(), "文 x² Eng");
        assert_eq!(paragraph.selected_source(), "文 **$x^2$** Eng");
    }

    #[test]
    fn mark_sets_a_readable_text_color_with_its_background() {
        use gpui::{Empty, TestApp};
        let mut app = TestApp::new();
        let mut window = app.open_window(|_, _| Empty);
        window.update(|_, _, cx| {
            cx.set_global(crate::Theme::default());
            let node_cx = NodeContext::default();

            // The default `<mark>` yellow needs dark text, whatever the theme's
            // text color is (light in a dark theme).
            let yellow: Hsla = gpui::rgb(0xfef08a).into();
            let style = mark_highlight(&TextMark::default().highlight(yellow), &node_cx, cx).style;
            assert_eq!(style.background_color, Some(yellow));
            assert_eq!(style.color, Some(gpui::black()));

            // A dark custom highlight gets light text instead.
            let navy: Hsla = gpui::rgb(0x1e3a8a).into();
            let style = mark_highlight(&TextMark::default().highlight(navy), &node_cx, cx).style;
            assert_eq!(style.color, Some(gpui::white()));

            // A translucent mark is composited with the theme surface before
            // choosing the text color. Fully transparent marks keep inherited ink.
            let translucent_black: Hsla = gpui::rgba(0x00000080).into();
            let translucent_white: Hsla = gpui::rgba(0xffffff4d).into();
            assert_eq!(
                mark_text_color(translucent_black, gpui::white()),
                gpui::black()
            );
            assert_eq!(
                mark_text_color(translucent_white, gpui::black()),
                gpui::white()
            );
            let transparent: Hsla = gpui::rgba(0x00000000).into();
            let style =
                mark_highlight(&TextMark::default().highlight(transparent), &node_cx, cx).style;
            assert_eq!(style.color, None);

            // Text that is not marked keeps the inherited color.
            let style = mark_highlight(&TextMark::default().bold(), &node_cx, cx).style;
            assert_eq!(style.color, None);
        });
    }

    #[test]
    fn translucent_mark_cache_tracks_theme_background() {
        use gpui::{Empty, TestApp};
        let mut app = TestApp::new();
        let mut window = app.open_window(|_, _| Empty);
        window.update(|_, _, cx| {
            cx.set_global(crate::Theme::default());
            let paragraph = Paragraph {
                children: vec![InlineNode::new("mark").marks(vec![(
                    0..4,
                    TextMark::default().highlight(gpui::rgba(0x00000033).into()),
                )])],
                ..Default::default()
            };
            let context = NodeContext::default();
            crate::Theme::global_mut(cx).tokens.colors.background = gpui::white();
            let (_, light, _) = paragraph.plain_render(&context, cx);
            assert_eq!(light[0].1.style.color, Some(gpui::black()));
            crate::Theme::global_mut(cx).tokens.colors.background = gpui::black();
            let (_, dark, _) = paragraph.plain_render(&context, cx);
            assert_eq!(dark[0].1.style.color, Some(gpui::white()));
        });
    }

    #[test]
    fn custom_inline_inherits_marks_and_resolves_link_references() {
        use gpui::{Empty, TestApp};
        let mut app = TestApp::new();
        let mut window = app.open_window(|_, _| Empty);
        window.update(|_, _, cx| {
            cx.set_global(crate::Theme::default());
            let mut node_cx = NodeContext::default();
            let mut mark = TextMark::default().bold();
            mark.italic = true;
            mark.strikethrough = true;
            mark.link = Some(LinkMark {
                identifier: Some("ref".into()),
                ..Default::default()
            });
            node_cx.link_refs.insert(
                "ref".into(),
                LinkMark {
                    url: "https://example.com".into(),
                    ..Default::default()
                },
            );
            let paragraph = Paragraph {
                children: vec![
                    InlineNode::custom(MarkdownNode::new("test", ()).text("x"))
                        .marks(vec![(0..1, mark)]),
                ],
                ..Default::default()
            };
            let items = paragraph.inline_flow_items(None, &[], &[], &node_cx, cx);
            let InlineFlowItem::Object { style, link, .. } = &items[0] else {
                panic!()
            };
            assert_eq!(style.font_weight, Some(FontWeight::BOLD));
            assert_eq!(style.font_style, Some(FontStyle::Italic));
            assert!(style.strikethrough.is_some());
            assert_eq!(link.as_ref().unwrap().url.as_ref(), "https://example.com");
        });
    }

    #[test]
    fn table_column_uses_prepared_inline_metrics_after_resource_update() {
        use crate::text::InlineElement;
        use crate::text::inline::test_draw::in_prepaint;
        use gpui::{Image, ImageFormat, TestApp};
        let mut app = TestApp::new();
        let width = Arc::new(std::sync::atomic::AtomicUsize::new(400));
        let render_width = width.clone();
        let mut node_cx = NodeContext::default();
        node_cx.markdown_extensions = Arc::new(MarkdownExtensions::default().plugin(
            crate::text::markdown_ext::TestInlinePlugin::new("test").render_with(
                move |_, _, _, _| {
                    Some(
                        InlineElement::new(
                            gpui::img(Arc::new(Image::from_bytes(
                                ImageFormat::Svg,
                                b"<svg/>".to_vec(),
                            )))
                            .w(px(
                                render_width.load(std::sync::atomic::Ordering::Relaxed) as f32
                            ))
                            .h(px(20.)),
                        )
                        .with_baseline(px(15.)),
                    )
                },
            ),
        ));
        let table = table_of(
            vec![
                vec![plain_cell("ordinary text")],
                vec![TableCell {
                    children: Paragraph {
                        children: vec![InlineNode::custom(MarkdownNode::new("test", ()).text("x"))],
                        ..Default::default()
                    },
                    width: None,
                }],
            ],
            vec![],
        );
        in_prepaint(&mut app, move |window, cx| {
            let mut cached = None;
            for expected in [400, 600, 10, 400] {
                width.store(expected, std::sync::atomic::Ordering::Relaxed);
                let measured = measure_table_columns(&table, 1, &node_cx, window, cx)[0];
                let current = cached_column_widths(&table);
                assert_eq!(
                    measured,
                    current.widths[0].max(expected as f32 + CELL_PAD_PX)
                );
                assert_eq!(current.custom_cells, vec![(1, 0)]);
                if let Some(cached) = cached.replace(current.clone()) {
                    assert!(Arc::ptr_eq(&cached, &current));
                }
            }
        });
    }

    fn cached_column_widths(table: &Table) -> Arc<TableColumnWidths> {
        table.column_widths_cache.0.lock().unwrap().clone().unwrap()
    }

    #[test]
    fn blockquote_typography_reaches_nested_table_measurement() {
        use crate::text::inline::test_draw::in_prepaint;
        use crate::text::inline::test_fonts::{BODY, MONO, WideMonoTextSystem};
        use gpui::TestApp;

        let quote = BlockNode::Blockquote {
            children: vec![BlockNode::Table(table_of(
                vec![vec![plain_cell("0123456789")]],
                vec![],
            ))],
            span: None,
        };
        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        in_prepaint(&mut app, move |window, cx| {
            cx.set_global(crate::Theme::default());
            window.with_text_style(
                Some(
                    StyleRefinement::default()
                        .font_family(BODY)
                        .text_size(px(15.))
                        .text,
                ),
                |window| {
                    for (refinement, expected_width) in [
                        (StyleRefinement::default(), 94.),
                        (
                            StyleRefinement::default()
                                .font_family(MONO)
                                .text_size(px(30.))
                                .font_weight(FontWeight::BOLD),
                            199.,
                        ),
                    ] {
                        let node_cx = NodeContext {
                            style: Arc::new(
                                TextViewStyle::default().with_blockquote_style(refinement),
                            ),
                            body_font_size: px(15.),
                            ..Default::default()
                        };
                        quote.render_block(NodeRenderOptions::default(), &node_cx, window, cx);
                        let BlockNode::Blockquote { children, .. } = &quote else {
                            unreachable!()
                        };
                        let BlockNode::Table(table) = &children[0] else {
                            unreachable!()
                        };
                        // Ten glyphs at the table's 14px size, plus 24px cell padding.
                        assert_eq!(cached_column_widths(table).widths, vec![expected_width]);
                    }
                },
            );
        });
    }

    #[test]
    fn table_columns_cache_preserves_plain_widths_and_clones() {
        use crate::text::inline::test_draw::in_prepaint;
        use crate::text::inline::test_fonts::{BODY, WideMonoTextSystem, record_shaped_lines};
        use gpui::{Refineable as _, TestApp, TextStyle};

        let long = "é界".repeat(2048);
        let table = table_of(
            vec![
                vec![plain_cell(&format!(" \t{long} \nshort\n ")), plain_cell("")],
                vec![plain_cell("short")],
                vec![],
                vec![plain_cell(""), plain_cell("a\nabcdefghijklmnop")],
            ],
            vec![],
        );
        let uncached = table.clone();
        let node_cx = NodeContext::default();
        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        let (table, node_cx, cached) = in_prepaint(&mut app, move |window, cx| {
            window.set_rem_size(px(20.));
            let style = TextStyle {
                font_family: BODY.into(),
                font_size: rems(1.).into(),
                ..Default::default()
            };
            let cached =
                window.with_text_style(Some(style.subtract(&Default::default())), |window| {
                    let (widths, shaped) = record_shaped_lines(|| {
                        measure_table_columns(&table, 2, &node_cx, window, cx)
                    });
                    assert_eq!(widths, vec![40960. + CELL_PAD_PX + CELL_BORDER_PX, 184.]);
                    assert!(shaped.iter().any(|line| line == &long));
                    assert_eq!(
                        table, uncached,
                        "derived widths do not change table equality"
                    );
                    assert!(uncached.column_widths_cache.0.lock().unwrap().is_none());

                    let cached = cached_column_widths(&table);
                    let cloned = table.clone();
                    for same in [&table, &cloned] {
                        let (again, shaped) = record_shaped_lines(|| {
                            measure_table_columns(same, 2, &node_cx, window, cx)
                        });
                        assert_eq!(again, widths);
                        assert!(shaped.is_empty());
                        assert!(Arc::ptr_eq(&cached, &cached_column_widths(same)));
                    }

                    // A different column count changes which cells draw borders.
                    assert_eq!(
                        measure_table_columns(&cloned, 3, &node_cx, window, cx),
                        vec![widths[0], widths[1] + CELL_BORDER_PX, CELL_MIN_PX]
                    );
                    assert!(!Arc::ptr_eq(&cached, &cached_column_widths(&cloned)));
                    assert!(Arc::ptr_eq(&cached, &cached_column_widths(&table)));
                    assert!(
                        measure_table_columns(&Table::default(), 0, &node_cx, window, cx)
                            .is_empty()
                    );
                    cached
                });
            (table, node_cx, cached)
        });
        // A parsed table can be rendered in another window. Do not reuse a
        // pixel-width cache from a different window's text system.
        in_prepaint(&mut app, move |window, cx| {
            window.set_rem_size(cached.rem_size);
            window.with_text_style(
                Some(cached.text_styles.body.subtract(&Default::default())),
                |window| {
                    measure_table_columns(&table, 2, &node_cx, window, cx);
                    assert!(!Arc::ptr_eq(&cached, &cached_column_widths(&table)));
                },
            );
        });
    }

    #[test]
    fn table_columns_cache_tracks_typography() {
        use crate::text::inline::test_draw::in_prepaint;
        use crate::text::inline::test_fonts::{BODY, MONO, WideMonoTextSystem};
        use gpui::{Refineable as _, TestApp, TextStyle};

        let code = "0123456789";
        let mut paragraph = Paragraph::default();
        paragraph
            .push(InlineNode::new(code).marks(vec![(0..code.len(), TextMark::default().code())]));
        let table = table_of(
            vec![vec![
                plain_cell(code),
                TableCell {
                    children: paragraph,
                    width: None,
                },
            ]],
            vec![],
        );
        let base = TextStyle {
            font_family: BODY.into(),
            font_size: rems(1.).into(),
            ..Default::default()
        };
        let mut larger = base.clone();
        larger.font_size = rems(2.).into();
        let mut bold = base.clone();
        bold.font_weight = FontWeight::BOLD;
        let mut mono = base.clone();
        mono.font_family = MONO.into();
        let normal_code = HighlightStyle::default();
        let bold_code = HighlightStyle {
            font_weight: Some(FontWeight::BOLD),
            ..Default::default()
        };
        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        in_prepaint(&mut app, move |window, cx| {
            let mut previous = None;
            for (style, rem_size, family, inline_code, expected) in [
                (base.clone(), 20., MONO, normal_code, [125., 207.]),
                (base.clone(), 30., MONO, normal_code, [175., 294.5]),
                (larger, 20., MONO, normal_code, [225., 382.]),
                (bold, 20., MONO, normal_code, [175., 250.75]),
                (mono, 20., MONO, normal_code, [225., 207.]),
                (base.clone(), 20., MONO, normal_code, [125., 207.]),
                (base.clone(), 20., BODY, normal_code, [125., 119.5]),
                (base.clone(), 20., MONO, normal_code, [125., 207.]),
                (base, 20., MONO, bold_code, [125., 250.75]),
            ] {
                let mut theme = crate::Theme::default();
                theme.tokens.typography.mono = family.into();
                cx.set_global(theme);
                window.set_rem_size(px(rem_size));
                let node_cx = NodeContext {
                    style: Arc::new(TextViewStyle::default().with_inline_code(inline_code)),
                    ..Default::default()
                };
                window.with_text_style(Some(style.subtract(&Default::default())), |window| {
                    let widths = measure_table_columns(&table, 2, &node_cx, window, cx);
                    for (width, expected) in widths.iter().zip(expected) {
                        assert!((width - expected).abs() < 0.01, "{width} != {expected}");
                    }
                    let cached = cached_column_widths(&table);
                    if let Some(previous) = previous.replace(cached.clone()) {
                        assert!(!Arc::ptr_eq(&previous, &cached));
                    }
                    assert_eq!(
                        measure_table_columns(&table, 2, &node_cx, window, cx),
                        widths
                    );
                    assert!(Arc::ptr_eq(&cached, &cached_column_widths(&table)));
                });
            }
        });
    }

    #[test]
    fn table_columns_cache_is_rebuilt_for_reparsed_tables() {
        use crate::text::format::markdown;
        use crate::text::inline::test_draw::in_prepaint;
        use crate::text::inline::test_fonts::{BODY, WideMonoTextSystem};
        use gpui::{Refineable as _, TestApp, TextStyle};

        let mut node_cx = NodeContext::default();
        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        in_prepaint(&mut app, move |window, cx| {
            let style = TextStyle {
                font_family: BODY.into(),
                font_size: px(20.).into(),
                ..Default::default()
            };
            window.with_text_style(Some(style.subtract(&Default::default())), |window| {
                let mut previous = None;
                for (text, expected) in [("longer cell", 134.), ("x", CELL_MIN_PX)] {
                    let source = format!("| h |\n| - |\n| {text} |\n");
                    let document = markdown::parse(&source, &mut node_cx).unwrap();
                    let BlockNode::Table(table) = &document.blocks[0] else {
                        panic!("expected a parsed table");
                    };
                    assert!(table.column_widths_cache.0.lock().unwrap().is_none());
                    assert_eq!(
                        measure_table_columns(table, 1, &node_cx, window, cx),
                        vec![expected]
                    );
                    let cached = cached_column_widths(table);
                    if let Some(previous) = previous.replace(cached.clone()) {
                        assert!(!Arc::ptr_eq(&previous, &cached));
                    }
                    assert_eq!(document.source.as_ref(), source);
                }
            });
        });
    }

    /// Table columns are sized from shaped text, so a column of inline code
    /// has to be measured in the code family. Measured in the body font, the
    /// wide-mono test font makes `col_w` come out at half the rendered width.
    #[test]
    fn table_column_of_inline_code_cells_fits_the_mono_width() {
        use crate::text::inline::test_fonts::{MONO, WideMonoTextSystem};
        use gpui::{Empty, TestApp};

        let code = "method_name()";
        let mut paragraph = Paragraph::default();
        paragraph
            .push(InlineNode::new(code).marks(vec![(0..code.len(), TextMark::default().code())]));
        let table = Table {
            children: vec![TableRow {
                children: vec![TableCell {
                    children: paragraph,
                    width: None,
                }],
            }],
            column_aligns: vec![],
            span: None,
            table_data_cache: TableDataCache::default(),
            column_widths_cache: TableColumnWidthsCache::default(),
        };
        let node_cx = NodeContext::default();

        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        let mut window = app.open_window(|_, _| Empty);
        let (col_w, font_size) = window.update(|_, window, cx| {
            let mut theme = crate::Theme::default();
            theme.tokens.typography.mono = MONO.into();
            cx.set_global(theme);
            let font_size = window.text_style().font_size.to_pixels(window.rem_size());
            (
                measure_table_columns(&table, 1, &node_cx, window, cx),
                font_size,
            )
        });

        let mono_w = f32::from(WideMonoTextSystem::width_of(code, MONO, font_size * 0.875));
        assert!(
            (col_w[0]
                - (mono_w + CELL_PAD_PX + crate::text::inline_flow::INLINE_CODE_PADDING * 2.))
                .abs()
                < 0.01,
            "col_w {} must fit the mono width {} plus padding {}",
            col_w[0],
            mono_w,
            CELL_PAD_PX
        );
    }

    #[test]
    fn code_block_highlights_are_cached_by_highlighter_identity() {
        use std::sync::atomic::{AtomicUsize, Ordering};

        let calls = Arc::new(AtomicUsize::new(0));
        let calls_for_highlighter = calls.clone();
        let highlighter: Arc<CodeBlockHighlighterFn> = Arc::new(move |_| {
            calls_for_highlighter.fetch_add(1, Ordering::Relaxed);
            Vec::new()
        });
        let block = CodeBlock::new("fn main() {}".into(), Some("rust".into()), None::<Span>);

        block.highlighted_styles(&highlighter);
        block.highlighted_styles(&highlighter);
        assert_eq!(calls.load(Ordering::Relaxed), 1);

        let replacement: Arc<CodeBlockHighlighterFn> = Arc::new(|_| Vec::new());
        block.highlighted_styles(&replacement);
        assert!(Arc::ptr_eq(
            &block
                .highlight_cache
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .highlighter,
            &replacement
        ));
    }

    #[test]
    fn a_new_highlighter_replaces_styles_instead_of_reusing_the_cache() {
        // Swapping the highlighter is how a theme change reaches a code block:
        // the parsed document is untouched, so the styles must come from the
        // new highlighter rather than from the styles cached for the old one.
        let light: Arc<CodeBlockHighlighterFn> = Arc::new(|_| {
            vec![(
                0..2,
                HighlightStyle {
                    color: Some(gpui::rgb(0x0000ff).into()),
                    ..Default::default()
                },
            )]
        });
        let dark: Arc<CodeBlockHighlighterFn> = Arc::new(|_| {
            vec![(
                0..2,
                HighlightStyle {
                    color: Some(gpui::rgb(0xffff00).into()),
                    ..Default::default()
                },
            )]
        });
        let block = CodeBlock::from_code("42", Some("json"));

        let light_styles = block.highlighted_styles(&light);
        let dark_styles = block.highlighted_styles(&dark);

        assert_eq!(light_styles[0].1.color, Some(gpui::rgb(0x0000ff).into()));
        assert_eq!(dark_styles[0].1.color, Some(gpui::rgb(0xffff00).into()));
        assert_eq!(block.code(), "42", "the document must survive the swap");
    }

    #[test]
    fn reconstruct_markdown_wraps_marked_runs() {
        // "bold" fully covered by a bold mark.
        let marks = vec![(0..4, TextMark::default().bold())];
        assert_eq!(reconstruct_markdown("bold", &marks, 0..4), "**bold**");
        // Partial selection inside the bold run still wraps the slice.
        assert_eq!(reconstruct_markdown("bold", &marks, 1..3), "**ol**");
    }

    #[test]
    fn reconstruct_markdown_emits_unmarked_text_verbatim() {
        // "a b c": plain, code, plain across three runs concatenated.
        let text = "a b c";
        let marks = vec![(2..3, TextMark::default().code())];
        assert_eq!(reconstruct_markdown(text, &marks, 0..5), "a `b` c");
        // Selecting only the plain tail.
        assert_eq!(reconstruct_markdown(text, &marks, 3..5), " c");
    }

    #[test]
    fn reconstruct_markdown_handles_code_italic_strike_link() {
        assert_eq!(
            reconstruct_markdown("x", &[(0..1, TextMark::default().code())], 0..1),
            "`x`"
        );
        assert_eq!(
            reconstruct_markdown("x", &[(0..1, TextMark::default().italic())], 0..1),
            "*x*"
        );
        assert_eq!(
            reconstruct_markdown("x", &[(0..1, TextMark::default().strikethrough())], 0..1),
            "~~x~~"
        );
        let link = TextMark::default().link(LinkMark {
            url: "https://example.com".into(),
            ..Default::default()
        });
        assert_eq!(
            reconstruct_markdown("x", &[(0..1, link)], 0..1),
            "[x](https://example.com)"
        );
    }

    #[test]
    fn reconstruct_markdown_nested_bold_italic() {
        // A single run marked both bold and italic (as produced by `**_x_**`).
        let mark = TextMark::default().bold().italic();
        // Inner (italic) is applied first, then bold: `***x***`.
        assert_eq!(reconstruct_markdown("x", &[(0..1, mark)], 0..1), "***x***");
    }

    /// Build a paragraph whose combined `state.text` is the concatenation of
    /// its children (mirroring `Paragraph::render`), then set the paragraph
    /// selection so `selected_source` can be exercised without a real paint.
    fn paragraph_with_children(children: Vec<InlineNode>) -> Paragraph {
        let combined: String = children.iter().map(|c| c.text.to_string()).collect();
        let paragraph = Paragraph {
            span: None,
            children,
            link_refs: HashMap::new(),
            state: Arc::new(Mutex::new(InlineState::default())),
            render_cache: ParagraphRenderCache::default(),
        };
        if let Ok(mut state) = paragraph.state.lock() {
            state.set_text(combined.into());
        }
        paragraph
    }

    fn set_paragraph_selection(paragraph: &Paragraph, range: Range<usize>) {
        if let Ok(mut state) = paragraph.state.lock() {
            state.selection = Some(range.into());
        }
    }

    #[test]
    fn paragraph_selected_source_maps_partial_selection_across_runs() {
        // "This has **bold** text." rendered as ["This has ", "bold", " text."].
        let children = vec![
            InlineNode::new("This has ").marks(vec![(0..9, TextMark::default())]),
            InlineNode::new("bold").marks(vec![(0..4, TextMark::default().bold())]),
            InlineNode::new(" text.").marks(vec![(0..6, TextMark::default())]),
        ];
        let paragraph = paragraph_with_children(children);

        // Select the whole paragraph: "This has bold text." -> source with **.
        set_paragraph_selection(&paragraph, 0..(9 + 4 + 6));
        assert_eq!(paragraph.selected_source(), "This has **bold** text.");

        // Select only across the boundary "has **bold** te".
        // Rendered offsets: "has " starts at 5, "bold" at 9..13, " te" 13..16.
        set_paragraph_selection(&paragraph, 5..16);
        assert_eq!(paragraph.selected_source(), "has **bold** te");

        // Select entirely inside the bold run -> still wrapped.
        set_paragraph_selection(&paragraph, 10..12);
        assert_eq!(paragraph.selected_source(), "**ol**");
    }

    #[test]
    fn paragraph_selected_source_matches_text_when_no_marks() {
        let children =
            vec![InlineNode::new("plain words").marks(vec![(0..11, TextMark::default())])];
        let paragraph = paragraph_with_children(children);
        set_paragraph_selection(&paragraph, 0..11);
        assert_eq!(paragraph.selected_source(), "plain words");
        assert_eq!(paragraph.selected_text(), "plain words");
    }

    /// Copy `blocks` the way a view in [`SelectionFormat::SourceAcrossStyles`]
    /// does, with every block painted.
    fn copy_across_styles(blocks: Vec<BlockNode>) -> String {
        let document = crate::text::document::ParsedDocument {
            blocks: blocks.into(),
            ..Default::default()
        };
        document.selected_text(SelectionFormat::SourceAcrossStyles, None)
    }

    #[test]
    fn source_across_styles_copies_plain_text_within_one_style() {
        // "This has **bold** text." rendered as ["This has ", "bold", " text."].
        let paragraph = || {
            paragraph_with_children(vec![
                InlineNode::new("This has ").marks(vec![(0..9, TextMark::default())]),
                InlineNode::new("bold").marks(vec![(0..4, TextMark::default().bold())]),
                InlineNode::new(" text.").marks(vec![(0..6, TextMark::default())]),
            ])
        };
        let copy = |range: Range<usize>| {
            let paragraph = paragraph();
            set_paragraph_selection(&paragraph, range);
            copy_across_styles(vec![BlockNode::Paragraph(paragraph)])
        };

        // Inside the bold run, and up to both of its boundaries.
        assert_eq!(copy(10..12), "ol\n");
        assert_eq!(copy(9..13), "bold\n");
        // Inside the plain text before it, up to the boundary.
        assert_eq!(copy(0..9), "This has \n");
        // Across the boundary, the selection takes in two styles.
        assert_eq!(copy(5..16), "has **bold** te");
        assert_eq!(copy(8..10), " **b**");
    }

    #[test]
    fn source_across_styles_drops_the_url_of_a_link_selected_alone() {
        let link = TextMark::default().link(LinkMark {
            url: "https://example.com".into(),
            ..Default::default()
        });
        let paragraph = paragraph_with_children(vec![
            InlineNode::new("see ").marks(vec![(0..4, TextMark::default())]),
            InlineNode::new("the docs").marks(vec![(0..8, link)]),
        ]);

        set_paragraph_selection(&paragraph, 4..12);
        assert_eq!(
            copy_across_styles(vec![BlockNode::Paragraph(paragraph.clone())]),
            "the docs\n"
        );

        set_paragraph_selection(&paragraph, 0..12);
        assert_eq!(
            copy_across_styles(vec![BlockNode::Paragraph(paragraph)]),
            "see [the docs](https://example.com)"
        );
    }

    #[test]
    fn source_across_styles_drops_the_markup_of_a_single_block() {
        let heading = BlockNode::Heading {
            level: 2,
            children: selected_paragraph("Title"),
            span: None,
        };
        assert_eq!(copy_across_styles(vec![heading]), "Title\n");

        let code = CodeBlock::from_code("let a = 1;\nlet b = 2;", Some("rust"));
        code.set_selection(0..10);
        assert_eq!(
            copy_across_styles(vec![BlockNode::CodeBlock(code)]),
            "let a = 1;\n"
        );

        let item = |text: &str| BlockNode::ListItem {
            children: vec![BlockNode::Paragraph(selected_paragraph(text))],
            spread: false,
            checked: None,
            span: None,
        };
        let unselected_item = BlockNode::ListItem {
            children: vec![BlockNode::Paragraph(paragraph_with_children(vec![
                InlineNode::new("two"),
            ]))],
            spread: false,
            checked: None,
            span: None,
        };
        let list = BlockNode::List {
            ordered: false,
            start: None,
            span: None,
            children: vec![item("one"), unselected_item],
        };
        assert_eq!(copy_across_styles(vec![list]), "one\n");
    }

    #[test]
    fn source_across_styles_keeps_the_source_across_blocks() {
        let item = |text: &str| BlockNode::ListItem {
            children: vec![BlockNode::Paragraph(selected_paragraph(text))],
            spread: false,
            checked: None,
            span: None,
        };
        let list = BlockNode::List {
            ordered: false,
            start: None,
            span: None,
            children: vec![item("one"), item("two")],
        };
        assert_eq!(copy_across_styles(vec![list]), "- one\n- two");

        assert_eq!(
            copy_across_styles(vec![
                BlockNode::Paragraph(selected_paragraph("start")),
                BlockNode::Paragraph(selected_paragraph("end")),
            ]),
            "start\n\nend"
        );
    }

    #[test]
    fn source_across_styles_keeps_the_source_of_an_inline_object() {
        let formula = InlineNode::custom(MarkdownNode::new("math", ()).text("x").markdown("$x$"));
        *formula.custom_selection.lock().unwrap() = true;
        let paragraph = Paragraph {
            children: vec![formula],
            ..Default::default()
        };
        assert_eq!(
            copy_across_styles(vec![BlockNode::Paragraph(paragraph)]),
            "$x$"
        );
    }

    fn selected_paragraph(text: &str) -> Paragraph {
        let len = text.len();
        let paragraph = paragraph_with_children(vec![
            InlineNode::new(text).marks(vec![(0..len, TextMark::default())]),
        ]);
        set_paragraph_selection(&paragraph, 0..len);
        paragraph
    }

    #[test]
    fn heading_selected_source_prefixes_hashes() {
        let heading = BlockNode::Heading {
            level: 2,
            children: selected_paragraph("Title"),
            span: None,
        };
        assert_eq!(heading.selected_text(SelectionFormat::Source), "## Title\n");
        // Rendered text keeps no marker.
        assert_eq!(heading.selected_text(SelectionFormat::Plain), "Title\n");
    }

    #[test]
    fn unordered_list_selected_source_prefixes_dash() {
        let list = BlockNode::List {
            ordered: false,
            start: None,
            span: None,
            children: vec![
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("one"))],
                    spread: false,
                    checked: None,
                    span: None,
                },
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("two"))],
                    spread: false,
                    checked: None,
                    span: None,
                },
            ],
        };
        assert_eq!(
            list.selected_text(SelectionFormat::Source),
            "- one\n- two\n"
        );
    }

    #[test]
    fn ordered_list_selected_source_preserves_start() {
        let list = BlockNode::List {
            ordered: true,
            start: Some(3),
            span: None,
            children: vec![
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("three"))],
                    spread: false,
                    checked: None,
                    span: None,
                },
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("four"))],
                    spread: false,
                    checked: None,
                    span: None,
                },
            ],
        };
        assert_eq!(list.to_markdown(), "3. three\n4. four");
        assert_eq!(
            list.selected_text(SelectionFormat::Source),
            "3. three\n4. four\n"
        );
    }

    #[test]
    fn ordered_list_selected_source_preserves_nested_starts_and_continuations() {
        let nested = BlockNode::List {
            ordered: true,
            start: Some(4),
            span: None,
            children: vec![
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("nested"))],
                    spread: false,
                    checked: None,
                    span: None,
                },
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("again"))],
                    spread: false,
                    checked: None,
                    span: None,
                },
            ],
        };
        let nested_list = BlockNode::List {
            ordered: true,
            start: Some(3),
            span: None,
            children: vec![
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("three")), nested],
                    spread: false,
                    checked: None,
                    span: None,
                },
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("four"))],
                    spread: false,
                    checked: None,
                    span: None,
                },
            ],
        };
        assert_eq!(
            nested_list.selected_text(SelectionFormat::Source),
            "3. three\n   4. nested\n   5. again\n4. four\n"
        );

        let loose_list = BlockNode::List {
            ordered: true,
            start: Some(3),
            span: None,
            children: vec![
                BlockNode::ListItem {
                    children: vec![
                        BlockNode::Paragraph(selected_paragraph("loose")),
                        BlockNode::Paragraph(selected_paragraph("continuation")),
                    ],
                    spread: true,
                    checked: None,
                    span: None,
                },
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("four"))],
                    spread: false,
                    checked: None,
                    span: None,
                },
            ],
        };
        assert_eq!(
            loose_list.selected_text(SelectionFormat::Source),
            "3. loose\n   continuation\n4. four\n"
        );
    }

    #[test]
    fn nested_list_selected_source_indents_sublists() {
        // - one
        //   - nested
        // - two
        let nested = BlockNode::List {
            ordered: false,
            start: None,
            span: None,
            children: vec![BlockNode::ListItem {
                children: vec![BlockNode::Paragraph(selected_paragraph("nested"))],
                spread: false,
                checked: None,
                span: None,
            }],
        };
        let list = BlockNode::List {
            ordered: false,
            start: None,
            span: None,
            children: vec![
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("one")), nested],
                    spread: false,
                    checked: None,
                    span: None,
                },
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("two"))],
                    spread: false,
                    checked: None,
                    span: None,
                },
            ],
        };
        assert_eq!(
            list.selected_text(SelectionFormat::Source),
            "- one\n  - nested\n- two\n"
        );
    }

    #[test]
    fn task_list_selected_source_restores_checkboxes() {
        let list = BlockNode::List {
            ordered: false,
            start: None,
            span: None,
            children: vec![
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("done"))],
                    spread: false,
                    checked: Some(true),
                    span: None,
                },
                BlockNode::ListItem {
                    children: vec![BlockNode::Paragraph(selected_paragraph("todo"))],
                    spread: false,
                    checked: Some(false),
                    span: None,
                },
            ],
        };
        assert_eq!(
            list.selected_text(SelectionFormat::Source),
            "- [x] done\n- [ ] todo\n"
        );
    }

    #[test]
    fn blockquote_selected_source_prefixes_gt() {
        let quote = BlockNode::Blockquote {
            span: None,
            children: vec![BlockNode::Paragraph(selected_paragraph("quoted text"))],
        };
        assert_eq!(
            quote.selected_text(SelectionFormat::Source),
            "> quoted text\n"
        );
    }

    #[test]
    fn table_selected_source_pipes_cells_with_alignment_row() {
        let cell = |text: &str| TableCell {
            children: selected_paragraph(text),
            width: None,
        };
        let table = Table {
            children: vec![
                TableRow {
                    children: vec![cell("Name"), cell("Age")],
                },
                TableRow {
                    children: vec![cell("Alice"), cell("30")],
                },
            ],
            column_aligns: vec![ColumnumnAlign::Left, ColumnumnAlign::Right],
            span: None,
            table_data_cache: TableDataCache::default(),
            column_widths_cache: TableColumnWidthsCache::default(),
        };
        let block = BlockNode::Table(table);
        assert_eq!(
            block.selected_text(SelectionFormat::Source),
            "| Name | Age |\n| :-- | --: |\n| Alice | 30 |\n"
        );
    }

    /// A drag that starts in a table cell stays in it, so the copy is the
    /// cell's text alone: no pipes, no delimiter row, no other cells or rows.
    #[test]
    fn a_selection_in_one_table_cell_copies_only_that_cell() {
        let table = table_of(
            vec![
                vec![plain_cell("Name"), plain_cell("Age")],
                vec![
                    TableCell {
                        children: selected_paragraph("Alice"),
                        width: None,
                    },
                    plain_cell("30"),
                ],
            ],
            vec![ColumnumnAlign::Left, ColumnumnAlign::Right],
        );
        let block = BlockNode::Table(table);
        assert_eq!(block.selected_text(SelectionFormat::Plain).trim(), "Alice");
        assert_eq!(block.selected_text(SelectionFormat::Source), "Alice\n");
    }

    /// A cell holding plain text, as `Table::to_markdown` and
    /// `Table::table_data` see it (neither needs a selection).
    fn plain_cell(text: &str) -> TableCell {
        TableCell {
            children: Paragraph::new(text.to_string()),
            width: None,
        }
    }

    fn table_of(rows: Vec<Vec<TableCell>>, column_aligns: Vec<ColumnumnAlign>) -> Table {
        Table {
            children: rows
                .into_iter()
                .map(|children| TableRow { children })
                .collect(),
            column_aligns,
            span: None,
            table_data_cache: TableDataCache::default(),
            column_widths_cache: TableColumnWidthsCache::default(),
        }
    }

    #[test]
    fn table_to_markdown_pipes_cells_with_alignment_row() {
        let table = table_of(
            vec![
                vec![plain_cell("Name"), plain_cell("Age"), plain_cell("Score")],
                vec![plain_cell("Alice"), plain_cell("30"), plain_cell("9.5")],
            ],
            vec![
                ColumnumnAlign::Left,
                ColumnumnAlign::Center,
                ColumnumnAlign::Right,
            ],
        );

        assert_eq!(
            table.to_markdown(),
            "| Name | Age | Score |\n| :-- | :-: | --: |\n| Alice | 30 | 9.5 |"
        );
        // The block arm delegates to it.
        assert_eq!(
            BlockNode::Table(table.clone()).to_markdown(),
            table.to_markdown()
        );
    }

    #[test]
    fn table_to_markdown_keeps_outer_pipes_for_a_single_column() {
        let table = table_of(
            vec![vec![plain_cell("Symbol")], vec![plain_cell("TSLA.US")]],
            vec![ColumnumnAlign::Left],
        );

        assert_eq!(table.to_markdown(), "| Symbol |\n| :-- |\n| TSLA.US |");
    }

    #[test]
    fn table_to_markdown_escapes_pipes_and_keeps_inline_marks() {
        let bold = TableCell {
            children: paragraph_with_children(vec![
                InlineNode::new("bold").marks(vec![(0..4, TextMark::default().bold())]),
            ]),
            width: None,
        };
        let table = table_of(
            vec![
                vec![plain_cell("a | b"), plain_cell("plain")],
                vec![plain_cell("c"), bold],
            ],
            vec![ColumnumnAlign::Left, ColumnumnAlign::Left],
        );

        assert_eq!(
            table.to_markdown(),
            "| a \\| b | plain |\n| :-- | :-- |\n| c | **bold** |"
        );
    }

    #[test]
    fn table_data_snapshots_plain_cells_and_markdown() {
        let mut table = table_of(
            vec![
                vec![plain_cell("  Name  "), plain_cell("Age")],
                vec![plain_cell("Alice"), plain_cell("30")],
            ],
            vec![ColumnumnAlign::Left, ColumnumnAlign::Right],
        );
        table.span = Some(Span { start: 4, end: 42 });

        let data = table.table_data();
        assert_eq!(data.headers, vec!["Name", "Age"]);
        assert_eq!(data.rows, vec![vec!["Alice", "30"]]);
        assert_eq!(data.markdown, table.to_markdown());
        assert_eq!(data.span, Some(4..42));
    }

    #[test]
    fn cloned_table_keeps_cached_table_data() {
        // Streaming appends deep-clone every block; the clone must reuse the
        // cached snapshot instead of rebuilding it.
        let table = table_of(
            vec![vec![plain_cell("Name")], vec![plain_cell("Alice")]],
            vec![ColumnumnAlign::Left],
        );
        let data = table.cached_table_data();

        let cloned = table.clone();
        assert!(Arc::ptr_eq(&data, &cloned.cached_table_data()));
    }

    #[test]
    fn table_data_handles_tables_without_rows() {
        // Header only: still a valid table, with no data rows.
        let header_only = table_of(
            vec![vec![plain_cell("Name"), plain_cell("Age")]],
            vec![ColumnumnAlign::Left, ColumnumnAlign::Left],
        );
        let data = header_only.table_data();
        assert_eq!(data.headers, vec!["Name", "Age"]);
        assert!(data.rows.is_empty());
        assert_eq!(data.markdown, "| Name | Age |\n| :-- | :-- |");

        // No rows at all (a table still streaming in): an empty snapshot.
        assert_eq!(Table::default().table_data(), TableData::default());
    }

    #[test]
    fn test_image_node_source() {
        use gpui::{ImageFormat, ImageSource, Resource};

        fn image_node(url: &str) -> ImageNode {
            ImageNode {
                url: url.into(),
                ..Default::default()
            }
        }

        // Document-provided values stay URI-backed, including `file://` and
        // scheme-less strings, so the document never gets implicit
        // filesystem access through `Resource::Embedded`.
        fn assert_uri(url: &str) {
            match image_node(url).source() {
                ImageSource::Resource(Resource::Uri(uri)) => assert_eq!(uri.as_ref(), url),
                _ => panic!("expected Uri for {url:?}"),
            }
        }
        assert_uri("https://example.com/logo.png");
        assert_uri("http://example.com/logo.png");
        assert_uri("website/public/logo.svg");
        assert_uri("./images/a.png");
        assert_uri("../images/a.png");
        assert_uri("/absolute/path/logo.svg");
        assert_uri("file:///absolute/path/logo.svg");
        assert_uri(r"C:\images\logo.png");
        assert_uri("docs/a:b.png");
        assert_uri("data:text/plain;base64,aGVsbG8=");

        // A `data:` image is decoded once and the same decoded image is
        // handed to every render.
        let node = image_node("data:image/png;base64,iVBORw0KGgo=");
        let ImageSource::Image(first) = node.source() else {
            panic!("expected an embedded image");
        };
        assert_eq!(first.format(), ImageFormat::Png);
        assert_eq!(first.bytes(), b"\x89PNG\r\n\x1a\n");
        let ImageSource::Image(second) = node.source() else {
            panic!("expected an embedded image");
        };
        assert!(Arc::ptr_eq(&first, &second));
    }

    fn image_paragraph(alt: &str, url: &str) -> Paragraph {
        let image = ImageNode {
            url: url.into(),
            alt: Some(alt.into()),
            ..Default::default()
        };
        Paragraph {
            span: None,
            children: vec![InlineNode::image(image)],
            link_refs: HashMap::new(),
            state: Arc::new(Mutex::new(InlineState::default())),
            render_cache: ParagraphRenderCache::default(),
        }
    }

    /// Every mark round-trips, including the two Markdown has no plain syntax
    /// for.
    #[test]
    fn marks_round_trip_through_reconstruction() {
        let wrap = |mark: TextMark| reconstruct_markdown("x", &[(0..1, mark)], 0..1);

        assert_eq!(wrap(TextMark::default().bold()), "**x**");
        assert_eq!(wrap(TextMark::default().italic()), "*x*");
        assert_eq!(wrap(TextMark::default().code()), "`x`");
        assert_eq!(wrap(TextMark::default().strikethrough()), "~~x~~");
        assert_eq!(
            wrap(TextMark::default().highlight(gpui::rgb(0xfef08a).into())),
            "==x=="
        );
        // No Markdown syntax for underline, so it keeps the tag it came from.
        assert_eq!(wrap(TextMark::default().underline()), "<u>x</u>");

        // A link keeps its title, which Markdown carries after the URL.
        assert_eq!(
            wrap(TextMark::default().link(LinkMark {
                url: "https://example.com".into(),
                title: Some("Tip".into()),
                ..Default::default()
            })),
            "[x](https://example.com \"Tip\")"
        );
    }

    /// A block the selection covers whole comes straight from the source, so it
    /// keeps what the author wrote instead of a normalized reconstruction.
    #[test]
    fn document_selected_source_slices_covered_blocks_from_the_source() {
        use crate::text::document::ParsedDocument;

        // `_italic_`, the `3.` start and the column padding all survive only
        // because the block is copied, not rebuilt.
        let source = "start\n\n3. _one_\n4. two\n\n---\n\nend";
        let list = "3. _one_\n4. two";
        let list_start = source.find(list).unwrap();
        let rule_start = source.find("---").unwrap();

        let document = ParsedDocument {
            source: source.into(),
            blocks: vec![
                BlockNode::Paragraph(selected_paragraph("start")),
                BlockNode::List {
                    ordered: true,
                    start: Some(3),
                    children: vec![],
                    span: Some(Span {
                        start: list_start,
                        end: list_start + list.len(),
                    }),
                },
                BlockNode::HorizontalRule {
                    span: Some(Span {
                        start: rule_start,
                        end: rule_start + 3,
                    }),
                },
                BlockNode::Paragraph(selected_paragraph("end")),
            ]
            .into(),
        };

        assert_eq!(
            document.selected_text(SelectionFormat::Source, None),
            "start\n\n3. _one_\n4. two\n\n---\n\nend"
        );
    }

    #[test]
    fn document_selected_source_includes_enclosed_image() {
        use crate::text::document::ParsedDocument;

        // A standalone image between two selected paragraphs is covered by the
        // selection, so it is copied whole even though it holds no selection of
        // its own — straight out of the source the parser located it in.
        let source = "before\n\n![alt](https://example.com/i.png)\n\nafter";
        let image_markdown = "![alt](https://example.com/i.png)";
        let start = source.find(image_markdown).unwrap();
        let mut image = image_paragraph("alt", "https://example.com/i.png");
        image.span = Some(Span {
            start,
            end: start + image_markdown.len(),
        });

        let document = ParsedDocument {
            source: source.into(),
            blocks: vec![
                BlockNode::Paragraph(selected_paragraph("before")),
                BlockNode::Paragraph(image),
                BlockNode::Paragraph(selected_paragraph("after")),
            ]
            .into(),
        };
        assert_eq!(
            document.selected_text(SelectionFormat::Source, None),
            "before\n\n![alt](https://example.com/i.png)\n\nafter"
        );
    }

    #[test]
    fn document_selected_source_drops_unenclosed_image() {
        use crate::text::document::ParsedDocument;

        // An image after the only selected block, with nothing selected after
        // it, is not enclosed and is dropped.
        let document = ParsedDocument {
            source: String::new().into(),
            blocks: vec![
                BlockNode::Paragraph(selected_paragraph("before")),
                BlockNode::Paragraph(image_paragraph("alt", "u")),
            ]
            .into(),
        };
        assert_eq!(
            document.selected_text(SelectionFormat::Source, None),
            "before"
        );
    }

    fn selected_code_block(code: &str, lang: Option<&str>) -> BlockNode {
        let block = CodeBlock::new(
            code.to_string().into(),
            lang.map(|l| l.to_string().into()),
            None::<Span>,
        );
        if let Ok(mut state) = block.state.lock() {
            let len = state.text.len();
            state.selection = Some((0..len).into());
        }
        BlockNode::CodeBlock(block)
    }

    #[test]
    fn code_block_selected_source_wraps_in_fence_with_lang() {
        let block = selected_code_block("let x = 1;\n", Some("rust"));
        let code = block.selected_text(SelectionFormat::Plain);
        let code_trimmed = code.trim_end_matches('\n');
        // The source wraps the (trailing-newline-trimmed) selected code in a
        // fenced block carrying the language; the block arm adds one trailing
        // newline.
        assert_eq!(
            block.selected_text(SelectionFormat::Source),
            format!("```rust\n{}\n```\n", code_trimmed)
        );
        assert!(
            block
                .selected_text(SelectionFormat::Source)
                .starts_with("```rust\n")
        );
        assert!(
            block
                .selected_text(SelectionFormat::Source)
                .trim_end()
                .ends_with("\n```")
        );
    }

    #[test]
    fn code_block_selected_source_without_lang() {
        let block = selected_code_block("plain\n", None);
        let code_trimmed = block.selected_text(SelectionFormat::Plain);
        let code_trimmed = code_trimmed.trim_end_matches('\n');
        assert_eq!(
            block.selected_text(SelectionFormat::Source),
            format!("```\n{}\n```\n", code_trimmed)
        );
    }

    #[test]
    fn document_selected_source_joins_blocks_with_blank_line() {
        use crate::text::document::ParsedDocument;

        // A heading, a paragraph, and a two-item ordered list, each fully
        // selected. Top-level blocks must be separated by a blank line so the
        // copied Markdown re-renders with the same structure.
        let document = ParsedDocument {
            source: String::new().into(),
            blocks: vec![
                BlockNode::Heading {
                    level: 1,
                    children: selected_paragraph("Title"),
                    span: None,
                },
                BlockNode::Paragraph(selected_paragraph("A paragraph.")),
                selected_code_block("let x = 1;\n", Some("rust")),
                BlockNode::List {
                    ordered: true,
                    start: Some(1),
                    span: None,
                    children: vec![
                        BlockNode::ListItem {
                            children: vec![BlockNode::Paragraph(selected_paragraph("one"))],
                            spread: false,
                            checked: None,
                            span: None,
                        },
                        BlockNode::ListItem {
                            children: vec![BlockNode::Paragraph(selected_paragraph("two"))],
                            spread: false,
                            checked: None,
                            span: None,
                        },
                    ],
                },
            ]
            .into(),
        };

        assert_eq!(
            document.selected_text(SelectionFormat::Source, None),
            "# Title\n\nA paragraph.\n\n```rust\nlet x = 1;\n```\n\n1. one\n2. two"
        );
    }

    #[test]
    fn code_block_equality_includes_code_content() {
        let first = CodeBlock::new("let value = 1;".into(), Some("rust".into()), None::<Span>);
        let second = CodeBlock::new("let value = 2;".into(), Some("rust".into()), None::<Span>);

        assert_ne!(first, second);
    }
}
