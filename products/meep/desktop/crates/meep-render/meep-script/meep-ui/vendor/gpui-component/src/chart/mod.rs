mod area_chart;
mod bar_chart;
mod candlestick_chart;
mod line_chart;
mod pie_chart;
mod radar_chart;
mod sankey_chart;

pub use area_chart::AreaChart;
pub use bar_chart::BarChart;
pub use candlestick_chart::CandlestickChart;
pub use line_chart::LineChart;
pub use pie_chart::PieChart;
pub use radar_chart::{RadarChart, RadarLabel};
pub use sankey_chart::{SankeyChart, SankeyLabel};

use std::{
    hash::{DefaultHasher, Hash, Hasher},
    panic::Location,
    rc::Rc,
};

use gpui::{
    AnyElement, App, Bounds, ContentMask, ElementId, Hsla, IntoElement, ParentElement as _, Pixels,
    SharedString, Size, TextAlign, Window, point, px,
};

use crate::{
    ActiveTheme,
    plot::{
        AxisLabelPlacement, AxisText, Grid, PlotAppear, PlotLabel,
        label::{TEXT_GAP, TEXT_HEIGHT, TEXT_SIZE, Text, measure_text_width},
        scale::{PlotValue, Scale, ScaleBand, ScaleLinear, ScalePoint},
        tooltip::Tooltip,
    },
};

/// The [`ElementId`] a chart carries when the caller names none: the source
/// location it was constructed at.
///
/// The crosshair, the hover lift, the tooltip and the path cache all need an id
/// unique among siblings, and a chart that has to be handed one per call site is
/// a chart every caller leaves static. One construction site written out once,
/// which is nearly every chart, is unique by construction.
///
/// The exception is one site rendering several charts as siblings, where every
/// copy shares this location and therefore one hover state and one path cache.
/// A `GlobalElementId` is the whole id stack, so rows that carry their own id —
/// which `List` and `uniform_list` give them — already separate the copies
/// underneath them; only id-less siblings collide, and those name an id with
/// `id`. GPUI takes this same trade-off for [`gpui::Window::use_state`].
#[track_caller]
pub(crate) fn caller_id() -> ElementId {
    ElementId::CodeLocation(*Location::caller())
}

/// A chart's appear: whether its data draws in the first time it is painted,
/// the key that replays it, and how far it has drawn in this frame.
pub(crate) struct ChartAppear {
    enabled: bool,
    generation: u64,
    current: PlotAppear,
}

impl Default for ChartAppear {
    fn default() -> Self {
        Self {
            enabled: true,
            generation: 0,
            current: PlotAppear::complete(),
        }
    }
}

impl ChartAppear {
    pub(crate) fn set_enabled(&mut self, enabled: bool) {
        self.enabled = enabled;
    }

    pub(crate) fn set_key(&mut self, key: impl Hash) {
        let mut hasher = DefaultHasher::new();
        key.hash(&mut hasher);
        self.generation = hasher.finish();
    }

    /// The generation a chart hands [`Plot::appear_generation`], or `None`
    /// when it opted out, so no appear is tracked and no frames are asked for.
    ///
    /// [`Plot::appear_generation`]: crate::plot::Plot::appear_generation
    pub(crate) fn generation(&self) -> Option<u64> {
        self.enabled.then_some(self.generation)
    }

    pub(crate) fn update(&mut self, appear: PlotAppear) {
        self.current = appear;
    }

    pub(crate) fn get(&self) -> &PlotAppear {
        &self.current
    }
}

/// The mask a chart that draws in from the left paints its series under while
/// it appears: everything left of `progress` of the way across the plot, which
/// starts `left` into `bounds`. It bleeds by half a hover dot, so a dot on the
/// plot's first point shows whole as soon as the reveal passes it, and there
/// is no mask once the appear is done.
pub(crate) fn reveal_mask(
    bounds: Bounds<Pixels>,
    left: f32,
    progress: f32,
) -> Option<ContentMask<Pixels>> {
    if progress >= 1. {
        return None;
    }
    let bleed = HOVER_DOT_SIZE / 2.;
    let start = bounds.left() + px(left) - bleed;
    let end = start + (bounds.right() + bleed - start) * progress.max(0.);
    Some(ContentMask {
        bounds: Bounds::from_corners(
            gpui::point(bounds.left() - bleed, bounds.top() - bleed),
            gpui::point(end, bounds.bottom() + bleed),
        ),
    })
}

