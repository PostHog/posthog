/// WrapMap: Soft-wrapping layer (Buffer → Wrap rows).
///
/// This module wraps the existing TextWrapper and provides:
/// - BufferPoint ↔ WrapPoint mapping
/// - Efficient buffer_line → wrap_row queries via prefix sum cache
/// - Incremental updates when text or layout changes
use std::ops::Range;

use gpui::{App, Font, Pixels};
use ropey::Rope;

use super::fold_map::FoldMap;
use super::text_wrapper::{LineItem, TextWrapper, WrapDisplayPoint, WrappingIndent};
use super::{BufferPoint, WrapPoint};
use crate::input::RopeExt;

/// WrapMap manages soft-wrapping and provides buffer ↔ wrap coordinate mapping.
///
/// Buffer line ↔ wrap row mapping is backed by the [`TextWrapper`]'s `SumTree`.
pub(super) struct WrapMap {
    /// The underlying text wrapper (reuses existing implementation)
    wrapper: TextWrapper,
}

impl WrapMap {
    pub(super) fn new(font: Font, font_size: Pixels, wrap_width: Option<Pixels>) -> Self {
        Self {
            wrapper: TextWrapper::new(font, font_size, wrap_width),
        }
    }

    /// Get total number of wrap rows (visual rows after soft-wrapping)
    #[inline]
    pub(super) fn wrap_row_count(&self) -> usize {
        self.wrapper.len()
    }

    /// Get total number of buffer lines (logical lines)
    #[inline]
    pub(super) fn buffer_line_count(&self) -> usize {
        self.wrapper.lines_count()
    }

    /// Convert buffer position to wrap position
    pub(super) fn buffer_pos_to_wrap_pos(&self, pos: BufferPoint) -> WrapPoint {
        let BufferPoint { line, col } = pos;

        // Clamp to valid range
        let line = line.min(self.buffer_line_count().saturating_sub(1));
        let line_item = self.wrapper.line(line);

        let col = if let Some(line_item) = line_item {
            col.min(line_item.len())
        } else {
            0
        };

        // Calculate offset in rope
        let line_start_offset = self.wrapper.text().line_start_offset(line);
        let offset = line_start_offset + col;

        // Use TextWrapper's existing conversion
        let display_point = self.wrapper.offset_to_display_point(offset);

        WrapPoint::new(display_point.row, display_point.column)
    }

    /// Convert wrap position to buffer position
    pub(super) fn wrap_pos_to_buffer_pos(&self, pos: WrapPoint) -> BufferPoint {
        let WrapPoint { row, col } = pos;

        // Clamp wrap_row to valid range
        let row = row.min(self.wrap_row_count().saturating_sub(1));

        // Use TextWrapper's existing conversion
        let display_point = WrapDisplayPoint::new(row, 0, col);
        let offset = self.wrapper.display_point_to_offset(display_point);

        // Convert offset to buffer position
        let point = self.wrapper.text().offset_to_point(offset);
        let line_start = self.wrapper.text().line_start_offset(point.row);
        let col = offset.saturating_sub(line_start);

        BufferPoint::new(point.row, col)
    }

    /// Get the buffer line for a given wrap row
    pub(super) fn wrap_row_to_buffer_line(&self, wrap_row: usize) -> usize {
        self.wrapper.wrap_row_to_buffer_line(wrap_row)
    }

    /// Get the first wrap row for a given buffer line
    pub(super) fn buffer_line_to_first_wrap_row(&self, line: usize) -> usize {
        self.wrapper.buffer_line_to_first_wrap_row(line)
    }

    /// Get the wrap row range for a buffer line: [start, end)
    pub(super) fn buffer_line_to_wrap_row_range(&self, line: usize) -> Range<usize> {
        self.wrapper.buffer_line_to_wrap_row_range(line)
    }

    /// Update text (incremental or full)
    pub(super) fn on_text_changed(
        &mut self,
        changed_text: &Rope,
        range: &Range<usize>,
        new_text: &Rope,
        cx: &mut App,
    ) {
        self.wrapper.adjust_inline_metrics(range, new_text.len());
        self.wrapper.update(changed_text, range, new_text, cx);
    }

    /// Update layout parameters (wrap width or font)
    pub(super) fn set_inline_metrics(
        &mut self,
        metrics: std::rc::Rc<[(std::ops::Range<usize>, Pixels)]>,
        cx: &mut App,
    ) {
        self.wrapper.set_inline_metrics(metrics, cx);
    }

    pub(super) fn on_layout_changed(&mut self, wrap_width: Option<Pixels>, cx: &mut App) {
        self.wrapper.set_wrap_width(wrap_width, cx);
    }

    /// Set the wrapping indent mode for continuation lines.
    pub(super) fn set_wrapping_indent(&mut self, wrapping_indent: WrappingIndent, cx: &mut App) {
        self.wrapper.set_wrapping_indent(wrapping_indent, cx);
    }

    /// Set the number of spaces per tab stop. Returns whether it changed.
    pub(super) fn set_tab_size(&mut self, tab_size: usize, cx: &mut App) -> bool {
        self.wrapper.set_tab_size(tab_size, cx)
    }

    /// Set font parameters
    pub(super) fn set_font(&mut self, font: Font, font_size: Pixels, cx: &mut App) {
        self.wrapper.set_font(font, font_size, cx);
    }

    /// Ensure text is prepared (initializes wrapper if needed)
    pub(super) fn ensure_text_prepared(&mut self, text: &Rope, cx: &mut App) -> bool {
        self.wrapper.prepare_if_need(text, cx)
    }

    /// Initialize with text
    pub(super) fn set_text(&mut self, text: &Rope, cx: &mut App) {
        self.wrapper.set_default_text(text);
        self.wrapper.prepare_if_need(text, cx);
    }

    /// Get access to the underlying wrapper (for rendering/hit-testing)
    pub(crate) fn wrapper(&self) -> &TextWrapper {
        &self.wrapper
    }

    /// Get the line item by buffer row index.
    #[inline]
    pub(crate) fn line(&self, row: usize) -> Option<&LineItem> {
        self.wrapper.line(row)
    }

    /// Get the rope text
    pub(super) fn text(&self) -> &Rope {
        self.wrapper.text()
    }

    /// Calculate how many wrap rows of a buffer line are visible (not folded)
    pub(super) fn visible_wrap_row_count_for_line(&self, line: usize, fold_map: &FoldMap) -> usize {
        let wrap_range = self.buffer_line_to_wrap_row_range(line);
        wrap_range
            .filter(|&wr| fold_map.wrap_row_to_display_row(wr).is_some())
            .count()
    }
}
