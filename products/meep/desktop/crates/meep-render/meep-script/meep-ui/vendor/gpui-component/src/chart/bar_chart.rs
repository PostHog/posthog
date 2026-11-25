use std::{hash::Hash, ops::RangeInclusive, rc::Rc};

use gpui::{
    AnyElement, App, Background, Bounds, Corners, ElementId, Hsla, IntoElement, LinearColorStop,
    Pixels, Point, SharedString, Size, TextAlign, Window, linear_gradient, point, px,
};
use gpui_component_macros::IntoPlot;

use crate::{
    ActiveTheme,
    plot::{
        AxisLabelPlacement, AxisLabelSide, AxisText, Grid, Plot, PlotAppear, PlotAxis, PlotLabel,
        label::{TEXT_GAP, TEXT_HEIGHT, TEXT_SIZE, Text, measure_text_width},
        scale::{PlotValue, Scale, ScaleBand, ScaleLinear},
        shape::{Bar, BarAlignment},
        tooltip::{CrossLine, PlotHover, Tooltip, TooltipState},
    },
};

use super::{
    AXIS_GAP, ChartAppear, MAX_BAND_WIDTH, TickFormat, TooltipContent, VALUE_AXIS_GAP,
    build_band_labels, caller_id, format_tick, labeled_items, value_axis_gap,
};

/// How much the bars away from the hovered one fade, as a share of their opacity.
const HOVER_DIM: f32 = 0.45;

/// The hover a bar chart paints, sampled once per frame in [`Plot::hover`].
#[derive(Clone, Copy)]
struct BarHover {
    /// Cross-axis center of the highlight band, gliding between bars.
    center: f32,
    /// How far the hover has faded in.
    focus: f32,
}

#[derive(IntoPlot)]
pub struct BarChart<T, B, V>
where
    T: 'static,
    B: Eq + Hash + Into<SharedString> + 'static,
    V: PlotValue,
{
    data: Vec<T>,
    band: Option<Rc<dyn Fn(&T) -> B>>,
    value: Option<Rc<dyn Fn(&T) -> V>>,
    fill: Option<Rc<dyn Fn(&T, Bounds<f32>, Bounds<f32>, BarAlignment) -> Background>>,
    #[allow(clippy::type_complexity)]
    fill_gradient:
        Option<Rc<dyn Fn(&T, RangeInclusive<f32>, &dyn Fn(f32) -> f32) -> [LinearColorStop; 2]>>,
    tick_margin: usize,
    label: Option<Rc<dyn Fn(&T) -> SharedString>>,
    label_color: Option<Rc<dyn Fn(&T) -> Hsla>>,
    label_axis: bool,
    value_axis: bool,
    value_axis_label_placement: AxisLabelPlacement,
    value_tick_count: usize,
    value_tick_format: Option<TickFormat>,
    band_count: Option<usize>,
    band_tick_count: Option<usize>,
    grid: bool,
    grid_dashed: bool,
    alignment: BarAlignment,
    corner_radii: Corners<Pixels>,
    padding_inner: f32,
    padding_outer: f32,
    max_band_width: Pixels,
    min_length: f32,
    id: ElementId,
    interactive: bool,
    appear: ChartAppear,
    name: Option<SharedString>,
    tooltip_content: TooltipContent<T>,
    /// The label gaps of horizontal bars, measured in `prepaint` for the frame,
    /// so `tooltip_state` (which has no window) can keep the hover off the labels.
    horizontal_gaps: (f32, f32),
    /// The value-axis gutter of vertical bars, measured in `prepaint`; see
    /// [`value_axis_gap`].
    value_label_gap: f32,
    hover: Option<BarHover>,
}