/// The size of the dot marking the hovered data point.
pub(crate) const HOVER_DOT_SIZE: Pixels = px(8.);

/// The ring behind the hovered dot at full focus; a [`Tooltip`] grows it out
/// of the dot as the hover fades in.
///
/// [`Tooltip`]: crate::plot::tooltip::Tooltip
pub(crate) const HOVER_HALO_SIZE: Pixels = px(20.);

/// How many points the x axis of a point chart (`LineChart`, `AreaChart`) is
/// laid out for: `point_count`, or the data's own length when that is unset or
/// smaller.
pub(crate) fn axis_point_count(point_count: Option<usize>, data_len: usize) -> usize {
    point_count.unwrap_or(data_len).max(data_len)
}

/// The x range a point scale spreads `data_len` points over, when the axis is
/// laid out for `point_count` of them across `width` pixels from `start`.
///
/// The data takes the leading points, so each keeps its place as the data grows.
pub(crate) fn point_range(start: f32, width: f32, data_len: usize, point_count: usize) -> [f32; 2] {
    let end = if point_count > 1 {
        width * data_len.saturating_sub(1) as f32 / (point_count - 1) as f32
    } else {
        width
    };
    [start, start + end]
}

/// The value range a y scale spans and the pixel range it maps onto, kept in
/// `f64` so tick labels can read the value at any height of the plot.
#[derive(Clone, Copy)]
pub(crate) struct ValueExtent {
    lo: f64,
    hi: f64,
    bottom: f32,
    top: f32,
}

impl ValueExtent {
    /// The value the scale puts at pixel `y`.
    pub(crate) fn value_at(&self, y: f32) -> f64 {
        if self.bottom == self.top {
            return self.lo;
        }
        self.lo + (self.hi - self.lo) * ((self.bottom - y) / (self.bottom - self.top)) as f64
    }

    /// The pixel the scale puts `value` at, or `None` for a scale with no extent.
    pub(crate) fn position_of(&self, value: f64) -> Option<f32> {
        if self.hi == self.lo {
            return None;
        }
        Some(
            self.bottom
                - ((value - self.lo) / (self.hi - self.lo)) as f32 * (self.bottom - self.top),
        )
    }
}

/// The y scale of a point chart, from `height` less the bottom `padding` up to
/// the top `padding`.
///
/// A pinned `domain` maps its ends onto that range; otherwise the scale fits
/// `values` from zero.
pub(crate) fn point_value_scale<Y>(
    values: impl IntoIterator<Item = Y>,
    domain: Option<(Y, Y)>,
    height: f32,
    (top, bottom): (f32, f32),
) -> (ScaleLinear<Y>, ValueExtent)
where
    Y: PlotValue,
{
    let domain: Vec<Y> = match domain {
        Some((min, max)) => vec![min, max],
        None => values.into_iter().chain(Some(Y::zero())).collect(),
    };
    let (lo, hi) = domain
        .iter()
        .filter_map(|v| v.to_f64())
        .fold((f64::MAX, f64::MIN), |(lo, hi), v| (lo.min(v), hi.max(v)));
    let extent = ValueExtent {
        lo,
        hi,
        bottom: height - bottom,
        top,
    };
    (ScaleLinear::new(domain, [height - bottom, top]), extent)
}

/// The height the charts reserve under the plot for x-axis labels, which they
/// draw at the default [`TEXT_SIZE`]: [`axis_gutter`](crate::plot::axis_gutter)
/// for that size.
pub(crate) const AXIS_GAP: f32 = TEXT_SIZE + TEXT_GAP * 4.;

