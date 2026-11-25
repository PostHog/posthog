use std::{hash::Hash, rc::Rc};

use gpui::{
    AnyElement, App, Background, Bounds, ElementId, Hsla, IntoElement, Pixels, Point, SharedString,
    Size, Window, point, px,
};
use gpui_component_macros::IntoPlot;

use crate::{
    ActiveTheme,
    plot::{
        AxisLabelPlacement, Curve, PathCaches, Plot, PlotAppear, PlotAxis,
        scale::{PlotValue, Scale, ScaleLinear, ScalePoint},
        shape::Area,
        tooltip::{CrossLine, Dot, Tooltip, TooltipState},
    },
};

use super::{
    AXIS_GAP, ChartAppear, HOVER_DOT_SIZE, HOVER_HALO_SIZE, PointAxes, TooltipContent, ValueExtent,
    axis_point_count, build_point_x_labels, caller_id, labeled_items, pinned_plot_mask,
    point_range, point_value_scale, reveal_mask,
};

#[derive(IntoPlot)]
pub struct AreaChart<T, X, Y>
where
    T: 'static,
    X: Clone + PartialEq + Into<SharedString> + 'static,
    Y: PlotValue,
{
    data: Vec<T>,
    x: Option<Rc<dyn Fn(&T) -> X>>,
    y: Vec<Rc<dyn Fn(&T) -> Y>>,
    strokes: Vec<Hsla>,
    curves: Vec<Curve>,
    fills: Vec<Background>,
    names: Vec<SharedString>,
    tooltip_content: TooltipContent<T>,
    tick_margin: usize,
    x_axis: bool,
    grid: bool,
    y_domain: Option<(Y, Y)>,
    point_count: Option<usize>,
    axes: PointAxes,
    id: ElementId,
    interactive: bool,
    appear: ChartAppear,
}

