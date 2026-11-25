use std::{
    any::Any,
    collections::HashMap,
    fmt,
    ops::Range,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
};

use gpui::{AnyElement, App, IntoElement, SharedString, Window};
use markdown::{ParseOptions, mdast};

use super::{InlineElement, InlineRenderContext};
use crate::text::node::Span;

static MARKDOWN_EXTENSIONS_REVISION: AtomicU64 = AtomicU64::new(1);

/// Re-export of the Markdown AST types used by custom parsers.
pub use markdown::mdast as markdown_ast;

/// Type for a custom Markdown block parser.
///
/// Parsers run during Markdown AST conversion, often on a background task. They
/// must not depend on [`Window`] or [`App`]; return parsed, reusable data in a
/// [`MarkdownNode`] and render it later with a block renderer.
pub type MarkdownBlockParserFn =
    dyn for<'a> Fn(&mdast::Node, &MarkdownParseContext<'a>) -> Option<MarkdownNode> + Send + Sync;

/// Type for a custom Markdown block renderer.
pub type MarkdownBlockRenderFn =
    dyn Fn(&MarkdownNode, &mut Window, &mut App) -> AnyElement + Send + Sync;

/// Parser for a single inline AST node; follows the block parser contract.
type MarkdownInlineParserFn = MarkdownBlockParserFn;

/// Produces a native GPUI inline element, or `None` for atomic text fallback.
/// Read prepared resources here; start asynchronous work outside rendering.
type MarkdownInlineRenderFn = dyn Fn(&MarkdownNode, &InlineRenderContext, &mut Window, &mut App) -> Option<InlineElement>
    + Send
    + Sync;

/// A reusable Markdown extension that parses and renders one custom node.
pub trait MarkdownPlugin: Send + Sync + 'static {
    /// Whether this plugin produces block-level nodes.
    ///
    /// Plugins are inline by default. Block plugins should return `true`.
    fn is_block(&self) -> bool {
        false
    }

    /// Stable name for nodes produced by this plugin.
    fn name(&self) -> &str;

    /// Convert an mdast node into a custom Markdown node.
    fn parse(&self, node: &mdast::Node, cx: &MarkdownParseContext<'_>) -> Option<MarkdownNode>;

    /// Render a custom Markdown node produced by this plugin.
    fn render(&self, node: &MarkdownNode, _window: &mut Window, _cx: &mut App) -> impl IntoElement {
        node.as_text().to_string()
    }

    /// Render an inline node using the existing `render` implementation.
    /// Override this only when inherited layout context or an explicit baseline is needed.
    fn render_inline(
        &self,
        node: &MarkdownNode,
        _context: &InlineRenderContext,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<InlineElement> {
        Some(InlineElement::new(self.render(node, window, cx)))
    }
}

/// Context passed to custom Markdown parsers.
pub struct MarkdownParseContext<'a> {
    source: &'a str,
    offset: usize,
}

impl<'a> MarkdownParseContext<'a> {
    pub(crate) fn new(source: &'a str, offset: usize) -> Self {
        Self { source, offset }
    }

    /// Source text for the Markdown fragment currently being parsed.
    pub fn source(&self) -> &'a str {
        self.source
    }

    /// Byte offset of `source` in the full document when parsing an appended
    /// fragment.
    pub fn offset(&self) -> usize {
        self.offset
    }

    /// Source slice for a specific mdast node.
    pub fn node_source(&self, node: &mdast::Node) -> Option<&'a str> {
        let position = node.position()?;
        self.source.get(position.start.offset..position.end.offset)
    }
}

/// A custom Markdown node produced by [`MarkdownExtensions`].
#[derive(Clone)]
pub struct MarkdownNode {
    name: SharedString,
    text: SharedString,
    markdown: SharedString,
    accessibility_label: Option<SharedString>,
    data: Arc<dyn Any + Send + Sync>,
    pub(crate) span: Option<Span>,
}