/// The widest a bar or candle is by default, in pixels, however few bands
/// share the width; see `BarChart::max_band_width`.
pub(crate) const MAX_BAND_WIDTH: f32 = 30.;

/// The least space kept beside the plot for value-axis tick labels drawn
/// outside it, in pixels; wider labels widen it (see [`value_axis_gap`]).
pub(crate) const VALUE_AXIS_GAP: f32 = 32.;

/// The gutter value-axis tick `labels` drawn outside the plot need: the widest
/// label and the gap before the plot, and never less than [`VALUE_AXIS_GAP`].
///
/// Measured in `prepaint`, which runs before `tooltip_state` and `paint`, so
/// hit-testing and painting share one gutter.
pub(crate) fn value_axis_gap(
    labels: impl IntoIterator<Item = SharedString>,
    window: &mut Window,
) -> f32 {
    labels
        .into_iter()
        .map(|label| measure_text_width(&label, px(TEXT_SIZE), window) + TEXT_GAP * 2.)
        .fold(VALUE_AXIS_GAP, f32::max)
}

/// A caller's tick label text for a value.
pub(crate) type TickFormat = Rc<dyn Fn(f64) -> SharedString>;

/// The default tick label: whole numbers bare, the rest to one decimal.
pub(crate) fn format_tick(value: f64) -> SharedString {
    if (value - value.round()).abs() < 0.001 {
        format!("{:.0}", value).into()
    } else {
        format!("{:.1}", value).into()
    }
}

/// Which of `len` items carry a category label: `label_count` of them evenly
/// spread from the first to the last when set, otherwise every `tick_margin`-th.
pub(crate) fn labeled_items(
    len: usize,
    label_count: Option<usize>,
    tick_margin: usize,
) -> Vec<bool> {
    match label_count {
        Some(count) => {
            let mut labeled = vec![false; len];
            match count {
                0 => {}
                1 => labeled.iter_mut().take(1).for_each(|l| *l = true),
                count if count >= len => labeled.iter_mut().for_each(|l| *l = true),
                count => {
                    for k in 0..count {
                        let ix =
                            (k as f32 * (len - 1) as f32 / (count - 1) as f32).round() as usize;
                        labeled[ix] = true;
                    }
                }
            }
            labeled
        }
        None => (0..len).map(|i| (i + 1) % tick_margin == 0).collect(),
    }
}

/// What a series chart (`LineChart`, `AreaChart`, `BarChart`, `RadarChart`,
/// `CandlestickChart`) writes in its hover tooltip, and the builders the five
/// charts forward to it.
pub(crate) struct TooltipContent<T> {
    title: Option<Rc<dyn Fn(&T) -> SharedString>>,
    value: Option<Rc<dyn Fn(&T, usize, f64) -> SharedString>>,
    value_color: Option<Rc<dyn Fn(&T, usize, f64) -> Hsla>>,
    content: Option<Rc<dyn Fn(&T, &mut Window, &mut App) -> AnyElement>>,
}

impl<T> Default for TooltipContent<T> {
    fn default() -> Self {
        Self {
            title: None,
            value: None,
            value_color: None,
            content: None,
        }
    }
}

