// @reference: https://d3js.org/d3-shape/radial-line

use std::f32::consts::PI;

use gpui::{
    Background, BorderStyle, Bounds, Hsla, PaintQuad, Path, PathBuilder, Pixels, Point, Window,
    point, px, quad, size,
};

const HALF_PI: f32 = PI / 2.;

/// A radial line generator, like `d3.lineRadial`.
///
/// Points are placed around the center of the plot bounds. The `angle`
/// accessor returns the angle in radians, with 0 at 12 o'clock and positive
/// angles proceeding clockwise. The `radius` accessor returns the distance
/// (in pixels) from the center.
///
/// Call [`RadialLine::closed`] to connect the last point back to the first
/// (like `d3.curveLinearClosed`), and [`RadialLine::fill`] to fill the
/// enclosed polygon, e.g. for radar charts.
///
/// Unlike [`Line`](super::Line), the accessors also receive the datum index,
/// matching d3's `(d, i)` accessor form, since radial charts typically derive
/// the angle from the index (e.g. `i * TAU / n`).
#[allow(clippy::type_complexity)]
pub struct RadialLine<T> {
    data: Vec<T>,
    angle: Box<dyn Fn(&T, usize) -> Option<f32>>,
    radius: Box<dyn Fn(&T, usize) -> Option<f32>>,
    closed: bool,
    fill: Option<Background>,
    stroke: Background,
    stroke_width: Pixels,
    dot: bool,
    dot_size: Pixels,
    dot_fill: Background,
    dot_stroke: Option<Hsla>,
}

impl<T> Default for RadialLine<T> {
    fn default() -> Self {
        Self {
            data: Vec::new(),
            angle: Box::new(|_, _| None),
            radius: Box::new(|_, _| None),
            closed: false,
            fill: None,
            stroke: Default::default(),
            stroke_width: px(1.),
            dot: false,
            dot_size: px(4.),
            dot_fill: gpui::transparent_black().into(),
            dot_stroke: None,
        }
    }
}

impl<T> RadialLine<T> {
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the data of the RadialLine.
    pub fn data<I>(mut self, data: I) -> Self
    where
        I: IntoIterator<Item = T>,
    {
        self.data = data.into_iter().collect();
        self
    }

    /// Set the angle accessor of the RadialLine.
    ///
    /// The accessor is called with the datum and its index, and returns the
    /// angle in radians, with 0 at 12 o'clock and positive angles proceeding
    /// clockwise.
    pub fn angle<F>(mut self, angle: F) -> Self
    where
        F: Fn(&T, usize) -> Option<f32> + 'static,
    {
        self.angle = Box::new(angle);
        self
    }

    /// Set the radius accessor of the RadialLine.
    ///
    /// The accessor is called with the datum and its index, and returns the
    /// distance (in pixels) from the center.
    pub fn radius<F>(mut self, radius: F) -> Self
    where
        F: Fn(&T, usize) -> Option<f32> + 'static,
    {
        self.radius = Box::new(radius);
        self
    }

    /// Connect the last point back to the first, like `d3.curveLinearClosed`.
    pub fn closed(mut self) -> Self {
        self.closed = true;
        self
    }

    /// Set the fill color of the polygon enclosed by the RadialLine.
    ///
    /// The fill path is always closed, regardless of [`RadialLine::closed`].
    pub fn fill(mut self, fill: impl Into<Background>) -> Self {
        self.fill = Some(fill.into());
        self
    }

    /// Set the stroke color of the RadialLine.
    pub fn stroke(mut self, stroke: impl Into<Background>) -> Self {
        self.stroke = stroke.into();
        self
    }

    /// Set the stroke width of the RadialLine.
    pub fn stroke_width(mut self, stroke_width: impl Into<Pixels>) -> Self {
        self.stroke_width = stroke_width.into();
        self
    }

    /// Draw a dot on every point.
    pub fn dot(mut self) -> Self {
        self.dot = true;
        self
    }

    /// Set the size of the dots on the RadialLine.
    pub fn dot_size(mut self, dot_size: impl Into<Pixels>) -> Self {
        self.dot_size = dot_size.into();
        self
    }

    /// Set the fill of the dots on the RadialLine.
    pub fn dot_fill(mut self, fill: impl Into<Background>) -> Self {
        self.dot_fill = fill.into();
        self
    }

    /// Set the 1px border color of the dots on the RadialLine. Defaults to the
    /// dot fill when it is a solid color.
    pub fn dot_stroke(mut self, stroke: impl Into<Hsla>) -> Self {
        self.dot_stroke = Some(stroke.into());
        self
    }

    #[deprecated(since = "0.7.0", note = "use `dot_fill`")]
    pub fn dot_fill_color(self, color: impl Into<Hsla>) -> Self {
        self.dot_fill(color.into())
    }