impl<T, X, Y> AreaChart<T, X, Y>
where
    X: Clone + PartialEq + Into<SharedString> + 'static,
    Y: PlotValue,
{
    #[track_caller]
    pub fn new<I>(data: I) -> Self
    where
        I: IntoIterator<Item = T>,
    {
        Self {
            data: data.into_iter().collect(),
            curves: vec![],
            strokes: vec![],
            fills: vec![],
            names: vec![],
            tooltip_content: TooltipContent::default(),
            tick_margin: 1,
            x: None,
            y: vec![],
            x_axis: true,
            grid: true,
            y_domain: None,
            point_count: None,
            axes: PointAxes::default(),
            id: caller_id(),
            interactive: true,
            appear: ChartAppear::default(),
        }
    }

    /// Name this chart's [`ElementId`], replacing the default taken from the
    /// construction site.
    ///
    /// Pass one where a single construction site renders several of these
    /// charts as siblings: they share the default id, and with it one hover
    /// state and one path cache. The id must be unique among those siblings.
    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = id.into();
        self
    }

    /// Turn this chart's interactive layer on or off. On by default.
    ///
    /// The layer is the hitbox under the cursor and what it drives: a crosshair
    /// and a dot per series mark the hovered point, and a tooltip shows a row
    /// each. Turn it off for a chart that only decorates, or one an element above
    /// it wants the cursor for: without a hitbox it neither answers the mouse nor
    /// takes the hover from what sits over it.
    pub fn interactive(mut self, interactive: bool) -> Self {
        self.interactive = interactive;
        self
    }

    /// Draw the data in the first time this chart is painted. On by default.
    ///
    /// The theme sets how long it takes, and the system's reduced-motion
    /// setting skips it. Turn it off for a chart that is painted again and
    /// again as it scrolls in and out of view, such as one in each row of a
    /// long list, where it would draw in every time.
    pub fn appear(mut self, appear: bool) -> Self {
        self.appear.set_enabled(appear);
        self
    }

    /// Draw the data in again whenever `key` changes, such as the symbol or
    /// period a chart shows.
    ///
    /// Without one the data draws in once, and later data paints in place.
    pub fn appear_key(mut self, key: impl Hash) -> Self {
        self.appear.set_key(key);
        self
    }

    /// Set the name of the most recently added series, shown in its tooltip row.
    ///
    /// Call after the matching [`AreaChart::y`] (e.g. `.y(..).stroke(..).name("Desktop")`).
    pub fn name(mut self, name: impl Into<SharedString>) -> Self {
        self.names.push(name.into());
        self
    }

    /// Set the hover tooltip's title for a datum, instead of its x value.
    pub fn tooltip_title(mut self, title: impl Fn(&T) -> SharedString + 'static) -> Self {
        self.tooltip_content.set_title(title);
        self
    }

    /// Set the text of each tooltip row's value; the raw number by default.
    ///
    /// The closure receives the datum, the row's index (the series' index in the order `y` added
    /// them) and the value the row reads.
    pub fn tooltip_value(
        mut self,
        value: impl Fn(&T, usize, f64) -> SharedString + 'static,
    ) -> Self {
        self.tooltip_content.set_value(value);
        self
    }

    /// Color each tooltip row's value, such as green or red by its sign; the
    /// tooltip's text color by default.
    ///
    /// The closure receives the same arguments as
    /// [`tooltip_value`](Self::tooltip_value).
    pub fn tooltip_value_color<H>(mut self, color: impl Fn(&T, usize, f64) -> H + 'static) -> Self
    where
        H: Into<Hsla>,
    {
        self.tooltip_content.set_value_color(color);
        self
    }

    /// Draw the tooltip box's content for a datum yourself, in place of the
    /// title and rows, for a layout they cannot express such as a table.
    ///
    /// The crosshair, the dots and where the box sits stay the chart's, and
    /// [`tooltip_title`](Self::tooltip_title), [`tooltip_value`](Self::tooltip_value)
    /// and [`tooltip_value_color`](Self::tooltip_value_color) no longer apply.
    pub fn tooltip_content<E>(
        mut self,
        content: impl Fn(&T, &mut Window, &mut App) -> E + 'static,
    ) -> Self
    where
        E: IntoElement,
    {
        self.tooltip_content.set_content(content);
        self
    }

    pub fn x(mut self, x: impl Fn(&T) -> X + 'static) -> Self {
        self.x = Some(Rc::new(x));
        self
    }

    pub fn y(mut self, y: impl Fn(&T) -> Y + 'static) -> Self {
        self.y.push(Rc::new(y));
        self
    }

    pub fn stroke(mut self, stroke: impl Into<Hsla>) -> Self {
        self.strokes.push(stroke.into());
        self
    }

    pub fn fill(mut self, fill: impl Into<Background>) -> Self {
        self.fills.push(fill.into());
        self
    }

    pub fn natural(mut self) -> Self {
        self.curves.push(Curve::Natural);
        self
    }

    pub fn linear(mut self) -> Self {
        self.curves.push(Curve::Linear);
        self
    }

    pub fn step_after(mut self) -> Self {
        self.curves.push(Curve::StepAfter);
        self
    }

    pub fn tick_margin(mut self, tick_margin: usize) -> Self {
        self.tick_margin = tick_margin;
        self
    }

    /// Show or hide the x-axis line and labels.
    ///
    /// Default is true.
    pub fn x_axis(mut self, x_axis: bool) -> Self {
        self.x_axis = x_axis;
        self
    }

    pub fn grid(mut self, grid: bool) -> Self {
        self.grid = grid;
        self
    }

    /// Pin the y axis to `min..=max` instead of fitting every series from zero.
    ///
    /// Pin it where zero is not a meaningful baseline, such as a price line
    /// that would otherwise be pressed flat against the top. The range keeps
    /// the `y_padding` headroom above `max`, 10px by default,
    /// and the series are clipped to the plot, so a value outside the range
    /// stops at its edge. Nothing is drawn when `min` equals `max`.
    pub fn y_domain(mut self, min: Y, max: Y) -> Self {
        self.y_domain = Some((min, max));
        self
    }

    /// Lay the x axis out for `count` evenly spaced points instead of the
    /// data's own length.
    ///
    /// The data takes the leading points in order, the i-th item on the i-th
    /// point, and the rest stay empty, as an intraday chart does before the
    /// close. The data has to be contiguous from the first point: a missing
    /// item shifts every later one a point to the left. A `count` below the
    /// data's length has no effect.
    pub fn point_count(mut self, count: usize) -> Self {
        self.point_count = Some(count);
        self
    }

    /// Show the y axis's tick labels, one at each of the `y_tick_count` ticks.
    ///
    /// Default is false.
    pub fn y_axis(mut self, y_axis: bool) -> Self {
        self.axes.y_axis = y_axis;
        self
    }

    /// Set where the y-axis tick labels sit: in a gutter left of the plot, or
    /// inside it beside their grid lines.
    ///
    /// Default is [`AxisLabelPlacement::Outside`].
    pub fn y_axis_label_placement(mut self, placement: AxisLabelPlacement) -> Self {
        self.axes.y_axis_label_placement = placement;
        self
    }

    /// Set how many ticks the y axis carries, evenly spaced from the baseline
    /// to the top edge with both ends included.
    ///
    /// The ticks place the horizontal grid lines and the tick labels, and each
    /// label reads the value the scale puts at its height. Values below 2 are
    /// raised to 2.
    ///
    /// Default is 5.
    pub fn y_tick_count(mut self, count: usize) -> Self {
        self.axes.y_tick_count = count.max(2);
        self
    }

    /// Set the text of each y-axis tick label from the value at its tick.
    pub fn y_tick_format<S>(mut self, format: impl Fn(f64) -> S + 'static) -> Self
    where
        S: Into<SharedString> + 'static,
    {
        self.axes.y_tick_format = Some(Rc::new(move |value| format(value).into()));
        self
    }

    /// Label `count` of the x values, spread evenly from the first to the
    /// last, instead of every `tick_margin`-th.
    ///
    /// With [`Self::point_count`] set, the labels spread over all the points the
    /// axis is laid out for, so they keep their places as the data grows; one
    /// that falls past the data is not drawn yet.
    pub fn x_tick_count(mut self, count: usize) -> Self {
        self.axes.x_tick_count = Some(count);
        self
    }

    /// Divide the plot into `count` columns with vertical grid lines, the first
    /// on its left edge.
    ///
    /// Default is 0, no vertical lines.
    pub fn grid_columns(mut self, count: usize) -> Self {
        self.axes.grid_columns = count;
        self
    }

    /// Draw the grid dashed or solid.
    ///
    /// Default is true.
    pub fn grid_dashed(mut self, dashed: bool) -> Self {
        self.axes.grid_dashed = dashed;
        self
    }

    /// Draw a dashed line across the plot at `value`, such as a previous close.
    ///
    /// Call again for more lines. A value outside the y axis is not drawn.
    pub fn reference_line(mut self, value: Y) -> Self {
        if let Some(value) = value.to_f64() {
            self.axes.reference_lines.push(value);
        }
        self
    }

    /// Set the space kept clear above the highest value and below the lowest,
    /// in pixels.
    ///
    /// Default is 10px above and none below.
    pub fn y_padding(mut self, top: f32, bottom: f32) -> Self {
        self.axes.y_padding = (top, bottom);
        self
    }

    /// Build the x (point) and y (linear) scales for the given bounds.
    ///
    /// Shared by `paint` and `tooltip_state` so the two stay in sync. Returns `None` when there
    /// is no x accessor or no series.
    fn scales(
        &self,
        bounds: Bounds<Pixels>,
    ) -> Option<(ScalePoint<X>, ScaleLinear<Y>, ValueExtent)> {
        let x_fn = self.x.as_ref()?;
        if self.y.is_empty() {
            return None;
        }

        let width = bounds.size.width.as_f32();
        let axis_gap = if self.x_axis { AXIS_GAP } else { 0. };
        let height = bounds.size.height.as_f32() - axis_gap;

        let len = self.data.len();
        let x = ScalePoint::new(
            self.data.iter().map(|v| x_fn(v)),
            point_range(
                self.axes.plot_left(),
                width - self.axes.plot_left(),
                len,
                axis_point_count(self.point_count, len),
            ),
        );
        let (y, extent) = point_value_scale(
            self.data
                .iter()
                .flat_map(|v| self.y.iter().map(|y_fn| y_fn(v))),
            self.y_domain,
            height,
            self.axes.y_padding,
        );

        Some((x, y, extent))
    }
}

impl<T, X, Y> Plot for AreaChart<T, X, Y>
where
    X: Clone + PartialEq + Into<SharedString> + 'static,
    Y: PlotValue,
{
    fn prepaint(
        &mut self,
        bounds: Bounds<Pixels>,
        window: &mut Window,
        _cx: &mut App,
    ) -> Vec<AnyElement> {
        // The y labels' gutter is measured before the x scale is laid out past it.
        if let Some((_, _, extent)) = self.scales(bounds) {
            let axis_gap = if self.x_axis { AXIS_GAP } else { 0. };
            let height = bounds.size.height.as_f32() - axis_gap;
            self.axes.measure_y_labels(extent, height, window);
        }
        vec![]
    }

    fn paint(&mut self, bounds: Bounds<Pixels>, window: &mut Window, cx: &mut App) {
        let Some(x_fn) = self.x.as_ref() else {
            return;
        };
        let Some((x, y, extent)) = self.scales(bounds) else {
            return;
        };

        let axis_gap = if self.x_axis { AXIS_GAP } else { 0. };
        let height = bounds.size.height.as_f32() - axis_gap;

        // Draw X axis
        // The axis runs under the plot only, clear of a value-axis gutter, so
        // its labels shift back by the gutter the x scale already includes.
        let left = self.axes.plot_left();
        let axis_bounds = Bounds {
            origin: bounds.origin + point(px(left), px(0.)),
            size: Size::new(bounds.size.width - px(left), bounds.size.height),
        };
        let mut axis = PlotAxis::new().stroke(cx.theme().border);
        if self.x_axis {
            let labeled = labeled_items(
                axis_point_count(self.point_count, self.data.len()),
                self.axes.x_tick_count,
                self.tick_margin,
            );
            let labels = build_point_x_labels(
                &self.data,
                x_fn.as_ref(),
                &x,
                axis_point_count(self.point_count, self.data.len()),
                &labeled,
                cx.theme().muted_foreground,
            )
            .into_iter()
            .map(|mut label| {
                label.tick -= px(left);
                label
            });
            axis = axis.x(height).x_label(labels);
        }
        axis.paint(&axis_bounds, window, cx);

        if self.grid {
            self.axes.paint_grid(bounds, height, window, cx);
        }

        // Draw area
        let default_fill: Background = cx.theme().chart_2.opacity(0.4).into();
        let default_stroke = cx.theme().chart_2;
        let areas = self.y.iter().enumerate().map(|(i, y_fn)| {
            let x = x.clone();
            let y = y.clone();
            let y_fn = y_fn.clone();

            let fill = *self.fills.get(i).unwrap_or(&default_fill);
            let stroke = *self.strokes.get(i).unwrap_or(&default_stroke);
            let curve = *self
                .curves
                .get(i)
                .unwrap_or(self.curves.first().unwrap_or(&Default::default()));

            Area::new()
                // One x domain entry per datum: project by index, not by lookup.
                .data(self.data.iter().enumerate())
                .x(move |(i, _)| x.tick_at(*i))
                .y0(height)
                .y1(move |(_, d)| y.tick(&y_fn(d)))
                .stroke(stroke)
                .curve(curve)
                .fill(fill)
        });

        let mask = self
            .y_domain
            .is_some()
            .then(|| pinned_plot_mask(bounds, height));
        // The areas draw in from the left under a mask, so their shapes, and
        // the cached paths, stay the same on every frame of the appear.
        let reveal = reveal_mask(bounds, left, self.appear.get().progress());
        window.with_content_mask(mask, |window| {
            window.with_content_mask(reveal, |window| {
                let caches = PathCaches::for_paint("areas", window, cx);
                caches.update(cx, |caches, _| {
                    for (i, area) in areas.enumerate() {
                        let (fill, line) = caches.slot_pair(i);
                        area.paint_cached(&bounds, fill, line, window);
                    }
                });
            });
        });

        self.axes
            .paint_reference_lines(extent, bounds, height, window, cx);
        self.axes.paint_y_labels(extent, bounds, height, window, cx);
    }

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }

    fn interactive(&self) -> bool {
        self.interactive
    }

    fn appear(&mut self, appear: PlotAppear, _window: &mut Window, _cx: &mut App) {
        self.appear.update(appear);
    }

    fn appear_generation(&self) -> Option<u64> {
        self.appear.generation()
    }

    fn tooltip_state(
        &self,
        position: Point<Pixels>,
        bounds: Bounds<Pixels>,
        _cx: &App,
    ) -> Option<TooltipState> {
        let (x, y, _) = self.scales(bounds)?;

        // Ignore the x-axis label gutter so hovering the labels doesn't show a tooltip.
        let axis_gap = if self.x_axis { AXIS_GAP } else { 0. };
        if position.y.as_f32() > bounds.size.height.as_f32() - axis_gap
            || position.x.as_f32() < self.axes.plot_left()
        {
            return None;
        }

        let index = x.nearest_index(position.x.as_f32());
        let d = self.data.get(index)?;
        let x_tick = x.tick_at(index)?;

        // One dot per series at the hovered x.
        let dots = self
            .y
            .iter()
            .filter_map(|y_fn| Some(point(px(x_tick), px(y.tick(&y_fn(d))?))))
            .collect();

        Some(TooltipState::new(
            index,
            point(px(x_tick), position.y),
            dots,
        ))
    }

    fn tooltip(
        &self,
        state: &TooltipState,
        cursor: Point<Pixels>,
        bounds: Bounds<Pixels>,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        let x_fn = self.x.as_ref()?;
        let d = self.data.get(state.index)?;

        let default_color = cx.theme().chart_2;
        let dot_stroke = cx.theme().background;
        let color = |i: usize| *self.strokes.get(i).unwrap_or(&default_color);

        // Follow the cursor; the crosshair and dots glide to the data point.
        let tooltip = Tooltip::new(cursor, bounds.size)
            .gap(px(8.))
            // Confine the crosshair to the plot area so it doesn't cross the x-axis.
            .cross_line(
                CrossLine::new(state.cross_line)
                    .height(bounds.size.height.as_f32() - if self.x_axis { AXIS_GAP } else { 0. }),
            )
            .dots(state.dots.iter().enumerate().map(|(i, p)| {
                Dot::new(*p)
                    .size(HOVER_DOT_SIZE)
                    .halo(HOVER_HALO_SIZE)
                    .stroke(dot_stroke)
                    .fill(color(i))
            }));

        let tooltip = self.tooltip_content.apply(
            tooltip,
            d,
            || Some(x_fn(d).into()),
            // One row per series: swatch + label + value.
            || {
                self.y
                    .iter()
                    .enumerate()
                    .map(|(i, y_fn)| {
                        let name = self.names.get(i).cloned().unwrap_or_default();
                        Some((color(i), name, y_fn(d).to_f64()?))
                    })
                    .collect::<Option<Vec<_>>>()
            },
            window,
            cx,
        )?;

        Some(tooltip.into_any_element())
    }
}