impl<T: 'static> TooltipContent<T> {
    pub(crate) fn set_title(&mut self, title: impl Fn(&T) -> SharedString + 'static) {
        self.title = Some(Rc::new(title));
    }

    pub(crate) fn set_value(&mut self, value: impl Fn(&T, usize, f64) -> SharedString + 'static) {
        self.value = Some(Rc::new(value));
    }

    pub(crate) fn set_value_color<H: Into<Hsla>>(
        &mut self,
        color: impl Fn(&T, usize, f64) -> H + 'static,
    ) {
        self.value_color = Some(Rc::new(move |d, ix, value| color(d, ix, value).into()));
    }

    pub(crate) fn set_content<E: IntoElement>(
        &mut self,
        content: impl Fn(&T, &mut Window, &mut App) -> E + 'static,
    ) {
        self.content = Some(Rc::new(move |d, window, cx| {
            content(d, window, cx).into_any_element()
        }));
    }

    /// The title for datum `d`: the caller's, or `fallback`, the chart's own,
    /// which a chart may not have.
    fn title_text(&self, d: &T, fallback: Option<SharedString>) -> Option<SharedString> {
        match self.title.as_ref() {
            Some(title) => Some(title(d)),
            None => fallback,
        }
    }

    /// The value text of row `ix`: the caller's, or the raw number.
    fn value_text(&self, d: &T, ix: usize, value: f64) -> SharedString {
        match self.value.as_ref() {
            Some(text) => text(d, ix, value),
            None => format!("{}", value).into(),
        }
    }

    /// Write the content of `tooltip` for datum `d`: the caller's own content when it renders
    /// one, otherwise the chart's `title`, if it has one, and one row per
    /// `(swatch, name, value)`. Neither is built when the caller renders, and
    /// `None` from `rows` means a row has no value to show.
    pub(crate) fn apply<R>(
        &self,
        tooltip: Tooltip,
        d: &T,
        title: impl FnOnce() -> Option<SharedString>,
        rows: impl FnOnce() -> Option<R>,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<Tooltip>
    where
        R: IntoIterator<Item = (Hsla, SharedString, f64)>,
    {
        if let Some(content) = self.content.as_ref() {
            return Some(tooltip.child(content(d, window, cx)));
        }
        let mut tooltip = match self.title_text(d, title()) {
            Some(title) => tooltip.title(title),
            None => tooltip,
        };
        for (ix, (swatch, name, value)) in rows()?.into_iter().enumerate() {
            tooltip = tooltip.row(swatch, name, self.value_text(d, ix, value));
            if let Some(color) = self.value_color.as_ref() {
                tooltip = tooltip.value_color(color(d, ix, value));
            }
        }
        Some(tooltip)
    }
}

/// The grid, value-axis labels and reference lines a point chart (`LineChart`,
/// `AreaChart`) draws, and the builders both charts forward to it.
pub(crate) struct PointAxes {
    pub(crate) y_axis: bool,
    pub(crate) y_axis_label_placement: AxisLabelPlacement,
    pub(crate) y_tick_count: usize,
    pub(crate) y_tick_format: Option<TickFormat>,
    pub(crate) x_tick_count: Option<usize>,
    pub(crate) grid_columns: usize,
    pub(crate) grid_dashed: bool,
    pub(crate) y_padding: (f32, f32),
    pub(crate) reference_lines: Vec<f64>,
    /// The value-axis gutter measured in `prepaint`; see [`value_axis_gap`].
    y_label_gap: f32,
}

impl Default for PointAxes {
    fn default() -> Self {
        Self {
            y_axis: false,
            y_axis_label_placement: AxisLabelPlacement::default(),
            y_tick_count: 5,
            y_tick_format: None,
            x_tick_count: None,
            grid_columns: 0,
            grid_dashed: true,
            y_padding: (10., 0.),
            reference_lines: vec![],
            y_label_gap: VALUE_AXIS_GAP,
        }
    }
}

impl PointAxes {
    /// Where the plot starts along x: past the value-axis gutter when the labels
    /// sit outside it.
    pub(crate) fn plot_left(&self) -> f32 {
        if self.y_axis && self.y_axis_label_placement == AxisLabelPlacement::Outside {
            self.y_label_gap
        } else {
            0.
        }
    }

    /// Measure the gutter the y labels need outside the plot, before the x
    /// scale is laid out past it.
    pub(crate) fn measure_y_labels(
        &mut self,
        extent: ValueExtent,
        height: f32,
        window: &mut Window,
    ) {
        if self.y_axis && self.y_axis_label_placement == AxisLabelPlacement::Outside {
            let labels = self
                .y_tick_labels(extent, height)
                .into_iter()
                .map(|(_, text)| text);
            self.y_label_gap = value_axis_gap(labels, window);
        }
    }

