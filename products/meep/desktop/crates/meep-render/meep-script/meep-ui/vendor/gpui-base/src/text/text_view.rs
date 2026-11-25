use std::{ops::Range, rc::Rc, sync::Arc};

use gpui::prelude::FluentBuilder as _;
use gpui::{
    AnyElement, App, Bounds, ClickEvent, ContentMask, Element, ElementId, Entity, Global,
    GlobalElementId, Hitbox, HitboxBehavior, InspectorElementId, InteractiveElement, IntoElement,
    LayoutId, MouseButton, ParentElement, Pixels, Refineable as _, SharedString, StyleRefinement,
    Styled, Window, div, point, px,
};

use crate::StyledExt;
use crate::text::TextViewFormat;
use crate::text::markdown_ext::{MarkdownExtensions, MarkdownNode, MarkdownPlugin};
use crate::text::node::{CodeBlock, TableData};
use crate::text::range_highlight::{PendingReveal, RevealProgress};
use crate::text::state::{LineSpan, SelectionFormat, TextViewState};
use crate::text::stream_fade::TextViewMotion;
use crate::{GlobalState, TextSelection, text::TextViewStyle};

/// Type for code block actions generator function.
pub(crate) type CodeBlockActionsFn =
    dyn Fn(&CodeBlock, &mut Window, &mut App) -> AnyElement + Send + Sync;

pub(crate) type CodeBlockHighlighterFn =
    dyn Fn(&CodeBlock) -> Vec<(Range<usize>, gpui::HighlightStyle)> + Send + Sync;

/// Application-wide defaults for TextViews that do not provide explicit
/// presentation or syntax-highlighting overrides.
#[derive(Clone, Default)]
pub struct TextViewDefaults {
    style: Option<TextViewStyle>,
    code_block_highlighter: Option<Arc<CodeBlockHighlighterFn>>,
    inherit_text_color: bool,
}

impl Global for TextViewDefaults {}

impl TextViewDefaults {
    /// Creates defaults that leave every text view as Base renders it.
    pub fn new() -> Self {
        Self::default()
    }

    /// Sets the style every text view starts from.
    pub fn with_style(mut self, style: TextViewStyle) -> Self {
        self.style = Some(style);
        self
    }

    /// The style every text view starts from, when set.
    pub(crate) fn style(&self) -> Option<&TextViewStyle> {
        self.style.as_ref()
    }

    /// The syntax highlighter for fenced code blocks, when set.
    pub(crate) fn code_block_highlighter(&self) -> Option<Arc<CodeBlockHighlighterFn>> {
        self.code_block_highlighter.clone()
    }

    /// Sets the syntax highlighter used for fenced code blocks.
    pub fn with_code_block_highlighter<F>(mut self, highlighter: F) -> Self
    where
        F: Fn(&CodeBlock) -> Vec<(Range<usize>, gpui::HighlightStyle)> + Send + Sync + 'static,
    {
        self.code_block_highlighter = Some(Arc::new(highlighter));
        self
    }

    /// Sets whether text views without an explicit [`TextView::style`] follow
    /// the text color their container sets, default false.
    ///
    /// The body text takes that color. On a surface inverted from the page,
    /// such as a `primary` fill, links, muted text, code, borders and
    /// selection are derived from it too, and the installed syntax highlighter
    /// is left out because its colors are made for the page. Enable this only
    /// when every window sets a text color at its root, as Component's does.
    pub fn with_inherit_text_color(mut self, inherit: bool) -> Self {
        self.inherit_text_color = inherit;
        self
    }

    /// Installs these defaults for the whole application.
    pub fn install(self, cx: &mut App) {
        cx.set_global(self);
    }

    /// Returns the installed defaults, or the Base ones when none were.
    pub fn global(cx: &App) -> Self {
        cx.try_global::<Self>().cloned().unwrap_or_default()
    }

    /// Whether a syntax highlighter was installed.
    pub fn has_code_block_highlighter(&self) -> bool {
        self.code_block_highlighter.is_some()
    }

    /// Whether text views follow the text color their container sets.
    pub fn inherit_text_color(&self) -> bool {
        self.inherit_text_color
    }
}

/// Type for the table actions generator function.
pub(crate) type TableActionsFn =
    dyn Fn(&TableData, &mut Window, &mut App) -> AnyElement + Send + Sync;

pub(crate) type ImageSourceFn = dyn Fn(&gpui::SharedUri) -> gpui::ImageSource + Send + Sync;

pub(crate) type LinkClickHandlerFn =
    dyn Fn(&SharedString, &ClickEvent, &mut Window, &mut App) + Send + Sync;

/// Kept by the element only, so unlike the handlers the state carries, it
/// may hold a `ScrollHandle`.
pub(crate) type RevealHandlerFn = dyn Fn(Bounds<Pixels>, &mut Window, &mut App);

pub(crate) fn handle_link_click(
    handler: &Option<Arc<LinkClickHandlerFn>>,
    url: SharedString,
    event: ClickEvent,
    window: &mut Window,
    cx: &mut App,
) {
    if let Some(handler) = handler {
        handler(&url, &event, window, cx);
    } else if match &event {
        ClickEvent::Mouse(click) => {
            matches!(click.up.button, MouseButton::Left | MouseButton::Middle)
        }
        ClickEvent::Keyboard(_) => true,
        ClickEvent::Touch(click) => !click.long_press,
    } {
        cx.open_url(&url);
    }
}

/// A text view that can render Markdown or HTML.
///
/// ## Goals
///
/// - Provide a rich text rendering component for such as Markdown or HTML,
/// used to display rich text in GPUI application (e.g., Help messages, Release notes)
/// - Support Markdown GFM and HTML (Simple HTML like Safari Reader Mode) for showing most common used markups.
/// - Support Heading, Paragraph, Bold, Italic, StrikeThrough, Code, Link, Image, Blockquote, List, Table, HorizontalRule, CodeBlock ...
///
/// ## Not Goals
///
/// - Customization of the complex style (some simple styles will be supported)
/// - As a Markdown editor or viewer (If you want to like this, you must fork your version).
/// - As a HTML viewer, we not support CSS, we only support basic HTML tags for used to as a content reader.
///
/// See also [`MarkdownElement`], [`HtmlElement`]
#[derive(Clone)]
pub struct TextView {
    id: ElementId,
    format: Option<TextViewFormat>,
    text: Option<SharedString>,
    pub(crate) state: Option<Entity<TextViewState>>,
    text_view_style: Option<TextViewStyle>,
    inline_code_style: Option<StyleRefinement>,
    list_style: Option<StyleRefinement>,
    blockquote_style: Option<StyleRefinement>,
    style: StyleRefinement,
    selectable: bool,
    selection_format: SelectionFormat,
    scrollable: bool,
    max_lines: Option<usize>,
    code_block_actions: Option<Arc<CodeBlockActionsFn>>,
    code_block_highlighter: Option<Arc<CodeBlockHighlighterFn>>,
    table_actions: Option<Arc<TableActionsFn>>,
    link_click_handler: Option<Arc<LinkClickHandlerFn>>,
    image_source: Option<Arc<ImageSourceFn>>,
    reveal_handler: Option<Rc<RevealHandlerFn>>,
    markdown_extensions: Arc<MarkdownExtensions>,
    motion: Option<TextViewMotion>,
}

/// A plugin that can configure a [`TextView`].
pub trait TextViewPlugin {
    fn setup(self, text_view: TextView) -> TextView;
}

impl<P> TextViewPlugin for P
where
    P: MarkdownPlugin,
{
    fn setup(self, mut text_view: TextView) -> TextView {
        let extensions = Arc::make_mut(&mut text_view.markdown_extensions);
        let current = std::mem::take(extensions);
        *extensions = current.plugin(self);
        text_view
    }
}

impl Styled for TextView {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl TextView {
    /// Create new TextView with managed state.
    pub fn new(state: &Entity<TextViewState>) -> Self {
        Self {
            id: ElementId::Name(state.entity_id().to_string().into()),
            state: Some(state.clone()),
            format: None,
            text: None,
            text_view_style: None,
            inline_code_style: None,
            list_style: None,
            blockquote_style: None,
            style: StyleRefinement::default(),
            selectable: true,
            selection_format: SelectionFormat::default(),
            scrollable: false,
            max_lines: None,
            code_block_actions: None,
            code_block_highlighter: None,
            table_actions: None,
            link_click_handler: None,
            image_source: None,
            reveal_handler: None,
            markdown_extensions: Arc::default(),
            motion: None,
        }
    }

    /// Create a new markdown text view.
    pub fn markdown(id: impl Into<ElementId>, markdown: impl Into<SharedString>) -> Self {
        Self {
            id: id.into(),
            format: Some(TextViewFormat::Markdown),
            text: Some(markdown.into()),
            text_view_style: None,
            inline_code_style: None,
            list_style: None,
            blockquote_style: None,
            style: StyleRefinement::default(),
            state: None,
            selectable: true,
            selection_format: SelectionFormat::default(),
            scrollable: false,
            max_lines: None,
            code_block_actions: None,
            code_block_highlighter: None,
            table_actions: None,
            link_click_handler: None,
            image_source: None,
            reveal_handler: None,
            markdown_extensions: Arc::default(),
            motion: None,
        }
    }

    /// Create a new html text view.
    pub fn html(id: impl Into<ElementId>, html: impl Into<SharedString>) -> Self {
        Self {
            id: id.into(),
            format: Some(TextViewFormat::Html),
            text: Some(html.into()),
            text_view_style: None,
            inline_code_style: None,
            list_style: None,
            blockquote_style: None,
            style: StyleRefinement::default(),
            state: None,
            selectable: true,
            selection_format: SelectionFormat::default(),
            scrollable: false,
            max_lines: None,
            code_block_actions: None,
            code_block_highlighter: None,
            table_actions: None,
            link_click_handler: None,
            image_source: None,
            reveal_handler: None,
            markdown_extensions: Arc::default(),
            motion: None,
        }
    }

    /// Overrides the source of every document image, including embedded data URLs.
    ///
    /// Used for both rendering and intrinsic-size measurement. The returned source
    /// is authoritative: pending or failed loads never fall back to the document URL.
    /// Without this override, images use Base's default URI and data URL handling.
    pub fn image_source<F>(mut self, resolver: F) -> Self
    where
        F: Fn(&gpui::SharedUri) -> gpui::ImageSource + Send + Sync + 'static,
    {
        self.image_source = Some(Arc::new(resolver));
        self
    }

    /// Refines inline code typography, background, border, radius, and padding
    /// over the resolved style. See [`TextViewStyle::with_inline_code_style`]
    /// for the supported properties. Unspecified properties are inherited.
    pub fn inline_code_style(mut self, style: StyleRefinement) -> Self {
        self.inline_code_style = Some(super::style::normalize_inline_code_style(style));
        self
    }

    /// Refines list markers over the resolved style. See
    /// [`TextViewStyle::with_list_style`] for where it applies.
    /// Unspecified properties are inherited.
    pub fn list_style(mut self, style: StyleRefinement) -> Self {
        self.list_style = Some(style);
        self
    }

    /// Refines blockquotes over the resolved style. See
    /// [`TextViewStyle::with_blockquote_style`] for where it applies.
    /// Unspecified properties are inherited.
    pub fn blockquote_style(mut self, style: StyleRefinement) -> Self {
        self.blockquote_style = Some(style);
        self
    }

    /// Set [`TextViewStyle`].
    pub fn style(mut self, style: TextViewStyle) -> Self {
        self.text_view_style = Some(style);
        self
    }

    /// Set whether the text view is selectable, default is true.
    pub fn selectable(mut self, selectable: bool) -> Self {
        self.selectable = selectable;
        self
    }

    /// Set the [`SelectionFormat`], default is [`SelectionFormat::Plain`].
    ///
    /// With [`SelectionFormat::Source`], selecting inside `**bold**` yields
    /// `**bold**` (the Markdown source) rather than `bold`.
    pub fn selection_format(mut self, selection_format: SelectionFormat) -> Self {
        self.selection_format = selection_format;
        self
    }

    /// Set the text view to be scrollable, default is false.
    ///
    /// ## If true for `scrollable`
    ///
    /// The `scrollable` mode used for large content,
    /// will show scrollbar, but requires the parent to have a fixed height,
    /// and use [`gpui::list`] to render the content in a virtualized way.
    ///
    /// ## If false to fit content
    ///
    /// The TextView will expand to fit all content, no scrollbar.
    /// This mode is suitable for small content, such as a few lines of text, a label, etc.
    pub fn scrollable(mut self, scrollable: bool) -> Self {
        self.scrollable = scrollable;
        self
    }

    /// Clamp the rendered content to at most `n` lines of body text.
    ///
    /// The view's height is capped at `n` × the base line height, and a line
    /// of glyphs is never cut in half: a line that would straddle the bottom
    /// of the box is left out whole, across paragraphs, lists, headings, code
    /// blocks and tables. Nothing is shown with less than a line of itself to
    /// show, so the border and padding a table row leads with never strands at
    /// the bottom; whatever has more than that is cut on the box edge and keeps
    /// the part that fits, rather than disappearing and leaving blank space
    /// behind.
    ///
    /// Check [`TextViewState::is_clamped`] (which answers for the frame that
    /// was last painted) to decide whether to show an "expand" affordance.
    ///
    /// `n` counts lines of body text, so paragraph spacing and taller lines
    /// mean fewer of them fit inside the capped height. A line taller than the
    /// whole budget keeps the part that fits rather than emptying the box.
    /// Ignored when [`Self::scrollable`] is set.
    pub fn max_lines(mut self, max_lines: usize) -> Self {
        self.max_lines = Some(max_lines);
        self
    }

    /// Set custom block actions for code blocks.
    ///
    /// The closure receives the [`CodeBlock`],
    /// and returns an element to display.
    pub fn code_block_actions<F, E>(mut self, f: F) -> Self
    where
        F: Fn(&CodeBlock, &mut Window, &mut App) -> E + Send + Sync + 'static,
        E: IntoElement,
    {
        self.code_block_actions = Some(Arc::new(move |code_block, window, cx| {
            f(&code_block, window, cx).into_any_element()
        }));
        self
    }

    /// Adds opt-in syntax highlighting for fenced code blocks.
    ///
    /// Returned byte ranges are relative to [`CodeBlock::code`]. Invalid
    /// ranges are discarded. Without this callback, code is unhighlighted.
    pub fn code_block_highlighter<F>(mut self, highlighter: F) -> Self
    where
        F: Fn(&CodeBlock) -> Vec<(Range<usize>, gpui::HighlightStyle)> + Send + Sync + 'static,
    {
        self.code_block_highlighter = Some(Arc::new(highlighter));
        self
    }

    /// Like [`Self::code_block_highlighter`], with a highlighter that can be
    /// handed to every frame.
    ///
    /// A code block reuses its highlights only while the highlighter is the
    /// same `Arc`, so a view built every frame with a fresh closure
    /// re-highlights every code block on every frame.
    #[doc(hidden)]
    pub fn shared_code_block_highlighter(
        mut self,
        highlighter: Arc<
            dyn Fn(&CodeBlock) -> Vec<(Range<usize>, gpui::HighlightStyle)> + Send + Sync,
        >,
    ) -> Self {
        self.code_block_highlighter = Some(highlighter);
        self
    }

    /// Set custom actions to be rendered below each Markdown table.
    ///
    /// The closure receives the [`TableData`],
    /// and returns an element to display.
    pub fn table_actions<F, E>(mut self, f: F) -> Self
    where
        F: Fn(&TableData, &mut Window, &mut App) -> E + Send + Sync + 'static,
        E: IntoElement,
    {
        self.table_actions = Some(Arc::new(move |table, window, cx| {
            f(table, window, cx).into_any_element()
        }));
        self
    }

    /// Handle pointer events on rendered links.
    ///
    /// The handler receives the resolved URL and the original GPUI click event.
    /// Without a handler, links open through App::open_url.
    pub fn on_link_click<F>(mut self, handler: F) -> Self
    where
        F: Fn(&SharedString, &ClickEvent, &mut Window, &mut App) + Send + Sync + 'static,
    {
        self.link_click_handler = Some(Arc::new(handler));
        self
    }

    /// Scroll a container that does not follow scroll requests to the line
    /// of [`TextViewState::reveal_range`].
    ///
    /// A `gpui::list` scrolls to that line by itself; a `div` with
    /// `overflow_y_scroll`, for one, does not. After a frame in which the
    /// line was laid out but not visible, the handler receives its bounds in
    /// window coordinates, to scroll the container, e.g. through its
    /// `ScrollHandle`, until the line is visible.
    pub fn on_reveal<F>(mut self, handler: F) -> Self
    where
        F: Fn(Bounds<Pixels>, &mut Window, &mut App) + 'static,
    {
        self.reveal_handler = Some(Rc::new(handler));
        self
    }

    /// Replace the Markdown extension registry.
    pub fn markdown_extensions(mut self, extensions: MarkdownExtensions) -> Self {
        self.markdown_extensions = Arc::new(extensions);
        self
    }

    /// Set the motion policy; see [`TextViewMotion`]. Without one, the
    /// state's own policy applies, which plays no motion by default.
    pub fn motion(mut self, motion: TextViewMotion) -> Self {
        self.motion = Some(motion);
        self
    }

    /// Enable MDX JSX/expression parsing.
    ///
    /// This disables raw HTML parsing because `markdown-rs` gives HTML
    /// priority over MDX when both are enabled.
    pub fn markdown_mdx(mut self) -> Self {
        let extensions = Arc::make_mut(&mut self.markdown_extensions);
        *extensions = extensions.clone().mdx();
        self
    }

    /// Register a custom block-level Markdown parser.
    ///
    /// The parser runs during Markdown AST conversion and must be independent
    /// of [`Window`] / [`App`]. Store any parsed data in [`MarkdownNode`] and
    /// render it later with [`Self::markdown_block_renderer`].
    pub fn markdown_block_parser<F>(mut self, parser: F) -> Self
    where
        F: for<'a> Fn(
                &markdown::mdast::Node,
                &crate::text::MarkdownParseContext<'a>,
            ) -> Option<MarkdownNode>
            + Send
            + Sync
            + 'static,
    {
        Arc::make_mut(&mut self.markdown_extensions).push_block_parser(parser);
        self
    }

    /// Register a renderer for a custom block-level Markdown node name.
    pub fn markdown_block_renderer<F, E>(
        mut self,
        name: impl Into<SharedString>,
        renderer: F,
    ) -> Self
    where
        F: Fn(&MarkdownNode, &mut Window, &mut App) -> E + Send + Sync + 'static,
        E: IntoElement,
    {
        Arc::make_mut(&mut self.markdown_extensions).push_block_renderer(name, renderer);
        self
    }