impl MarkdownNode {
    /// Create a custom Markdown node with a stable name and typed data.
    pub fn new<T>(name: impl Into<SharedString>, data: T) -> Self
    where
        T: Any + Send + Sync + 'static,
    {
        Self {
            name: name.into(),
            text: SharedString::default(),
            markdown: SharedString::default(),
            accessibility_label: None,
            data: Arc::new(data),
            span: None,
        }
    }

    /// Stable name for this custom node.
    pub fn name(&self) -> &str {
        &self.name
    }

    /// Text representation of this custom node.
    pub fn as_text(&self) -> &str {
        &self.text
    }

    /// Markdown representation of this custom node.
    pub fn as_markdown(&self) -> &str {
        &self.markdown
    }

    /// Full-document UTF-8 source byte range, including syntax delimiters.
    pub fn source_range(&self) -> Option<Range<usize>> {
        self.span.map(|span| span.start..span.end)
    }

    /// Name exposed to accessibility clients, defaulting to the plain text.
    pub fn accessibility_name(&self) -> &str {
        self.accessibility_label.as_deref().unwrap_or(&self.text)
    }

    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        let label = label.into();
        self.accessibility_label = (!label.is_empty()).then_some(label);
        self
    }

    /// Plain text, sharing this node's buffer.
    ///
    /// The inline flow rebuilds its items every frame and holds text by value,
    /// so going through [`Self::as_text`] would allocate a `String` per object
    /// per frame.
    pub(crate) fn shared_text(&self) -> SharedString {
        self.text.clone()
    }

    /// Accessible name, sharing this node's buffer. Defaults to the plain text.
    pub(crate) fn shared_accessibility_name(&self) -> SharedString {
        self.accessibility_label
            .clone()
            .unwrap_or_else(|| self.text.clone())
    }

    pub(crate) fn with_inline_source(mut self, source: &str) -> Self {
        if self.text.is_empty() {
            self.text = source.to_string().into();
        }
        if self.markdown.is_empty() {
            self.markdown = source.to_string().into();
        }
        self
    }

    /// Set the text representation of this custom node.
    pub fn text(mut self, text: impl Into<SharedString>) -> Self {
        self.text = text.into();
        self
    }

    /// Set the Markdown representation of this custom node.
    pub fn markdown(mut self, markdown: impl Into<SharedString>) -> Self {
        self.markdown = markdown.into();
        self
    }

    /// Read typed data.
    pub fn data<T>(&self) -> Option<&T>
    where
        T: Any + Send + Sync + 'static,
    {
        self.data.downcast_ref()
    }

    pub(crate) fn set_span(&mut self, span: Option<Span>) {
        self.span = span;
    }

    pub(crate) fn to_markdown(&self) -> String {
        if self.markdown.is_empty() {
            self.text.to_string()
        } else {
            self.markdown.to_string()
        }
    }
}

impl fmt::Debug for MarkdownNode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("MarkdownNode")
            .field("name", &self.name)
            .field("text", &self.text)
            .field("markdown", &self.markdown)
            .field("span", &self.span)
            .finish_non_exhaustive()
    }
}

impl PartialEq for MarkdownNode {
    fn eq(&self, other: &Self) -> bool {
        self.name == other.name
            && self.text == other.text
            && self.markdown == other.markdown
            && self.accessibility_label == other.accessibility_label
            && self.span == other.span
    }
}

/// Registry for custom Markdown parsing and rendering.
#[derive(Clone, Default)]
pub struct MarkdownExtensions {
    enable_mdx: bool,
    enable_frontmatter: bool,
    block_parsers: Vec<Arc<MarkdownBlockParserFn>>,
    block_renderers: HashMap<SharedString, Arc<MarkdownBlockRenderFn>>,
    inline_parsers: Vec<Arc<MarkdownInlineParserFn>>,
    inline_renderers: HashMap<SharedString, Arc<MarkdownInlineRenderFn>>,
    revision: u64,
    parser_revision: u64,
}

