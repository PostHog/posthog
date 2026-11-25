use gpui::{
    App, Background, Bounds, FontWeight, Hsla, PathBuilder, Pixels, Point, SharedString, TextAlign,
    Window, point, px,
};

use super::{
    label::PlotLabel, label::TEXT_GAP, label::TEXT_HEIGHT, label::TEXT_SIZE, label::Text,
    origin_point,
};

/// The x-axis gutter for labels at the default [`TEXT_SIZE`].
#[deprecated(
    since = "0.7.0",
    note = "use `axis_gutter` with the label font size the chart draws"
)]
pub const AXIS_GAP: f32 = 18.;

/// The space below (or above) an x-axis line that tick labels of `font_size`
/// need: the gap [`PlotAxis`] leaves between the line and the labels, the
/// labels themselves, and a trailing gap.
///
/// A chart reserves this much of its height for the axis. With the default
/// [`TEXT_SIZE`] it is 18px; a styled layer drawing larger labels passes its
/// own size so the plot shrinks to fit them.
pub fn axis_gutter(font_size: Pixels) -> f32 {
    font_size.as_f32() + TEXT_GAP * 4.
}

/// Which side of an axis line the tick labels render on.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum AxisLabelSide {
    /// X-axis: labels below the line. Y-axis: labels right of the line. (Default.)
    #[default]
    End,
    /// X-axis: labels above the line. Y-axis: labels left of the line.
    Start,
}

/// Where a chart draws the tick labels of its value axis.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum AxisLabelPlacement {
    /// In a gutter beside the plot, which the plot shrinks to make room for. (Default.)
    #[default]
    Outside,
    /// Over the plot's edge, beside the grid line each label reads, so the plot
    /// keeps its full size.
    Inside,
}

/// A tick label on a [`PlotAxis`]: its text, where along the axis it sits and
/// how it is drawn. `font_size` defaults to [`TEXT_SIZE`].
#[non_exhaustive]
pub struct AxisText {
    pub text: SharedString,
    pub tick: Pixels,
    pub color: Hsla,
    pub font_size: Pixels,
    pub align: TextAlign,
}

impl AxisText {
    pub fn new(text: impl Into<SharedString>, tick: impl Into<Pixels>, color: Hsla) -> Self {
        Self {
            text: text.into(),
            tick: tick.into(),
            color,
            font_size: TEXT_SIZE.into(),
            align: TextAlign::Left,
        }
    }

    pub fn font_size(mut self, font_size: impl Into<Pixels>) -> Self {
        self.font_size = font_size.into();
        self
    }

    pub fn align(mut self, align: TextAlign) -> Self {
        self.align = align;
        self
    }
}

/// Axis lines and their tick labels.
///
/// The builders only record values: where the lines sit, which side their
/// labels take and the labels themselves are combined when the axis paints,
/// so they can be set in any order.
pub struct PlotAxis {
    x: Option<Pixels>,
    x_labels: Vec<AxisText>,
    x_axis: bool,
    x_label_side: AxisLabelSide,
    y: Option<Pixels>,
    y_labels: Vec<AxisText>,
    y_axis: bool,
    y_label_side: AxisLabelSide,
    stroke: Background,
}

impl Default for PlotAxis {
    fn default() -> Self {
        Self::new()
    }
}

impl PlotAxis {
    pub fn new() -> Self {
        Self {
            x: None,
            x_labels: Vec::new(),
            x_axis: true,
            x_label_side: AxisLabelSide::default(),
            y: None,
            y_labels: Vec::new(),
            y_axis: false,
            y_label_side: AxisLabelSide::default(),
            stroke: Hsla::default().into(),
        }
    }

    /// Place the x-axis line at `position` from the top of the plot. Without
    /// it the x-axis draws neither its line nor its labels.
    pub fn x(mut self, position: impl Into<Pixels>) -> Self {
        self.x = Some(position.into());
        self
    }

    /// Show or hide the x-axis line; its labels are drawn either way.
    ///
    /// Default is true.
    pub fn x_axis(mut self, x_axis: bool) -> Self {
        self.x_axis = x_axis;
        self
    }

    /// Set the tick labels of the x-axis.
    pub fn x_label(mut self, labels: impl IntoIterator<Item = AxisText>) -> Self {
        self.x_labels = labels.into_iter().collect();
        self
    }

    /// Set which side of the x-axis line tick labels render on.
    pub fn x_label_side(mut self, side: AxisLabelSide) -> Self {
        self.x_label_side = side;
        self
    }

    /// Place the y-axis line at `position` from the left of the plot. Without
    /// it the y-axis draws neither its line nor its labels.
    pub fn y(mut self, position: impl Into<Pixels>) -> Self {
        self.y = Some(position.into());
        self
    }