    /// Apply a reusable text view plugin.
    pub fn plugin<P>(self, plugin: P) -> Self
    where
        P: TextViewPlugin,
    {
        plugin.setup(self)
    }
}

impl IntoElement for TextView {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

pub struct TextViewLayoutState {
    state: Entity<TextViewState>,
    element: AnyElement,
}

pub struct TextViewPrepaintState {
    hitbox: Hitbox,
    /// Where paint has to pull the `max_lines` clip up to, because a glyph line
    /// straddles the bottom of the box. `None` leaves the clip at the box edge,
    /// where the container's hidden overflow already applies it.
    clip_bottom: Option<Pixels>,
    /// The touch handles this view owns, with their hitboxes.
    touch_handles: crate::TouchHandleLayout,
}

/// Absorbs sub-pixel layout jitter: a line ending within a pixel of the box
/// bottom counts as fitting inside it.
const CLIP_EPSILON: Pixels = px(1.);

/// The bottom of the last whole line at or above `y`, with the height of a line
/// where it sits.
fn last_line_bottom_above(spans: &[LineSpan], y: Pixels) -> Option<(Pixels, Pixels)> {
    let mut last: Option<(Pixels, Pixels)> = None;
    let mut keep = |bottom: Pixels, line_height: Pixels| {
        if bottom <= y + CLIP_EPSILON && last.is_none_or(|(last, _)| bottom > last) {
            last = Some((bottom, line_height));
        }
    };

    for span in spans {
        if span.line_height <= px(0.) {
            continue;
        }
        let mut bottom = span.top + span.line_height;
        while bottom <= span.bottom + CLIP_EPSILON {
            keep(bottom, span.line_height);
            bottom += span.line_height;
        }
        // The span's own bottom covers a last line taller than the rest.
        keep(span.bottom, span.line_height);
    }

    last
}

/// Where to clip, given the lines a descendant `Inline` reported. `None` leaves
/// the clip on the box edge.
///
/// Two things are never shown: half a line of glyphs, and anything with less
/// than a line of itself to show. A line straddling `box_bottom` is left out
/// whole, and so is the strip between it and the line before — the border and
/// padding a table row leads with reads as a rendering fault rather than as a
/// row. Whatever has more than a line to show is cut on the edge and keeps the
/// part that fits, so the box holds no blank space it could have filled.
fn line_safe_clip_bottom(
    spans: &[LineSpan],
    box_bottom: Pixels,
    content_bottom: Pixels,
) -> Option<Pixels> {
    let mut clip = box_bottom;

    for span in spans {
        if span.line_height <= px(0.)
            || span.top >= box_bottom
            || span.bottom <= box_bottom + CLIP_EPSILON
        {
            continue;
        }
        let whole_lines = ((box_bottom - span.top) / span.line_height).floor();
        let line_top = span.top + span.line_height * whole_lines;
        // A line starting on the box edge is not straddling it.
        if line_top < box_bottom - CLIP_EPSILON {
            clip = clip.min(line_top);
        }
    }

    let Some((last_line_bottom, line_height)) = last_line_bottom_above(spans, clip) else {
        // Leaving the straddling line out would leave nothing at all — a first
        // line taller than the whole budget, a heading in a one-line box. It
        // keeps the part that fits instead, because an empty clamp reads as
        // broken where a cut one reads as more to come.
        return None;
    };

    // Snap away a scrap. Only content that continues past the box can leave
    // one: the space under the last line of a document that fits is the box's
    // own, not a piece of something below.
    if content_bottom > box_bottom + CLIP_EPSILON {
        let strip = clip - last_line_bottom;
        if strip > CLIP_EPSILON && strip < line_height {
            clip = last_line_bottom;
        }
    }

    (clip < box_bottom - CLIP_EPSILON).then_some(clip)
}

impl Element for TextView {
    type RequestLayoutState = TextViewLayoutState;
    type PrepaintState = TextViewPrepaintState;

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
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
    ) -> (LayoutId, Self::RequestLayoutState) {
        let state = if let Some(state) = self.state.clone() {
            state
        } else {
            let default_format = self.format.unwrap_or(TextViewFormat::Markdown);
            let default_text = self.text.clone().unwrap_or_default();

            let state = window.use_keyed_state(
                SharedString::from(format!("{}/state", self.id)),
                cx,
                move |_, cx| {
                    if default_format == TextViewFormat::Markdown {
                        TextViewState::markdown(default_text.as_str(), cx)
                    } else {
                        TextViewState::html(default_text.as_str(), cx)
                    }
                },
            );
            self.state = Some(state.clone());
            state
        };

        // `max_lines` needs the whole document laid out to snap the clip to a
        // whole line, so it only applies to the fit-content mode.
        let max_lines = self.max_lines.filter(|_| !self.scrollable);

        // Resolve the style by reference: this runs every frame, and the
        // style only reaches the state when it changed.
        let defaults = cx.try_global::<TextViewDefaults>();
        let theme_style;
        let mut text_view_style = match (
            &self.text_view_style,
            defaults.and_then(|d| d.style.as_ref()),
        ) {
            (Some(style), _) | (None, Some(style)) => style,
            (None, None) => {
                theme_style = TextViewStyle::from_theme(&crate::Theme::global(cx));
                &theme_style
            }
        };
        // Follow the text color the container sets for its surface, so rich
        // text stays readable in a filled bubble or a selected row.
        let surface_style;
        let mut on_inverted_surface = false;
        if self.text_view_style.is_none() && defaults.is_some_and(|d| d.inherit_text_color) {
            let color = self
                .style
                .text
                .color
                .unwrap_or_else(|| window.text_style().color);
            if color != text_view_style.foreground() {
                on_inverted_surface = text_view_style.is_inverted_by(color);
                surface_style = text_view_style.on_text_color(color);
                text_view_style = &surface_style;
            }
        }
        let inline_style;
        if let Some(refinement) = &self.inline_code_style {
            let mut style = text_view_style.inline_code_style().clone();
            style.refine(refinement);
            inline_style = text_view_style.clone().with_inline_code_style(style);
            text_view_style = &inline_style;
        }
        let block_style;
        if self.list_style.is_some() || self.blockquote_style.is_some() {
            let mut style = text_view_style.clone();
            if let Some(refinement) = &self.list_style {
                let mut marker = style.list_style().clone();
                marker.refine(refinement);
                style = style.with_list_style(marker);
            }
            if let Some(refinement) = &self.blockquote_style {
                let mut quote = style.blockquote_style().clone();
                quote.refine(refinement);
                style = style.with_blockquote_style(quote);
            }
            block_style = style;
            text_view_style = &block_style;
        }
        let foreground = text_view_style.foreground();
        let text_view_style = (*state.read(cx).text_view_style != *text_view_style)
            .then(|| Arc::new(text_view_style.clone()));
        let code_block_highlighter = self.code_block_highlighter.clone().or_else(|| {
            defaults
                .filter(|_| !on_inverted_surface)
                .and_then(|d| d.code_block_highlighter.clone())
        });

        state.update(cx, |state, cx| {
            if text_view_style.is_some()
                || match (&state.code_block_highlighter, &code_block_highlighter) {
                    (Some(previous), Some(next)) => !Arc::ptr_eq(previous, next),
                    (None, None) => false,
                    _ => true,
                }
            {
                state.preserve_selection_for_reflow();
            }
            state.code_block_actions = self.code_block_actions.clone();
            state.code_block_highlighter = code_block_highlighter;
            state.table_actions = self.table_actions.clone();
            state.link_click_handler = self.link_click_handler.clone();
            state.image_source = self.image_source.clone();
            state.set_markdown_extensions(self.markdown_extensions.clone(), cx);
            if let Some(motion) = &self.motion {
                state.set_motion(motion.clone());
            }
            state.selectable = self.selectable;
            state.selection_format = self.selection_format;
            state.scrollable = self.scrollable;
            state.max_lines = max_lines;
            if let Some(text_view_style) = text_view_style {
                state.text_view_style = text_view_style;
            }

            if let Some(text) = &self.text {
                state.set_element_text(text, cx);
            }
        });

        let focus_handle = state.read(cx).focus_handle.clone();
        let list_state = state.read(cx).list_state.clone();
        // Cap the box at `n` body-text lines (the effective text style may be
        // refined by this view's own style, e.g. `.text_sm()`); hidden
        // overflow also clips descendant hitboxes to the box during prepaint.
        let max_lines_cap = max_lines.map(|max_lines| {
            let mut text_style = window.text_style();
            text_style.refine(&self.style.text);
            text_style.line_height_in_pixels(window.rem_size()) * max_lines as f32
        });

        let mut el = div()
            .id(("text-view-scroll", state.entity_id()))
            .key_context("TextView")
            .track_focus(&focus_handle)
            .when(self.scrollable, |this| this.size_full())
            .when_some(max_lines_cap, |this, cap| this.max_h(cap).overflow_hidden())
            .relative()
            .text_color(foreground)
            .on_action(move |_: &crate::input::Copy, window, cx| {
                let text = TextSelection::selected_text(window, cx).trim().to_string();
                if text.is_empty() {
                    cx.propagate();
                    return;
                }
                cx.write_to_clipboard(gpui::ClipboardItem::new_string(text));
            })
            .on_action(window.listener_for(&state, TextViewState::on_action_select_all))
            .map(|this| {
                if self.scrollable {
                    this.child(crate::ScrollBounce::new(
                        ("text-view-bounce", state.entity_id()),
                        &list_state,
                        state.clone(),
                    ))
                } else {
                    this.child(state.clone())
                }
            })
            // Overlay controls must paint after the document, otherwise rich
            // content and selection backgrounds cover the thumb and hitbox.
            .when(self.scrollable, |this| {
                this.child(
                    div().absolute().inset_0().child(
                        crate::Scrollbar::vertical(&list_state)
                            .id(("text-view-scrollbar", state.entity_id()))
                            .viewport_from_layout(),
                    ),
                )
            })
            .refine_style(&self.style)
            .into_any_element();
        let layout_id = el.request_layout(window, cx);
        (layout_id, TextViewLayoutState { state, element: el })
    }

    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        request_layout: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let state = request_layout.state.clone();
        let max_lines_active = state.read(cx).max_lines.is_some();
        if max_lines_active {
            if let Ok(mut line_spans) = state.read(cx).line_spans.lock() {
                line_spans.clear();
            }
        }
        // Descendants read the view through the state stack during prepaint
        // (in addition to the paint-time push below): `Inline`s report their
        // line spans when `max_lines` is set, and table cells look for the
        // selection anchor.
        GlobalState::global(cx).push_text_view_state(state.clone());
        request_layout.element.prepaint(window, cx);
        GlobalState::global(cx).pop_text_view_state();

        let mut clip_bottom = None;
        if max_lines_active {
            let (line_spans, content_bottom) = {
                let state = state.read(cx);
                (
                    state
                        .line_spans
                        .lock()
                        .map(|spans| spans.clone())
                        .unwrap_or_default(),
                    state.bounds().bottom(),
                )
            };
            // The content keeps its natural height inside the capped box, so
            // this sees everything the box cannot show — including a tall image
            // that reports no lines of its own.
            let clipped = content_bottom > bounds.bottom() + px(1.);
            // Notify on change so observers (e.g. an "expand" button gated on
            // `is_clamped`) re-render once the flag flips.
            if state.read(cx).clamped != clipped {
                state.update(cx, |state, cx| {
                    state.clamped = clipped;
                    cx.notify();
                });
            }
            if clipped {
                clip_bottom = line_safe_clip_bottom(&line_spans, bounds.bottom(), content_bottom);
            }
        }

        let hitbox = window.insert_hitbox(bounds, HitboxBehavior::Normal);
        // Over the text, so after its hitbox.
        let touch_handles = if self.selectable {
            state
                .read(cx)
                .selection_adapter
                .prepaint_touch_handles(window, cx)
        } else {
            crate::TouchHandleLayout::default()
        };
        TextViewPrepaintState {
            hitbox,
            clip_bottom,
            touch_handles,
        }
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        request_layout: &mut Self::RequestLayoutState,
        prepaint: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        let state = &request_layout.state;
        if self.selectable {
            state.read(cx).selection_adapter.begin_frame();
        }

        GlobalState::global(cx).push_text_view_state(state.clone());
        if let Some(clip_bottom) = prepaint.clip_bottom {
            // Snap the `max_lines` clip to the last whole line that fits, so a
            // line of glyphs is never cut in half.
            let mask = ContentMask {
                bounds: Bounds::from_corners(bounds.origin, point(bounds.right(), clip_bottom)),
            };
            window.with_content_mask(Some(mask), |window| {
                request_layout.element.paint(window, cx);
            });
        } else {
            request_layout.element.paint(window, cx);
        }
        GlobalState::global(cx).pop_text_view_state();

        // Every list has scrolled by now, so the line of a reveal is where
        // it ends up this frame.
        if state.read(cx).pending_reveal.is_some() {
            let progress = state.update(cx, |state, _| {
                state.pending_reveal.as_mut().map(PendingReveal::progress)
            });
            match progress {
                Some(RevealProgress::Shown) => {
                    state.update(cx, |state, _| state.pending_reveal = None);
                }
                Some(RevealProgress::Hidden(line)) => {
                    if let Some(handler) = &self.reveal_handler {
                        handler(line, window, cx);
                    }
                }
                Some(RevealProgress::NotLaidOut) | None => {}
            }
        }

        if self.selectable {
            let (adapter, scroll_offset, content_bounds, self_scroll, handle_color) = {
                let state = state.read(cx);
                (
                    state.selection_adapter.clone(),
                    state.scroll_offset(),
                    state.bounds(),
                    state.scrollable,
                    state.text_view_style.selection().alpha(1.),
                )
            };
            adapter.register(
                prepaint.hitbox.clone(),
                content_bounds,
                scroll_offset,
                self_scroll,
                window,
                cx,
            );
            // The handles of a touch selection go over the text, and under
            // whatever is painted over the text after it.
            adapter.paint_touch_handles(&prepaint.touch_handles, handle_color, window, cx);
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };

    use super::{TextView, TextViewPlugin};
    use crate::text::{SelectionFormat, TableData, TextViewState, TextViewStyle};
    use gpui::{
        AppContext as _, Bounds, ClickEvent, Context, Entity, InteractiveElement as _, IntoElement,
        Modifiers, MouseButton, MouseDownEvent, MouseUpEvent, Overflow, ParentElement as _, Pixels,
        Render, SharedString, StatefulInteractiveElement as _, StyleRefinement, Styled as _,
        TestAppContext, VisualTestContext, Window, div, point, prelude::FluentBuilder as _, px,
        rems,
    };

    struct TextViewTestRoot {
        text_view: Entity<TextViewState>,
    }

    struct InlineHoverTestRoot {
        view: Entity<TextViewState>,
        builds: Arc<AtomicUsize>,
        format: crate::text::SelectionFormat,
    }