impl MarkdownExtensions {
    /// Change this revision when parser captures or plugin configuration change.
    /// Reusing it allows equivalent registrations rebuilt during rendering to
    /// retain the parsed document. Renderer-only changes do not need a new value.
    pub fn parser_revision(mut self, revision: u64) -> Self {
        self.parser_revision = revision;
        self.bump_revision();
        self
    }

    /// Enable YAML frontmatter parsing.
    ///
    /// Frontmatter is disabled by default because it is not part of CommonMark
    /// or GFM. Register a block parser or [`MarkdownPlugin`] to render the
    /// resulting [`mdast::Node::Yaml`] node.
    pub fn frontmatter(mut self) -> Self {
        self.enable_frontmatter = true;
        self.bump_revision();
        self
    }

    /// Enable MDX JSX/expression constructs.
    ///
    /// This disables raw HTML constructs because `markdown-rs` gives HTML
    /// priority over MDX when both are enabled.
    pub fn mdx(mut self) -> Self {
        self.enable_mdx = true;
        self.bump_revision();
        self
    }

    /// Register a parser for block-level Markdown AST nodes.
    pub fn block_parser<F>(mut self, parser: F) -> Self
    where
        F: for<'a> Fn(&mdast::Node, &MarkdownParseContext<'a>) -> Option<MarkdownNode>
            + Send
            + Sync
            + 'static,
    {
        self.push_block_parser(parser);
        self
    }

    /// Register a renderer for a custom block node name.
    pub fn block_renderer<F, E>(mut self, name: impl Into<SharedString>, renderer: F) -> Self
    where
        F: Fn(&MarkdownNode, &mut Window, &mut App) -> E + Send + Sync + 'static,
        E: IntoElement,
    {
        self.push_block_renderer(name, renderer);
        self
    }

    /// Apply a reusable Markdown plugin.
    pub fn plugin<P>(self, plugin: P) -> Self
    where
        P: MarkdownPlugin,
    {
        let plugin = Arc::new(plugin);
        let name = SharedString::from(plugin.name().to_string());
        let parser = plugin.clone();
        let renderer = plugin;

        if parser.is_block() {
            let mut extensions = self.block_parser(move |node, cx| parser.parse(node, cx));
            extensions.push_block_renderer(name, move |node, window, cx| {
                renderer.render(node, window, cx).into_any_element()
            });
            extensions
        } else {
            let mut extensions = self;
            extensions
                .inline_parsers
                .push(Arc::new(move |node, cx| parser.parse(node, cx)));
            extensions.inline_renderers.insert(
                name,
                Arc::new(move |node, context, window, cx| {
                    renderer.render_inline(node, context, window, cx)
                }),
            );
            extensions.bump_revision();
            extensions
        }
    }

    pub(crate) fn revision(&self) -> u64 {
        self.revision
    }

    /// Whether replacing these extension handles can change the parsed tree.
    ///
    /// Render methods commonly rebuild equivalent plugin closures every frame.
    /// Their globally unique revisions differ, but the parser shape remains
    /// stable; render handles may be refreshed without reparsing the document.
    pub(crate) fn has_same_parser_configuration(&self, other: &Self) -> bool {
        self.parser_revision == other.parser_revision
            && self.enable_mdx == other.enable_mdx
            && self.enable_frontmatter == other.enable_frontmatter
            && self.block_parsers.len() == other.block_parsers.len()
            && self.block_renderers.len() == other.block_renderers.len()
            && self.inline_parsers.len() == other.inline_parsers.len()
            && self.inline_renderers.len() == other.inline_renderers.len()
            && self
                .inline_renderers
                .keys()
                .all(|name| other.inline_renderers.contains_key(name))
            && self
                .block_renderers
                .keys()
                .all(|name| other.block_renderers.contains_key(name))
    }

    pub(crate) fn push_block_parser<F>(&mut self, parser: F)
    where
        F: for<'a> Fn(&mdast::Node, &MarkdownParseContext<'a>) -> Option<MarkdownNode>
            + Send
            + Sync
            + 'static,
    {
        self.block_parsers.push(Arc::new(parser));
        self.bump_revision();
    }

    pub(crate) fn push_block_renderer<F, E>(&mut self, name: impl Into<SharedString>, renderer: F)
    where
        F: Fn(&MarkdownNode, &mut Window, &mut App) -> E + Send + Sync + 'static,
        E: IntoElement,
    {
        self.block_renderers.insert(
            name.into(),
            Arc::new(move |node, window, cx| renderer(node, window, cx).into_any_element()),
        );
        self.bump_revision();
    }

    pub(crate) fn parse_options(&self) -> ParseOptions {
        let mut options = ParseOptions::gfm();
        options.constructs.frontmatter = self.enable_frontmatter;
        options.constructs.math_text = true;
        // Both fences or neither: with only `math_text` on, the inline
        // construct swallows a `$$` block, so a block plugin matching
        // `Node::Math` never fires and the formula renders inline.
        options.constructs.math_flow = true;
        if self.enable_mdx {
            options.constructs.html_flow = false;
            options.constructs.html_text = false;
            options.constructs.mdx_expression_flow = true;
            options.constructs.mdx_expression_text = true;
            options.constructs.mdx_jsx_flow = true;
            options.constructs.mdx_jsx_text = true;
        }
        options
    }

    pub(crate) fn parse_block(
        &self,
        node: &mdast::Node,
        cx: &MarkdownParseContext<'_>,
    ) -> Option<MarkdownNode> {
        for parser in &self.block_parsers {
            if let Some(node) = parser(node, cx) {
                return Some(node);
            }
        }
        None
    }

    pub(crate) fn parse_inline(
        &self,
        node: &mdast::Node,
        cx: &MarkdownParseContext<'_>,
    ) -> Option<MarkdownNode> {
        self.inline_parsers
            .iter()
            .find_map(|parser| parser(node, cx))
    }

    pub(crate) fn render_inline(
        &self,
        node: &MarkdownNode,
        context: &InlineRenderContext,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<InlineElement> {
        self.inline_renderers
            .get(node.name())
            .and_then(|render| render(node, context, window, cx))
    }

    pub(crate) fn render_block(
        &self,
        node: &MarkdownNode,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        self.block_renderers
            .get(node.name())
            .map(|render| render(node, window, cx))
    }

    fn bump_revision(&mut self) {
        self.revision = MARKDOWN_EXTENSIONS_REVISION.fetch_add(1, Ordering::Relaxed);
    }
}