    #[deprecated(since = "0.7.0", note = "use `dot_stroke`")]
    pub fn dot_stroke_color(self, color: impl Into<Hsla>) -> Self {
        self.dot_stroke(color)
    }

    /// Paint a dot on the RadialLine.
    fn paint_dot(&self, dot: Point<Pixels>) -> PaintQuad {
        quad(
            gpui::bounds(dot, size(self.dot_size, self.dot_size)),
            self.dot_size / 2.,
            self.dot_fill,
            px(1.),
            self.dot_stroke
                .or_else(|| self.dot_fill.as_solid())
                .unwrap_or_default(),
            BorderStyle::default(),
        )
    }

    /// Resolve the data to points around the center of the bounds.
    fn points(&self, bounds: &Bounds<Pixels>) -> Vec<Point<Pixels>> {
        let center_x = bounds.origin.x.as_f32() + bounds.size.width.as_f32() / 2.;
        let center_y = bounds.origin.y.as_f32() + bounds.size.height.as_f32() / 2.;

        self.data
            .iter()
            .enumerate()
            .filter_map(|(i, v)| {
                let angle = (self.angle)(v, i)? - HALF_PI;
                let radius = (self.radius)(v, i)?;

                Some(point(
                    px(center_x + radius * angle.cos()),
                    px(center_y + radius * angle.sin()),
                ))
            })
            .collect()
    }

    fn path(
        &self,
        bounds: &Bounds<Pixels>,
    ) -> (Option<Path<Pixels>>, Option<Path<Pixels>>, Vec<PaintQuad>) {
        let points = self.points(bounds);
        let mut paint_dots = vec![];

        if self.dot {
            let dot_radius = self.dot_size / 2.;
            for p in &points {
                paint_dots.push(self.paint_dot(point(p.x - dot_radius, p.y - dot_radius)));
            }
        }

        if points.is_empty() {
            return (None, None, paint_dots);
        }

        let fill_path = self.fill.and_then(|_| {
            if points.len() < 3 {
                return None;
            }

            let mut builder = PathBuilder::fill();
            builder.add_polygon(&points, true);
            builder.build().ok()
        });

        let mut builder = PathBuilder::stroke(self.stroke_width);
        builder.move_to(points[0]);
        for p in &points[1..] {
            builder.line_to(*p);
        }
        if self.closed && points.len() > 2 {
            builder.close();
        }

        (fill_path, builder.build().ok(), paint_dots)
    }

    /// Paint the RadialLine.
    pub fn paint(&self, bounds: &Bounds<Pixels>, window: &mut Window) {
        let (fill_path, stroke_path, dots) = self.path(bounds);

        if let (Some(path), Some(fill)) = (fill_path, self.fill) {
            window.paint_path(path, fill);
        }
        if let Some(path) = stroke_path {
            window.paint_path(path, self.stroke);
        }
        for dot in dots {
            window.paint_quad(dot);
        }
    }
}

#[cfg(test)]
mod tests {
    use std::f32::consts::TAU;

    use super::*;

    use gpui::{Bounds, point, px};

    #[test]
    fn test_radial_line_points() {
        let data = vec![1., 1., 1., 1.];
        let line = RadialLine::new()
            .data(data)
            .angle(|_, i| Some(i as f32 * TAU / 4.))
            .radius(|v, _| Some(*v * 10.));

        let bounds = Bounds::new(point(px(0.), px(0.)), size(px(100.), px(100.)));
        let points = line.points(&bounds);

        // 4 points around the center (50, 50), at 12, 3, 6 and 9 o'clock.
        assert_eq!(points.len(), 4);
        let expected = [(50., 40.), (60., 50.), (50., 60.), (40., 50.)];
        for (p, (x, y)) in points.iter().zip(expected) {
            assert!((p.x.as_f32() - x).abs() < 1e-4);
            assert!((p.y.as_f32() - y).abs() < 1e-4);
        }
    }

    #[test]
    fn test_radial_line_path() {
        let data = vec![1., 2., 3.];
        let bounds = Bounds::new(point(px(0.), px(0.)), size(px(100.), px(100.)));

        let line = RadialLine::new()
            .data(data.clone())
            .angle(|_, i| Some(i as f32 * TAU / 3.))
            .radius(|v, _| Some(*v * 10.));

        let (fill_path, stroke_path, dots) = line.path(&bounds);
        assert!(fill_path.is_none());
        assert!(stroke_path.is_some());
        assert!(dots.is_empty());

        let line = RadialLine::new()
            .data(data)
            .angle(|_, i| Some(i as f32 * TAU / 3.))
            .radius(|v, _| Some(*v * 10.))
            .closed()
            .fill(gpui::black())
            .dot();

        let (fill_path, stroke_path, dots) = line.path(&bounds);
        assert!(fill_path.is_some());
        assert!(stroke_path.is_some());
        assert_eq!(dots.len(), 3);
    }
}