    struct InlineHoverCard;
    impl Render for InlineHoverCard {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .debug_selector(|| "inline-test-card".into())
                .w(px(120.))
                .h(px(40.))
                .child("Member profile")
        }
    }

    impl Render for InlineHoverTestRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let builds = self.builds.clone();
            div()
                .pl(px(150.))
                .w(px(300.))
                .text_size(px(16.))
                .child(crate::TextSelectionLayer)
                .child(
                    TextView::new(&self.view)
                        .selection_format(self.format)
                        .plugin(
                            crate::text::markdown_ext::TestInlinePlugin::new("mention")
                                .parse_with(|node, _| {
                                    let markdown::mdast::Node::Link(link) = node else {
                                        return None;
                                    };
                                    let handle = link.url.strip_prefix("mention:")?;
                                    Some(
                                        crate::text::MarkdownNode::new("mention", ())
                                            .text(format!("@{handle}")),
                                    )
                                })
                                .render_with(move |_, _, _, _| {
                                    let builds = builds.clone();
                                    Some(crate::text::InlineElement::new(
                                        crate::HoverCard::new("mention-hover")
                                            .anchor(gpui::Anchor::TopCenter)
                                            .trigger(div().child("@member"))
                                            .content(move |_, _, cx| {
                                                builds.fetch_add(1, Ordering::Relaxed);
                                                div()
                                                    .id("hover-content")
                                                    .child(cx.new(|_| InlineHoverCard))
                                            }),
                                    ))
                                }),
                        ),
                )
        }
    }

    #[gpui::test]
    fn text_view_follows_the_text_color_of_its_container(cx: &mut TestAppContext) {
        struct Root {
            inherited: Entity<TextViewState>,
            explicit: Entity<TextViewState>,
            surface_text: gpui::Hsla,
        }
        impl Render for Root {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(300.))
                    .text_color(crate::ColorTokens::light().foreground)
                    .child(
                        div()
                            .text_color(self.surface_text)
                            .child(TextView::new(&self.inherited))
                            .child(TextView::new(&self.explicit).style(TextViewStyle::default())),
                    )
            }
        }

        let colors = crate::ColorTokens::light();
        cx.update(|cx| {
            crate::init(cx);
            super::TextViewDefaults::new()
                .with_style(TextViewStyle::default())
                .with_inherit_text_color(true)
                .install(cx);
        });
        let (root, cx) = cx.add_window_view(|_, cx| Root {
            inherited: cx.new(|cx| TextViewState::markdown("[link](https://a.b) `code`", cx)),
            explicit: cx.new(|cx| TextViewState::markdown("text", cx)),
            surface_text: colors.primary_foreground,
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
        });

        root.read_with(cx, |root, cx| {
            let inherited = &root.inherited.read(cx).text_view_style;
            assert_eq!(inherited.foreground(), colors.primary_foreground);
            assert_eq!(inherited.link(), colors.primary_foreground);
            assert!(inherited.is_dark());

            let explicit = &root.explicit.read(cx).text_view_style;
            assert_eq!(explicit.foreground(), colors.foreground);
            assert_eq!(explicit.link(), TextViewStyle::default().link());
        });
    }

    #[gpui::test]
    fn inline_plugin_reuses_render_and_preserves_native_child_events(cx: &mut TestAppContext) {
        use std::sync::Mutex;
        struct ControlPlugin(Arc<Mutex<Vec<String>>>);
        impl crate::text::MarkdownPlugin for ControlPlugin {
            fn name(&self) -> &str {
                "control"
            }
            fn parse(
                &self,
                node: &markdown::mdast::Node,
                _: &crate::text::MarkdownParseContext<'_>,
            ) -> Option<crate::text::MarkdownNode> {
                let markdown::mdast::Node::Link(link) = node else {
                    return None;
                };
                let label = link.url.strip_prefix("control:")?;
                Some(crate::text::MarkdownNode::new("control", ()).text(label.to_string()))
            }
            fn render(
                &self,
                node: &crate::text::MarkdownNode,
                _: &mut Window,
                _: &mut gpui::App,
            ) -> impl IntoElement {
                let clicks = self.0.clone();
                let label = node.as_text().to_string();
                div()
                    .id("same-control-id")
                    .w(px(60.))
                    .h(px(24.))
                    .on_mouse_down(MouseButton::Left, |_, _, cx| cx.stop_propagation())
                    .on_click(move |_, _, _| clicks.lock().unwrap().push(label.clone()))
                    .child(node.as_text().to_string())
            }
        }
        struct Root {
            view: Entity<TextViewState>,
            clicks: Arc<Mutex<Vec<String>>>,
        }
        impl Render for Root {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(300.))
                    .child(crate::TextSelectionLayer)
                    .child(TextView::new(&self.view).plugin(ControlPlugin(self.clicks.clone())))
            }
        }
        cx.update(crate::init);
        let clicks = Arc::new(Mutex::new(Vec::new()));
        let captured = clicks.clone();
        let (root, cx) = cx.add_window_view(move |_, cx| Root {
            view: cx.new(|cx| TextViewState::markdown("[one](control:one)[two](control:two)", cx)),
            clicks,
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
        });
        let bounds = root.read_with(cx, |root, cx| {
            root.view.read(cx).selection_adapter.text_bounds()
        });
        assert_eq!(bounds.len(), 2);
        for bounds in bounds {
            cx.simulate_click(bounds.center(), Modifiers::default());
            cx.update(|window, cx| {
                window.draw(cx).clear(cx);
            });
        }
        assert_eq!(*captured.lock().unwrap(), vec!["one", "two"]);
    }

    #[gpui::test]
    fn inline_hover_card_is_lazy_and_retains_atomic_copy(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let builds = Arc::new(AtomicUsize::new(0));
        let source = "[@member](mention:member)";
        let (root, cx) = cx.add_window_view(|_, cx| InlineHoverTestRoot {
            view: cx.new(|cx| TextViewState::markdown(source, cx)),
            builds: builds.clone(),
            format: crate::text::SelectionFormat::Plain,
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(builds.load(Ordering::Relaxed), 0);
        let view = root.read_with(cx, |root, _| root.view.clone());
        let bounds = view.read_with(cx, |view, _| view.selection_adapter.text_bounds()[0]);
        cx.update(|window, cx| {
            window.simulate_mouse_move(point(bounds.right() - px(1.), bounds.center().y), cx)
        });
        cx.run_until_parked();
        cx.executor()
            .advance_clock(std::time::Duration::from_secs(1));
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(
            builds.load(Ordering::Relaxed) > 0,
            "hover did not build the card"
        );
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let card = cx
            .debug_bounds("inline-test-card")
            .expect("hover card should be painted");
        assert!(
            (card.center().x - bounds.center().x).abs() < px(1.),
            "card {card:?} must be centered on mention {bounds:?}"
        );
        assert!(
            card.top() >= bounds.bottom(),
            "card should be below the mention"
        );
        for (format, expected) in [
            (crate::text::SelectionFormat::Plain, "@member"),
            (crate::text::SelectionFormat::Source, source),
        ] {
            root.update(cx, |root, cx| {
                root.format = format;
                cx.notify();
            });
            view.update(cx, |view, cx| {
                view.set_selection_format(format, cx);
                view.select_all(cx);
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            assert_eq!(
                view.read_with(cx, |view, _| view.selected_text()).trim(),
                expected
            );
        }
    }

    struct InlinePluginTestRoot {
        text_view: Entity<TextViewState>,
        width: Pixels,
        font_size: Pixels,
        source_format: bool,
        prepared_size: Option<Arc<AtomicUsize>>,
    }

    impl Render for InlinePluginTestRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let prepared_size = self.prepared_size.clone();
            div().w(self.width).text_size(self.font_size).child(crate::TextSelectionLayer).child(
                TextView::new(&self.text_view)
                    .selection_format(if self.source_format { crate::text::SelectionFormat::Source }
                        else { crate::text::SelectionFormat::Plain })

                    .plugin(crate::text::markdown_ext::TestInlinePlugin::new("math").parse_with(|node, _| {
                        let markdown::mdast::Node::InlineMath(math) = node else { return None };
                        Some(crate::text::MarkdownNode::new("math", ()).text(format!("{}²", math.value)))
                    }).render_with(move |_, context, _, _| {
                        let value = prepared_size.as_ref()?.load(Ordering::Relaxed) as f32;
                        let image = Arc::new(gpui::Image::from_bytes(gpui::ImageFormat::Svg,
                            b"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"40\" height=\"40\"><path d=\"M0 0L40 40\" stroke=\"black\"/></svg>".to_vec()));
                        let unit = context.font_size() / 16.;
                        Some(crate::text::InlineElement::new(gpui::img(image).w(unit * value).h(unit * value)).with_baseline(unit * value * 0.75))
                    })))
        }
    }

    #[gpui::test]
    fn inline_plugins_drag_and_copy_across_formulas_in_both_directions(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| InlinePluginTestRoot {
            text_view: cx.new(|cx| TextViewState::markdown("中文 $x$ $y$ English", cx)),
            width: px(420.),
            font_size: px(16.),
            source_format: false,
            prepared_size: None,
        });
        let cx: &mut VisualTestContext = cx;
        for font_size in [16., 24., 32.] {
            for width in [60., 160., 420.] {
                for prepared in [None, Some(32)] {
                    for source_format in [false, true] {
                        root.update(cx, |root, cx| {
                            root.source_format = source_format;
                            root.width = px(width);
                            root.font_size = px(font_size);
                            root.prepared_size =
                                prepared.map(|value| Arc::new(AtomicUsize::new(value)));
                            cx.notify();
                        });
                        cx.run_until_parked();
                        cx.update(|window, cx| window.draw(cx).clear(cx));
                        let bounds =
                            root.read_with(cx, |root, cx| root.text_view.read(cx).bounds());
                        let text_bounds = root.read_with(cx, |root, cx| {
                            root.text_view.read(cx).selection_adapter.text_bounds()
                        });
                        let first = text_bounds.first().unwrap();
                        let last = text_bounds.last().unwrap();
                        let left =
                            point(first.left() + px(0.1), first.top() + first.size.height / 2.);
                        let right =
                            point(last.right() - px(0.1), last.top() + last.size.height / 2.);
                        for (start, end) in [(left, right), (right, left)] {
                            cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
                            cx.update(|window, cx| window.draw(cx).clear(cx));
                            cx.simulate_mouse_move(end, MouseButton::Left, Modifiers::default());
                            cx.update(|window, cx| window.draw(cx).clear(cx));
                            cx.simulate_mouse_up(end, MouseButton::Left, Modifiers::default());
                            cx.update(|window, cx| window.draw(cx).clear(cx));
                            let selected = root
                                .read_with(cx, |root, cx| root.text_view.read(cx).selected_text());
                            assert_eq!(
                                selected.trim(),
                                if source_format {
                                    "中文 $x$ $y$ English"
                                } else {
                                    "中文 x² y² English"
                                },
                                "start={start:?} end={end:?} bounds={bounds:?} width={width} font_size={font_size} prepared={prepared:?}"
                            );
                        }
                    }
                }
            }
        }
    }

    #[gpui::test]
    fn inline_resource_size_update_reflows_without_changing_selection(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let prepared_size = Arc::new(AtomicUsize::new(16));
        let (root, cx) = cx.add_window_view(|_, cx| InlinePluginTestRoot {
            text_view: cx.new(|cx| TextViewState::markdown("中文 $x$ $y$ English", cx)),
            width: px(160.),
            font_size: px(16.),
            source_format: false,
            prepared_size: Some(prepared_size.clone()),
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let before = root.read_with(cx, |root, cx| root.text_view.read(cx).bounds());
        let regions = root.read_with(cx, |root, cx| {
            root.text_view.read(cx).selection_adapter.text_bounds()
        });
        let first = regions.first().unwrap();
        let last = regions.last().unwrap();
        let start = point(first.left() + px(0.1), first.top() + px(10.));
        let end = point(last.right() - px(0.1), last.top() + px(10.));
        cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_mouse_move(end, MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_mouse_up(end, MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(
            root.read_with(cx, |root, cx| root.text_view.read(cx).selected_text())
                .trim(),
            "中文 x² y² English"
        );
        prepared_size.store(100, Ordering::Relaxed);
        root.update(cx, |root, cx| {
            root.text_view
                .update(cx, |state, cx| state.invalidate_inline_layout(cx))
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let after = root.read_with(cx, |root, cx| root.text_view.read(cx).bounds());
        assert!(after.size.height > before.size.height * 2.);
        assert_eq!(
            root.read_with(cx, |root, cx| root.text_view.read(cx).selected_text())
                .trim(),
            "中文 x² y² English"
        );
    }

    #[gpui::test]
    fn triple_click_on_formula_selects_its_entire_mixed_line(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| InlinePluginTestRoot {
            text_view: cx.new(|cx| TextViewState::markdown("before $x$ after", cx)),
            width: px(420.),
            font_size: px(16.),
            source_format: false,
            prepared_size: None,
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let regions = root.read_with(cx, |root, cx| {
            root.text_view.read(cx).selection_adapter.text_bounds()
        });
        let formula = regions[1];
        let position = formula.center();
        cx.simulate_event(MouseDownEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 3,
            first_mouse: false,
        });
        cx.simulate_event(MouseUpEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 3,
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(
            root.read_with(cx, |root, cx| root.text_view.read(cx).selected_text())
                .trim(),
            "before x² after"
        );
        root.update(cx, |root, cx| {
            root.source_format = true;
            cx.notify();
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(
            root.read_with(cx, |root, cx| root.text_view.read(cx).selected_text())
                .trim(),
            "before $x$ after"
        );
    }

    #[gpui::test]
    fn double_click_on_formula_selects_only_that_object(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| InlinePluginTestRoot {
            text_view: cx.new(|cx| TextViewState::markdown("before $x$ after", cx)),
            width: px(420.),
            font_size: px(16.),
            source_format: false,
            prepared_size: None,
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let regions = root.read_with(cx, |root, cx| {
            root.text_view.read(cx).selection_adapter.text_bounds()
        });
        let position = regions[1].center();
        cx.simulate_event(MouseDownEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
            first_mouse: false,
        });
        cx.simulate_event(MouseUpEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        // Two clicks stop at the object; only three take the whole line.
        assert_eq!(
            root.read_with(cx, |root, cx| root.text_view.read(cx).selected_text())
                .trim(),
            "x²"
        );
    }

    /// A scrollable viewport, so the list has a bounded height to measure
    /// against and `max_offset_for_scrollbar` reports a real scroll extent.
    struct ScrollExtentTestRoot {
        text_view: Entity<TextViewState>,
    }

    impl Render for ScrollExtentTestRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(400.))
                .h(px(200.))
                .overflow_hidden()
                .child(TextView::new(&self.text_view).scrollable(true))
        }
    }

    /// `count` paragraphs, each `words` words long, so two documents can share
    /// a block count while differing wildly in height.
    fn document_of(count: usize, words: usize) -> String {
        (1..=count)
            .map(|i| format!("Block {i}: {}", "lorem ipsum dolor ".repeat(words)))
            .collect::<Vec<_>>()
            .join("\n\n")
    }

    /// Replacing a document with one that happens to have the *same* block
    /// count must still re-measure. `Document::render_root` only resets the
    /// list when the count changes, so without an explicit re-measure every
    /// cached height stays with the previous document and the scroll extent
    /// keeps describing it.
    #[gpui::test]
    fn replacing_a_document_with_an_equal_block_count_remeasures(cx: &mut TestAppContext) {
        cx.update(crate::init);

        const BLOCKS: usize = 24;
        let short = document_of(BLOCKS, 1);
        let tall = document_of(BLOCKS, 60);

        let (root, cx) = cx.add_window_view(|_, cx| ScrollExtentTestRoot {
            text_view: cx.new(|cx| TextViewState::markdown(&short, cx)),
        });
        let cx: &mut VisualTestContext = cx;

        // The list is populated and measured during layout, so every
        // assertion below has to follow a real frame.
        let settle = |cx: &mut VisualTestContext| {
            cx.run_until_parked();
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.run_until_parked();
        };
        settle(cx);

        let scroll_extent = |cx: &mut VisualTestContext| {
            root.read_with(cx, |root, cx| {
                root.text_view
                    .read(cx)
                    .list_state()
                    .max_offset_for_scrollbar()
                    .y
            })
        };

        let short_extent = scroll_extent(cx);

        root.update(cx, |root, cx| {
            root.text_view
                .update(cx, |state, cx| state.set_text(&tall, cx));
        });
        settle(cx);

        root.read_with(cx, |root, cx| {
            assert_eq!(
                root.text_view.read(cx).list_state().item_count(),
                BLOCKS,
                "the replacement must keep the block count, or the list resets and the bug cannot occur"
            );
        });

        let tall_extent = scroll_extent(cx);
        assert!(
            tall_extent > short_extent * 5.,
            "a much taller document must grow the scroll extent, but it went from \
             {short_extent:?} to {tall_extent:?}"
        );
    }

    struct StatelessMarkdownRoot {
        renders: Arc<AtomicUsize>,
    }

    impl Render for StatelessMarkdownRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            self.renders.fetch_add(1, Ordering::Relaxed);
            div().child(
                TextView::markdown("stateless-markdown", include_str!("../../../../README.md"))
                    .markdown_block_parser(|_, _| None),
            )
        }
    }

    struct DummyTextViewPlugin;

    impl TextViewPlugin for DummyTextViewPlugin {
        fn setup(self, mut text_view: TextView) -> TextView {
            text_view.selectable = true;
            text_view
        }
    }

    #[gpui::test]
    fn text_view_constructors_are_selectable_by_default(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("state", cx)));

        assert!(TextView::new(&state).selectable);
        assert!(TextView::markdown("markdown", "text").selectable);
        assert!(TextView::html("html", "<p>text</p>").selectable);
    }

    #[gpui::test]
    fn stateless_markdown_with_rebuilt_parser_settles(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let renders = Arc::new(AtomicUsize::new(0));
        let (_, cx) = cx.add_window_view({
            let renders = renders.clone();
            move |_, _| StatelessMarkdownRoot { renders }
        });
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let renders_after_redraw = renders.load(Ordering::Relaxed);
        cx.run_until_parked();
        assert_eq!(
            renders.load(Ordering::Relaxed),
            renders_after_redraw,
            "an unchanged TextView must not schedule another render after its parser is rebuilt",
        );
    }

    #[gpui::test]
    fn markdown_data_url_image_is_decoded_inline(cx: &mut TestAppContext) {
        use gpui::{Image, ImageFormat, ImageSource};

        // A 1x1 red PNG.
        const PNG_BASE64: &str = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==";

        cx.update(crate::init);
        let markdown = format!("Inline ![dot](data:image/png;base64,{PNG_BASE64}) image");
        let (_, cx) = cx.add_window_view(|_, cx| TextViewTestRoot::new(&markdown, cx));
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        // `Image` keys the asset system by a hash of its bytes, so rebuilding it
        // from the same body finds the entry the text view's `img` registered
        // when it rendered — proof the body was decoded in place instead of
        // being fetched over HTTP.
        let bytes = data_url::DataUrl::process(&format!("data:image/png;base64,{PNG_BASE64}"))
            .unwrap()
            .decode_to_vec()
            .unwrap()
            .0;
        let image = Arc::new(Image::from_bytes(ImageFormat::Png, bytes));
        assert!(
            cx.update(|_, cx| ImageSource::Image(image).is_asset_cached(cx)),
            "the data URL image must be handed to GPUI as decoded bytes",
        );
    }

    #[gpui::test]
    fn unstyled_text_view_uses_base_tokens_for_link_and_input_selection(cx: &mut TestAppContext) {
        cx.update(crate::init);
        cx.update(|cx| {
            let colors = &mut crate::Theme::global_mut(cx).tokens.colors;
            colors.primary = gpui::rgb(0x55aaff).into();
            colors.selection = gpui::rgb(0x335577).into();
        });
        let (root, cx) = cx.add_window_view(|_, cx| TextViewTestRoot::new("[link](url)", cx));
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        root.read_with(cx, |root, cx| {
            let style = &root.text_view.read(cx).text_view_style;
            assert_eq!(style.link(), gpui::rgb(0x55aaff).into());
            assert_eq!(style.selection(), gpui::rgb(0x335577).into());
        });
    }

    #[gpui::test]
    fn inline_code_view_refinement_keeps_unspecified_style_properties(cx: &mut TestAppContext) {
        use super::{TextViewDefaults, TextViewStyle};
        struct StyledCode(Entity<TextViewState>);
        impl Render for StyledCode {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                TextView::new(&self.0)
                    .inline_code_style(
                        StyleRefinement::default()
                            .border_1()
                            .border_color(gpui::blue()),
                    )
                    .into_any_element()
            }
        }
        cx.update(crate::init);
        cx.update(|cx| {
            cx.set_global(
                TextViewDefaults::default().with_style(
                    TextViewStyle::default().with_inline_code_style(
                        StyleRefinement::default()
                            .text_size(rems(1.))
                            .bg(gpui::red()),
                    ),
                ),
            )
        });
        let (root, cx) = cx.add_window_view(|_, cx| {
            StyledCode(cx.new(|cx| TextViewState::markdown("before `code` after", cx)))
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        root.read_with(cx, |root, cx| {
            let state = root.0.read(cx);
            let style = state.text_view_style.inline_code_style();
            assert_eq!(style.text.font_size, Some(rems(1.).into()));
            assert_eq!(style.background, Some(gpui::red().into()));
            assert_eq!(style.border_color, Some(gpui::blue()));
            assert_eq!(style.border_widths.left, Some(px(1.).into()));
        });
    }

    #[gpui::test]
    fn list_and_blockquote_view_refinements_keep_unspecified_style_properties(
        cx: &mut TestAppContext,
    ) {
        use super::{TextViewDefaults, TextViewStyle};
        struct StyledBlocks(Entity<TextViewState>);
        impl Render for StyledBlocks {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                TextView::new(&self.0)
                    .list_style(StyleRefinement::default().text_color(gpui::blue()))
                    .blockquote_style(StyleRefinement::default().border_color(gpui::blue()))
                    .into_any_element()
            }
        }
        cx.update(crate::init);
        cx.update(|cx| {
            cx.set_global(
                TextViewDefaults::default().with_style(
                    TextViewStyle::default()
                        .with_list_style(
                            StyleRefinement::default().font_weight(gpui::FontWeight::BOLD),
                        )
                        .with_blockquote_style(StyleRefinement::default().border_l_4()),
                ),
            )
        });
        let (root, cx) = cx.add_window_view(|_, cx| {
            StyledBlocks(cx.new(|cx| TextViewState::markdown("- item\n\n> quote", cx)))
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        root.read_with(cx, |root, cx| {
            let style = &root.0.read(cx).text_view_style;
            let marker = style.list_style();
            assert_eq!(marker.text.color, Some(gpui::blue()));
            assert_eq!(marker.text.font_weight, Some(gpui::FontWeight::BOLD));
            let quote = style.blockquote_style();
            assert_eq!(quote.border_color, Some(gpui::blue()));
            assert_eq!(quote.border_widths.left, Some(px(4.).into()));
        });
    }

    impl TextViewTestRoot {
        fn new(text: &str, cx: &mut Context<Self>) -> Self {
            let text = text.to_string();
            let text_view = cx.new(|cx| TextViewState::markdown(&text, cx));
            Self { text_view }
        }
    }

    impl Render for TextViewTestRoot {
        fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(160.))
                .child(
                    div()
                        .h(px(24.))
                        .overflow_hidden()
                        .child(TextView::new(&self.text_view).selectable(true)),
                )
                .child(div().h(px(40.)).child("footer"))
        }
    }

    struct TableSelectionTestRoot {
        text_view: Entity<TextViewState>,
    }

    impl Render for TableSelectionTestRoot {
        fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
            div()
                .debug_selector(|| "table-selection-root".into())
                .w(px(520.))
                .child(crate::TextSelectionLayer)
                .child(TextView::new(&self.text_view))
        }
    }

    #[gpui::test]
    fn table_drag_selection_settles_without_requesting_idle_frames(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, cx| TableSelectionTestRoot {
            text_view: cx.new(|cx| {
                TextViewState::markdown(
                    "| Header 1 | Header 2 |\n| --- | --- |\n| Cell A | Cell B |\n| Cell C | Cell D |",
                    cx,
                )
            }),
        });
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        let bounds = cx
            .debug_bounds("table-selection-root")
            .expect("table bounds");
        let start = point(bounds.left() + px(24.), bounds.top() + px(16.));
        let end = point(bounds.right() - px(24.), bounds.bottom() - px(16.));
        cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
        cx.simulate_mouse_move(end, MouseButton::Left, Modifiers::default());
        cx.simulate_mouse_up(end, MouseButton::Left, Modifiers::default());

        assert!(cx.update(|window, cx| crate::TextSelection::has_selection(window, cx)));
        assert_eq!(
            cx.update(|window, cx| window.simulate_next_frame(cx)),
            0,
            "finished table selection must not continuously request frames"
        );
    }

    /// A drag that starts in a table cell selects only in that cell, also when
    /// the pointer leaves the cell. A drag that starts outside the table still
    /// selects through it.
    #[gpui::test]
    fn table_drag_from_a_cell_stays_in_that_cell(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| TableSelectionTestRoot {
            text_view: cx.new(|cx| {
                TextViewState::markdown(
                    "Intro\n\n| Header 1 | Header 2 |\n| --- | --- |\n| Cell A | Cell B |\n| Cell C | Cell D |",
                    cx,
                )
            }),
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let text_bounds = root.read_with(cx, |root, cx| {
            root.text_view.read(cx).selection_adapter.text_bounds()
        });
        assert_eq!(text_bounds.len(), 7, "{text_bounds:?}");
        let [intro, _, _, cell_a, cell_b, _, cell_d] = text_bounds[..] else {
            unreachable!()
        };
        let table = cx
            .debug_bounds("table-selection-root")
            .expect("table bounds");
        let start_of = |bounds: Bounds<Pixels>| point(bounds.left() + px(0.1), bounds.center().y);
        let end_of = |bounds: Bounds<Pixels>| point(bounds.right() - px(0.1), bounds.center().y);

        let mut drag = |start, end| {
            cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.simulate_mouse_move(end, MouseButton::Left, Modifiers::default());
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.simulate_mouse_up(end, MouseButton::Left, Modifiers::default());
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let selected = root.read_with(cx, |root, cx| root.text_view.read(cx).selected_text());
            let copied = cx.update(|window, cx| crate::TextSelection::selected_text(window, cx));
            (selected.trim().to_string(), copied.trim().to_string())
        };

        // Down and right, out of the table: the rest of the cell, nothing else.
        let below = point(table.right() - px(2.), table.bottom() - px(1.));
        let expected = ("Cell A".to_string(), "Cell A".to_string());
        assert_eq!(drag(start_of(cell_a), below), expected);

        // Back along its line into the cell before it, and up and out of the
        // table: the start of the cell, nothing else.
        let expected = ("Cell B".to_string(), "Cell B".to_string());
        let left = point(cell_a.center().x, cell_b.center().y);
        assert_eq!(drag(end_of(cell_b), left), expected);
        let above = point(table.left() + px(2.), intro.top());
        assert_eq!(drag(end_of(cell_b), above), expected);

        // From the paragraph before the table, the selection goes through it.
        let (selected, copied) = drag(start_of(intro), end_of(cell_d));
        for text in ["Intro", "Header 1", "Cell A", "Cell B", "Cell C", "Cell D"] {
            assert!(selected.contains(text), "{text} not in {selected:?}");
            assert!(copied.contains(text), "{text} not in {copied:?}");
        }

        // Copy before the frame that paints the last move: Copy projects the
        // selection itself and keeps it in the cell too.
        cx.simulate_mouse_down(start_of(cell_a), MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_mouse_move(end_of(cell_a), MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.simulate_mouse_move(below, MouseButton::Left, Modifiers::default());
        cx.simulate_mouse_up(below, MouseButton::Left, Modifiers::default());
        let copied = cx.update(|window, cx| crate::TextSelection::selected_text(window, cx));
        assert_eq!(copied.trim(), "Cell A");
    }

    struct CellSelectionTestRoot {
        text_view: Entity<TextViewState>,
        scrollable: bool,
    }

    impl Render for CellSelectionTestRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(520.))
                .h(px(400.))
                .child(crate::TextSelectionLayer)
                .child(TextView::new(&self.text_view).scrollable(self.scrollable))
        }
    }

    #[gpui::test]
    fn table_cell_copy_excludes_following_blocks_in_a_scrollable_view(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| CellSelectionTestRoot {
            text_view: cx.new(|cx| TextViewState::markdown(
                "| Header | Other |\n| --- | --- |\n| Cell A | Cell B |\n\nMiddle paragraph\n\nLast paragraph", cx)),
            scrollable: true,
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let rows = root.read_with(cx, |root, cx| {
            root.text_view.read(cx).selection_adapter.text_bounds()
        });
        assert_eq!(rows.len(), 6, "{rows:?}");
        let start = point(rows[2].left() + px(0.1), rows[2].center().y);
        let inside = point(rows[2].right() - px(0.1), rows[2].center().y);
        let end = point(rows[5].right() - px(0.1), rows[5].center().y);
        cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
        cx.simulate_mouse_move(inside, MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        // The copy callback must constrain the logical block range even before paint.
        cx.simulate_mouse_move(end, MouseButton::Left, Modifiers::default());
        cx.simulate_mouse_up(end, MouseButton::Left, Modifiers::default());
        for format in [SelectionFormat::Plain, SelectionFormat::Source] {
            root.update(cx, |root, cx| {
                root.text_view
                    .update(cx, |state, cx| state.set_selection_format(format, cx))
            });
            let copied = cx.update(|window, cx| crate::TextSelection::selected_text(window, cx));
            assert_eq!(copied.trim(), "Cell A", "{format:?}");
        }
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let selected = root.read_with(cx, |root, cx| root.text_view.read(cx).selected_text());
        assert_eq!(selected.trim(), "Cell A");
    }

    #[gpui::test]
    fn table_cell_touch_select_all_includes_every_cell(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| CellSelectionTestRoot {
            text_view: cx.new(|cx| {
                TextViewState::markdown(
                    "| Header | Other |\n| --- | --- |\n| Cell A | Cell B |",
                    cx,
                )
            }),
            scrollable: false,
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let rows = root.read_with(cx, |root, cx| {
            root.text_view.read(cx).selection_adapter.text_bounds()
        });
        let position = rows[2].center();
        for phase in [gpui::TouchPhase::Started, gpui::TouchPhase::Ended] {
            cx.simulate_event(gpui::LongPressEvent {
                phase,
                start_position: position,
                position,
            });
        }
        cx.update(|window, cx| {
            window.draw(cx).clear(cx);
            crate::TextSelection::select_all(window, cx);
            window.draw(cx).clear(cx);
        });
        let copied = cx.update(|window, cx| crate::TextSelection::selected_text(window, cx));
        let selected = root.read_with(cx, |root, cx| root.text_view.read(cx).selected_text());
        for text in ["Header", "Other", "Cell A", "Cell B"] {
            assert!(selected.contains(text), "{selected:?}");
            assert!(copied.contains(text), "{copied:?}");
        }
    }

    #[gpui::test]
    fn table_cell_selection_does_not_leak_into_another_window(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let start = {
            let (root, cx) = cx.add_window_view(|_, cx| CellSelectionTestRoot {
                text_view: cx.new(|cx| {
                    TextViewState::markdown(
                        "| Header | Other |\n| --- | --- |\n| Cell A | Cell B |",
                        cx,
                    )
                }),
                scrollable: false,
            });
            cx.run_until_parked();
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let rows = root.read_with(cx, |root, cx| {
                root.text_view.read(cx).selection_adapter.text_bounds()
            });
            let start = point(rows[0].left() + px(0.1), rows[0].center().y);
            let end = point(rows[0].right() - px(0.1), rows[0].center().y);
            cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
            cx.simulate_mouse_move(end, MouseButton::Left, Modifiers::default());
            cx.simulate_mouse_up(end, MouseButton::Left, Modifiers::default());
            cx.update(|window, cx| window.draw(cx).clear(cx));
            assert_eq!(
                cx.update(|window, cx| crate::TextSelection::selected_text(window, cx))
                    .trim(),
                "Header"
            );
            start
        };
        let (root, cx) = cx.add_window_view(|_, cx| CellSelectionTestRoot {
            text_view: cx.new(|cx| TextViewState::markdown("ordinary text in another window", cx)),
            scrollable: false,
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let rows = root.read_with(cx, |root, cx| {
            root.text_view.read(cx).selection_adapter.text_bounds()
        });
        assert!(rows[0].contains(&start), "{start:?}, {rows:?}");
        let end = point(rows[0].right() - px(0.1), rows[0].center().y);
        cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
        cx.simulate_mouse_move(end, MouseButton::Left, Modifiers::default());
        cx.simulate_mouse_up(end, MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let selected = root.read_with(cx, |root, cx| root.text_view.read(cx).selected_text());
        let copied = cx.update(|window, cx| crate::TextSelection::selected_text(window, cx));
        assert!(!selected.trim().is_empty());
        assert_eq!(copied, selected);
    }

    struct InlineImageTextViewTestRoot {
        text_view: Entity<TextViewState>,
    }

    impl InlineImageTextViewTestRoot {
        fn new(cx: &mut Context<Self>) -> Self {
            let text_view = cx.new(|cx| {
                TextViewState::markdown(
                    "Build Status ![inline image](https://example.com/image.svg) after",
                    cx,
                )
            });
            Self { text_view }
        }
    }

    impl Render for InlineImageTextViewTestRoot {
        fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(420.))
                .child(TextView::new(&self.text_view).selectable(true))
        }
    }

    #[gpui::test]
    fn inline_image_keeps_surrounding_text_on_same_line(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (content, cx) = cx.add_window_view(|_, cx| InlineImageTextViewTestRoot::new(cx));
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let inline_bounds = content.read_with(cx, |content, cx| {
            content.text_view.read(cx).selection_adapter.text_bounds()
        });

        assert_eq!(inline_bounds.len(), 2);
        assert_eq!(
            inline_bounds[0].top(),
            inline_bounds[1].top(),
            "text before and after an inline image should share a rendered line"
        );
        assert!(
            inline_bounds[1].left() - inline_bounds[0].right() > px(8.),
            "inline image should reserve horizontal space in the text layout"
        );
        assert!(
            inline_bounds[1].left() - inline_bounds[0].right() < px(40.),
            "unloaded inline image fallback should stay generic and compact"
        );
    }

    #[gpui::test]
    fn inline_html_image_after_newline_does_not_panic(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, cx| {
            TextViewTestRoot::new(
                "Hi\n[<img src=\"https://example.com/image.svg\">](https://google.com/)",
                cx,
            )
        });
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
    }

    struct FittedListTestRoot {
        text_view: Entity<TextViewState>,
        width: Pixels,
    }

    impl Render for FittedListTestRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(self.width)
                .flex()
                .flex_col()
                .items_end()
                .text_size(px(16.))
                .child(crate::TextSelectionLayer)
                .child(
                    div()
                        .debug_selector(|| "fitted-list".into())
                        .flex()
                        .flex_col()
                        .min_w_0()
                        .max_w_full()
                        .p_4()
                        .child(TextView::new(&self.text_view).selectable(true)),
                )
        }
    }

    fn fitted_list_bounds(
        source: &str,
        width: f32,
        cx: &mut TestAppContext,
    ) -> (Bounds<Pixels>, Vec<Bounds<Pixels>>) {
        let (root, cx) = cx.add_window_view(|_, cx| FittedListTestRoot {
            text_view: cx.new(|cx| TextViewState::markdown(source, cx)),
            width: px(width),
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let bubble = cx.debug_bounds("fitted-list").unwrap();
        let rows = root.read_with(cx, |root, cx| {
            root.text_view.read(cx).selection_adapter.text_bounds()
        });
        assert!(!rows.is_empty(), "list text must be painted: {source:?}");
        for row in &rows {
            assert!(
                row.left() >= bubble.left() && row.right() <= bubble.right(),
                "text must remain visible inside the fitted container: {source:?}, {bubble:?}, {row:?}"
            );
        }
        (bubble, rows)
    }

    #[gpui::test]
    fn fitted_lists_include_their_body_width(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (plain, _) = fitted_list_bounds("Hello world", 600., cx);
        for source in [
            "3. Hello world",
            "- Hello world",
            "- [ ] Hello world",
            "- [x] Hello world",
            "Intro\n\n- Hello world",
            "- Outer\n  - Hello world",
        ] {
            let (bubble, _) = fitted_list_bounds(source, 600., cx);
            assert!(
                bubble.size.width > plain.size.width,
                "the marker must leave room for the full body: {source:?}, {bubble:?}, {plain:?}"
            );
        }
    }

    #[gpui::test]
    fn fitted_lists_wrap_their_body_within_the_available_width(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let body = "Visible text that wraps without being clipped. ".repeat(12);
        for width in [600., 180.] {
            for prefix in ["3. ", "- ", "- [ ] ", "- [x] ", "- Outer\n  - "] {
                let (bubble, rows) = fitted_list_bounds(&format!("{prefix}{body}"), width, cx);
                assert!(bubble.size.width <= px(width));
                assert!(rows.len() > 1, "the body must wrap: {prefix:?}, {width}");
            }
        }
    }

    #[gpui::test]
    fn list_item_renders_fenced_code_block_at_document_width(cx: &mut TestAppContext) {
        struct ListItemBlockRoot;

        impl Render for ListItemBlockRoot {
            fn render(
                &mut self,
                _window: &mut Window,
                _cx: &mut Context<Self>,
            ) -> impl IntoElement {
                div().w(px(840.)).h(px(400.)).child(
                    crate::h_resizable("markdown-width-test")
                        .child(crate::resizable_panel().child(div()))
                        .child(crate::resizable_panel().child(
                            TextView::markdown(
                                "list-with-code",
                                "1. List item\n   ```rust\n   nested code\n   ```\n\n```rust\ntop-level code\n```",
                            )
                            .code_block_actions(|code_block, _, _| {
                                let selector = if code_block.code().contains("nested") {
                                    "nested-code-action"
                                } else {
                                    "top-level-code-action"
                                };
                                div()
                                    .debug_selector(move || selector.into())
                                    .child("Copy")
                            })
                            .scrollable(true)
                            .p_5()
                            .flex_none(),
                        )),
                )
            }
        }

        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| ListItemBlockRoot);
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let nested_action = cx.debug_bounds("nested-code-action").unwrap();
        let top_level_action = cx.debug_bounds("top-level-code-action").unwrap();
        assert!(
            top_level_action.right() - nested_action.right() < px(32.),
            "nested code block should fill the list item's available width"
        );
    }

    /// Height cap of the scrolling code block in [`ScrollingCodeRoot`].
    const CODE_HEIGHT: Pixels = px(60.);

    struct ScrollingCodeRoot {
        text_view: Entity<TextViewState>,
        actions: bool,
    }

    impl Render for ScrollingCodeRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let mut code_block = StyleRefinement::default().max_h(CODE_HEIGHT);
            code_block.overflow.y = Some(Overflow::Scroll);

            div().w(px(320.)).h(px(200.)).child(
                TextView::new(&self.text_view)
                    .style(TextViewStyle::default().with_code_block(code_block))
                    .when(self.actions, |this| {
                        this.code_block_actions(|_, _, _| {
                            div().debug_selector(|| "code-action".into()).child("Copy")
                        })
                    })
                    .scrollable(true),
            )
        }
    }

    #[gpui::test]
    fn scrolling_code_block_keeps_wheel_from_the_list(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let code = (0..50).map(|i| format!("line {i}\n")).collect::<String>();
        let tail = "Paragraph after the code.\n\n".repeat(20);
        let markdown = format!("```\n{code}```\n\n{tail}");

        // Scrolling must not depend on `code_block_actions`, which is what
        // gives a non-scrolling block its id.
        for actions in [false, true] {
            let (root, cx) = cx.add_window_view(|_, cx| ScrollingCodeRoot {
                text_view: cx.new(|cx| TextViewState::markdown(&markdown, cx)),
                actions,
            });
            let cx: &mut VisualTestContext = cx;
            let draw = |cx: &mut VisualTestContext| {
                cx.run_until_parked();
                cx.update(|window, cx| window.draw(cx).clear(cx));
            };
            let step = px(20.);
            let wheel_at = |cx: &mut VisualTestContext, y: Pixels| {
                cx.simulate_event(gpui::ScrollEvent {
                    position: point(px(20.), y),
                    delta: gpui::ScrollDelta::Pixels(point(px(0.), -step)),
                    ..Default::default()
                });
            };
            // The code block is first in the view, and painted lines are
            // clipped to its viewport: the first code line's bottom moves with
            // the code, the first line below the viewport moves with the list.
            let edges = |cx: &mut VisualTestContext| {
                let lines = root.read_with(cx, |root, cx| {
                    root.text_view.read(cx).selection_adapter.text_bounds()
                });
                let paragraph = lines.iter().find(|line| line.top() >= CODE_HEIGHT).unwrap();
                (lines[0].bottom(), paragraph.top())
            };
            draw(cx);
            let (code_bottom, paragraph_top) = edges(cx);
            let action = cx.debug_bounds("code-action");

            // Over the code block: the code scrolls, the list and the pinned
            // actions stay put.
            wheel_at(cx, CODE_HEIGHT / 2.);
            draw(cx);
            assert_eq!(
                edges(cx),
                (code_bottom - step, paragraph_top),
                "actions: {actions}"
            );
            assert_eq!(cx.debug_bounds("code-action"), action);

            // Below the code block the list still scrolls. Only inequality
            // holds: once the paragraph moves into the code's band, `edges`
            // picks the next one down.
            wheel_at(cx, CODE_HEIGHT * 2.5);
            draw(cx);
            assert_ne!(edges(cx).1, paragraph_top, "actions: {actions}");
        }
    }

    /// Draw a Markdown table with a `table_actions` hook installed, and return
    /// the painted bounds of the actions element plus the data it received.
    /// `scroll` opts into the horizontally scrollable table layout.
    fn draw_table_with_actions(
        cx: &mut TestAppContext,
        scroll: bool,
    ) -> (Bounds<Pixels>, TableData) {
        use std::sync::{Arc, Mutex};

        struct TableRoot {
            scroll: bool,
            captured: Arc<Mutex<Vec<TableData>>>,
        }

        impl Render for TableRoot {
            fn render(
                &mut self,
                _window: &mut Window,
                _cx: &mut Context<Self>,
            ) -> impl IntoElement {
                let captured = self.captured.clone();
                let mut table_style = StyleRefinement::default();
                if self.scroll {
                    table_style.overflow.x = Some(Overflow::Scroll);
                }

                div().w(px(320.)).child(
                    TextView::markdown(
                        "table-actions",
                        "| Name | Age |\n|:--|--:|\n| Alice | 30 |\n| Bob | 41 |",
                    )
                    .style(TextViewStyle::default().with_table(table_style))
                    .table_actions(move |table, _, _| {
                        if let Ok(mut captured) = captured.lock() {
                            captured.push(table.clone());
                        }
                        div().debug_selector(|| "table-action".into()).child("Copy")
                    }),
                )
            }
        }

        cx.update(crate::init);
        let captured = Arc::new(Mutex::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let captured = captured.clone();
            move |_, _| TableRoot { scroll, captured }
        });
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let bounds = cx
            .debug_bounds("table-action")
            .expect("table actions should be painted");
        let data = captured
            .lock()
            .expect("captured table data")
            .last()
            .cloned()
            .expect("table actions hook should receive the table");

        (bounds, data)
    }

    #[gpui::test]
    fn table_actions_render_below_the_table(cx: &mut TestAppContext) {
        for scroll in [false, true] {
            let (bounds, data) = draw_table_with_actions(cx, scroll);

            // Header plus two data rows are painted above the actions row.
            assert!(
                bounds.top() > px(40.),
                "actions should sit below the table (scroll: {scroll}), got {:?}",
                bounds.top()
            );
            assert_eq!(data.headers, vec!["Name", "Age"]);
            assert_eq!(data.rows, vec![vec!["Alice", "30"], vec!["Bob", "41"]]);
            assert_eq!(
                data.markdown,
                "| Name | Age |\n| :-- | --: |\n| Alice | 30 |\n| Bob | 41 |"
            );
            assert_eq!(data.span, Some(0..52));
        }
    }

    #[test]
    fn plugin_accepts_text_view_plugins_beyond_markdown() {
        let view = TextView::markdown("plugin-test", "").plugin(DummyTextViewPlugin);

        assert!(view.selectable);
    }

    #[test]
    fn syntax_highlighting_is_opt_in() {
        let default_view = TextView::markdown("default-code", "```rust\nfn main() {}\n```");
        assert!(default_view.code_block_highlighter.is_none());

        let view = default_view.code_block_highlighter(|block| {
            vec![(
                0..block.code().len(),
                gpui::HighlightStyle {
                    color: Some(gpui::rgb(0x3366ff).into()),
                    ..Default::default()
                },
            )]
        });
        assert!(view.code_block_highlighter.is_some());
    }

    #[gpui::test]
    fn clipped_markdown_link_does_not_open(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, cx| {
            TextViewTestRoot::new("visible\n\n[hidden](https://example.com)", cx)
        });
        let cx: &mut VisualTestContext = cx;

        cx.simulate_click(point(px(10.), px(34.)), Modifiers::default());

        assert_eq!(cx.opened_url(), None);
    }

    struct MaxLinesTestRoot {
        text_view: Entity<TextViewState>,
        max_lines: usize,
    }

    impl MaxLinesTestRoot {
        fn new(text: &str, max_lines: usize, cx: &mut Context<Self>) -> Self {
            let text_view = cx.new(|cx| TextViewState::markdown(text, cx));
            Self {
                text_view,
                max_lines,
            }
        }
    }

    impl Render for MaxLinesTestRoot {
        fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(200.))
                .child(TextView::new(&self.text_view).max_lines(self.max_lines))
        }
    }

    #[test]
    fn the_clip_only_moves_for_a_straddling_glyph_line() {
        use super::line_safe_clip_bottom;
        use crate::text::state::LineSpan;

        let spans = [
            // Lines end at 20 / 40 / 60.
            LineSpan {
                top: px(0.),
                bottom: px(60.),
                line_height: px(20.),
            },
            // A second block after an 8px gap; lines end at 88 / 108 / 128.
            LineSpan {
                top: px(68.),
                bottom: px(128.),
                line_height: px(20.),
            },
        ];

        // Content continues well past the box in every case but the last.
        let below = px(400.);

        // A box ending inside the line 88..108 leaves that line out whole.
        assert_eq!(
            line_safe_clip_bottom(&spans, px(100.), below),
            Some(px(88.))
        );

        // A box ending on a line boundary has nothing to pull the clip up for.
        assert_eq!(line_safe_clip_bottom(&spans, px(88.), below), None);

        // A strip below the last line shorter than a line — the border and
        // padding a block leads with — is not worth showing.
        assert_eq!(line_safe_clip_bottom(&spans, px(64.), below), Some(px(60.)));

        // One taller than a line is: whatever crosses the edge keeps the part
        // that fits rather than leaving the box half empty.
        let one_block = [LineSpan {
            top: px(0.),
            bottom: px(60.),
            line_height: px(20.),
        }];
        assert_eq!(line_safe_clip_bottom(&one_block, px(200.), below), None);

        // Nothing crosses the edge at all: the space under the last line is
        // the box's own, not a scrap of something below.
        assert_eq!(line_safe_clip_bottom(&spans, px(130.), px(128.)), None);
    }

    #[test]
    fn a_line_taller_than_the_budget_keeps_the_part_that_fits() {
        use super::line_safe_clip_bottom;
        use crate::text::state::LineSpan;

        // A heading line of 28px, in a box capped at one 26px body line.
        let heading = [LineSpan {
            top: px(70.),
            bottom: px(98.),
            line_height: px(28.),
        }];

        assert_eq!(line_safe_clip_bottom(&heading, px(96.), px(400.)), None);
    }

    #[test]
    fn the_clip_does_not_stop_on_a_row_of_border_and_padding() {
        use super::line_safe_clip_bottom;
        use crate::text::state::LineSpan;

        // Two table rows, each one line of text, 9px of border and padding
        // between them.
        let rows = [
            LineSpan {
                top: px(100.),
                bottom: px(126.),
                line_height: px(26.),
            },
            LineSpan {
                top: px(135.),
                bottom: px(161.),
                line_height: px(26.),
            },
        ];

        // Leaving out the second row's text would strand the 9px it leads
        // with, so the clip goes back to the row above it.
        assert_eq!(
            line_safe_clip_bottom(&rows, px(148.), px(400.)),
            Some(px(126.))
        );
    }

    /// A clamped view nested the way an application nests one: inside a card,
    /// inside a region that fills a window of a known height. The height an
    /// ancestor hands down must not reach the clamped content and hide the
    /// overflow the clamp measures — with the content stretched to the capped
    /// box, nothing looks clipped and lines get cut in half.
    struct ClampedPageRoot {
        text_view: Entity<TextViewState>,
        max_lines: usize,
    }

    impl Render for ClampedPageRoot {
        fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
            use crate::{h_flex, v_flex};

            v_flex()
                .size_full()
                .p_4()
                .gap_4()
                .child(h_flex().max_w(px(480.)).gap_3().child("header"))
                .child(
                    v_flex()
                        .flex_1()
                        .min_h_0()
                        .gap_4()
                        .id("clamped-page-scroll")
                        .child(
                            v_flex()
                                .max_w(px(480.))
                                .p_3()
                                .gap_2()
                                .child(TextView::new(&self.text_view).max_lines(self.max_lines)),
                        )
                        .overflow_y_scroll(),
                )
        }
    }

    #[gpui::test]
    fn max_lines_measures_overflow_inside_a_sized_page(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| {
            let text_view = cx.new(|cx| {
                TextViewState::markdown(
                    "first\n\nsecond\n\nthird\n\nfourth\n\nfifth\n\nsixth\n\nseventh",
                    cx,
                )
            });
            ClampedPageRoot {
                text_view,
                max_lines: 3,
            }
        });
        let cx: &mut VisualTestContext = cx;

        assert!(root.read_with(cx, |root, cx| root.text_view.read(cx).is_clamped()));
    }

    #[gpui::test]
    fn max_lines_clamps_overflowing_content(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| {
            MaxLinesTestRoot::new(
                "first\n\nsecond\n\nthird\n\nfourth\n\nfifth\n\nsixth",
                2,
                cx,
            )
        });
        let cx: &mut VisualTestContext = cx;

        assert!(root.read_with(cx, |root, cx| root.text_view.read(cx).is_clamped()));
    }

    #[gpui::test]
    fn max_lines_leaves_short_content_unclamped(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (root, cx) = cx.add_window_view(|_, cx| MaxLinesTestRoot::new("only line", 3, cx));
        let cx: &mut VisualTestContext = cx;

        assert!(!root.read_with(cx, |root, cx| root.text_view.read(cx).is_clamped()));
    }

    #[gpui::test]
    fn heading_refinement_changes_rendered_heading_geometry(cx: &mut TestAppContext) {
        struct HeadingStyleRoot;

        impl Render for HeadingStyleRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .flex()
                    .items_start()
                    .child(
                        div()
                            .debug_selector(|| "default-h1".into())
                            .child(TextView::markdown("default-h1-view", "# Heading")),
                    )
                    .child(div().debug_selector(|| "custom-h1".into()).child(
                        TextView::markdown("custom-heading-view", "# Heading").style(
                            TextViewStyle::default().with_heading(|level| {
                                if level == 1 {
                                    StyleRefinement::default().pb(rems(2.))
                                } else {
                                    StyleRefinement::default()
                                }
                            }),
                        ),
                    ))
                    .child(
                        div()
                            .debug_selector(|| "default-h2".into())
                            .child(TextView::markdown("default-h2-view", "## Heading")),
                    )
                    .child(div().debug_selector(|| "custom-h2".into()).child(
                        TextView::markdown("custom-h2-view", "## Heading").style(
                            TextViewStyle::default().with_heading(|level| {
                                if level == 1 {
                                    StyleRefinement::default().pb(rems(2.))
                                } else {
                                    StyleRefinement::default()
                                }
                            }),
                        ),
                    ))
            }
        }

        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| HeadingStyleRoot);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let default_h1 = cx.debug_bounds("default-h1").unwrap();
        let custom_h1 = cx.debug_bounds("custom-h1").unwrap();
        let default_h2 = cx.debug_bounds("default-h2").unwrap();
        let custom_h2 = cx.debug_bounds("custom-h2").unwrap();
        assert!(custom_h1.size.height > default_h1.size.height);
        assert_eq!(custom_h2.size.height, default_h2.size.height);
    }

    #[gpui::test]
    fn max_lines_disables_links_hidden_by_the_clamp(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, cx| {
            MaxLinesTestRoot::new(
                "first\n\nsecond\n\nthird\n\n[hidden](https://example.com)",
                2,
                cx,
            )
        });
        let cx: &mut VisualTestContext = cx;

        // Click far below the clamped box, where the link would sit unclamped.
        cx.simulate_click(point(px(10.), px(150.)), Modifiers::default());

        assert_eq!(cx.opened_url(), None);
    }

    #[gpui::test]
    fn scaled_inline_code_keeps_links_and_drag_selection(cx: &mut TestAppContext) {
        struct SelectionRoot {
            text_view: Entity<TextViewState>,
            format: crate::text::SelectionFormat,
        }
        impl Render for SelectionRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(160.))
                    .child(crate::TextSelectionLayer)
                    .child(TextView::new(&self.text_view).selection_format(self.format))
            }
        }
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(|_, cx| SelectionRoot {
            format: crate::text::SelectionFormat::Plain,
            text_view: cx
                .new(|cx| TextViewState::markdown("[`code`](https://example.com) after", cx)),
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(cx.opened_url(), Some("https://example.com".to_string()));
        // Just past the code span's leading padding, on its first glyph.
        cx.simulate_mouse_down(
            point(px(5.), px(8.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_move(
            point(px(155.), px(20.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_up(
            point(px(155.), px(20.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let selected = view.read_with(cx, |view, cx| view.text_view.read(cx).selected_text());
        assert_eq!(selected.trim(), "code after");
        view.update(cx, |view, cx| {
            view.format = crate::text::SelectionFormat::Source;
            cx.notify();
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let selected = view.read_with(cx, |view, cx| view.text_view.read(cx).selected_text());
        assert_eq!(selected.trim(), "[`code`](https://example.com) after");
    }

    /// Inline-code Markdown takes the deferred `InlineFlow` path. Its layout
    /// must use the heading's resolved typography rather than the ambient body
    /// style that remains after the heading's style stack has been popped.
    ///
    /// This is a real request-layout → measured-layout → prepaint → paint test:
    /// the deterministic text system makes bold glyphs wider than body glyphs.
    /// Before the fix, the code heading was allocated using normal body metrics
    /// but its fragments painted bold, so the wrapped heading text crossed into
    /// the following paragraph.
    #[test]
    fn inline_code_heading_reserves_painted_wrapped_lines_and_list_baseline() {
        use crate::text::inline::test_fonts::{MONO, WideMonoTextSystem};
        use gpui::{TestApp, rems};

        const MARKDOWN: &str = "The same words with inline code.\n\nThe same words with `inline code`.\n\n- The same words with inline code.\n- The same words with `inline code`.\n\n# Heading with inline code\n# Heading with `inline code`\n\nthis is a test";

        struct MarkdownRoot {
            text_view: Entity<TextViewState>,
            width: Pixels,
            preview_zoom: f32,
        }

        impl Render for MarkdownRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(self.width)
                    // Match example-markdown: preview zoom changes TextView's
                    // inherited text size, not the window rem size.
                    .text_size(rems(self.preview_zoom))
                    .child(crate::TextSelectionLayer)
                    .child(TextView::new(&self.text_view).selectable(true))
            }
        }

        fn draw(
            app: &mut TestApp,
            width: Pixels,
            preview_zoom: f32,
        ) -> (Bounds<Pixels>, Vec<Bounds<Pixels>>, String) {
            let mut window = app.open_window(|_, cx| MarkdownRoot {
                text_view: cx.new(|cx| TextViewState::markdown(MARKDOWN, cx)),
                width,
                preview_zoom,
            });
            window.draw();
            app.run_until_parked();
            window.draw();
            window.update(|root, _, cx| {
                root.text_view.update(cx, |state, cx| state.select_all(cx));
            });
            window.draw();
            window.read(|root, cx| {
                let state = root.text_view.read(cx);
                (
                    state.bounds(),
                    state.selection_adapter.text_bounds(),
                    state.selected_text(),
                )
            })
        }

        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        app.update(|cx| {
            crate::init(cx);
            crate::Theme::global_mut(cx).tokens.typography.mono = MONO.into();
        });

        for (case, width, preview_zoom) in [
            // At the root 16px size the plain heading fits, while bold inline
            // fragments need their own measured widths.
            ("default-16px", px(600.), 1.),
            // A narrow view exercises intentional heading wrapping.
            ("narrow-16px", px(320.), 1.),
            // Preview zoom applies through `.text_size(rems(zoom))`.
            ("zoom-1.25", px(600.), 1.25),
        ] {
            let (view_bounds, text_bounds, selected_text) = draw(&mut app, width, preview_zoom);
            assert!(
                text_bounds.len() > 8,
                "{case}: expected all markdown fragments"
            );
            assert_eq!(
                selected_text.trim(),
                "The same words with inline code.\nThe same words with inline code.\nThe same words with inline code.\nThe same words with inline code.\nHeading with inline code\nHeading with inline code\nthis is a test",
                "{case}: wrapped inline-code text was lost or duplicated"
            );
            let following = text_bounds.last().expect("following paragraph must paint");
            let painted_bottom = text_bounds
                .iter()
                .map(|bounds| bounds.bottom())
                .max()
                .expect("markdown must paint text");
            // This is intentionally not a fragment-count or selection-only
            // assertion: `text_bounds` are the shaped Inline layouts produced
            // during paint. No painted wrapped line may reach the following
            // paragraph's origin, and the TextView allocation must contain the
            // complete painted document.
            assert!(
                text_bounds[..text_bounds.len() - 1]
                    .iter()
                    .all(|bounds| bounds.bottom() <= following.top()),
                "{case}: heading/list text painted through the following paragraph;                  following={following:?}, text_bounds={text_bounds:?}, view={view_bounds:?}"
            );
            assert!(
                painted_bottom <= view_bounds.bottom(),
                "{case}: TextView height did not reserve its painted text;                  painted_bottom={painted_bottom:?}, view={view_bounds:?}"
            );
        }
    }

    #[test]
    fn ordered_markdown_list_start_reaches_layout_marker() {
        use crate::text::inline::test_fonts::{WideMonoTextSystem, record_shaped_lines};
        use gpui::TestApp;

        struct MarkdownRoot {
            text_view: Entity<TextViewState>,
        }

        impl Render for MarkdownRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div().w(px(400.)).child(TextView::new(&self.text_view))
            }
        }

        #[derive(Clone, Copy)]
        enum Format {
            Markdown,
            Html,
        }

        fn shaped_markers(format: Format, source: &str) -> Vec<String> {
            let (_, shaped_lines) = record_shaped_lines(|| {
                let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
                app.update(crate::init);
                let mut window = app.open_window(|_, cx| MarkdownRoot {
                    text_view: cx.new(|cx| match format {
                        Format::Markdown => TextViewState::markdown(source, cx),
                        Format::Html => TextViewState::html(source, cx),
                    }),
                });
                window.draw();
                app.run_until_parked();
                window.draw();
            });

            let mut markers = shaped_lines
                .into_iter()
                .filter(|line| line.len() <= 3 && line.ends_with('.'))
                .collect::<Vec<_>>();
            markers.dedup();
            markers
        }

        let starts_at_one = "1. one\n2. two";
        assert_eq!(
            shaped_markers(Format::Markdown, starts_at_one),
            ["1.", "2."]
        );
        assert_eq!(
            shaped_markers(Format::Html, "<ol><li>one</li><li>two</li></ol>"),
            ["1.", "2."]
        );

        assert_eq!(
            shaped_markers(Format::Markdown, "3. hello\n4. world"),
            ["3.", "4."]
        );

        let nested_starts_at_four = "1. outer\n\n   4. nested\n   5. again";
        assert_eq!(
            shaped_markers(Format::Markdown, nested_starts_at_four),
            ["1.", "D.", "E."]
        );

        let nested_starts_at_zero = "1. outer\n\n   0. zero";
        assert_eq!(
            shaped_markers(Format::Markdown, nested_starts_at_zero),
            ["1.", "0."]
        );
    }

    /// A line with inline code takes `InlineFlow` and a plain line takes the
    /// ordinary text path; both must be the same height, or a list with one
    /// code item is unevenly spaced (#3162). The fractional scale factor and
    /// zooms give line heights that are not whole logical pixels.
    #[test]
    fn inline_code_line_is_as_tall_as_a_plain_line() {
        use crate::text::inline::test_fonts::{MONO, WideMonoTextSystem};
        use gpui::{TestApp, rems};

        struct LineRoot {
            plain: Entity<TextViewState>,
            code: Entity<TextViewState>,
            preview_zoom: f32,
        }

        impl Render for LineRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(600.))
                    .text_size(rems(self.preview_zoom))
                    .child(TextView::new(&self.plain))
                    .child(TextView::new(&self.code))
            }
        }

        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        app.update(|cx| {
            crate::init(cx);
            crate::Theme::global_mut(cx).tokens.typography.mono = MONO.into();
        });
        for scale_factor in [1.6, 2.] {
            for preview_zoom in [1., 1.25] {
                let mut window = app.open_window(|_, cx| LineRoot {
                    plain: cx.new(|cx| TextViewState::markdown("plain body words", cx)),
                    code: cx.new(|cx| TextViewState::markdown("plain `code` words", cx)),
                    preview_zoom,
                });
                window.simulate_scale_factor_change(scale_factor);
                window.draw();
                app.run_until_parked();
                window.draw();
                let (plain, code) = window.read(|root, cx| {
                    (
                        root.plain.read(cx).bounds().size.height,
                        root.code.read(cx).bounds().size.height,
                    )
                });
                assert_eq!(code, plain, "scale {scale_factor}, zoom {preview_zoom}");
            }
        }
    }

    /// The code-bearing list item takes `InlineFlow`; the plain item takes the
    /// ordinary text path. Their first body glyphs must begin at the same row
    /// position relative to their own TextView origins.
    #[test]
    fn inline_code_list_body_paint_origin_matches_plain_list_item() {
        use crate::text::inline::test_fonts::{MONO, WideMonoTextSystem};
        use gpui::{TestApp, rems};

        struct ListRoot {
            plain: Entity<TextViewState>,
            code: Entity<TextViewState>,
            preview_zoom: f32,
        }

        impl Render for ListRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(600.))
                    .text_size(rems(self.preview_zoom))
                    .child(crate::TextSelectionLayer)
                    .child(TextView::new(&self.plain).selectable(true))
                    .child(TextView::new(&self.code).selectable(true))
            }
        }

        fn draw(app: &mut TestApp, preview_zoom: f32) -> (Pixels, Pixels) {
            let mut window = app.open_window(|_, cx| ListRoot {
                plain: cx.new(|cx| TextViewState::markdown("- plain body words", cx)),
                code: cx.new(|cx| TextViewState::markdown("- plain `code` words", cx)),
                preview_zoom,
            });
            window.draw();
            app.run_until_parked();
            window.draw();
            window.read(|root, cx| {
                let first_body_line_top = |view: &Entity<TextViewState>| {
                    let view = view.read(cx);
                    let painted_line = view
                        .selection_adapter
                        .text_bounds()
                        .into_iter()
                        .next()
                        .expect("list item should paint its first body line");
                    painted_line.top() - view.bounds().top()
                };
                (
                    first_body_line_top(&root.plain),
                    first_body_line_top(&root.code),
                )
            })
        }

        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        app.update(|cx| {
            crate::init(cx);
            crate::Theme::global_mut(cx).tokens.typography.mono = MONO.into();
        });
        for (case, preview_zoom) in [("16px", 1.), ("zoom-1.25", 1.25), ("zoom-1.5", 1.5)] {
            let (plain_origin, code_origin) = draw(&mut app, preview_zoom);
            assert_eq!(
                code_origin, plain_origin,
                "{case}: code list body paint origin {code_origin:?} must match plain {plain_origin:?}"
            );
        }
    }

    #[test]
    fn inline_code_fragment_does_not_paint_past_its_reserved_row() {
        use crate::text::inline::test_fonts::{MONO, WideMonoTextSystem};
        use gpui::TestApp;

        const TEXT_BACKGROUND: u32 = 0x20f0b0;

        struct MarkdownRoot {
            text_view: Entity<TextViewState>,
        }

        impl Render for MarkdownRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(640.))
                    .text_size(px(17.9))
                    .text_bg(gpui::rgb(TEXT_BACKGROUND))
                    .child(TextView::new(&self.text_view))
            }
        }

        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        app.update(|cx| {
            crate::init(cx);
            crate::Theme::global_mut(cx).tokens.typography.mono = MONO.into();
        });
        let mut window = app.open_window(|_, cx| MarkdownRoot {
            text_view: cx.new(|cx| TextViewState::markdown("`main` starts the paragraph", cx)),
        });
        window.draw();
        app.run_until_parked();
        window.draw();

        let (view_bounds, painted) = window.update(|root, window, cx| {
            let view_bounds = root
                .text_view
                .read(cx)
                .bounds()
                .scale(window.scale_factor());
            let text_background: gpui::Background = gpui::rgb(TEXT_BACKGROUND).into();
            let painted = window
                .painted_quads()
                .into_iter()
                .filter(|quad| quad.background == text_background)
                .map(|quad| quad.bounds)
                .collect::<Vec<_>>();
            (view_bounds, painted)
        });

        assert!(
            !painted.is_empty(),
            "the inherited text background must make actual text paint observable"
        );
        assert!(
            painted
                .iter()
                .all(|bounds| bounds.bottom() <= view_bounds.bottom()),
            "an inline-code fragment wrapped a second time after InlineFlow reserved one row; \
             text background quads={painted:?}, reserved TextView bounds={view_bounds:?}"
        );
    }

    #[test]
    fn table_row_backgrounds_follow_the_frame_corner_radius() {
        use gpui::TestApp;

        const HEAD_BACKGROUND: u32 = 0x11aa77;
        const RADIUS: f32 = 8.;

        struct RoundedTableRoot {
            text_view: Entity<TextViewState>,
            scroll: bool,
        }

        impl Render for RoundedTableRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let mut table = StyleRefinement::default();
                table.corner_radii.top_left = Some(px(RADIUS).into());
                table.corner_radii.top_right = Some(px(RADIUS).into());
                table.corner_radii.bottom_left = Some(px(RADIUS).into());
                table.corner_radii.bottom_right = Some(px(RADIUS).into());
                if self.scroll {
                    table.overflow.x = Some(gpui::Overflow::Scroll);
                }
                let style = TextViewStyle::default()
                    .with_code_background(gpui::rgb(HEAD_BACKGROUND).into())
                    .with_table(table);
                div()
                    .w(px(400.))
                    .child(TextView::new(&self.text_view).style(style))
            }
        }

        for scroll in [false, true] {
            let mode = if scroll { "scroll" } else { "wrap" };
            let mut app = TestApp::new();
            app.update(crate::init);
            let mut window = app.open_window(|_, cx| RoundedTableRoot {
                text_view: cx
                    .new(|cx| TextViewState::markdown("| a | b |\n| --- | --- |\n| 1 | 2 |", cx)),
                scroll,
            });
            window.draw();
            app.run_until_parked();
            window.draw();

            let (quad, scale) = window.update(|_, window, _| {
                let head: gpui::Background = gpui::rgb(HEAD_BACKGROUND).into();
                let quad = window
                    .painted_quads()
                    .into_iter()
                    .find(|quad| quad.background == head)
                    .unwrap_or_else(|| panic!("{mode}: the header background quad is painted"));
                (quad, window.scale_factor())
            });

            // GPUI clips children with a rectangular mask, so the header fill
            // must carry the frame radius itself, inset by the 1px border.
            let expected = px(RADIUS - 1.).scale(scale);
            assert_eq!(quad.corner_radii.top_left, expected, "{mode}: top left");
            assert_eq!(quad.corner_radii.top_right, expected, "{mode}: top right");
            let square = px(0.).scale(scale);
            assert_eq!(quad.corner_radii.bottom_left, square, "{mode}: bottom left");
            assert_eq!(
                quad.corner_radii.bottom_right, square,
                "{mode}: bottom right"
            );
        }
    }

    /// A table wider than its frame shrinks its widest column. A narrower
    /// column keeps its content width rather than shrinking by the same
    /// ratio and wrapping the end of its text onto a line of its own, in the
    /// header and the body alike, and with the cell and frame refinements
    /// the text renders with.
    #[test]
    fn table_keeps_narrow_columns_on_one_line_while_wide_ones_wrap() {
        use crate::text::inline::test_fonts::WideMonoTextSystem;
        use gpui::TestApp;
        use std::sync::Arc;

        const CELL_BACKGROUND: u32 = 0x11aa77;

        struct TableRoot {
            text_view: Entity<TextViewState>,
            width: Pixels,
            style: TextViewStyle,
        }

        impl Render for TableRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(self.width)
                    .child(TextView::new(&self.text_view).style(self.style.clone()))
            }
        }

        let short = "Operating revenue (USD)";
        let source = format!(
            "| {short} | Note |\n| --- | --- |\n| {short} | x |\n| 1 | {} |",
            "word ".repeat(30)
        );
        // Heights of the first column's cells, top to bottom.
        let first_column = |width: f32, style: TextViewStyle| {
            let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
            app.update(crate::init);
            let cell = style.table_cell().clone().bg(gpui::rgb(CELL_BACKGROUND));
            let style = style.with_table_cell(cell);
            let mut window = app.open_window(|_, cx| TableRoot {
                text_view: cx.new(|cx| TextViewState::markdown(&source, cx)),
                width: px(width),
                style,
            });
            window.draw();
            app.run_until_parked();
            window.draw();
            window.update(|_, window, _| {
                let background: gpui::Background = gpui::rgb(CELL_BACKGROUND).into();
                let cells: Vec<_> = window
                    .painted_quads()
                    .into_iter()
                    .filter(|quad| quad.background == background)
                    .map(|quad| quad.bounds)
                    .collect();
                let left = cells.iter().map(|bounds| bounds.origin.x).min().unwrap();
                let mut column: Vec<_> = cells
                    .into_iter()
                    .filter(|bounds| bounds.origin.x == left)
                    .collect();
                column.sort_by_key(|bounds| bounds.origin.y);
                column
                    .iter()
                    .map(|bounds| bounds.size.height)
                    .collect::<Vec<_>>()
            })
        };
        let scroll = || {
            let mut table = StyleRefinement::default();
            table.overflow.x = Some(gpui::Overflow::Scroll);
            TextViewStyle::default().with_table(table)
        };

        for (layout, style) in [("wrap", TextViewStyle::default()), ("scroll", scroll())] {
            let fits = first_column(4000., style.clone());
            let narrow = first_column(700., style);
            assert_eq!(fits.len(), 3, "{layout}: three rows");
            assert_eq!(fits[0], fits[2], "{layout}: the header fits on one line");
            assert_eq!(narrow[..2], fits[..2], "{layout}: the short column wraps");
        }

        let single_line = first_column(4000., TextViewStyle::default())[0];
        let padded = TextViewStyle::default().with_table_cell(StyleRefinement::default().px_4());
        assert_eq!(
            first_column(4000., padded)[0],
            single_line,
            "the cell padding refinement leaves the text its measured width"
        );
        let bold = TextViewStyle::default()
            .with_table(StyleRefinement::default().font_weight(gpui::FontWeight::BOLD));
        assert_eq!(
            first_column(4000., bold)[0],
            single_line,
            "the table text refinement is measured"
        );
    }

    #[gpui::test]
    fn markdown_link_opens_url_without_handler(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) =
            cx.add_window_view(|_, cx| TextViewTestRoot::new("[example](https://example.com)", cx));
        let cx: &mut VisualTestContext = cx;

        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        assert_eq!(cx.opened_url(), Some("https://example.com".to_string()));
    }

    #[gpui::test]
    fn right_click_does_not_open_url_without_handler(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (_, cx) =
            cx.add_window_view(|_, cx| TextViewTestRoot::new("[example](https://example.com)", cx));
        let cx: &mut VisualTestContext = cx;

        cx.simulate_mouse_down(
            point(px(10.), px(10.)),
            MouseButton::Right,
            Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(10.), px(10.)),
            MouseButton::Right,
            Modifiers::default(),
        );

        assert_eq!(cx.opened_url(), None);
    }

    #[gpui::test]
    fn link_handler_receives_button_and_modifiers(cx: &mut TestAppContext) {
        use std::sync::{Arc, Mutex};

        struct LinkRoot {
            text_view: Entity<TextViewState>,
            clicks: Arc<Mutex<Vec<(SharedString, ClickEvent)>>>,
        }

        impl Render for LinkRoot {
            fn render(
                &mut self,
                _window: &mut Window,
                _cx: &mut Context<Self>,
            ) -> impl IntoElement {
                let clicks = self.clicks.clone();
                div()
                    .w(px(240.))
                    .child(
                        TextView::new(&self.text_view).on_link_click(move |url, event, _, _| {
                            clicks.lock().unwrap().push((url.clone(), event.clone()));
                        }),
                    )
            }
        }

        cx.update(crate::init);
        let clicks = Arc::new(Mutex::new(Vec::new()));
        let captured = clicks.clone();
        let (_, cx) = cx.add_window_view(move |_, cx| LinkRoot {
            text_view: cx.new(|cx| TextViewState::markdown("[example](https://example.com)", cx)),
            clicks,
        });
        let cx: &mut VisualTestContext = cx;

        let mut modifiers = Modifiers::default();
        modifiers.control = true;
        cx.simulate_click(point(px(10.), px(10.)), modifiers);
        cx.simulate_mouse_down(
            point(px(10.), px(10.)),
            MouseButton::Middle,
            Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(10.), px(10.)),
            MouseButton::Middle,
            Modifiers::default(),
        );
        cx.simulate_mouse_down(
            point(px(10.), px(10.)),
            MouseButton::Right,
            Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(10.), px(10.)),
            MouseButton::Right,
            Modifiers::default(),
        );

        let clicks = captured.lock().unwrap();
        assert_eq!(clicks.len(), 3);
        assert_eq!(clicks[0].0, "https://example.com");
        assert!(!clicks[0].1.is_right_click() && !clicks[0].1.is_middle_click());
        assert!(clicks[0].1.modifiers().control);
        assert!(clicks[1].1.is_middle_click());
        assert!(clicks[2].1.is_right_click());
        assert_eq!(cx.opened_url(), None);
    }

    #[gpui::test]
    fn inline_object_inherits_bold_and_link_clicks_without_opening_on_drag(
        cx: &mut TestAppContext,
    ) {
        use std::sync::{Arc, Mutex};
        struct Root {
            state: Entity<TextViewState>,
            clicks: Arc<Mutex<Vec<SharedString>>>,
        }
        impl Render for Root {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let clicks = self.clicks.clone();
                let extensions = crate::text::MarkdownExtensions::default().plugin(
                    crate::text::markdown_ext::TestInlinePlugin::new("math")
                        .parse_with(|node, _| {
                            matches!(node, markdown::mdast::Node::InlineMath(_)).then(|| {
                                super::super::MarkdownNode::new("math", ()).text("formula")
                            })
                        })
                        .render_with(|_, context, _, _| {
                            assert_eq!(context.text_style().font_weight, gpui::FontWeight::BOLD);
                            Some(super::super::InlineElement::new(div().child("formula")))
                        }),
                );
                div().w(px(300.)).child(crate::TextSelectionLayer).child(
                    TextView::new(&self.state)
                        .markdown_extensions(extensions)
                        .on_link_click(move |url, _, _, _| {
                            clicks.lock().unwrap().push(url.clone())
                        }),
                )
            }
        }
        cx.update(crate::init);
        let clicks = Arc::new(Mutex::new(Vec::new()));
        let captured = clicks.clone();
        let (root, cx) = cx.add_window_view(move |_, cx| Root {
            state: cx.new(|cx| TextViewState::markdown("**[$x$](https://example.com)**", cx)),
            clicks,
        });
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let bounds = root.read_with(cx, |root, cx| {
            root.state.read(cx).selection_adapter.text_bounds()[0]
        });
        for button in [MouseButton::Left, MouseButton::Middle, MouseButton::Right] {
            cx.simulate_mouse_down(bounds.center(), button, Modifiers::default());
            cx.simulate_mouse_up(bounds.center(), button, Modifiers::default());
        }
        assert_eq!(captured.lock().unwrap().len(), 3);
        let start = point(bounds.left() + px(1.), bounds.center().y);
        let end = point(bounds.right() - px(1.), bounds.center().y);
        cx.simulate_mouse_down(start, MouseButton::Left, Modifiers::default());
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_move(end, Some(MouseButton::Left), Modifiers::default());
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_up(end, MouseButton::Left, Modifiers::default());
        assert_eq!(captured.lock().unwrap().len(), 3);
    }

    #[gpui::test]
    fn linked_image_handler_receives_left_middle_and_right_clicks(cx: &mut TestAppContext) {
        use std::sync::{Arc, Mutex};

        struct LinkedImageRoot {
            text_view: Entity<TextViewState>,
            clicks: Arc<Mutex<Vec<(SharedString, ClickEvent)>>>,
        }

        impl Render for LinkedImageRoot {
            fn render(
                &mut self,
                _window: &mut Window,
                _cx: &mut Context<Self>,
            ) -> impl IntoElement {
                let clicks = self.clicks.clone();
                div().w(px(160.)).child(
                    TextView::new(&self.text_view)
                        .selectable(true)
                        .on_link_click(move |url, event, _, _| {
                            clicks.lock().unwrap().push((url.clone(), event.clone()));
                        }),
                )
            }
        }

        cx.update(crate::init);
        let clicks = Arc::new(Mutex::new(Vec::new()));
        let captured = clicks.clone();
        let (content, cx) = cx.add_window_view(move |_, cx| LinkedImageRoot {
                text_view: cx.new(|cx| {
                    TextViewState::markdown(
                        r#"Before [<img src="https://example.com/image.svg" width="32" height="32">](https://example.com/image-link) after."#,
                        cx,
                    )
                }),
                clicks,
            }
        );
        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let inline_bounds = content.read_with(cx, |content, cx| {
            content.text_view.read(cx).selection_adapter.text_bounds()
        });
        assert!(
            inline_bounds.len() >= 2,
            "linked image needs text bounds on both sides: {inline_bounds:?}"
        );
        assert!(
            inline_bounds[1].left() - inline_bounds[0].right() >= px(24.),
            "linked image did not reserve the expected click target: {inline_bounds:?}"
        );
        let position = point(
            inline_bounds[0].right() + (inline_bounds[1].left() - inline_bounds[0].right()) * 0.5,
            inline_bounds[0].top() + px(8.),
        );
        for button in [MouseButton::Left, MouseButton::Middle, MouseButton::Right] {
            cx.simulate_mouse_down(position, button, Modifiers::default());
            cx.simulate_mouse_up(position, button, Modifiers::default());
        }

        let clicks = captured.lock().unwrap();
        assert_eq!(clicks.len(), 3);
        assert!(
            clicks
                .iter()
                .all(|(url, _)| url == "https://example.com/image-link")
        );
        assert!(!clicks[0].1.is_right_click() && !clicks[0].1.is_middle_click());
        assert!(clicks[1].1.is_middle_click());
        assert!(clicks[2].1.is_right_click());
        assert_eq!(cx.opened_url(), None);
    }

    #[gpui::test]
    fn clipped_markdown_cannot_start_selection(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (view, cx) = cx
            .add_window_view(|_, cx| TextViewTestRoot::new("visible\n\nhidden selection text", cx));
        let cx: &mut VisualTestContext = cx;

        cx.simulate_mouse_down(
            point(px(10.), px(34.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.simulate_mouse_move(
            point(px(90.), px(34.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.simulate_mouse_up(
            point(px(90.), px(34.)),
            MouseButton::Left,
            Modifiers::default(),
        );

        let selected_text = view.read_with(cx, |root, cx| root.text_view.read(cx).selected_text());
        assert!(
            selected_text.is_empty(),
            "unexpected selection: {selected_text:?}"
        );
    }

    /// A tall selectable TextView clipped by a short `overflow_hidden` viewport,
    /// with a large blank footer below so a drag can extend the selection band
    /// past the bottom of the clip while still proxy-anchoring to the view.
    struct ClippedTallTextViewTestRoot {
        text_view: Entity<TextViewState>,
    }

    impl ClippedTallTextViewTestRoot {
        fn new(cx: &mut Context<Self>) -> Self {
            // Four separate blocks; only the first (and maybe part of the
            // second) fit inside the 40px clip. "charlie"/"delta" render well
            // below it.
            let text_view =
                cx.new(|cx| TextViewState::markdown("alpha\n\nbravo\n\ncharlie\n\ndelta", cx));
            Self { text_view }
        }
    }

    impl Render for ClippedTallTextViewTestRoot {
        fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(200.))
                .child(crate::TextSelectionLayer)
                .child(
                    div()
                        .h(px(40.))
                        .overflow_hidden()
                        .child(TextView::new(&self.text_view).selectable(true)),
                )
                // A tall blank footer so a drag can reach a y below the clipped
                // text; a press there proxy-anchors to the TextView above.
                .child(div().h(px(160.)))
        }
    }

    /// Regression for copying a selection taller than the visible viewport.
    ///
    /// The selection band runs from visible text at the top down to a point
    /// far below the clip. Every glyph of the painted TextView is laid out even
    /// though the lower ones are clipped away, so the copied text must include
    /// the clipped-out "charlie"/"delta" — not just what is on screen. This
    /// guards against re-adding a `content_mask` gate in
    /// `Inline::layout_selections`.
    #[gpui::test]
    fn selection_band_beyond_clip_copies_offscreen_text(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (content, cx) = cx.add_window_view(|_, cx| ClippedTallTextViewTestRoot::new(cx));
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        // Anchor on visible text near the top, then drag to a point well below
        // the 40px clip (into the blank footer) and to the far right so the
        // last line is fully covered.
        cx.simulate_mouse_down(
            point(px(2.), px(8.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_move(
            point(px(180.), px(150.)),
            Some(MouseButton::Left),
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.simulate_mouse_up(
            point(px(180.), px(150.)),
            MouseButton::Left,
            Modifiers::default(),
        );
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let selected_text =
            content.read_with(cx, |root, cx| root.text_view.read(cx).selected_text());
        assert!(
            selected_text.contains("delta"),
            "clipped-out text was not copied: {selected_text:?}"
        );
        assert!(
            selected_text.contains("charlie"),
            "clipped-out text was not copied: {selected_text:?}"
        );
    }

    #[gpui::test]
    fn double_click_selects_word(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (view, cx) =
            cx.add_window_view(|_, cx| TextViewTestRoot::new("quick select value", cx));

        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let position = point(px(10.), px(16.));
        cx.simulate_event(MouseDownEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
            first_mouse: false,
        });
        cx.simulate_event(MouseUpEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 2,
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let selected_text = view.read_with(cx, |root, cx| root.text_view.read(cx).selected_text());
        assert_eq!(selected_text.trim(), "quick");
    }

    #[gpui::test]
    fn long_press_selects_word_then_drag_extends_selection(cx: &mut TestAppContext) {
        struct TouchRoot {
            text_view: Entity<TextViewState>,
        }
        impl Render for TouchRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(300.))
                    .child(crate::TextSelectionLayer)
                    .child(TextView::new(&self.text_view).selectable(true))
            }
        }
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(|_, cx| TouchRoot {
            text_view: cx.new(|cx| TextViewState::markdown("quick select value", cx)),
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let start_position = point(px(10.), px(16.));
        cx.simulate_event(gpui::LongPressEvent {
            phase: gpui::TouchPhase::Started,
            start_position,
            position: start_position,
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        assert_eq!(
            view.read_with(cx, |root, cx| root.text_view.read(cx).selected_text())
                .trim(),
            "quick"
        );
        for phase in [gpui::TouchPhase::Moved, gpui::TouchPhase::Ended] {
            cx.simulate_event(gpui::LongPressEvent {
                phase,
                start_position,
                position: point(px(220.), px(16.)),
            });
        }
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        assert_eq!(
            view.read_with(cx, |root, cx| root.text_view.read(cx).selected_text())
                .trim(),
            "quick select value"
        );
    }

    #[gpui::test]
    fn long_press_release_keeps_handles_which_drag_the_selection(cx: &mut TestAppContext) {
        use crate::{SelectionEdge, TextSelection};

        struct TouchRoot {
            text_view: Entity<TextViewState>,
        }
        impl Render for TouchRoot {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(300.))
                    .child(crate::TextSelectionLayer)
                    .child(TextView::new(&self.text_view).selectable(true))
            }
        }
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(|_, cx| TouchRoot {
            text_view: cx.new(|cx| TextViewState::markdown("quick select value", cx)),
        });
        let draw = |cx: &mut VisualTestContext| {
            cx.update(|window, cx| {
                let _ = window.draw(cx);
            });
        };
        let selected = |cx: &mut VisualTestContext| {
            view.read_with(cx, |root, cx| root.text_view.read(cx).selected_text())
                .trim()
                .to_string()
        };
        cx.run_until_parked();
        draw(cx);

        let start_position = point(px(70.), px(16.));
        for phase in [gpui::TouchPhase::Started, gpui::TouchPhase::Ended] {
            cx.simulate_event(gpui::LongPressEvent {
                phase,
                start_position,
                position: start_position,
            });
            draw(cx);
        }
        assert_eq!(selected(cx), "select");
        let snapshot = cx
            .update(|window, cx| TextSelection::touch_selection(window, cx))
            .expect("a released long press keeps its handles");
        assert!(snapshot.is_menu_open());
        assert!(!snapshot.is_empty());
        assert!(snapshot.start().left() < snapshot.end().left());

        // Drag the end handle to the end of the line. The finger holds the
        // knob below the line, the selection follows along the line.
        let end = snapshot.end();
        let finger = point(end.left(), end.bottom() + px(20.));
        cx.update(|window, cx| {
            TextSelection::begin_edge_drag(SelectionEdge::End, finger, window, cx);
        });
        draw(cx);
        let snapshot = cx
            .update(|window, cx| TextSelection::touch_selection(window, cx))
            .unwrap();
        assert_eq!(snapshot.dragging(), Some(SelectionEdge::End));
        assert!(!snapshot.is_menu_open());
        cx.update(|window, cx| {
            TextSelection::update_edge_drag(point(px(290.), finger.y), window, cx);
        });
        draw(cx);
        assert_eq!(selected(cx), "select value");
        cx.update(|window, cx| TextSelection::end_edge_drag(window, cx));
        draw(cx);
        let snapshot = cx
            .update(|window, cx| TextSelection::touch_selection(window, cx))
            .unwrap();
        assert!(snapshot.is_menu_open());
        assert_eq!(snapshot.dragging(), None);
        let select_start = snapshot.start().left();

        // Select All from the menu is a view-local selection; its handles
        // still drag, turning it back into a point selection.
        cx.update(|_, cx| {
            view.update(cx, |root, cx| {
                root.text_view.update(cx, |state, cx| state.select_all(cx));
            });
        });
        draw(cx);
        assert_eq!(selected(cx), "quick select value");
        let snapshot = cx
            .update(|window, cx| TextSelection::touch_selection(window, cx))
            .expect("select all keeps the touch selection");
        let start = snapshot.start();
        cx.update(|window, cx| {
            TextSelection::begin_edge_drag(SelectionEdge::Start, start.origin, window, cx);
            TextSelection::update_edge_drag(point(select_start, start.origin.y), window, cx);
            TextSelection::end_edge_drag(window, cx);
        });
        draw(cx);
        assert_eq!(selected(cx), "select value");

        // A press on the menu leaves the selection alone; one on the text
        // clears it.
        let menu = gpui::Bounds::new(point(px(0.), px(200.)), gpui::size(px(120.), px(32.)));
        cx.update(|window, cx| TextSelection::register_touch_ui(menu, window, cx));
        cx.simulate_event(MouseDownEvent {
            position: point(px(10.), px(210.)),
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 1,
            first_mouse: false,
        });
        assert_eq!(selected(cx), "select value");
        cx.simulate_event(MouseDownEvent {
            position: point(px(10.), px(16.)),
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 1,
            first_mouse: false,
        });
        cx.simulate_event(MouseUpEvent {
            position: point(px(10.), px(16.)),
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 1,
        });
        draw(cx);
        assert!(
            cx.update(|window, cx| TextSelection::touch_selection(window, cx))
                .is_none()
        );
    }

    #[gpui::test]
    fn triple_click_selects_paragraph(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let (view, cx) =
            cx.add_window_view(|_, cx| TextViewTestRoot::new("quick select value", cx));

        let cx: &mut VisualTestContext = cx;
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let position = point(px(10.), px(10.));
        cx.simulate_event(MouseDownEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 3,
            first_mouse: false,
        });
        cx.simulate_event(MouseUpEvent {
            position,
            modifiers: Modifiers::default(),
            button: MouseButton::Left,
            click_count: 3,
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        let selected_text = view.read_with(cx, |root, cx| root.text_view.read(cx).selected_text());
        assert_eq!(selected_text.trim(), "quick select value");
    }

    mod multi_click_drag {
        use super::*;

        struct Root {
            text_view: Entity<TextViewState>,
        }

        impl Render for Root {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(400.))
                    .child(crate::TextSelectionLayer)
                    .child(TextView::new(&self.text_view).selectable(true))
            }
        }

        fn setup<'a>(
            markdown: &str,
            cx: &'a mut TestAppContext,
        ) -> (Entity<TextViewState>, &'a mut VisualTestContext) {
            cx.update(crate::init);
            let (root, cx) = cx.add_window_view(|_, cx| Root {
                text_view: cx.new(|cx| TextViewState::markdown(markdown, cx)),
            });
            cx.run_until_parked();
            cx.update(|window, cx| window.draw(cx).clear(cx));
            (root.read_with(cx, |root, _| root.text_view.clone()), cx)
        }

        /// Just inside the character at `index` of the painted `text`.
        fn position(
            state: &Entity<TextViewState>,
            text: &str,
            index: usize,
            cx: &mut VisualTestContext,
        ) -> gpui::Point<Pixels> {
            state.read_with(cx, |state, _| {
                state.selection_adapter.text_position(text, index)
            })
        }

        fn press(
            position: gpui::Point<Pixels>,
            click_count: usize,
            shift: bool,
            cx: &mut VisualTestContext,
        ) {
            cx.simulate_event(MouseDownEvent {
                position,
                modifiers: Modifiers {
                    shift,
                    ..Default::default()
                },
                button: MouseButton::Left,
                click_count,
                first_mouse: false,
            });
        }

        fn drag(position: gpui::Point<Pixels>, cx: &mut VisualTestContext) {
            cx.simulate_event(gpui::MouseMoveEvent {
                position,
                pressed_button: Some(MouseButton::Left),
                modifiers: Modifiers::default(),
            });
        }

        fn release(position: gpui::Point<Pixels>, click_count: usize, cx: &mut VisualTestContext) {
            cx.simulate_event(MouseUpEvent {
                position,
                modifiers: Modifiers::default(),
                button: MouseButton::Left,
                click_count,
            });
        }

        fn selected(state: &Entity<TextViewState>, cx: &mut VisualTestContext) -> String {
            cx.update(|window, cx| window.draw(cx).clear(cx));
            state.read_with(cx, |state, _| state.selected_text().trim().to_string())
        }

        #[gpui::test]
        fn double_click_drag_extends_the_selection_by_words(cx: &mut TestAppContext) {
            let (first, second) = ("alpha beta gamma", "delta epsilon zeta");
            let (state, cx) = setup(&format!("{first}\n\n{second}"), cx);

            press(position(&state, first, 7, cx), 2, false, cx);
            assert_eq!(selected(&state, cx), "beta");
            drag(position(&state, first, 8, cx), cx);
            assert_eq!(selected(&state, cx), "beta");
            drag(position(&state, first, 13, cx), cx);
            assert_eq!(selected(&state, cx), "beta gamma");
            // Backward, the whole of the word the drag started from stays.
            drag(position(&state, first, 1, cx), cx);
            assert_eq!(selected(&state, cx), "alpha beta");
            let end = position(&state, second, 8, cx);
            drag(end, cx);
            assert_eq!(selected(&state, cx), "beta gamma\ndelta epsilon");
            release(end, 2, cx);
            assert_eq!(selected(&state, cx), "beta gamma\ndelta epsilon");
        }

        #[gpui::test]
        fn triple_click_drag_extends_the_selection_by_paragraphs(cx: &mut TestAppContext) {
            let (state, cx) = setup("first one\n\nsecond one\n\nthird one", cx);

            press(position(&state, "second one", 2, cx), 3, false, cx);
            assert_eq!(selected(&state, cx), "second one");
            drag(position(&state, "third one", 2, cx), cx);
            assert_eq!(selected(&state, cx), "second one\nthird one");
            let end = position(&state, "first one", 2, cx);
            drag(end, cx);
            assert_eq!(selected(&state, cx), "first one\nsecond one");
            release(end, 3, cx);
            assert_eq!(selected(&state, cx), "first one\nsecond one");
        }

        /// A hard break adds a line to a paragraph without ending that paragraph.
        #[gpui::test]
        fn triple_click_drag_and_shift_click_keep_hard_break_paragraphs_whole(
            cx: &mut TestAppContext,
        ) {
            let first = "first top\nfirst bottom";
            let last = "last top\nlast bottom";
            let (state, cx) = setup(
                "first top  \nfirst bottom\n\nmiddle\n\nlast top  \nlast bottom",
                cx,
            );

            press(position(&state, "middle", 2, cx), 3, false, cx);
            assert_eq!(selected(&state, cx), "middle");
            let after = position(&state, last, 2, cx);
            drag(after, cx);
            assert_eq!(selected(&state, cx), format!("middle\n{last}"));
            let before = position(&state, first, "first top\n".len() + 2, cx);
            drag(before, cx);
            assert_eq!(selected(&state, cx), format!("{first}\nmiddle"));
            release(before, 3, cx);

            press(after, 1, true, cx);
            release(after, 1, cx);
            assert_eq!(selected(&state, cx), format!("middle\n{last}"));
            press(before, 1, true, cx);
            release(before, 1, cx);
            assert_eq!(selected(&state, cx), format!("{first}\nmiddle"));
        }

        /// Inline code lays a paragraph out in pieces; the drag snaps the same.
        #[gpui::test]
        fn multi_click_drag_snaps_across_inline_code(cx: &mut TestAppContext) {
            let (state, cx) = setup("plain words\n\nuse `code` in here", cx);

            press(position(&state, "plain words", 8, cx), 2, false, cx);
            drag(position(&state, " in here", 6, cx), cx);
            assert_eq!(selected(&state, cx), "words\nuse code in here");
            release(position(&state, " in here", 6, cx), 2, cx);

            press(position(&state, "plain words", 2, cx), 3, false, cx);
            assert_eq!(selected(&state, cx), "plain words");
            drag(position(&state, "use ", 1, cx), cx);
            assert_eq!(selected(&state, cx), "plain words\nuse code in here");
        }

        #[gpui::test]
        fn shift_click_after_a_double_click_extends_by_words(cx: &mut TestAppContext) {
            let text = "alpha beta gamma";
            let (state, cx) = setup(text, cx);

            let word = position(&state, text, 7, cx);
            press(word, 2, false, cx);
            release(word, 2, cx);
            let after = position(&state, text, 13, cx);
            press(after, 1, true, cx);
            release(after, 1, cx);
            assert_eq!(selected(&state, cx), "beta gamma");
            let before = position(&state, text, 1, cx);
            press(before, 1, true, cx);
            release(before, 1, cx);
            assert_eq!(selected(&state, cx), "alpha beta");
        }
    }

    mod copy_before_paint {
        use super::*;
        use crate::{TextSelection, text::SelectionFormat};

        const MARKDOWN: &str = "中文 **café**\n\nβeta `\u{2009}code\u{2009}` 👩‍💻\n\n終わり";
        const PLAIN: &str = "中文 café\nβeta \u{2009}code\u{2009} 👩‍💻\n終わり\n";

        struct Root {
            state: Entity<TextViewState>,
            format: SelectionFormat,
            width: Pixels,
            scrollable: bool,
        }

        impl Render for Root {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(self.width)
                    .when(self.scrollable, |el| el.h(px(160.)))
                    .child(crate::TextSelectionLayer)
                    .child(
                        TextView::new(&self.state)
                            .scrollable(self.scrollable)
                            .selection_format(self.format),
                    )
            }
        }

        fn setup(
            format: SelectionFormat,
            cx: &mut TestAppContext,
        ) -> (Entity<TextViewState>, &mut VisualTestContext) {
            cx.update(crate::init);
            let (root, cx) = cx.add_window_view(|_, cx| Root {
                state: cx.new(|cx| TextViewState::markdown(MARKDOWN, cx)),
                format,
                width: px(520.),
                scrollable: false,
            });
            cx.run_until_parked();
            cx.update(|window, cx| window.draw(cx).clear(cx));
            (root.read_with(cx, |root, _| root.state.clone()), cx)
        }

        fn document<'a>(
            markdown: &str,
            format: SelectionFormat,
            scrollable: bool,
            cx: &'a mut TestAppContext,
        ) -> (Entity<Root>, &'a mut VisualTestContext) {
            cx.update(crate::init);
            let (root, cx) = cx.add_window_view(|_, cx| Root {
                state: cx.new(|cx| TextViewState::markdown(markdown, cx)),
                format,
                width: px(520.),
                scrollable,
            });
            cx.run_until_parked();
            cx.update(|window, cx| window.draw(cx).clear(cx));
            (root, cx)
        }

        fn scroll_to(state: &Entity<TextViewState>, ix: usize, cx: &mut VisualTestContext) {
            state.read_with(cx, |state, _| {
                state.list_state.scroll_to(gpui::ListOffset {
                    item_ix: ix,
                    offset_in_item: px(0.),
                })
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
        }

        fn endpoints(
            state: &Entity<TextViewState>,
            cx: &mut VisualTestContext,
        ) -> (
            gpui::Point<Pixels>,
            gpui::Point<Pixels>,
            gpui::Point<Pixels>,
        ) {
            let rows = state.read_with(cx, |state, _| state.selection_adapter.text_bounds());
            let first = rows.first().unwrap();
            let last = rows.last().unwrap();
            (
                point(first.left() + px(0.1), first.center().y),
                point(first.right() - px(0.1), first.center().y),
                point(last.right() - px(0.1), last.center().y),
            )
        }

        // Raw dispatch is intentional: simulate_event may draw after each
        // packet, concealing the exact native before-paint race.
        fn press(position: gpui::Point<Pixels>, window: &mut Window, cx: &mut gpui::App) {
            window.dispatch_event(
                gpui::PlatformInput::MouseDown(MouseDownEvent {
                    position,
                    button: MouseButton::Left,
                    click_count: 1,
                    ..Default::default()
                }),
                cx,
            );
        }

        fn extend(position: gpui::Point<Pixels>, window: &mut Window, cx: &mut gpui::App) {
            window.dispatch_event(
                gpui::PlatformInput::MouseMove(gpui::MouseMoveEvent {
                    position,
                    pressed_button: Some(MouseButton::Left),
                    ..Default::default()
                }),
                cx,
            );
        }

        fn release(position: gpui::Point<Pixels>, window: &mut Window, cx: &mut gpui::App) {
            window.dispatch_event(
                gpui::PlatformInput::MouseUp(MouseUpEvent {
                    position,
                    button: MouseButton::Left,
                    modifiers: Modifiers::default(),
                    click_count: 1,
                }),
                cx,
            );
        }

        fn assert_copy(expected: &str, window: &mut Window, cx: &mut gpui::App) {
            // Dispatch synchronously on the native current focus, without
            // focusing a different entity or using deferred window dispatch.
            let focus = window.focused(cx).expect("gesture focuses TextView");
            focus.dispatch_action(&crate::input::Copy, window, cx);
            assert_eq!(
                cx.read_from_clipboard().and_then(|item| item.text()),
                Some(expected.trim().to_string())
            );
            assert!(focus.is_focused(window));
            assert_eq!(TextSelection::selected_text(window, cx), expected);
        }

        #[gpui::test]
        fn custom_inline_and_block_copy_project_with_the_text(cx: &mut TestAppContext) {
            struct CustomRoot {
                state: Entity<TextViewState>,
                format: SelectionFormat,
                extensions: crate::text::MarkdownExtensions,
            }
            impl Render for CustomRoot {
                fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                    div().w(px(520.)).child(crate::TextSelectionLayer).child(
                        TextView::new(&self.state)
                            .selection_format(self.format)
                            .markdown_extensions(self.extensions.clone()),
                    )
                }
            }
            for format in [SelectionFormat::Plain, SelectionFormat::Source] {
                cx.update(crate::init);
                let extensions = crate::text::MarkdownExtensions::default()
                    .plugin(
                        crate::text::markdown_ext::TestInlinePlugin::new("math").parse_with(
                            |node, _| {
                                let markdown::mdast::Node::InlineMath(math) = node else {
                                    return None;
                                };
                                Some(
                                    crate::text::MarkdownNode::new("math", ())
                                        .text(format!("{}²", math.value)),
                                )
                            },
                        ),
                    )
                    .block_parser(|node, _| {
                        matches!(node, markdown::mdast::Node::ThematicBreak(_)).then(|| {
                            crate::text::MarkdownNode::new("block", ())
                                .text("BLOCK")
                                .markdown("---")
                        })
                    })
                    .block_renderer("block", |_, _, _| {
                        div()
                            .debug_selector(|| "copy-custom-block".into())
                            .w(px(520.))
                            .h(px(40.))
                    });
                let (root, cx) = cx.add_window_view(|_, cx| CustomRoot {
                    state: cx
                        .new(|cx| TextViewState::markdown("before $x$ after\n\n---\n\nlast", cx)),
                    format,
                    extensions,
                });
                cx.run_until_parked();
                cx.update(|window, cx| window.draw(cx).clear(cx));
                let state = root.read_with(cx, |root, _| root.state.clone());
                let (start, _, end) = endpoints(&state, cx);
                let expected = if format == SelectionFormat::Plain {
                    "before x² after\nBLOCK\nlast\n"
                } else {
                    "before $x$ after\n\n---\n\nlast"
                };
                cx.update(|window, cx| {
                    press(start, window, cx);
                    extend(end, window, cx);
                    assert_copy(expected, window, cx);
                    release(end, window, cx);
                });
                cx.update(|window, cx| window.draw(cx).clear(cx));
                cx.update(|window, cx| assert_copy(expected, window, cx));
                let block = cx.debug_bounds("copy-custom-block").unwrap();
                cx.update(|window, cx| {
                    press(block.center(), window, cx);
                    extend(point(block.center().x, block.bottom() + px(1.)), window, cx);
                    assert_copy(
                        if format == SelectionFormat::Plain {
                            "BLOCK\n"
                        } else {
                            "---"
                        },
                        window,
                        cx,
                    );
                });
            }
        }

        #[gpui::test]
        fn unicode_180_paragraph_copy_extends_and_retracts_before_paint(cx: &mut TestAppContext) {
            let markdown = (0..180)
                .map(|ix| format!("p{ix:03} **café** 中文 👩‍💻 `\u{2009}code\u{2009}`"))
                .collect::<Vec<_>>()
                .join("\n\n");
            // Expected bytes are constructed independently of rendered_text(),
            // selected_text(), and the document's selection serializer.
            let expected = (0..180)
                .map(|ix| format!("p{ix:03} café 中文 👩‍💻 \u{2009}code\u{2009}\n"))
                .collect::<String>();
            let (root, cx) = document(&markdown, SelectionFormat::Plain, false, cx);
            cx.simulate_resize(gpui::size(px(800.), px(12000.)));
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let state = root.read_with(cx, |root, _| root.state.clone());
            let rows = state.read_with(cx, |state, _| state.selection_adapter.text_bounds());
            let first = rows.first().unwrap();
            let first_end = rows
                .iter()
                .take_while(|row| row.top() < first.bottom())
                .last()
                .unwrap();
            let last = rows.last().unwrap();
            assert!(last.top() > first.top() + px(3000.));
            let start = point(first.left() + px(0.1), first.center().y);
            let short_end = point(first_end.right() - px(0.1), first_end.center().y);
            let end = point(last.right() - px(0.1), last.center().y);
            let short = "p000 café 中文 👩‍💻 \u{2009}code\u{2009}\n";
            cx.update(|window, cx| {
                press(start, window, cx);
                extend(short_end, window, cx);
                assert_copy(short, window, cx);
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.update(|window, cx| {
                extend(end, window, cx);
                assert_copy(&expected, window, cx);
                extend(short_end, window, cx);
                assert_copy(short, window, cx);
            });
        }

        #[gpui::test]
        fn scrolling_before_paint_keeps_the_completed_frame_coordinates(cx: &mut TestAppContext) {
            let markdown = format!(
                "{}\n\nlast",
                "alpha beta gamma delta epsilon zeta ".repeat(30)
            );
            let (root, cx) = document(&markdown, SelectionFormat::Plain, true, cx);
            root.update(cx, |root, cx| {
                root.width = px(180.);
                cx.notify();
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let state = root.read_with(cx, |root, _| root.state.clone());
            let rows = state.read_with(cx, |state, _| state.selection_adapter.text_bounds());
            let first = rows[0];
            let (start, end) = state.read_with(cx, |state, _| {
                (
                    state.selection_adapter.first_text_position(0),
                    state.selection_adapter.first_text_position("alpha".len()),
                )
            });
            cx.update(|window, cx| {
                press(start, window, cx);
                extend(end, window, cx);
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.update(|window, cx| {
                state.read(cx).list_state.scroll_by(first.size.height);
                // The logical offset changed, registration and native pixels
                // have not. This must not select the next wrapped row.
                assert_copy("alpha\n", window, cx);
            });
        }

        #[gpui::test]
        fn offscreen_remeasurement_is_not_a_copy_projection(cx: &mut TestAppContext) {
            let markdown = (0..180)
                .map(|ix| format!("row {ix:03} café 中文"))
                .collect::<Vec<_>>()
                .join("\n\n");
            let (root, cx) = document(&markdown, SelectionFormat::Plain, true, cx);
            let state = root.read_with(cx, |root, _| root.state.clone());
            scroll_to(&state, 90, cx);
            root.update(cx, |root, cx| {
                root.width = px(260.);
                cx.notify();
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            scroll_to(&state, 90, cx);
            // measure_all has remeasured earlier, unpainted paragraphs at the
            // new width. Only this completed paint supplies Copy geometry.
            let (start, end, _) = endpoints(&state, cx);
            cx.update(|window, cx| {
                press(start, window, cx);
                extend(end, window, cx);
                assert_copy("row 090 café 中文\n", window, cx);
            });
        }

        #[gpui::test]
        fn virtualized_flow_retains_its_source_owned_partial_anchor(cx: &mut TestAppContext) {
            for format in [SelectionFormat::Plain, SelectionFormat::Source] {
                let tail = (1..180)
                    .map(|ix| format!("row {ix:03} café 中文"))
                    .collect::<Vec<_>>();
                let markdown = format!("PREFIX `code` suffix\n\n{}", tail.join("\n\n"));
                let expected = if format == SelectionFormat::Plain {
                    format!("code suffix\n{}\n", tail.join("\n"))
                } else {
                    format!("`code` suffix\n\n{}", tail.join("\n\n"))
                };
                let (root, cx) = document(&markdown, format, true, cx);
                let state = root.read_with(cx, |root, _| root.state.clone());
                let rows = state.read_with(cx, |state, _| state.selection_adapter.text_bounds());
                let code = rows[1];
                let suffix = rows[2];
                assert!(code.left() < suffix.left());
                cx.update(|window, cx| {
                    press(point(code.left() + px(0.1), code.center().y), window, cx);
                    extend(
                        point(suffix.right() - px(0.1), suffix.center().y),
                        window,
                        cx,
                    );
                });
                cx.update(|window, cx| window.draw(cx).clear(cx));
                scroll_to(&state, 179, cx);
                // Two completed frames let GPUI retire temporary flow fragments.
                cx.update(|window, cx| window.draw(cx).clear(cx));
                let (_, _, end) = endpoints(&state, cx);
                cx.update(|window, cx| {
                    extend(end, window, cx);
                    assert_copy(&expected, window, cx);
                });
            }
        }

        #[gpui::test]
        fn a_new_range_copies_before_its_first_selection_paint(cx: &mut TestAppContext) {
            let (state, cx) = setup(SelectionFormat::Plain, cx);
            let (start, _, end) = endpoints(&state, cx);
            cx.update(|window, cx| {
                press(start, window, cx);
                extend(end, window, cx);
                assert_copy(PLAIN, window, cx);
            });
        }

        #[gpui::test]
        fn an_established_range_extends_and_retracts_without_paint(cx: &mut TestAppContext) {
            let (state, cx) = setup(SelectionFormat::Plain, cx);
            let (start, first_end, end) = endpoints(&state, cx);
            cx.update(|window, cx| {
                press(start, window, cx);
                extend(first_end, window, cx);
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.update(|window, cx| {
                assert_copy("中文 café\n", window, cx);
                extend(end, window, cx);
                assert_copy(PLAIN, window, cx);
                extend(first_end, window, cx);
                assert_copy("中文 café\n", window, cx);
            });
        }

        #[gpui::test]
        fn source_copy_projects_the_current_range_without_paint(cx: &mut TestAppContext) {
            let (state, cx) = setup(SelectionFormat::Source, cx);
            let (start, first_end, end) = endpoints(&state, cx);
            cx.update(|window, cx| {
                press(start, window, cx);
                extend(first_end, window, cx);
                assert_copy("中文 **café**", window, cx);
                extend(end, window, cx);
                assert_copy(MARKDOWN, window, cx);
                extend(first_end, window, cx);
                assert_eq!(TextSelection::selected_text(window, cx), "中文 **café**");
            });
        }

        #[gpui::test]
        fn a_blank_gesture_does_not_reuse_the_previous_range(cx: &mut TestAppContext) {
            let (state, cx) = setup(SelectionFormat::Plain, cx);
            let (start, first_end, end) = endpoints(&state, cx);
            cx.update(|window, cx| {
                press(start, window, cx);
                extend(end, window, cx);
                assert_eq!(TextSelection::selected_text(window, cx), PLAIN);
                release(end, window, cx);
                press(first_end + point(px(20.), px(0.)), window, cx);
                extend(first_end + point(px(60.), px(0.)), window, cx);
                assert_eq!(TextSelection::selected_text(window, cx), "");
            });
        }

        #[gpui::test]
        fn replacing_source_cannot_reproject_old_content(cx: &mut TestAppContext) {
            for format in [SelectionFormat::Plain, SelectionFormat::Source] {
                for replacement in ["replacement".to_string(), "replacement ".repeat(500)] {
                    let (state, cx) = setup(format, cx);
                    let (start, _, end) = endpoints(&state, cx);
                    cx.update(|window, cx| {
                        press(start, window, cx);
                        extend(end, window, cx);
                        assert_eq!(
                            TextSelection::selected_text(window, cx),
                            if format == SelectionFormat::Plain {
                                PLAIN
                            } else {
                                MARKDOWN
                            }
                        );
                        // Large replacements leave the previous parsed document
                        // in place while parsing; neither size may reuse it.
                        state.update(cx, |state, cx| state.set_text(&replacement, cx));
                        assert_eq!(TextSelection::selected_text(window, cx), "");
                    });
                }
            }
        }
    }

    // Regression: markdown `TextView` items inside an outer `gpui::list` with
    // `measure_all` must keep a stable total content height while scrolling.
    // Before synchronous full-replace parsing, off-screen markdown views were
    // first measured with empty content and the scrollbar thumb jittered as the
    // total height grew during scrolling.
    #[gpui::test]
    fn outer_list_content_total_stable_while_scrolling(cx: &mut TestAppContext) {
        use gpui::{ListAlignment, ListState, list};

        const ITEMS: &[&str] = &[
            "# Heading\n\nA paragraph long enough to wrap across several lines and produce a non-trivial height.",
            "Short.",
            "Paragraph A\n\nParagraph B\n\nParagraph C with more words to increase the height.",
            "## Subheading\n\n- One\n- Two\n- Three\n\nClosing paragraph.",
            "Only one line.",
            "**Bold**: medium length text with `code` mixed with regular words.",
            "1. First\n2. Second\n3. Third\n\nA short closing paragraph.",
            "A long message with enough words to wrap across multiple lines, create a taller item, and verify that off-screen measurement matches visible measurement.",
        ];
        let n = 40usize;

        struct ListRoot {
            state: ListState,
        }
        impl Render for ListRoot {
            fn render(&mut self, _w: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
                div().w(px(360.)).h(px(500.)).child(
                    list(self.state.clone(), |ix, _w, _cx| {
                        div()
                            .w_full()
                            .child(TextView::markdown(
                                ("md", ix as u64),
                                ITEMS[ix % ITEMS.len()],
                            ))
                            .into_any_element()
                    })
                    .size_full(),
                )
            }
        }

        cx.update(crate::init);
        let state = ListState::new(n, ListAlignment::Top, px(2048.)).measure_all();
        let probe = state.clone();
        let (_view, cx) = cx.add_window_view(|_w, _cx| ListRoot { state });
        let cx: &mut VisualTestContext = cx;

        cx.run_until_parked();
        cx.update(|w, cx| {
            let _ = w.draw(cx);
        });
        cx.run_until_parked();
        cx.update(|w, cx| {
            let _ = w.draw(cx);
        });

        let total = |p: &ListState| {
            f32::from(p.max_offset_for_scrollbar().y + p.viewport_bounds().size.height)
        };
        let mut totals = vec![total(&probe)];
        for _ in 0..20 {
            probe.scroll_by(px(150.));
            cx.update(|w, cx| {
                let _ = w.draw(cx);
            });
            cx.run_until_parked();
            totals.push(total(&probe));
        }
        let min = totals.iter().cloned().fold(f32::INFINITY, f32::min);
        let max = totals.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
        println!(
            "OUTER_LIST_PROBE min={min:.1} max={max:.1} delta={:.1}",
            max - min
        );
        assert!(
            (max - min) < 2.0,
            "list content total jittered while scrolling: min={min} max={max} totals={totals:?}"
        );
    }
}