impl<T, B, V> BarChart<T, B, V>
where
    B: Eq + Hash + Into<SharedString> + 'static,
    V: PlotValue,
{
    #[track_caller]
    pub fn new<I>(data: I) -> Self
    where
        I: IntoIterator<Item = T>,
    {
        Self {
            data: data.into_iter().collect(),
            band: None,
            value: None,
            fill: None,
            fill_gradient: None,
            tick_margin: 1,
            label: None,
            label_color: None,
            label_axis: true,
            value_axis: false,
            value_axis_label_placement: AxisLabelPlacement::default(),
            value_tick_count: 5,
            value_tick_format: None,
            band_count: None,
            band_tick_count: None,
            grid: true,
            grid_dashed: true,
            alignment: BarAlignment::default(),
            corner_radii: Corners::all(px(0.)),
            padding_inner: 0.4,
            padding_outer: 0.2,
            max_band_width: px(MAX_BAND_WIDTH),
            min_length: 0.,
            id: caller_id(),
            interactive: true,
            appear: ChartAppear::default(),
            name: None,
            tooltip_content: TooltipContent::default(),
            horizontal_gaps: (0., 0.),
            value_label_gap: VALUE_AXIS_GAP,
            hover: None,
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
    /// marks the hovered band, and a tooltip shows its category and value. Turn
    /// it off for a chart that only decorates, or one an element above it wants
    /// the cursor for: without a hitbox it neither answers the mouse nor takes
    /// the hover from what sits over it.
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

    /// Set the series name shown in the hover tooltip row (e.g. "Desktop").
    pub fn name(mut self, name: impl Into<SharedString>) -> Self {
        self.name = Some(name.into());
        self
    }

    /// Set the hover tooltip's title for a datum, instead of its band value.
    pub fn tooltip_title(mut self, title: impl Fn(&T) -> SharedString + 'static) -> Self {
        self.tooltip_content.set_title(title);
        self
    }

    /// Set the text of the tooltip row's value; the raw number by default.
    ///
    /// The closure receives the datum and the value the row reads.
    pub fn tooltip_value(mut self, value: impl Fn(&T, f64) -> SharedString + 'static) -> Self {
        self.tooltip_content.set_value(move |d, _, v| value(d, v));
        self
    }

    /// Color the tooltip row's value, such as green or red by its sign; the
    /// tooltip's text color by default.
    ///
    /// The closure receives the same arguments as
    /// [`tooltip_value`](Self::tooltip_value).
    pub fn tooltip_value_color<H>(mut self, color: impl Fn(&T, f64) -> H + 'static) -> Self
    where
        H: Into<Hsla>,
    {
        self.tooltip_content
            .set_value_color(move |d, _, value| color(d, value));
        self
    }

    /// Draw the tooltip box's content for a datum yourself, in place of the
    /// title and rows, for a layout they cannot express such as a table.
    ///
    /// The highlight band and where the box sits stay the chart's, and
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

    /// Map each datum to its band-axis value (the categorical/ordinal axis).
    pub fn band(mut self, band: impl Fn(&T) -> B + 'static) -> Self {
        self.band = Some(Rc::new(band));
        self
    }

    /// Map each datum to its numeric value along the value axis.
    pub fn value(mut self, value: impl Fn(&T) -> V + 'static) -> Self {
        self.value = Some(Rc::new(value));
        self
    }

    /// Set a per-datum verbatim fill.
    ///
    /// The closure receives:
    ///
    /// 1. the datum,
    /// 2. the **bar's bounds** in pixel space, expressed relative to the
    ///    chart's origin (i.e. the bar's painted rectangle within the chart),
    /// 3. the **chart's bounds** in pixel space with origin `(0, 0)` and size
    ///    equal to the full chart extent, and
    /// 4. the bar's [`BarAlignment`] (so callers can branch on orientation,
    ///    e.g. flip a gradient angle).
    ///
    /// Both rectangles share the same coordinate system, so callers can
    /// implement arbitrary chart-aware backgrounds — bar-local gradients,
    /// chart-wide gradients, patterns, sampled colormaps, etc. — without any
    /// help from the library.
    ///
    /// Accepts any type convertible to [`Background`]. Setting this clears any
    /// previously set [`BarChart::fill_gradient`].
    pub fn fill<Bg>(
        mut self,
        fill: impl Fn(&T, Bounds<f32>, Bounds<f32>, BarAlignment) -> Bg + 'static,
    ) -> Self
    where
        Bg: Into<Background> + 'static,
    {
        self.fill = Some(Rc::new(move |t, bar_bounds, chart_bounds, alignment| {
            fill(t, bar_bounds, chart_bounds, alignment).into()
        }));
        self.fill_gradient = None;
        self
    }

    /// Set a per-datum auto-oriented linear gradient fill.
    ///
    /// The closure receives the datum, the chart's full data range
    /// (`chart_range`, derived from all data values), and a `chart_to_bar`
    /// remap helper that maps a chart-value coordinate to a bar-local
    /// gradient position (where `0.0` is the bar's base and `1.0` is its tip).
    ///
    /// Use bar-local positions directly for per-bar gradients (every bar
    /// looks the same regardless of its value):
    ///
    /// ```ignore
    /// .fill_gradient(|_, _, _| [
    ///     linear_color_stop(c.opacity(0.3), 0.0),
    ///     linear_color_stop(c, 1.0),
    /// ])
    /// ```
    ///
    /// Or use `chart_to_bar` to position stops at chart-relative values, so
    /// each bar shows the slice of a chart-wide gradient corresponding to
    /// its own `[base, value]` span:
    ///
    /// ```ignore
    /// .fill_gradient(|_, chart_range, chart_to_bar| [
    ///     linear_color_stop(c.opacity(0.3), chart_to_bar(*chart_range.start())),
    ///     linear_color_stop(c,              chart_to_bar(*chart_range.end())),
    /// ])
    /// ```
    ///
    /// Stop positions returned outside `[0, 1]` are clipped to the bar; the
    /// library interpolates colors at the clip points so the on-bar gradient
    /// still matches the chart-wide one.
    ///
    /// The gradient angle is derived from [`BarAlignment`] so stop-0 is at the
    /// base and stop-1 at the tip. Setting this clears any previously set
    /// [`BarChart::fill`].
    pub fn fill_gradient(
        mut self,
        fill: impl Fn(&T, RangeInclusive<f32>, &dyn Fn(f32) -> f32) -> [LinearColorStop; 2] + 'static,
    ) -> Self {
        self.fill_gradient = Some(Rc::new(fill));
        self.fill = None;
        self
    }

    pub fn tick_margin(mut self, tick_margin: usize) -> Self {
        self.tick_margin = tick_margin;
        self
    }

    pub fn label<S>(mut self, label: impl Fn(&T) -> S + 'static) -> Self
    where
        S: Into<SharedString> + 'static,
    {
        self.label = Some(Rc::new(move |t| label(t).into()));
        self
    }

    /// Color each bar's [`label`](Self::label) text, instead of the theme's
    /// foreground for all of them.
    ///
    /// Takes a closure per bar, as [`fill`](Self::fill) does, so a label can
    /// follow its bar's color.
    pub fn label_color<H>(mut self, color: impl Fn(&T) -> H + 'static) -> Self
    where
        H: Into<Hsla> + 'static,
    {
        self.label_color = Some(Rc::new(move |t| color(t).into()));
        self
    }

    /// Show or hide the band-axis line and labels.
    ///
    /// Default is true.
    pub fn label_axis(mut self, label_axis: bool) -> Self {
        self.label_axis = label_axis;
        self
    }

    /// Show or hide the value-axis tick labels.
    ///
    /// Placed [`Outside`](AxisLabelPlacement::Outside), the default, the labels
    /// take a gutter along the band axis, left of vertical bars and below
    /// horizontal ones.
    ///
    /// Default is false.
    pub fn value_axis(mut self, value_axis: bool) -> Self {
        self.value_axis = value_axis;
        self
    }

    /// Set how many ticks the value axis carries, evenly spaced from the
    /// baseline to the far edge with both ends included, which drives both the
    /// grid lines and the value-axis tick labels.
    ///
    /// Unlike [`Self::tick_margin`], a stride over the band axis categories,
    /// this counts the ticks themselves. Values below 2 are raised to 2.
    ///
    /// Default is 5.
    pub fn value_tick_count(mut self, count: usize) -> Self {
        self.value_tick_count = count.max(2);
        self
    }

    /// Set where the value-axis tick labels sit: in a gutter beside the bars,
    /// or inside the plot beside their grid lines, which keeps the bars' room.
    ///
    /// Default is [`AxisLabelPlacement::Outside`].
    pub fn value_axis_label_placement(mut self, placement: AxisLabelPlacement) -> Self {
        self.value_axis_label_placement = placement;
        self
    }

    /// Set the text of each value-axis tick label from the value at its tick.
    ///
    /// Default is whole numbers bare and the rest to one decimal.
    pub fn value_tick_format<S>(mut self, format: impl Fn(f64) -> S + 'static) -> Self
    where
        S: Into<SharedString> + 'static,
    {
        self.value_tick_format = Some(Rc::new(move |value| format(value).into()));
        self
    }

    /// Lay the band axis out for `count` bands instead of the data's own
    /// length.
    ///
    /// The data takes the leading bands in order and the rest stay empty, so
    /// each bar keeps its width and place as the data grows. A `count` below
    /// the data's length has no effect.
    pub fn band_count(mut self, count: usize) -> Self {
        self.band_count = Some(count);
        self
    }

    /// Label `count` of the bands, spread evenly from the first to the last,
    /// instead of every `tick_margin`-th.
    ///
    /// With [`Self::band_count`] set, the labels spread over all the bands, so
    /// they keep their places as the data grows; one that falls on an empty band
    /// is not drawn yet.
    pub fn band_tick_count(mut self, count: usize) -> Self {
        self.band_tick_count = Some(count);
        self
    }

    pub fn grid(mut self, grid: bool) -> Self {
        self.grid = grid;
        self
    }

    /// Draw the grid dashed or solid.
    ///
    /// Default is true.
    pub fn grid_dashed(mut self, dashed: bool) -> Self {
        self.grid_dashed = dashed;
        self
    }

    /// Set the bar alignment.
    ///
    /// Default is [`BarAlignment::Bottom`].
    pub fn alignment(mut self, alignment: BarAlignment) -> Self {
        self.alignment = alignment;
        self
    }

    /// Set the corner radii applied to every bar rectangle.
    ///
    /// Use [`Corners::all`] for uniform rounding, or construct [`Corners`] manually
    /// to round only specific corners (e.g. just the tip end of each bar).
    pub fn corner_radii(mut self, corner_radii: impl Into<Corners<Pixels>>) -> Self {
        self.corner_radii = corner_radii.into();
        self
    }

    /// Set the gap between neighbouring bars, as a share of each band.
    ///
    /// Default is 0.4.
    pub fn padding_inner(mut self, padding: f32) -> Self {
        self.padding_inner = padding;
        self
    }

    /// Set the gap before the first bar and after the last, as a share of a band.
    ///
    /// Default is 0.2.
    pub fn padding_outer(mut self, padding: f32) -> Self {
        self.padding_outer = padding;
        self
    }

    /// Keep every bar at most `width` wide, so a few bars across a wide chart
    /// stay narrow instead of filling their bands.
    ///
    /// Default is 30px.
    pub fn max_band_width(mut self, width: impl Into<Pixels>) -> Self {
        self.max_band_width = width.into();
        self
    }

    /// Draw every bar at least `length` pixels long, so a zero or tiny value
    /// still shows a stub instead of disappearing into the baseline.
    ///
    /// The stub grows the way the bar's value would: away from the zero line,
    /// to the negative side for a negative value and to the positive side for
    /// zero. A bar already that long is left alone.
    ///
    /// Default is 0.
    pub fn min_length(mut self, length: f32) -> Self {
        self.min_length = length;
        self
    }

    /// The band scale (matching `paint`): spans the height for horizontal bars, the width
    /// otherwise. Shared by `tooltip_state` and `tooltip`.
    fn band_scale(&self, bounds: Bounds<Pixels>) -> Option<ScaleBand<B>> {
        let band_fn = self.band.as_ref()?;
        let band_extent = if self.alignment.is_horizontal() {
            bounds.size.height.as_f32()
        } else {
            bounds.size.width.as_f32()
        };
        // Value-axis labels eat into the band extent at one end; `band_offset`
        // shifts the bands away from that end when it is the leading one.
        let extent = (band_extent - self.value_axis_gap()).max(0.);
        Some(
            ScaleBand::new(self.data.iter().map(|v| band_fn(v)), [0., extent])
                .band_count(self.band_count.unwrap_or(0))
                .max_band_width(self.max_band_width.as_f32())
                .padding_inner(self.padding_inner)
                .padding_outer(self.padding_outer),
        )
    }

    /// Offset added to every band-scale tick.
    ///
    /// [`ScaleBand`] ignores the start of its range, so vertical bars are shifted
    /// by hand to clear the value-axis labels on their left. Horizontal bars put
    /// those labels below the plot, past the end of the band axis, so they need no
    /// shift.
    fn band_offset(&self) -> f32 {
        if self.alignment.is_horizontal() {
            0.
        } else {
            self.value_axis_gap()
        }
    }

    /// The value axis for `bounds`: the scale the bars grow along, and the
    /// pixel positions of its baseline and far edge. `paint` lays the bars out
    /// on it and the tooltip reads the hovered bar's frame from it.
    fn value_scale(&self, bounds: Bounds<Pixels>) -> Option<(ScaleLinear<V>, f32, f32)> {
        let value_fn = self.value.as_ref()?;
        let value_dim = if self.alignment.is_horizontal() {
            bounds.size.width.as_f32()
        } else {
            bounds.size.height.as_f32()
        };
        let axis_gap = if self.label_axis { AXIS_GAP } else { 0. };
        // For horizontal charts the band labels (category names) are rendered
        // along the value axis and can be arbitrarily wide, so we measure the
        // actual maximum label width instead of using a fixed constant.
        // Similarly, value labels (numbers) at the bar ends are measured so the
        // scale range is always shrunk by exactly the right amount.
        // Vertical bars keep a line of text clear past the tallest bar when they
        // carry value labels, so the label above it stays inside the chart.
        let far_gap = if self.label.is_some() {
            TEXT_HEIGHT
        } else {
            10.
        };
        let (band_gap, value_end_gap) = if self.alignment.is_horizontal() {
            self.horizontal_gaps
        } else {
            (axis_gap, far_gap)
        };
        // The baseline, and the far edge opposite it.
        let (baseline, far) = match self.alignment {
            BarAlignment::Bottom => (value_dim - axis_gap, far_gap),
            BarAlignment::Top => (axis_gap, value_dim - far_gap),
            BarAlignment::Left => (band_gap, value_dim - value_end_gap),
            BarAlignment::Right => (value_dim - band_gap, value_end_gap),
        };
        let scale = ScaleLinear::new(
            self.data.iter().map(|v| value_fn(v)).chain(Some(V::zero())),
            [baseline, far],
        );
        Some((scale, baseline, far))
    }

    /// The frame `paint` gives datum `d`'s bar, the one `fill` receives.
    fn bar_frame(
        &self,
        d: &T,
        band_scale: &ScaleBand<B>,
        bounds: Bounds<Pixels>,
    ) -> Option<Bounds<f32>> {
        let (band_fn, value_fn) = (self.band.as_ref()?, self.value.as_ref()?);
        let (value_scale, baseline, _) = self.value_scale(bounds)?;
        let zero = value_scale.tick(&V::zero()).unwrap_or(baseline);
        let cross = band_scale.tick(&band_fn(d))? + self.band_offset();
        let end = bar_end(
            &value_scale,
            value_fn(d),
            zero,
            self.alignment,
            self.min_length,
        )?;
        let (lo, length) = (end.min(zero), (end - zero).abs());
        let band_width = band_scale.band_width();
        Some(if self.alignment.is_horizontal() {
            Bounds {
                origin: Point::new(lo, cross),
                size: Size::new(length, band_width),
            }
        } else {
            Bounds {
                origin: Point::new(cross, lo),
                size: Size::new(band_width, length),
            }
        })
    }

    /// The data range `fill_gradient` reads, the same for every bar.
    fn gradient_range(&self) -> RangeInclusive<f32> {
        let Some(value_fn) = self.value.as_ref() else {
            return 0.0..=0.0;
        };
        let mut lo = 0.0_f32;
        let mut hi = 0.0_f32;
        for v in &self.data {
            if let Some(f) = value_fn(v).to_f32() {
                lo = lo.min(f);
                hi = hi.max(f);
            }
        }
        lo..=hi
    }

    /// The color a tooltip row shows for datum `d`: its bar's, the first stop
    /// of a gradient, or the default fill when `fill` returns a gradient,
    /// whose stops can't be read back. `frame` is the bar's, as `paint` lays it
    /// out.
    fn bar_color(&self, d: &T, frame: Bounds<f32>, bounds: Bounds<Pixels>, cx: &App) -> Hsla {
        let default = cx.theme().chart_2;
        if let Some(fill) = self.fill_gradient.as_ref() {
            let value = self
                .value
                .as_ref()
                .and_then(|value_fn| value_fn(d).to_f32())
                .unwrap_or(0.);
            let [first, _] = bar_gradient(fill.as_ref(), d, value, self.gradient_range());
            return first.color;
        }
        let Some(fill) = self.fill.as_ref() else {
            return default;
        };
        let chart_bounds = Bounds {
            origin: Point::new(0., 0.),
            size: Size::new(bounds.size.width.as_f32(), bounds.size.height.as_f32()),
        };
        fill(d, frame, chart_bounds, self.alignment)
            .as_solid()
            .unwrap_or(default)
    }

    /// The gutter the value-axis labels take along the band axis: none unless
    /// they are shown outside the plot.
    fn value_axis_gap(&self) -> f32 {
        if !self.value_axis || self.value_axis_label_placement != AxisLabelPlacement::Outside {
            0.
        } else if self.alignment.is_horizontal() {
            // Below the plot, where the gap is a line of text tall.
            VALUE_AXIS_GAP
        } else {
            self.value_label_gap
        }
    }

    /// The bands the band axis is laid out for: the data's, or the
    /// [`Self::band_count`] when larger.
    fn band_slots(&self) -> usize {
        self.band_count.unwrap_or(0).max(self.data.len())
    }

    /// The value-axis tick label text, from the domain maximum at the far end
    /// down to the minimum at the baseline, matching the value scale.
    fn value_tick_labels(&self) -> Vec<SharedString> {
        let Some(value_fn) = self.value.as_ref() else {
            return vec![];
        };
        // The data plus zero, as `value_scale` spans.
        let (lo, hi) = self.data.iter().fold((0.0_f32, 0.0_f32), |(lo, hi), v| {
            let f = value_fn(v).to_f32().unwrap_or(0.);
            (lo.min(f), hi.max(f))
        });
        let steps = (self.value_tick_count - 1) as f32;
        (0..self.value_tick_count)
            .map(|i| {
                let value = (hi - (hi - lo) * i as f32 / steps) as f64;
                match self.value_tick_format.as_ref() {
                    Some(format) => format(value),
                    None => format_tick(value),
                }
            })
            .collect()
    }

    /// Label gaps `(band_side, value_end_side)` reserved along the value axis for
    /// horizontal bars, measured from the actual label text. Measured once per frame
    /// in `prepaint` and kept in `horizontal_gaps`, so `paint` and the tooltip share
    /// one measurement and the crosshair lines up with the bar region.
    fn measure_horizontal_gaps(&self, window: &mut Window) -> (f32, f32) {
        let Some(band_fn) = self.band.as_ref() else {
            return (0., 0.);
        };
        let font_size = px(TEXT_SIZE);
        let band_gap = if self.label_axis {
            self.data
                .iter()
                .map(|v| {
                    let s: SharedString = band_fn(v).into();
                    measure_text_width(&s, font_size, window)
                })
                .fold(0f32, f32::max)
                + TEXT_GAP * 2.
        } else {
            0.
        };
        let value_end_gap = if let Some(label_fn) = self.label.as_ref() {
            self.data
                .iter()
                .map(|v| measure_text_width(&label_fn(v), font_size, window))
                .fold(0f32, f32::max)
                + TEXT_GAP * 2.
        } else {
            TEXT_GAP * 4.
        };
        (band_gap, value_end_gap)
    }

    /// The extent `(start, length)` of the bars along the value axis, which the
    /// hover is confined to so the axis labels never show a tooltip.
    fn value_extent(&self, bounds: Bounds<Pixels>) -> (f32, f32) {
        if self.alignment.is_horizontal() {
            let (band_gap, value_end_gap) = self.horizontal_gaps;
            let length = (bounds.size.width.as_f32() - band_gap - value_end_gap).max(0.);
            let start = if matches!(self.alignment, BarAlignment::Left) {
                band_gap
            } else {
                value_end_gap
            };
            (start, length)
        } else {
            let axis_gap = if self.label_axis { AXIS_GAP } else { 0. };
            let length = bounds.size.height.as_f32() - axis_gap;
            let start = if matches!(self.alignment, BarAlignment::Top) {
                axis_gap
            } else {
                0.
            };
            (start, length)
        }
    }

    /// Whether the cursor is over a bar's row or column rather than the axis labels.
    fn is_over_bars(&self, position: Point<Pixels>, bounds: Bounds<Pixels>) -> bool {
        let (start, length) = self.value_extent(bounds);
        if self.alignment.is_horizontal() {
            let value_labels_top = bounds.size.height.as_f32() - VALUE_AXIS_GAP;
            (start..=start + length).contains(&position.x.as_f32())
                && !(self.value_axis_gap() > 0. && position.y.as_f32() > value_labels_top)
        } else {
            (start..=start + length).contains(&position.y.as_f32())
                && position.x.as_f32() >= self.band_offset()
        }
    }
}

impl<T, B, V> Plot for BarChart<T, B, V>
where
    B: Eq + Hash + Into<SharedString> + 'static,
    V: PlotValue,
{
    fn prepaint(
        &mut self,
        _bounds: Bounds<Pixels>,
        window: &mut Window,
        _cx: &mut App,
    ) -> Vec<AnyElement> {
        self.horizontal_gaps = if self.alignment.is_horizontal() {
            self.measure_horizontal_gaps(window)
        } else {
            (0., 0.)
        };
        if self.value_axis && !self.alignment.is_horizontal() {
            self.value_label_gap = value_axis_gap(self.value_tick_labels(), window);
        }
        vec![]
    }

    fn paint(&mut self, bounds: Bounds<Pixels>, window: &mut Window, cx: &mut App) {
        let (Some(band_fn), Some(value_fn)) = (self.band.as_ref(), self.value.as_ref()) else {
            return;
        };

        let total_width = bounds.size.width.as_f32();
        let total_height = bounds.size.height.as_f32();
        let alignment = self.alignment;
        let is_horizontal = alignment.is_horizontal();

        // Band scale spans the full extent perpendicular to the value axis. Shared with the
        // tooltip via `band_scale()` so the bars and the hover crosshair stay aligned.
        let Some(band_scale) = self.band_scale(bounds) else {
            return;
        };
        let band_width = band_scale.band_width();

        let Some((value_scale, baseline, far)) = self.value_scale(bounds) else {
            return;
        };

        // Where zero sits along the value axis. Bars grow from here rather than from
        // the geometric baseline, so negative values extend to the opposite side. With
        // no negative data zero is the domain minimum and this is the baseline.
        let zero_pixel = value_scale.tick(&V::zero()).unwrap_or(baseline);
        let band_offset = self.band_offset();

        // Grid lines and the zero line span their bounds edge to edge, so they are
        // painted into bounds inset by the value-axis gap. Without this they run
        // straight through the value-axis labels.
        let value_axis_gap = self.value_axis_gap();
        let plot_bounds = if is_horizontal {
            Bounds {
                origin: bounds.origin,
                size: Size::new(bounds.size.width, bounds.size.height - px(value_axis_gap)),
            }
        } else {
            Bounds {
                origin: bounds.origin + point(px(value_axis_gap), px(0.)),
                size: Size::new(bounds.size.width - px(value_axis_gap), bounds.size.height),
            }
        };

        // Draw band axis (with categorical labels).
        let mut axis = PlotAxis::new().stroke(cx.theme().border);
        if self.label_axis {
            match alignment {
                BarAlignment::Bottom | BarAlignment::Top => {
                    axis = axis.x(zero_pixel);

                    // Labels are placed one at a time rather than through
                    // `x_label`, because a chart with negative values needs them
                    // on either side of the zero line: each label goes on the side
                    // its own bar leaves empty.
                    let labeled =
                        labeled_items(self.band_slots(), self.band_tick_count, self.tick_margin);
                    let labels = self
                        .data
                        .iter()
                        .enumerate()
                        .filter(|(i, _)| labeled[*i])
                        .filter_map(|(_, d)| {
                            let band_x = band_scale.tick(&band_fn(d))?;
                            let value = value_fn(d).to_f32().unwrap_or(0.);
                            let label_y = if label_below_zero_line(value, alignment) {
                                zero_pixel + TEXT_GAP
                            } else {
                                zero_pixel - TEXT_GAP - TEXT_SIZE
                            };

                            Some(
                                Text::new(
                                    band_fn(d).into(),
                                    point(px(band_x + band_offset + band_width / 2.), px(label_y)),
                                    cx.theme().muted_foreground,
                                )
                                .align(TextAlign::Center),
                            )
                        })
                        .collect();
                    PlotLabel::new(labels).paint(&bounds, window, cx);
                }
                BarAlignment::Left | BarAlignment::Right => {
                    let labels = build_band_labels(
                        &self.data,
                        band_fn.as_ref(),
                        &band_scale,
                        band_width,
                        &labeled_items(self.band_slots(), self.band_tick_count, self.tick_margin),
                        cx.theme().muted_foreground,
                    );
                    let (side, align) = if matches!(alignment, BarAlignment::Left) {
                        (AxisLabelSide::Start, TextAlign::Right)
                    } else {
                        (AxisLabelSide::End, TextAlign::Left)
                    };
                    axis = axis
                        .y(zero_pixel)
                        .y_label_side(side)
                        .y_label(labels.into_iter().map(|t| t.align(align)));
                }
            }
        }
        axis.paint(&plot_bounds, window, cx);

        let value_ticks = value_tick_positions(far, baseline, self.value_tick_count);
        let steps = value_ticks.len() - 1;

        // Draw grid, excluding the line at the baseline.
        if self.grid {
            let grid = Grid::new().stroke(cx.theme().chart_grid);
            let grid = if self.grid_dashed {
                grid.dash_array(&[px(4.), px(2.)])
            } else {
                grid
            };
            let lines = value_ticks[..steps].to_vec();
            let grid = if is_horizontal {
                grid.x(lines)
            } else {
                grid.y(lines)
            };
            grid.paint(&plot_bounds, window);
        }

        // Labels inside the plot are painted after the bars, so no bar covers them.
        let mut inside_labels = None;
        if self.value_axis {
            // Ticks run from `far` (the domain maximum) to `baseline` (the minimum),
            // so the labels walk the domain in the same direction.
            let color = cx.theme().muted_foreground;
            let texts = self
                .value_tick_labels()
                .into_iter()
                .zip(value_ticks.iter().copied());

            match self.value_axis_label_placement {
                // The labels go in the gap `band_scale` kept clear for them,
                // right-aligned against the plot area for vertical bars and centred
                // under it otherwise.
                AxisLabelPlacement::Outside => {
                    let labels = texts.map(|(text, tick)| AxisText::new(text, px(tick), color));
                    let value_axis = if is_horizontal {
                        PlotAxis::new()
                            .x_axis(false)
                            .x(px(total_height - VALUE_AXIS_GAP))
                            .x_label(labels.map(|t| t.align(TextAlign::Center)))
                    } else {
                        PlotAxis::new()
                            .y_axis(false)
                            .y(px(value_axis_gap - TEXT_GAP * 2.))
                            .y_label(labels.map(|t| t.align(TextAlign::Right)))
                    };
                    value_axis.paint(&bounds, window, cx);
                }
                // Over the plot beside each grid line: above it for vertical bars
                // but for the topmost, which would leave the plot, and along the
                // bottom edge for horizontal ones.
                AxisLabelPlacement::Inside => {
                    let labels = texts
                        .map(|(text, tick)| {
                            if is_horizontal {
                                Text::new(text, point(tick, total_height - TEXT_HEIGHT), color)
                                    .align(TextAlign::Center)
                            } else {
                                let top = if tick < TEXT_HEIGHT {
                                    tick + TEXT_GAP
                                } else {
                                    tick - TEXT_HEIGHT
                                };
                                Text::new(text, point(TEXT_GAP, top), color)
                            }
                        })
                        .collect();
                    inside_labels = Some(PlotLabel::new(labels));
                }
            }
        }

        // Draw bars.
        let band_fn_cloned = band_fn.clone();
        let value_fn_cloned = value_fn.clone();
        let default_fill: Background = cx.theme().chart_2.into();
        let fill = self.fill.clone();
        let fill_gradient = self.fill_gradient.clone();
        let label_color = cx.theme().foreground;
        let label_color_fn = self.label_color.clone();
        let min_length = self.min_length;

        // Chart bounds in pixel space, with origin (0, 0) and size equal to
        // the full chart extent. Passed to user `fill` closures so they can
        // position chart-wide backgrounds (gradients, patterns, etc.).
        let chart_bounds: Bounds<f32> = Bounds {
            origin: Point::new(0., 0.),
            size: Size::new(total_width, total_height),
        };

        // Chart data range in f32 — passed to `fill_gradient` callers and used
        // by the `chart_to_bar` remap helper.
        let chart_range = self.gradient_range();

        // The hovered bar keeps its color while the others fade behind it. The
        // highlight band springs between bars, so each bar's emphasis follows the
        // band's distance from it and the focus hands over as the band slides.
        let hover = self.hover;
        let step = band_scale.step().max(f32::EPSILON);
        let emphasis = move |frame: Bounds<f32>| -> f32 {
            let Some(hover) = hover else {
                return 1.;
            };
            let center = if is_horizontal {
                frame.origin.y + frame.size.height / 2.
            } else {
                frame.origin.x + frame.size.width / 2.
            };
            let distance = ((center - hover.center).abs() / step).min(1.);
            1. - HOVER_DIM * hover.focus * distance
        };

        // Every bar grows out of the zero line together as the chart appears,
        // the way Chart.js draws bars in.
        let appear = self.appear.get().progress();

        let mut bar = Bar::new()
            .data(&self.data)
            .alignment(alignment)
            .band_width(band_width)
            .cross(move |d| band_scale.tick(&band_fn_cloned(d)).map(|t| t + band_offset))
            .base(move |_| zero_pixel)
            .value(move |d| {
                let end = bar_end(
                    &value_scale,
                    value_fn_cloned(d),
                    zero_pixel,
                    alignment,
                    min_length,
                )?;
                Some(zero_pixel + (end - zero_pixel) * appear)
            })
            .corner_radii(self.corner_radii);

        bar = match (fill, fill_gradient) {
            (_, Some(fg)) => {
                let value_fn_for_grad = value_fn.clone();
                bar.fill(move |d, frame, alignment| {
                    let v = value_fn_for_grad(d).to_f32().unwrap_or(0.);
                    let [s0, s1] = bar_gradient(fg.as_ref(), d, v, chart_range.clone());
                    let bg: Background = linear_gradient(alignment.gradient_angle(), s0, s1);
                    bg.opacity(emphasis(frame))
                })
            }
            (Some(f), _) => bar.fill(move |d, frame, alignment| {
                f(d, frame, chart_bounds, alignment).opacity(emphasis(frame))
            }),
            _ => bar.fill(move |_, frame, _| default_fill.opacity(emphasis(frame))),
        };

        if let Some(label) = self.label.as_ref() {
            let label = label.clone();
            let text_align = match alignment {
                BarAlignment::Bottom | BarAlignment::Top => TextAlign::Center,
                BarAlignment::Left => TextAlign::Left,
                BarAlignment::Right => TextAlign::Right,
            };
            bar = bar.label(move |d, p| {
                // A value label rides the end of its bar and fades in with it.
                let color = label_color_fn
                    .as_ref()
                    .map_or(label_color, |f| f(d))
                    .opacity(appear);
                vec![Text::new(label(d), p, color).align(text_align)]
            });
        }

        bar.paint(&bounds, window, cx);
        if let Some(labels) = inside_labels {
            labels.paint(&bounds, window, cx);
        }
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
        let band_fn = self.band.as_ref()?;
        self.value.as_ref()?;

        // Skip the tooltip when the cursor is over the axis labels, not a bar.
        if !self.is_over_bars(position, bounds) {
            return None;
        }

        // Only the band scale is needed to hit-test which bar is hovered; the label
        // gaps were measured in `prepaint`, so no `window` is required here.
        let is_horizontal = self.alignment.is_horizontal();
        let band_scale = self.band_scale(bounds)?;
        let band_width = band_scale.band_width();

        let band_offset = self.band_offset();
        let cursor_band = if is_horizontal {
            position.y
        } else {
            position.x
        };
        let index = band_scale.nearest_index(cursor_band.as_f32() - band_offset);
        let d = self.data.get(index)?;
        let center = band_scale.tick(&band_fn(d))? + band_offset + band_width / 2.;

        // Vertical bars: vertical crosshair at the bar's x. Horizontal bars: horizontal
        // crosshair at the bar's y. The box tracks the cursor either way.
        let cross_line = if is_horizontal {
            point(position.x, px(center))
        } else {
            point(px(center), position.y)
        };

        Some(TooltipState::new(index, cross_line, vec![]))
    }

    fn hover(&mut self, hover: Option<&PlotHover>, window: &mut Window, cx: &mut App) {
        self.hover = hover.map(|hover| {
            // The band slides to the hovered bar; on the first hovered frame it
            // adopts the bar instead of travelling from where the last hover ended.
            let target = if self.alignment.is_horizontal() {
                hover.state().cross_line.y
            } else {
                hover.state().cross_line.x
            };
            let center = hover.glide(("bar-chart", "band"), target, window, cx);
            BarHover {
                center: center.as_f32(),
                focus: hover.progress(),
            }
        });
    }

    fn tooltip(
        &self,
        state: &TooltipState,
        cursor: Point<Pixels>,
        bounds: Bounds<Pixels>,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        let (band_fn, value_fn) = (self.band.as_ref()?, self.value.as_ref()?);
        let d = self.data.get(state.index)?;
        let name = self.name.clone().unwrap_or_default();

        // Highlight the hovered bar with a translucent band the width of the bar, instead
        // of a hairline. Confined to the plot area so it doesn't cover the axis labels,
        // and centered where the band has glided to, which the other bars also fade by.
        let band_scale = self.band_scale(bounds)?;
        let band_width = band_scale.band_width();
        let center = self.hover.map_or(state.cross_line, |hover| {
            if self.alignment.is_horizontal() {
                point(state.cross_line.x, px(hover.center))
            } else {
                point(px(hover.center), state.cross_line.y)
            }
        });
        let (start, length) = self.value_extent(bounds);
        let cross_line = if self.alignment.is_horizontal() {
            CrossLine::new(center)
                .horizontal()
                .h_span(start, length)
                .band(px(band_width))
        } else {
            CrossLine::new(center)
                .span(start, length)
                .band(px(band_width))
        };

        let frame = self.bar_frame(d, &band_scale, bounds).unwrap_or_default();
        let swatch = self.bar_color(d, frame, bounds, cx);

        // Follow the cursor; `hover` already glides the band.
        let tooltip = Tooltip::new(cursor, bounds.size)
            .glide(false)
            .gap(px(8.))
            .cross_line(cross_line);

        let tooltip = self.tooltip_content.apply(
            tooltip,
            d,
            || Some(band_fn(d).into()),
            || Some([(swatch, name, value_fn(d).to_f64()?)]),
            window,
            cx,
        )?;

        Some(tooltip.into_any_element())
    }
}

/// The end a bar showing `value` reaches along the value axis, at least
/// `min_length` pixels from `zero`.
fn bar_end<V>(
    scale: &ScaleLinear<V>,
    value: V,
    zero: f32,
    alignment: BarAlignment,
    min_length: f32,
) -> Option<f32>
where
    V: PlotValue,
{
    let tick = scale.tick(&value)?;
    Some(extend_to_min_length(
        tick,
        zero,
        value < V::zero(),
        alignment,
        min_length,
    ))
}

/// Push a bar's value end away from `zero` until the bar is `min` pixels long,
/// in the direction its value grows for `alignment`.
fn extend_to_min_length(
    tick: f32,
    zero: f32,
    negative: bool,
    alignment: BarAlignment,
    min: f32,
) -> f32 {
    if (tick - zero).abs() >= min {
        return tick;
    }
    let grows_toward_origin = matches!(alignment, BarAlignment::Bottom | BarAlignment::Right);
    if grows_toward_origin != negative {
        zero - min
    } else {
        zero + min
    }
}

/// The two stops `fill` gives datum `d` with bar value `value`, mapped from the
/// chart's `range` onto the bar and clipped to it.
fn bar_gradient<T>(
    fill: &dyn Fn(&T, RangeInclusive<f32>, &dyn Fn(f32) -> f32) -> [LinearColorStop; 2],
    d: &T,
    value: f32,
    range: RangeInclusive<f32>,
) -> [LinearColorStop; 2] {
    let bar_lo = value.min(0.);
    let bar_span = (value.max(0.) - bar_lo).max(f32::EPSILON);
    let chart_to_bar = |chart_value: f32| (chart_value - bar_lo) / bar_span;
    clip_stops_to_bar(fill(d, range, &chart_to_bar))
}

/// Clip a two-stop gradient to bar-local `[0, 1]`, interpolating colors at the
/// clip points so the on-bar gradient matches the (possibly broader) gradient
/// the caller defined.
///
/// When a stop position falls outside `[0, 1]` (e.g. because `chart_to_bar`
/// returned a value past the bar's edge for a chart-relative gradient),
/// gpui's renderer would clamp the position and lose the gradient effect.
/// This function instead replaces such a stop with the color sampled along
/// the line through both stops at position `0.0` or `1.0`, preserving the
/// visual slice.
fn clip_stops_to_bar(stops: [LinearColorStop; 2]) -> [LinearColorStop; 2] {
    let [a, b] = stops;
    let p0 = a.percentage;
    let p1 = b.percentage;
    let lerp = |t: f32| -> Hsla {
        Hsla {
            h: a.color.h + (b.color.h - a.color.h) * t,
            s: a.color.s + (b.color.s - a.color.s) * t,
            l: a.color.l + (b.color.l - a.color.l) * t,
            a: a.color.a + (b.color.a - a.color.a) * t,
        }
    };
    let span = p1 - p0;
    let sample = |target: f32| -> Hsla {
        if span.abs() < f32::EPSILON {
            a.color
        } else {
            lerp((target - p0) / span)
        }
    };
    let new_a = if (0. ..=1.).contains(&p0) {
        a
    } else {
        LinearColorStop {
            color: sample(p0.clamp(0., 1.)),
            percentage: p0.clamp(0., 1.),
        }
    };
    let new_b = if (0. ..=1.).contains(&p1) {
        b
    } else {
        LinearColorStop {
            color: sample(p1.clamp(0., 1.)),
            percentage: p1.clamp(0., 1.),
        }
    };
    [new_a, new_b]
}

/// Whether a vertical bar's category label belongs below the zero line.
///
/// A bar grows away from the zero line, so its label goes on the side the bar
/// leaves empty. Which side that is flips with both the sign of the value and the
/// alignment. A zero-length bar counts as positive, which puts its label in the
/// axis gap rather than inside the plot.
fn label_below_zero_line(value: f32, alignment: BarAlignment) -> bool {
    (value < 0.) == (alignment == BarAlignment::Top)
}

/// `count` evenly spaced tick positions along the value axis.
///
/// Runs from `far` (the value domain's maximum) through `baseline` (its minimum)
/// inclusive, so the last position is the baseline. `count` is at least 2.
fn value_tick_positions(far: f32, baseline: f32, count: usize) -> Vec<f32> {
    let steps = (count - 1) as f32;
    (0..count)
        .map(|i| far + (baseline - far) * i as f32 / steps)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_label_below_zero_line() {
        // Bottom-aligned: positive bars grow up, leaving the space below free.
        assert!(label_below_zero_line(5., BarAlignment::Bottom));
        assert!(label_below_zero_line(0., BarAlignment::Bottom));
        assert!(!label_below_zero_line(-5., BarAlignment::Bottom));

        // Top-aligned bars grow the other way, so the sides swap.
        assert!(!label_below_zero_line(5., BarAlignment::Top));
        assert!(!label_below_zero_line(0., BarAlignment::Top));
        assert!(label_below_zero_line(-5., BarAlignment::Top));
    }

    #[test]
    fn test_value_tick_positions() {
        // Both ends are included, so 5 ticks means 4 intervals.
        assert_eq!(
            value_tick_positions(10., 110., 5),
            vec![10., 35., 60., 85., 110.]
        );

        // Top-aligned charts have the baseline before the far edge.
        assert_eq!(value_tick_positions(110., 10., 3), vec![110., 60., 10.]);

        assert_eq!(value_tick_positions(0., 50., 2), vec![0., 50.]);
    }

    #[test]
    fn test_min_length_extends_away_from_zero() {
        // A zero or tiny bar grows the way a positive one would.
        assert_eq!(
            extend_to_min_length(100., 100., false, BarAlignment::Bottom, 2.),
            98.
        );
        assert_eq!(
            extend_to_min_length(10., 10., false, BarAlignment::Top, 2.),
            12.
        );
        assert_eq!(
            extend_to_min_length(10., 10., false, BarAlignment::Left, 2.),
            12.
        );
        assert_eq!(
            extend_to_min_length(90., 90., false, BarAlignment::Right, 2.),
            88.
        );

        // A small negative bar grows to the other side of the zero line.
        assert_eq!(
            extend_to_min_length(50.5, 50., true, BarAlignment::Bottom, 2.),
            52.
        );

        // A bar already long enough is left alone.
        assert_eq!(
            extend_to_min_length(40., 100., false, BarAlignment::Bottom, 2.),
            40.
        );
    }

    #[test]
    fn value_tick_labels_walk_the_domain_from_the_far_end() {
        use super::BarChart;

        let chart = BarChart::new([10., 20.])
            .band(|v| format!("{v}"))
            .value(|v| *v)
            .value_tick_count(3);
        assert_eq!(chart.value_tick_labels(), vec!["20", "10", "0"]);

        let money = chart.value_tick_format(|v| format!("${v:.0}"));
        assert_eq!(money.value_tick_labels(), vec!["$20", "$10", "$0"]);

        // Labels spread over every band, so they stay put as the data grows.
        assert_eq!(money.band_count(12).band_slots(), 12);
    }

    #[test]
    fn a_band_count_keeps_each_bar_in_its_band() {
        use gpui::{Bounds, point, px, size};

        use super::BarChart;
        use crate::plot::{AxisLabelPlacement, scale::Scale};

        let bounds = Bounds::new(point(px(0.), px(0.)), size(px(40.), px(100.)));
        let chart = |data: &[f64], count| {
            BarChart::new(data.to_vec())
                .band(|v| format!("{v}"))
                .value(|v| *v)
                .band_count(count)
        };

        // Two bars laid out for four bands take the first half of the width.
        let wide = chart(&[1., 2.], 2).band_scale(bounds).unwrap();
        let narrow = chart(&[1., 2.], 4).band_scale(bounds).unwrap();
        assert_eq!(narrow.band_width() * 2., wide.band_width());
        assert!(narrow.tick(&"2".to_string()).unwrap() < 20.);

        // A bar keeps its place as the data grows into the empty bands.
        let grown = chart(&[1., 2., 3.], 4).band_scale(bounds).unwrap();
        assert_eq!(grown.tick(&"2".to_string()), narrow.tick(&"2".to_string()));
        assert_eq!(grown.band_width(), narrow.band_width());

        // Labels inside the plot leave the bars their full width.
        let outside = chart(&[1., 2.], 2).value_axis(true);
        let inside = chart(&[1., 2.], 2)
            .value_axis(true)
            .value_axis_label_placement(AxisLabelPlacement::Inside);
        assert_eq!(outside.value_axis_gap(), super::VALUE_AXIS_GAP);
        assert_eq!(inside.value_axis_gap(), 0.);
    }

    /// A tooltip row shows its bar's color: a solid fill as is, a
    /// `fill_gradient` by its first stop, and the default fill otherwise.
    #[gpui::test]
    fn the_tooltip_swatch_follows_the_bar_color(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        let bars = || {
            BarChart::new([1., -2.])
                .band(|d: &f64| SharedString::from(format!("{d}")))
                .value(|d: &f64| *d)
        };
        let frame = Bounds::default();
        let bounds = Bounds::new(point(px(0.), px(0.)), gpui::size(px(100.), px(100.)));
        let (default, solid, gradient, stops) = cx.update(|cx| {
            let gain = gpui::green();
            let loss = gpui::red();
            let default = bars().bar_color(&1., frame, bounds, cx);
            let solid = bars()
                .fill(move |d: &f64, _, _, _| if *d >= 0. { gain } else { loss })
                .bar_color(&-2., frame, bounds, cx);
            let gradient = bars()
                .fill(move |_: &f64, _, _, _| {
                    linear_gradient(
                        0.,
                        gpui::linear_color_stop(gain, 0.),
                        gpui::linear_color_stop(loss, 1.),
                    )
                })
                .bar_color(&1., frame, bounds, cx);
            let stops = bars()
                .fill_gradient(move |_: &f64, _, _| {
                    [
                        gpui::linear_color_stop(gain, 0.),
                        gpui::linear_color_stop(loss, 1.),
                    ]
                })
                .bar_color(&1., frame, bounds, cx);
            (default, solid, gradient, stops)
        });
        let chart_2 = cx.update(|cx| cx.theme().chart_2);

        assert_eq!(default, chart_2);
        assert_eq!(solid, gpui::red());
        assert_eq!(gradient, chart_2);
        assert_eq!(stops, gpui::green());
    }

    /// The tooltip reads each bar's frame as `paint` lays it out, so a `fill`
    /// that reads the frame colors the swatch as it colors the bar.
    #[test]
    fn the_tooltip_reads_the_painted_bar_frame() {
        let bars = BarChart::new([1., -2.])
            .band(|d: &f64| SharedString::from(format!("{d}")))
            .value(|d: &f64| *d);
        let bounds = Bounds::new(point(px(0.), px(0.)), gpui::size(px(100.), px(100.)));
        let band_scale = bars.band_scale(bounds).expect("bars have a band scale");
        let up = bars.bar_frame(&1., &band_scale, bounds).expect("a frame");
        let down = bars.bar_frame(&-2., &band_scale, bounds).expect("a frame");

        // Both grow from zero: one up, one down twice as far.
        assert_eq!(up.origin.y + up.size.height, down.origin.y);
        assert!((down.size.height - 2. * up.size.height).abs() < 0.01);
        assert!(up.origin.x < down.origin.x);
        assert_eq!(up.size.width, band_scale.band_width());
    }
}
