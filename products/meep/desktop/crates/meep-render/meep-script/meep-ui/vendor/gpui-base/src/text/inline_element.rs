use gpui::{AnyElement, IntoElement, Pixels, TextStyle};

/// A GPUI element participating as one atomic object in a text line.
///
/// Use native GPUI styles, events and components on the element. TextView
/// measures its intrinsic size and wraps around the whole object. Fixed-width
/// elements keep their actual size; constrain them with GPUI styles as needed.
pub struct InlineElement {
    pub(crate) element: AnyElement,
    pub(crate) baseline: Option<Pixels>,
}

impl InlineElement {
    pub fn new(element: impl IntoElement) -> Self {
        Self {
            element: element.into_any_element(),
            baseline: None,
        }
    }

    /// Distance from the top edge to the alphabetic baseline, in logical pixels.
    /// By default the box aligns its bottom with the surrounding text's descent.
    pub fn with_baseline(mut self, baseline: Pixels) -> Self {
        self.baseline = Some(baseline);
        self
    }
}

/// Inherited typography for a format-independent inline renderer.
///
/// TextView builds this while laying a line out; renderers only read it.
#[derive(Clone)]
pub struct InlineRenderContext {
    text_style: TextStyle,
    font_size: Pixels,
    line_height: Pixels,
    rem_size: Pixels,
}

impl InlineRenderContext {
    pub(crate) fn new(
        text_style: TextStyle,
        font_size: Pixels,
        line_height: Pixels,
        rem_size: Pixels,
    ) -> Self {
        Self {
            text_style,
            font_size,
            line_height,
            rem_size,
        }
    }

    /// Effective text style at the object's position, marks already applied.
    pub fn text_style(&self) -> &TextStyle {
        &self.text_style
    }

    /// Font size of the surrounding text, in logical pixels.
    pub fn font_size(&self) -> Pixels {
        self.font_size
    }

    /// Line height of the surrounding text, in logical pixels.
    pub fn line_height(&self) -> Pixels {
        self.line_height
    }

    /// Root font size, for resolving rem-relative lengths.
    pub fn rem_size(&self) -> Pixels {
        self.rem_size
    }
}
