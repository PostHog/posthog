/// Display mapping system for Editor/Input.
///
/// This module implements a layered display mapping architecture:
/// - **WrapMap**: Handles soft-wrapping (buffer → wrap rows)
/// - **FoldMap**: Handles folding (wrap rows → display rows)
/// - **DisplayMap**: Public facade for Editor/Input
///
/// The goal is to provide a clean, unified API where Editor only needs to know
/// about `BufferPoint ↔ DisplayPoint` mapping, without worrying about internal wrap/fold complexity.
mod display_map;
mod inline_line;
pub(crate) use inline_line::{InlineFragment, InputLine};
mod fold_map;
mod folding;
mod text_wrapper;
mod wrap_map;

// Re-export public API
pub use self::display_map::{DisplayMap, WrappingIndent};
pub(crate) use self::text_wrapper::LineLayout;

// Re-export FoldRange and extract_fold_ranges
pub use folding::FoldRange;

/// Position in the buffer (logical text).
///
/// - `line`: 0-based logical line number (split by `\n`)
/// - `col`: 0-based column offset (byte offset)
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct BufferPoint {
    pub line: usize,
    pub col: usize,
}

impl BufferPoint {
    pub fn new(line: usize, col: usize) -> Self {
        Self { line, col }
    }
}

/// Position after soft-wrapping but before folding (internal).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub(super) struct WrapPoint {
    pub row: usize,
    pub col: usize,
}

impl WrapPoint {
    pub(super) fn new(row: usize, col: usize) -> Self {
        Self { row, col }
    }
}

/// Final display position (after soft-wrapping and folding).
///
/// - `row`: 0-based display row (final visible row)
/// - `col`: 0-based display column
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct DisplayPoint {
    pub row: usize,
    pub col: usize,
}

impl DisplayPoint {
    pub fn new(row: usize, col: usize) -> Self {
        Self { row, col }
    }
}
