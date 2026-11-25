use std::fmt::Debug;

use gpui::{
    App, Bounds, FontWeight, Hsla, Pixels, Point, ShapedLine, SharedString, TextAlign, TextRun,
    Window, point, px,
};

use super::origin_point;

/// The default label font size, in pixels, of [`Text`] and
/// [`AxisText`](super::AxisText).
///
/// A default, not a rule: a styled layer passes its own size through
/// `font_size`, and reserves axis space with [`axis_gutter`](super::axis_gutter)
/// for that size.
pub const TEXT_SIZE: f32 = 10.;
/// The default gap, in pixels, between a label and what it labels.
pub const TEXT_GAP: f32 = 2.;
/// The default height, in pixels, a label line takes: [`TEXT_SIZE`] plus
/// [`TEXT_GAP`].
pub const TEXT_HEIGHT: f32 = TEXT_SIZE + TEXT_GAP;

fn shape_label(
    text: &SharedString,
    font_size: Pixels,
    color: Hsla,
    window: &mut Window,
) -> ShapedLine {
    let text_run = TextRun {
        len: text.len(),
        font: window.text_style().font(),
        color,
        background_color: None,
        underline: None,
        strikethrough: None,
    };
    window
        .text_system()
        .shape_line(text.clone(), font_size, &[text_run], None)
}

/// Returns the rendered width of `text` at `font_size` using the window's
/// current text style.  Used for layout calculations that need to reserve
/// space for labels before the scale ranges are fixed.
pub fn measure_text_width(text: &SharedString, font_size: Pixels, window: &mut Window) -> f32 {
    if text.is_empty() {
        return 0.;
    }
    shape_label(
        text,
        font_size,
        Hsla {
            h: 0.,
            s: 0.,
            l: 0.,
            a: 1.,
        },
        window,
    )
    .width()
    .as_f32()
}

/// Truncate `text` with a trailing ellipsis so it fits within `max_width` at
/// `font_size`. Returns `text` unchanged when it already fits; returns just
/// the ellipsis when not even one character fits. `max_width <= 0` is treated
/// as "no budget" and returns `text` unchanged (the caller has no room to
/// reason about).
pub fn truncate_text_to_width(
    text: &SharedString,
    font_size: Pixels,
    max_width: f32,
    window: &mut Window,
) -> SharedString {
    if max_width <= 0. || measure_text_width(text, font_size, window) <= max_width {
        return text.clone();
    }

    const ELLIPSIS: &str = "…";
    // Byte offsets of every char boundary after the first char; cutting at
    // `cuts[k]` keeps the first `k + 1` chars.
    let cuts: Vec<usize> = text.char_indices().skip(1).map(|(i, _)| i).collect();

    // Binary search the largest prefix whose text + ellipsis still fits.
    let mut best: Option<usize> = None;
    let (mut lo, mut hi) = (0usize, cuts.len());
    while lo < hi {
        let mid = (lo + hi) / 2;
        let candidate = SharedString::from(format!("{}{ELLIPSIS}", &text[..cuts[mid]]));
        if measure_text_width(&candidate, font_size, window) <= max_width {
            best = Some(mid);
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }

    match best {
        Some(mid) => SharedString::from(format!("{}{ELLIPSIS}", &text[..cuts[mid]])),
        None => SharedString::from(ELLIPSIS),
    }
}

/// A label [`PlotLabel`] draws: its text, where it sits relative to the plot
/// origin and how it is drawn. `font_size` defaults to [`TEXT_SIZE`].
#[non_exhaustive]
pub struct Text {
    pub text: SharedString,
    pub origin: Point<Pixels>,
    pub color: Hsla,
    pub font_size: Pixels,
    pub font_weight: FontWeight,
    pub align: TextAlign,
}

impl Text {
    pub fn new<T>(text: impl Into<SharedString>, origin: Point<T>, color: Hsla) -> Self
    where
        T: Default + Clone + Copy + Debug + PartialEq + Into<Pixels>,
    {
        let origin = point(origin.x.into(), origin.y.into());

        Self {
            text: text.into(),
            origin,
            color,
            font_size: TEXT_SIZE.into(),
            font_weight: FontWeight::NORMAL,
            align: TextAlign::Left,
        }
    }

    /// Set the font size of the Text.
    pub fn font_size(mut self, font_size: impl Into<Pixels>) -> Self {
        self.font_size = font_size.into();
        self
    }

    /// Set the font weight of the Text.
    pub fn font_weight(mut self, font_weight: FontWeight) -> Self {
        self.font_weight = font_weight;
        self
    }

    /// Set the alignment of the Text.
    pub fn align(mut self, align: TextAlign) -> Self {
        self.align = align;
        self
    }
}

impl<I> From<I> for PlotLabel
where
    I: Iterator<Item = Text>,
{
    fn from(items: I) -> Self {
        Self::new(items.collect())
    }
}

#[derive(Default)]
pub struct PlotLabel(Vec<Text>);

impl PlotLabel {
    pub fn new(items: Vec<Text>) -> Self {
        Self(items)
    }

    /// Paint the Label.
    pub fn paint(&self, bounds: &Bounds<Pixels>, window: &mut Window, cx: &mut App) {
        for Text {
            text,
            origin,
            color,
            font_size,
            font_weight: _,
            align,
        } in self.0.iter()
        {
            let origin = origin_point(origin.x, origin.y, bounds.origin);

            let line = shape_label(text, *font_size, *color, window);
            let origin = match align {
                TextAlign::Left => origin,
                TextAlign::Right => origin - point(line.width(), px(0.)),
                _ => origin - point(line.width() / 2., px(0.)),
            };
            let _ = line.paint(origin, *font_size, *align, None, window, cx);
        }
    }
}
