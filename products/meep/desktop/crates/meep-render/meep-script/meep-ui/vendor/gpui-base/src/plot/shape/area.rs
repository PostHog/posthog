// @reference: https://d3js.org/d3-shape/area

use gpui::{Background, Bounds, Path, PathBuilder, Pixels, Point, Window, px};

use crate::plot::{Curve, PathCache, ShapeKey, origin_point};

#[allow(clippy::type_complexity)]
pub struct Area<T> {
    data: Vec<T>,
    x: Box<dyn Fn(&T) -> Option<f32>>,
    y0: Option<f32>,
    y1: Box<dyn Fn(&T) -> Option<f32>>,
    fill: Background,
    stroke: Background,
    curve: Curve,
}

impl<T> Default for Area<T> {
    fn default() -> Self {
        Self {
            data: Vec::new(),
            x: Box::new(|_| None),
            y0: None,
            y1: Box::new(|_| None),
            fill: Default::default(),
            stroke: Default::default(),
            curve: Curve::default(),
        }
    }
}

impl<T> Area<T> {
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the data of the Area.
    pub fn data<I>(mut self, data: I) -> Self
    where
        I: IntoIterator<Item = T>,
    {
        self.data = data.into_iter().collect();
        self
    }

    /// Set the x of the Area.
    pub fn x<F>(mut self, x: F) -> Self
    where
        F: Fn(&T) -> Option<f32> + 'static,
    {
        self.x = Box::new(x);
        self
    }

    /// Set the y0 of the Area.
    pub fn y0(mut self, y0: f32) -> Self {
        self.y0 = Some(y0);
        self
    }

    /// Set the y1 of the Area.
    pub fn y1<F>(mut self, y1: F) -> Self
    where
        F: Fn(&T) -> Option<f32> + 'static,
    {
        self.y1 = Box::new(y1);
        self
    }

    /// Set the fill color of the Area.
    pub fn fill(mut self, fill: impl Into<Background>) -> Self {
        self.fill = fill.into();
        self
    }

    /// Set the stroke color of the Area.
    pub fn stroke(mut self, stroke: impl Into<Background>) -> Self {
        self.stroke = stroke.into();
        self
    }

    /// Set how the Area's top line connects its points. Defaults to
    /// [`Curve::Natural`].
    pub fn curve(mut self, curve: Curve) -> Self {
        self.curve = curve;
        self
    }

    fn path(&self, bounds: &Bounds<Pixels>) -> (Option<Path<Pixels>>, Option<Path<Pixels>>) {
        let origin = bounds.origin;
        let mut area_builder = PathBuilder::fill();
        let mut line_builder = PathBuilder::stroke(px(1.));

        let mut points = vec![];

        let mut first_x_tick = None;
        let mut last_x_tick = None;
        for (index, v) in self.data.iter().enumerate() {
            if index == 0 {
                first_x_tick = (self.x)(v);
            }
            if index == self.data.len() - 1 {
                last_x_tick = (self.x)(v);
            }
            let x_tick = (self.x)(v);
            let y_tick = (self.y1)(v);

            if let (Some(x), Some(y)) = (x_tick, y_tick) {
                let pos = origin_point(px(x), px(y), origin);

                points.push(pos);
            }
        }

        if points.is_empty() {
            return (None, None);
        }

        if points.len() == 1 {
            area_builder.move_to(points[0]);
            line_builder.move_to(points[0]);
            return (area_builder.build().ok(), line_builder.build().ok());
        }

        match self.curve {
            Curve::Natural => {
                area_builder.move_to(points[0]);
                line_builder.move_to(points[0]);
                let n = points.len();
                for i in 0..n - 1 {
                    let p0 = if i == 0 { points[0] } else { points[i - 1] };
                    let p1 = points[i];
                    let p2 = points[i + 1];
                    let p3 = if i + 2 < n {
                        points[i + 2]
                    } else {
                        points[n - 1]
                    };

                    // Catmull-Rom to Bezier
                    let c1 = Point::new(p1.x + (p2.x - p0.x) / 6.0, p1.y + (p2.y - p0.y) / 6.0);
                    let c2 = Point::new(p2.x - (p3.x - p1.x) / 6.0, p2.y - (p3.y - p1.y) / 6.0);

                    area_builder.cubic_bezier_to(p2, c1, c2);
                    line_builder.cubic_bezier_to(p2, c1, c2);
                }
            }
            Curve::Linear => {
                area_builder.move_to(points[0]);
                line_builder.move_to(points[0]);
                for p in &points[1..] {
                    area_builder.line_to(*p);
                    line_builder.line_to(*p);
                }
            }
            Curve::StepAfter => {
                area_builder.move_to(points[0]);
                line_builder.move_to(points[0]);
                for (i, p) in points.windows(2).enumerate() {
                    area_builder.line_to(Point::new(p[1].x, p[0].y));
                    line_builder.line_to(Point::new(p[1].x, p[0].y));
                    // Don't draw the vertical line for the last point
                    if i < points.len() - 2 {
                        area_builder.line_to(p[1]);
                        line_builder.line_to(p[1]);
                    }
                }
            }
        }

        // Close path
        if let (Some(first), Some(last), Some(y)) = (first_x_tick, last_x_tick, self.y0) {
            area_builder.line_to(origin_point(px(last), px(y), bounds.origin));
            area_builder.line_to(origin_point(px(first), px(y), bounds.origin));
            area_builder.close();
        }

        (area_builder.build().ok(), line_builder.build().ok())
    }

    /// Paint the Area, reusing the fill and stroke tessellated by an earlier
    /// paint while the projected points, baseline and curve style are
    /// unchanged. `fill` and `line` are the two caches this area keeps
    /// together; see [`Line::paint_cached`](super::Line::paint_cached).
    pub fn paint_cached(
        &self,
        bounds: &Bounds<Pixels>,
        fill: &mut PathCache,
        line: &mut PathCache,
        window: &mut Window,
    ) {
        let mut key = ShapeKey::new((self.curve, self.y0.map(f32::to_bits)));
        for v in self.data.iter() {
            if let (Some(x), Some(y)) = ((self.x)(v), (self.y1)(v)) {
                key.f32(x).f32(y);
            }
        }
        let key = key.finish();
        let local = Bounds::new(Point::default(), bounds.size);
        // One miss builds both paths; the second cache takes the stroke from
        // the stash instead of building again.
        let mut stroke_path = None;
        let fill_path = fill.get(key, bounds.origin, || {
            let (area, stroke) = self.path(&local);
            stroke_path = Some(stroke);
            area
        });
        let line_path = line.get(key, bounds.origin, || {
            stroke_path.take().unwrap_or_else(|| self.path(&local).1)
        });
        if let Some(area) = fill_path {
            window.paint_path(area, self.fill);
        }
        if let Some(line) = line_path {
            window.paint_path(line, self.stroke);
        }
    }

    /// Paint the Area.
    pub fn paint(&self, bounds: &Bounds<Pixels>, window: &mut Window) {
        let (area, line) = self.path(bounds);

        if let Some(area) = area {
            window.paint_path(area, self.fill);
        }
        if let Some(line) = line {
            window.paint_path(line, self.stroke);
        }
    }
}