#[cfg(test)]
mod tests {
    use gpui::{Bounds, point, px, size};

    use super::AreaChart;
    use crate::plot::scale::Scale;

    fn bounds() -> Bounds<gpui::Pixels> {
        Bounds::new(point(px(0.), px(0.)), size(px(100.), px(50.)))
    }

    fn chart(data: Vec<f64>) -> AreaChart<(usize, f64), String, f64> {
        AreaChart::new(data.into_iter().enumerate())
            .x(|(i, _)| i.to_string())
            .y(|(_, v)| *v)
            .x_axis(false)
    }

    #[test]
    fn test_point_count_fills_the_leading_part() {
        let (x, _, _) = chart(vec![1., 2., 3.])
            .point_count(5)
            .scales(bounds())
            .unwrap();
        assert_eq!(x.tick(&"0".to_string()), Some(0.));
        assert_eq!(x.tick(&"2".to_string()), Some(50.));

        let (x, _, _) = chart(vec![1., 2., 3.])
            .point_count(2)
            .scales(bounds())
            .unwrap();
        assert_eq!(x.tick(&"2".to_string()), Some(100.));
    }

    #[test]
    fn test_y_domain_replaces_the_fit_from_zero() {
        let (_, y, _) = chart(vec![10., 20.])
            .y_domain(10., 20.)
            .scales(bounds())
            .unwrap();
        assert_eq!(y.tick(&10.), Some(50.));
        assert_eq!(y.tick(&20.), Some(10.));

        let (_, y, _) = chart(vec![10., 20.]).scales(bounds()).unwrap();
        assert_eq!(y.tick(&0.), Some(50.));
        assert_eq!(y.tick(&20.), Some(10.));
    }
}