    /// Each y tick's position and the label text for the value there.
    fn y_tick_labels(&self, extent: ValueExtent, height: f32) -> Vec<(f32, SharedString)> {
        self.tick_positions(height)
            .into_iter()
            .map(|y| {
                let value = extent.value_at(y);
                let text = match self.y_tick_format.as_ref() {
                    Some(format) => format(value),
                    None => format_tick(value),
                };
                (y, text)
            })
            .collect()
    }

    /// The plot area within `bounds`: past the value-axis gutter and above the
    /// x axis at `height`.
    pub(crate) fn plot_bounds(&self, bounds: Bounds<Pixels>, height: f32) -> Bounds<Pixels> {
        let left = self.plot_left();
        Bounds {
            origin: bounds.origin + point(px(left), px(0.)),
            size: Size::new(bounds.size.width - px(left), px(height)),
        }
    }

    /// The y ticks, evenly spaced in pixels from the top edge (0) to the
    /// baseline (`height`), both included.
    fn tick_positions(&self, height: f32) -> Vec<f32> {
        let count = self.y_tick_count.max(2);
        (0..count)
            .map(|i| height * i as f32 / (count - 1) as f32)
            .collect()
    }

    /// Paint the grid: a line at every y tick but the baseline, which the x axis
    /// draws, and `grid_columns` evenly spaced vertical lines from the left edge.
    pub(crate) fn paint_grid(
        &self,
        bounds: Bounds<Pixels>,
        height: f32,
        window: &mut Window,
        cx: &mut App,
    ) {
        let plot = self.plot_bounds(bounds, height);
        let mut rows = self.tick_positions(height);
        rows.pop();
        let width = plot.size.width.as_f32();
        let columns: Vec<f32> = (0..self.grid_columns)
            .map(|i| width * i as f32 / self.grid_columns as f32)
            .collect();
        let grid = Grid::new().y(rows).x(columns).stroke(cx.theme().chart_grid);
        let grid = if self.grid_dashed {
            grid.dash_array(&[px(4.), px(2.)])
        } else {
            grid
        };
        grid.paint(&plot, window);
    }

    /// Paint a dashed line across the plot at each reference value, darker than
    /// the grid so it reads apart from a dashed grid line.
    pub(crate) fn paint_reference_lines(
        &self,
        extent: ValueExtent,
        bounds: Bounds<Pixels>,
        height: f32,
        window: &mut Window,
        cx: &mut App,
    ) {
        let rows: Vec<f32> = self
            .reference_lines
            .iter()
            .filter_map(|v| extent.position_of(*v))
            .filter(|y| (0. ..=height).contains(y))
            .collect();
        if rows.is_empty() {
            return;
        }
        Grid::new()
            .y(rows)
            .stroke(cx.theme().muted_foreground)
            .dash_array(&[px(4.), px(2.)])
            .paint(&self.plot_bounds(bounds, height), window);
    }

    /// Paint a tick label at every y tick, reading the value the scale puts there.
    pub(crate) fn paint_y_labels(
        &self,
        extent: ValueExtent,
        bounds: Bounds<Pixels>,
        height: f32,
        window: &mut Window,
        cx: &mut App,
    ) {
        if !self.y_axis {
            return;
        }
        let color = cx.theme().muted_foreground;
        let labels = self
            .y_tick_labels(extent, height)
            .into_iter()
            .map(|(y, text)| {
                match self.y_axis_label_placement {
                    // Beside its grid line, above it but for the top one, which
                    // would leave the plot.
                    AxisLabelPlacement::Inside => {
                        let top = if y < TEXT_HEIGHT {
                            y + TEXT_GAP
                        } else {
                            y - TEXT_HEIGHT
                        };
                        Text::new(text, point(TEXT_GAP, top), color)
                    }
                    AxisLabelPlacement::Outside => {
                        let top = (y - TEXT_SIZE / 2.).clamp(0., (height - TEXT_SIZE).max(0.));
                        Text::new(text, point(self.y_label_gap - TEXT_GAP * 2., top), color)
                            .align(TextAlign::Right)
                    }
                }
            })
            .collect();
        PlotLabel::new(labels).paint(&bounds, window, cx);
    }
}