/// Test fixture that exercises the same plugin registration path as applications.
#[cfg(test)]
pub(super) struct TestInlinePlugin {
    name: &'static str,
    parser: Option<Arc<MarkdownInlineParserFn>>,
    renderer: Option<Arc<MarkdownInlineRenderFn>>,
}

#[cfg(test)]
impl TestInlinePlugin {
    pub(super) fn new(name: &'static str) -> Self {
        Self {
            name,
            parser: None,
            renderer: None,
        }
    }

    pub(super) fn parse_with<F>(mut self, parser: F) -> Self
    where
        F: for<'a> Fn(&mdast::Node, &MarkdownParseContext<'a>) -> Option<MarkdownNode>
            + Send
            + Sync
            + 'static,
    {
        self.parser = Some(Arc::new(parser));
        self
    }

    pub(super) fn render_with<F>(mut self, renderer: F) -> Self
    where
        F: Fn(&MarkdownNode, &InlineRenderContext, &mut Window, &mut App) -> Option<InlineElement>
            + Send
            + Sync
            + 'static,
    {
        self.renderer = Some(Arc::new(renderer));
        self
    }
}

#[cfg(test)]
impl MarkdownPlugin for TestInlinePlugin {
    fn name(&self) -> &str {
        self.name
    }

    fn parse(&self, node: &mdast::Node, cx: &MarkdownParseContext<'_>) -> Option<MarkdownNode> {
        self.parser.as_ref().and_then(|parse| parse(node, cx))
    }

    fn render_inline(
        &self,
        node: &MarkdownNode,
        context: &InlineRenderContext,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<InlineElement> {
        self.renderer
            .as_ref()
            .and_then(|render| render(node, context, window, cx))
    }
}
