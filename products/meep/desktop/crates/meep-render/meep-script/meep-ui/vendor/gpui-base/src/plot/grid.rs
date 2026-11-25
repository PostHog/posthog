use gpui::{Background, Bounds, Pixels, Point, Window, fill, point, px, size};

use super::origin_point;

/// Axis-aligned grid lines across a plot, at the given x and y positions.
#[derive(Default)]
pub struct Grid {
    x: Vec<Pixels>,
    y: Vec<Pixels>,
    stroke: Background,
    dash_array: Option<Vec<Pixels>>,
}

impl Grid {
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the positions of the vertical lines, from the left of the plot.
    pub fn x(mut self, x: impl IntoIterator<Item = impl Into<Pixels>>) -> Self {
        self.x = x.into_iter().map(Into::into).collect();
        self
    }

    /// Set the positions of the horizontal lines, from the top of the plot.
    pub fn y(mut self, y: impl IntoIterator<Item = impl Into<Pixels>>) -> Self {
        self.y = y.into_iter().map(Into::into).collect();
        self
    }

    /// Set the stroke of the grid lines.
    pub fn stroke(mut self, stroke: impl Into<Background>) -> Self {
        self.stroke = stroke.into();
        self
    }

    /// Set the dash array of the grid lines.
    pub fn dash_array(mut self, dash_array: &[Pixels]) -> Self {
        self.dash_array = Some(dash_array.to_vec());
        self
    }

    fn points(&self, bounds: &Bounds<Pixels>) -> Vec<(Point<Pixels>, Point<Pixels>)> {
        let size = bounds.size;
        let origin = bounds.origin;

        let mut x = self
            .x
            .iter()
            .map(|x| {
                (
                    origin_point(*x, px(0.), origin),
                    origin_point(*x, size.height, origin),
                )
            })
            .collect::<Vec<_>>();

        let y = self
            .y
            .iter()
            .map(|y| {
                (
                    origin_point(px(0.), *y, origin),
                    origin_point(size.width, *y, origin),
                )
            })
            .collect::<Vec<_>>();

        x.extend(y);
        x
    }

    /// Paint the Grid.
    ///
    /// Grid lines are axis-aligned, so each one (or each dash of one) is a
    /// 1px quad rather than a stroked path: a chart repaints its grid on
    /// every frame while it scrolls, and tessellating each line — measuring
    /// and sampling it first when dashed — was the largest cost of painting a
    /// chart card.
    pub fn paint(&self, bounds: &Bounds<Pixels>, window: &mut Window) {
        for (start, end) in self.points(bounds) {
            for (start, end) in dash_segments(start, end, self.dash_array.as_deref()) {
                window.paint_quad(fill(line_bounds(start, end), self.stroke));
            }
        }
    }
}

/// The box a 1px stroke of the axis-aligned line `start`–`end` covers:
/// centred on the coordinate, as `PathBuilder::stroke(px(1.))` draws it.
fn line_bounds(start: Point<Pixels>, end: Point<Pixels>) -> Bounds<Pixels> {
    let half = px(0.5);
    if start.x == end.x {
        let top = start.y.min(end.y);
        Bounds::new(
            point(start.x - half, top),
            size(px(1.), start.y.max(end.y) - top),
        )
    } else {
        let left = start.x.min(end.x);
        Bounds::new(
            point(left, start.y - half),
            size(start.x.max(end.x) - left, px(1.)),
        )
    }
}

/// Splits the line `start`–`end` into the dashes of `dash_array`, walked from
/// `start` with the SVG `stroke-dasharray` rules `PathBuilder` follows: values
/// alternate dash and gap, and an odd-length array repeats to an even one.
/// Without a dash array the whole line is one segment.
fn dash_segments(
    start: Point<Pixels>,
    end: Point<Pixels>,
    dash_array: Option<&[Pixels]>,
) -> Vec<(Point<Pixels>, Point<Pixels>)> {
    let Some(dash_array) = dash_array.filter(|dashes| !dashes.is_empty()) else {
        return vec![(start, end)];
    };
    let length = ((end.x - start.x).as_f32().powi(2) + (end.y - start.y).as_f32().powi(2)).sqrt();
    if length <= 0. || dash_array.iter().all(|dash| dash.as_f32() <= 0.) {
        return vec![(start, end)];
    }
    let at = |distance: f32| {
        let t = distance / length;
        point(
            start.x + (end.x - start.x) * t,
            start.y + (end.y - start.y) * t,
        )
    };
    let pattern_len = if dash_array.len() % 2 == 1 {
        dash_array.len() * 2
    } else {
        dash_array.len()
    };
    let mut segments = Vec::new();
    let mut position = 0.;
    let mut index = 0;
    while position < length {
        let dash = dash_array[index % dash_array.len()].as_f32().max(0.);
        let next = (position + dash).min(length);
        if index % 2 == 0 && next > position {
            segments.push((at(position), at(next)));
        }
        position = next;
        index = (index + 1) % pattern_len;
    }
    segments
}

#[cfg(test)]
mod tests {
    use super::*;

    fn xs(segments: &[(Point<Pixels>, Point<Pixels>)]) -> Vec<(f32, f32)> {
        segments
            .iter()
            .map(|(start, end)| (start.x.as_f32(), end.x.as_f32()))
            .collect()
    }

    #[test]
    fn solid_line_is_one_segment() {
        let segments = dash_segments(point(px(0.), px(5.)), point(px(10.), px(5.)), None);
        assert_eq!(xs(&segments), vec![(0., 10.)]);
        let segments = dash_segments(point(px(0.), px(5.)), point(px(10.), px(5.)), Some(&[]));
        assert_eq!(xs(&segments), vec![(0., 10.)]);
    }

    #[test]
    fn dashes_alternate_and_clip_at_the_end() {
        let segments = dash_segments(
            point(px(0.), px(5.)),
            point(px(11.), px(5.)),
            Some(&[px(4.), px(2.)]),
        );
        assert_eq!(xs(&segments), vec![(0., 4.), (6., 10.)]);
    }

    #[test]
    fn odd_dash_array_repeats_like_svg() {
        // 5,3,2 is 5 on, 3 off, 2 on, 5 off, 3 on, 2 off.
        let segments = dash_segments(
            point(px(0.), px(0.)),
            point(px(0.), px(20.)),
            Some(&[px(5.), px(3.), px(2.)]),
        );
        let ys: Vec<_> = segments
            .iter()
            .map(|(start, end)| (start.y.as_f32(), end.y.as_f32()))
            .collect();
        assert_eq!(ys, vec![(0., 5.), (8., 10.), (15., 18.)]);
    }

    #[test]
    fn line_box_is_one_pixel_centred_on_the_coordinate() {
        let vertical = line_bounds(point(px(10.), px(0.)), point(px(10.), px(40.)));
        assert_eq!(vertical.origin, point(px(9.5), px(0.)));
        assert_eq!(vertical.size, size(px(1.), px(40.)));
        let horizontal = line_bounds(point(px(40.), px(7.)), point(px(0.), px(7.)));
        assert_eq!(horizontal.origin, point(px(0.), px(6.5)));
        assert_eq!(horizontal.size, size(px(40.), px(1.)));
    }
}