/// The mask a point chart paints its series under once its y axis is pinned,
/// so a value outside the pinned domain stops at the plot area instead of
/// running over the x-axis labels. It bleeds by half a hover dot, keeping
/// strokes and dots on the plot's edges whole.
pub(crate) fn pinned_plot_mask(bounds: Bounds<Pixels>, height: f32) -> ContentMask<Pixels> {
    let bleed = HOVER_DOT_SIZE / 2.;
    ContentMask {
        bounds: Bounds::from_corners(
            bounds.origin - gpui::point(bleed, bleed),
            gpui::point(bounds.right() + bleed, bounds.top() + px(height) + bleed),
        ),
    }
}

/// Build x-axis labels for point-based scales (`LineChart`, `AreaChart`).
///
/// Point scales place items at evenly spaced positions, on an axis laid out for
/// `point_count` of them. A label on the first point is left-aligned, one on
/// the last is right-aligned, and the rest are centered.
pub(crate) fn build_point_x_labels<T, X>(
    data: &[T],
    x_fn: &dyn Fn(&T) -> X,
    x_scale: &ScalePoint<X>,
    point_count: usize,
    labeled: &[bool],
    color: Hsla,
) -> Vec<AxisText>
where
    X: PartialEq + Into<SharedString>,
{
    data.iter()
        .enumerate()
        .filter_map(|(i, d)| {
            if !labeled.get(i).copied().unwrap_or(false) {
                return None;
            }
            x_scale.tick_at(i).map(|x_tick| {
                let align = match i {
                    0 if point_count == 1 => TextAlign::Center,
                    0 => TextAlign::Left,
                    i if i == point_count - 1 => TextAlign::Right,
                    _ => TextAlign::Center,
                };
                AxisText::new(x_fn(d).into(), x_tick, color).align(align)
            })
        })
        .collect()
}

