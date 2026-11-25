use std::sync::Arc;

use gpui::{HighlightStyle, Pixels, Rems, StyleRefinement, px, rems};

use crate::highlighter::HighlightTheme;

/// TextViewStyle used to customize the style for [`super::TextView`].
///
/// This is the component-level style. It is folded onto the style the active
/// [`crate::Theme`] already derived, so a field left at its default keeps the
/// themed value rather than overriding it with a neutral one.
#[derive(Clone)]
pub struct TextViewStyle {
    /// Gap of each paragraphs, default is 0.75 rem.
    pub paragraph_gap: Rems,
    /// Base font size for headings, default is 14px.
    ///
    /// Left at the default together with [`Self::heading_font_size`], headings
    /// follow the text view's own scale, proportional to the body text.
    pub heading_base_font_size: Pixels,
    /// Function to calculate heading font size based on heading level (1-6).
    ///
    /// The first parameter is the heading level (1-6), the second parameter is
    /// the base font size.
    pub heading_font_size: Option<Arc<dyn Fn(u8, Pixels) -> Pixels + Send + Sync + 'static>>,
    /// Highlight theme for code blocks. Default: [`HighlightTheme::default_light()`]
    pub highlight_theme: Arc<HighlightTheme>,
    /// The style refinement for code blocks.
    ///
    /// Set `overflow.y` to `Overflow::Scroll` with a max height here to scroll
    /// long code inside the block, e.g.
    /// `TextViewStyle::default().code_block({ let mut s = StyleRefinement::default().max_h(px(320.)); s.overflow.y = Some(Overflow::Scroll); s })`.
    pub code_block: StyleRefinement,
    /// Style refinement applied to the table container (the bordered wrapper
    /// in wrap mode, the scroll viewport in horizontal-scroll mode).
    ///
    /// Set `overflow_x: scroll` here for adaptive table layout: columns fit
    /// their content when space allows, shrink (wrapping cell text) down to a
    /// per-column floor when the frame is narrower, and below that the table
    /// scrolls horizontally instead of squeezing further, e.g.
    /// `TextViewStyle::default().table({ let mut s = StyleRefinement::default(); s.overflow.x = Some(Overflow::Scroll); s })`.
    pub table: StyleRefinement,
    /// Style refinement applied to the header row (the first row) of a table,
    /// on top of the `table_head` background and foreground from the theme.
    pub table_head: StyleRefinement,
    /// Style refinement applied to each table cell.
    ///
    /// With the scroll layout, set `white_space: nowrap` here to keep cells
    /// on a single line — columns then never shrink and the table scrolls as
    /// soon as the content is wider than the frame.
    pub table_cell: StyleRefinement,
    /// The highlight style for inline code.
    ///
    /// Default is [`HighlightStyle::default()`], the `background_color` will
    /// fallback to `cx.theme().accent`, if it is `None`.
    pub inline_code: HighlightStyle,
    /// Whether content-specific rendering should use dark-mode assets.
    pub is_dark: bool,
}

impl Default for TextViewStyle {
    fn default() -> Self {
        Self {
            paragraph_gap: rems(0.75),
            heading_base_font_size: px(14.),
            heading_font_size: None,
            highlight_theme: HighlightTheme::default_light().clone(),
            code_block: StyleRefinement::default(),
            table: StyleRefinement::default(),
            table_head: StyleRefinement::default(),
            table_cell: StyleRefinement::default(),
            inline_code: HighlightStyle::default(),
            is_dark: false,
        }
    }
}

impl PartialEq for TextViewStyle {
    fn eq(&self, other: &Self) -> bool {
        self.paragraph_gap == other.paragraph_gap
            && self.heading_base_font_size == other.heading_base_font_size
            && match (&self.heading_font_size, &other.heading_font_size) {
                (Some(left), Some(right)) => (1..=6).all(|level| {
                    left(level, self.heading_base_font_size)
                        == right(level, other.heading_base_font_size)
                }),
                (None, None) => true,
                _ => false,
            }
            && self.highlight_theme == other.highlight_theme
            && self.code_block == other.code_block
            && self.table == other.table
            && self.table_head == other.table_head
            && self.table_cell == other.table_cell
            && self.inline_code == other.inline_code
            && self.is_dark == other.is_dark
    }
}

impl TextViewStyle {
    /// Set paragraph gap, default is 0.75 rem.
    pub fn paragraph_gap(mut self, gap: Rems) -> Self {
        self.paragraph_gap = gap;
        self
    }
    /// Set the function that resolves a heading's font size from its level
    /// (1-6) and [`Self::heading_base_font_size`].
    pub fn heading_font_size<F>(mut self, f: F) -> Self
    where
        F: Fn(u8, Pixels) -> Pixels + Send + Sync + 'static,
    {
        self.heading_font_size = Some(Arc::new(f));
        self
    }
    /// Set style for code blocks.
    ///
    /// Set `overflow.y` to `Overflow::Scroll` with a max height on the
    /// refinement to scroll long code inside the block instead of growing it.
    pub fn code_block(mut self, style: StyleRefinement) -> Self {
        self.code_block = style;
        self
    }
    /// Set style for inline code spans.
    pub fn inline_code(mut self, style: HighlightStyle) -> Self {
        self.inline_code = style;
        self
    }
    /// Set extra style for the table container.
    ///
    /// Set `overflow_x: scroll` on the refinement for adaptive layout: cells
    /// wrap as the frame narrows, and once columns reach their minimum width
    /// the table scrolls horizontally instead of shrinking further.
    pub fn table(mut self, style: StyleRefinement) -> Self {
        self.table = style;
        self
    }
    /// Set extra style for the table header row.
    pub fn table_head(mut self, style: StyleRefinement) -> Self {
        self.table_head = style;
        self
    }
    /// Set extra style for each table cell.
    ///
    /// With the scroll table layout, `white_space: nowrap` here keeps cells
    /// on a single line and the table scrolls whenever the content is wider
    /// than the frame.
    pub fn table_cell(mut self, style: StyleRefinement) -> Self {
        self.table_cell = style;
        self
    }
}