    /// Show or hide the y-axis line; its labels are drawn either way.
    ///
    /// Default is false.
    pub fn y_axis(mut self, y_axis: bool) -> Self {
        self.y_axis = y_axis;
        self
    }

    /// Set the tick labels of the y-axis.
    pub fn y_label(mut self, labels: impl IntoIterator<Item = AxisText>) -> Self {
        self.y_labels = labels.into_iter().collect();
        self
    }

    /// Set which side of the y-axis line tick labels render on.
    pub fn y_label_side(mut self, side: AxisLabelSide) -> Self {
        self.y_label_side = side;
        self
    }

    /// Set the stroke of the axis lines.
    pub fn stroke(mut self, stroke: impl Into<Background>) -> Self {
        self.stroke = stroke.into();
        self
    }

    /// The x-axis labels placed against the line at `x`.
    fn x_texts(&self, x: Pixels) -> Vec<Text> {
        self.x_labels
            .iter()
            .map(|t| {
                let y = match self.x_label_side {
                    AxisLabelSide::End => x + px(TEXT_GAP * 3.),
                    AxisLabelSide::Start => x - px(TEXT_GAP + TEXT_HEIGHT),
                };
                axis_text(t, point(t.tick, y))
            })
            .collect()
    }

    /// The y-axis labels placed against the line at `y`.
    fn y_texts(&self, y: Pixels) -> Vec<Text> {
        self.y_labels
            .iter()
            .map(|t| {
                let x = match self.y_label_side {
                    AxisLabelSide::End => y + px(TEXT_GAP),
                    AxisLabelSide::Start => y - px(TEXT_GAP),
                };
                axis_text(t, point(x, t.tick - px(TEXT_SIZE / 2.)))
            })
            .collect()
    }

    fn draw_axis(&self, start_point: Point<Pixels>, end_point: Point<Pixels>, window: &mut Window) {
        let mut builder = PathBuilder::stroke(px(1.));
        builder.move_to(start_point);
        builder.line_to(end_point);
        if let Ok(path) = builder.build() {
            window.paint_path(path, self.stroke);
        }
    }

    /// Paint the Axis.
    pub fn paint(&self, bounds: &Bounds<Pixels>, window: &mut Window, cx: &mut App) {
        let origin = bounds.origin;

        if let Some(x) = self.x {
            if self.x_axis {
                self.draw_axis(
                    origin_point(px(0.), x, origin),
                    origin_point(bounds.size.width, x, origin),
                    window,
                );
            }
            PlotLabel::new(self.x_texts(x)).paint(bounds, window, cx);
        }

        if let Some(y) = self.y {
            if self.y_axis {
                self.draw_axis(
                    origin_point(y, px(0.), origin),
                    origin_point(y, bounds.size.height, origin),
                    window,
                );
            }
            PlotLabel::new(self.y_texts(y)).paint(bounds, window, cx);
        }
    }
}

/// `label` as the text [`PlotLabel`] draws at `origin`.
fn axis_text(label: &AxisText, origin: Point<Pixels>) -> Text {
    Text::new(label.text.clone(), origin, label.color)
        .font_size(label.font_size)
        .font_weight(FontWeight::NORMAL)
        .align(label.align)
}

#[cfg(test)]
mod tests {
    use gpui::{Hsla, px};

    use super::*;

    fn labels() -> Vec<AxisText> {
        vec![
            AxisText::new("a", px(10.), Hsla::default()),
            AxisText::new("b", px(20.), Hsla::default()).align(TextAlign::Right),
        ]
    }

    fn origins(texts: Vec<Text>) -> Vec<(SharedString, Point<Pixels>)> {
        texts.into_iter().map(|t| (t.text, t.origin)).collect()
    }

    #[test]
    fn builder_order_does_not_move_labels() {
        let labels_first = PlotAxis::new()
            .x_label(labels())
            .x(px(50.))
            .x_label_side(AxisLabelSide::Start)
            .y_label(labels())
            .y(px(30.))
            .y_label_side(AxisLabelSide::Start);
        let labels_last = PlotAxis::new()
            .x_label_side(AxisLabelSide::Start)
            .x(px(50.))
            .x_label(labels())
            .y_label_side(AxisLabelSide::Start)
            .y(px(30.))
            .y_label(labels());

        assert_eq!(
            origins(labels_first.x_texts(px(50.))),
            origins(labels_last.x_texts(px(50.)))
        );
        assert_eq!(
            origins(labels_first.y_texts(px(30.))),
            origins(labels_last.y_texts(px(30.)))
        );
        // The side set after the labels still applies to them.
        assert_eq!(
            labels_first.x_texts(px(50.))[0].origin.y,
            px(50. - TEXT_GAP - TEXT_HEIGHT)
        );
    }

    #[test]
    fn axis_gutter_fits_default_labels() {
        assert_eq!(axis_gutter(px(TEXT_SIZE)), 18.);
    }
}