/// Build axis labels for band-based scales (`BarChart`, `CandlestickChart`).
///
/// Band scales place items in evenly sized bands. The returned `tick`
/// coordinate is the centre of each band along the band axis; the caller
/// decides whether to feed the result to `PlotAxis::x_label` (vertical
/// charts) or `PlotAxis::y_label` (horizontal charts).
pub(crate) fn build_band_labels<T, X>(
    data: &[T],
    x_fn: &dyn Fn(&T) -> X,
    x_scale: &ScaleBand<X>,
    band_width: f32,
    labeled: &[bool],
    color: Hsla,
) -> Vec<AxisText>
where
    X: Eq + Hash + Into<SharedString>,
{
    data.iter()
        .enumerate()
        .filter_map(|(i, d)| {
            if !labeled.get(i).copied().unwrap_or(false) {
                return None;
            }
            x_scale.tick(&x_fn(d)).map(|x_tick| {
                // Call x_fn again to get an owned value for the label text.
                AxisText::new(x_fn(d).into(), x_tick + band_width / 2., color)
                    .align(TextAlign::Center)
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use std::cell::Cell;

    use gpui::{Hsla, SharedString, TestAppContext, blue, div, green, point, px, red, size};

    use super::TooltipContent;
    use crate::{
        chart::PieChart,
        plot::{Plot, tooltip::Tooltip},
    };

    fn chart() -> PieChart<f32> {
        PieChart::new([1., 2.])
    }

    /// The whole point of the default: a chart nobody gave an id to is still
    /// interactive, because every caller forgot to ask for it.
    #[test]
    fn a_chart_is_interactive_without_being_given_an_id() {
        assert!(Plot::id(&chart()).is_some());
    }

    /// Two construction sites must not share hover state or a path cache.
    #[test]
    fn charts_built_at_different_sites_get_different_ids() {
        assert_ne!(
            Plot::id(&PieChart::new([1.])),
            Plot::id(&PieChart::new([1.]))
        );
    }

    /// One site reached twice is one id — the caveat `id` exists for.
    #[test]
    fn charts_built_at_one_site_share_an_id() {
        assert_eq!(Plot::id(&chart()), Plot::id(&chart()));
    }

    /// The escape hatch: a chart turned off has no hitbox, so nothing above it
    /// has to fight it for the cursor, but it keeps its id for its appear and
    /// its caches.
    #[test]
    fn a_chart_turned_off_keeps_its_id_but_not_its_hitbox() {
        let off = chart().interactive(false);
        assert!(!Plot::interactive(&off));
        assert!(Plot::id(&off).is_some());
        assert_eq!(
            Plot::id(&chart().id("pie").interactive(false)),
            Some("pie".into())
        );
    }

    /// Without a key a chart appears once; a key names the generation that
    /// replays it.
    #[test]
    fn an_appear_key_replays_the_appear() {
        assert_eq!(Plot::appear_generation(&chart()), Some(0));
        assert_eq!(Plot::appear_generation(&chart().appear(false)), None);
        let a = Plot::appear_generation(&chart().appear_key("AAPL.US"));
        let b = Plot::appear_generation(&chart().appear_key("TSLA.US"));
        assert_ne!(a, b);
        assert_eq!(a, Plot::appear_generation(&chart().appear_key("AAPL.US")));
    }

    /// Only a label on the axis's last point hugs the right edge; the last item
    /// of data laid out for more points sits mid-axis and stays centered.
    #[test]
    fn only_the_last_point_right_aligns_its_label() {
        use gpui::{Hsla, TextAlign};

        use super::{build_point_x_labels, point_range};
        use crate::plot::scale::ScalePoint;

        let data = ["a", "b", "c"];
        let align = |point_count| {
            let x = ScalePoint::new(
                data.to_vec(),
                point_range(0., 100., data.len(), point_count),
            );
            build_point_x_labels(
                &data,
                &|d: &&'static str| *d,
                &x,
                point_count,
                &[true; 3],
                Hsla::default(),
            )
            .into_iter()
            .map(|label| label.align)
            .collect::<Vec<_>>()
        };

        assert_eq!(
            align(3),
            [TextAlign::Left, TextAlign::Center, TextAlign::Right]
        );
        assert_eq!(
            align(5),
            [TextAlign::Left, TextAlign::Center, TextAlign::Center]
        );
    }

    #[test]
    fn a_named_id_replaces_the_default() {
        assert_eq!(
            Plot::id(&chart().id("pie")),
            Some(gpui::ElementId::Name("pie".into()))
        );
    }

    /// The default five ticks put the grid where it always was: four lines
    /// splitting the plot, the baseline left to the x axis.
    #[test]
    fn the_default_ticks_keep_the_grid_in_place() {
        let axes = super::PointAxes::default();
        let mut rows = axes.tick_positions(100.);
        rows.pop();
        assert_eq!(rows, vec![0., 25., 50., 75.]);
    }

    #[test]
    fn a_label_count_spreads_labels_from_the_first_item_to_the_last() {
        use super::labeled_items;

        let shown = |len, count| {
            labeled_items(len, Some(count), 1)
                .iter()
                .enumerate()
                .filter_map(|(i, &on)| on.then_some(i))
                .collect::<Vec<_>>()
        };
        assert_eq!(shown(11, 3), vec![0, 5, 10]);
        assert_eq!(shown(10, 2), vec![0, 9]);
        assert_eq!(shown(3, 5), vec![0, 1, 2]);
        assert_eq!(shown(4, 1), vec![0]);
        assert!(shown(4, 0).is_empty());

        // Without a count the stride still decides.
        assert_eq!(labeled_items(4, None, 2), vec![false, true, false, true]);
    }

    /// A tick label reads the value its height stands for, so the top one reads
    /// past the highest value by the padding above it.
    #[test]
    fn a_tick_reads_the_value_at_its_height() {
        use super::point_value_scale;

        let (_, extent) = point_value_scale([10., 20.], None, 110., (10., 0.));
        assert_eq!(extent.value_at(110.), 0.);
        assert_eq!(extent.value_at(10.), 20.);
        assert!((extent.value_at(0.) - 22.).abs() < 1e-4);
        assert_eq!(extent.position_of(20.), Some(10.));

        let (_, extent) = point_value_scale([0.], Some((100., 200.)), 100., (0., 0.));
        assert_eq!(extent.value_at(0.), 200.);
        assert_eq!(extent.position_of(150.), Some(50.));
    }

    /// Unset, the tooltip reads the chart's own title and the raw number;
    /// set, the caller's text replaces both.
    #[test]
    fn tooltip_text_falls_back_to_the_chart_own() {
        let mut content = TooltipContent::<f64>::default();
        assert_eq!(
            content.title_text(&1., Some("Jan".into())),
            Some("Jan".into())
        );
        assert_eq!(content.title_text(&1., None), None);
        assert_eq!(content.value_text(&1., 0, 1234.5).as_ref(), "1234.5");

        content.set_title(|d| format!("Day {d}").into());
        content.set_value(|_, _, value| format!("${value:.2}").into());
        assert_eq!(content.title_text(&3., None), Some("Day 3".into()));
        assert_eq!(content.value_text(&3., 0, 1234.5).as_ref(), "$1234.50");
    }

    /// Rows read the caller's value text and color, one per series, each told
    /// which row it is.
    #[gpui::test]
    fn tooltip_fill_writes_each_row_with_the_value_color(cx: &mut TestAppContext) {
        let mut content = TooltipContent::<f64>::default();
        content.set_value(|_, ix, value| format!("{ix}: {value:+}").into());
        content.set_value_color(|_, _, value| if value >= 0. { green() } else { red() });
        let cx = cx.add_empty_window();
        let tooltip = cx
            .update(|window, cx| {
                content.apply(
                    Tooltip::new(point(px(0.), px(0.)), size(px(100.), px(100.))),
                    &1.,
                    || Some("Jan".into()),
                    || Some([(blue(), "Open".into(), 2.), (blue(), "Close".into(), -1.)]),
                    window,
                    cx,
                )
            })
            .expect("rows are given");

        assert_eq!(tooltip.title_for_test().map(|t| t.as_ref()), Some("Jan"));
        assert_eq!(
            tooltip.rows_for_test(),
            vec![
                ("0: +2".into(), Some(green())),
                ("1: -1".into(), Some(red()))
            ]
        );
    }

    /// Without a title of the chart's or the caller's, the tooltip has none, as a
    /// radar with element labels shows.
    #[gpui::test]
    fn tooltip_fill_leaves_the_title_off_without_one(cx: &mut TestAppContext) {
        let content = TooltipContent::<f64>::default();
        let cx = cx.add_empty_window();
        let tooltip = cx
            .update(|window, cx| {
                content.apply(
                    Tooltip::new(point(px(0.), px(0.)), size(px(100.), px(100.))),
                    &1.,
                    || None,
                    || Some([(blue(), "Alpha".into(), 80.)]),
                    window,
                    cx,
                )
            })
            .expect("rows are given");

        assert!(tooltip.title_for_test().is_none());
        assert_eq!(tooltip.rows_for_test(), vec![("80".into(), None)]);
    }

    /// A caller's own content replaces the title and rows, which are never built,
    /// so a series without a value doesn't hide it.
    #[gpui::test]
    fn tooltip_fill_renders_the_caller_content_without_building_rows(cx: &mut TestAppContext) {
        let mut content = TooltipContent::<f64>::default();
        content.set_title(|_| "Caller".into());
        content.set_content(|_, _, _| div());
        let built = Cell::new(false);
        let cx = cx.add_empty_window();
        let tooltip = cx.update(|window, cx| {
            content.apply(
                Tooltip::new(point(px(0.), px(0.)), size(px(100.), px(100.))),
                &1.,
                || {
                    built.set(true);
                    Some("Jan".into())
                },
                || -> Option<[(Hsla, SharedString, f64); 0]> {
                    built.set(true);
                    None
                },
                window,
                cx,
            )
        });

        let tooltip = tooltip.expect("the caller renders");
        assert!(!built.get());
        assert!(tooltip.title_for_test().is_none());
        assert!(tooltip.rows_for_test().is_empty());
    }
}
