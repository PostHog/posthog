//! Conservative width intervals reuse the original Unicode wrapping decisions without approximating glyphs.

use gpui::{Boundary, Pixels, px};

#[cfg(test)]
mod tests;

#[cfg(test)]
thread_local! {
    /// Actual glyph-measurement passes distinguish cache reuse from visually identical recomputation.
    pub(super) static MEASURED_LINES: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

/// All comparisons that chose the current line breaks must retain their truth value.
#[derive(Clone, Copy, Debug)]
pub(super) struct WidthRange {
    /// Inclusive lower bound in logical pixels, rounded inward for floating point subtraction.
    minimum: Pixels,
    /// Exclusive upper bound in logical pixels, also rounded inward.
    maximum: Pixels,
}

impl WidthRange {
    /// An empty line imposes no width constraint until a glyph measurement narrows it.
    pub(super) fn all() -> Self {
        Self {
            minimum: Pixels::MIN,
            maximum: Pixels::MAX,
        }
    }

    /// Unknown measurement semantics (notably inline elements) must always take the original path.
    pub(super) fn empty() -> Self {
        Self {
            minimum: px(0.),
            maximum: px(0.),
        }
    }

    /// Report the original fit predicate and retain a safe interval for the enclosing viewport.
    /// `indent` is subtracted from its width to obtain `available` on continuation rows.
    pub(super) fn fits(&mut self, measured: Pixels, available: Pixels, indent: Pixels) -> bool {
        let fits = measured <= available;
        let boundary = f32::from(measured + indent);
        if fits {
            self.minimum = self.minimum.max(px(boundary.next_up()));
        } else {
            self.maximum = self.maximum.min(px(boundary.next_down()));
        }
        fits
    }

    /// Combine line/substring constraints; an empty intersection simply disables reuse.
    pub(super) fn intersect(&mut self, other: Self) {
        self.minimum = self.minimum.max(other.minimum);
        self.maximum = self.maximum.min(other.maximum);
    }

    /// NaN and threshold boundaries fail closed, allowing the original measurer to decide.
    pub(super) fn contains(self, width: Pixels) -> bool {
        width >= self.minimum && width < self.maximum
    }
}

/// The exact upstream break sequence plus the range over which its measured decisions hold.
pub(super) struct MeasuredWrap {
    /// Byte offsets and continuation indentation, unchanged from the original algorithm.
    pub(super) boundaries: Vec<Boundary>,
    /// Valid only for the same text, font, wrapping policy and inline geometry.
    pub(super) valid_widths: WidthRange,
}

impl MeasuredWrap {
    /// Preserve a result for which no measured reuse interval is available.
    pub(super) fn uncached(boundaries: Vec<Boundary>) -> Self {
        Self {
            boundaries,
            valid_widths: WidthRange::empty(),
        }
    }
}
