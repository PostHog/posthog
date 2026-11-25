use std::{hash::Hash, rc::Rc};

use gpui::{
    AnyElement, App, Bounds, ElementId, Hsla, IntoElement, Pixels, Point, SharedString, Window,
    fill, point, px,
};
use gpui_component_macros::IntoPlot;
use rust_i18n::t;

use crate::{
    ActiveTheme,
    plot::{
        Grid, Plot, PlotAppear, PlotAxis, origin_point,
        scale::{PlotValue, Scale, ScaleBand, ScaleLinear},
        tooltip::{CrossLine, Tooltip, TooltipState},
    },
};

use super::{
    AXIS_GAP, ChartAppear, MAX_BAND_WIDTH, TooltipContent, build_band_labels, caller_id,
    labeled_items, reveal_mask,
};

#[derive(IntoPlot)]
pub struct CandlestickChart<T, X, Y>
where
    T: 'static,
    X: Eq + Hash + Into<SharedString> + 'static,
    Y: PlotValue,
{
    data: Vec<T>,
    x: Option<Rc<dyn Fn(&T) -> X>>,
    open: Option<Rc<dyn Fn(&T) -> Y>>,
    high: Option<Rc<dyn Fn(&T) -> Y>>,
    low: Option<Rc<dyn Fn(&T) -> Y>>,
    close: Option<Rc<dyn Fn(&T) -> Y>>,
    tick_margin: usize,
    body_width_ratio: f32,
    max_band_width: Pixels,
    x_axis: bool,
    grid: bool,
    bullish: Option<Hsla>,
    bearish: Option<Hsla>,
    id: ElementId,
    interactive: bool,
    appear: ChartAppear,
    tooltip_content: TooltipContent<T>,
}

impl<T, X, Y> CandlestickChart<T, X, Y>
where
    X: Eq + Hash + Into<SharedString> + 'static,
    Y: PlotValue,
{
    #[track_caller]
    pub fn new<I>(data: I) -> Self
    where
        I: IntoIterator<Item = T>,
    {
        Self {
            data: data.into_iter().collect(),
            x: None,
            open: None,
            high: None,
            low: None,
            close: None,
            tick_margin: 1,
            body_width_ratio: 0.8,
            max_band_width: px(MAX_BAND_WIDTH),
            x_axis: true,
            grid: true,
            bullish: None,
            bearish: None,
            id: caller_id(),
            interactive: true,
            appear: ChartAppear::default(),
            tooltip_content: TooltipContent::default(),
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
    /// The layer is the hitbox under the cursor and what it drives: a highlight
    /// band marks the hovered candle, and a tooltip shows its open, high, low and
    /// close. Turn it off for a chart that only decorates, or one an element
    /// above it wants the cursor for: without a hitbox it neither answers the
    /// mouse nor takes the hover from what sits over it.
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

    /// Set the hover tooltip's title for a datum, instead of its x value.
    pub fn tooltip_title(mut self, title: impl Fn(&T) -> SharedString + 'static) -> Self {
        self.tooltip_content.set_title(title);
        self
    }

    /// Set the text of each tooltip row's value; the raw number by default.
    ///
    /// The closure receives the datum, the row's index (0 to 3 for open, high, low and close) and
    /// the value the row reads.
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

    pub fn x(mut self, x: impl Fn(&T) -> X + 'static) -> Self {
        self.x = Some(Rc::new(x));
        self
    }

    pub fn open(mut self, open: impl Fn(&T) -> Y + 'static) -> Self {
        self.open = Some(Rc::new(open));
        self
    }

    pub fn high(mut self, high: impl Fn(&T) -> Y + 'static) -> Self {
        self.high = Some(Rc::new(high));
        self
    }

    pub fn low(mut self, low: impl Fn(&T) -> Y + 'static) -> Self {
        self.low = Some(Rc::new(low));
        self
    }

    pub fn close(mut self, close: impl Fn(&T) -> Y + 'static) -> Self {
        self.close = Some(Rc::new(close));
        self
    }

    pub fn tick_margin(mut self, tick_margin: usize) -> Self {
        self.tick_margin = tick_margin;
        self
    }

    pub fn body_width_ratio(mut self, ratio: f32) -> Self {
        self.body_width_ratio = ratio;
        self
    }

    /// Keep every candle's band at most `width` wide, so a few candles across
    /// a wide chart stay narrow.
    ///
    /// Default is 30px.
    pub fn max_band_width(mut self, width: impl Into<Pixels>) -> Self {
        self.max_band_width = width.into();
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

    /// Set the color of a candle that closed above its open.
    ///
    /// Defaults to the theme's `chart.bullish` color. Markets that read a rise
    /// as red set this and [`Self::bearish`] the other way round.
    pub fn bullish(mut self, color: impl Into<Hsla>) -> Self {
        self.bullish = Some(color.into());
        self
    }

    /// Set the color of a candle that closed at or below its open.
    ///
    /// Defaults to the theme's `chart.bearish` color.
    pub fn bearish(mut self, color: impl Into<Hsla>) -> Self {
        self.bearish = Some(color.into());
        self
    }

    /// The candle colors, `(bullish, bearish)`, set or from the theme.
    fn candle_colors(&self, cx: &App) -> (Hsla, Hsla) {
        (
            self.bullish.unwrap_or(cx.theme().chart_bullish),
            self.bearish.unwrap_or(cx.theme().chart_bearish),
        )
    }

    /// The band scale along the x axis. Shared by `paint` and `tooltip_state` so
    /// the candles and the hover band stay aligned.
    fn x_scale(&self, bounds: Bounds<Pixels>) -> Option<ScaleBand<X>> {
        let x_fn = self.x.as_ref()?;
        Some(
            ScaleBand::new(
                self.data.iter().map(|v| x_fn(v)),
                [0., bounds.size.width.as_f32()],
            )
            .max_band_width(self.max_band_width.as_f32())
            .padding_inner(0.4)
            .padding_outer(0.2),
        )
    }

    /// The height of the plot area above the x-axis labels.
    fn plot_height(&self, bounds: Bounds<Pixels>) -> f32 {
        bounds.size.height.as_f32() - if self.x_axis { AXIS_GAP } else { 0. }
    }
}

impl<T, X, Y> Plot for CandlestickChart<T, X, Y>
where
    X: Eq + Hash + Into<SharedString> + 'static,
    Y: PlotValue,
{
    fn paint(&mut self, bounds: Bounds<Pixels>, window: &mut Window, cx: &mut App) {
        let (Some(x_fn), Some(open_fn), Some(high_fn), Some(low_fn), Some(close_fn)) = (
            self.x.as_ref(),
            self.open.as_ref(),
            self.high.as_ref(),
            self.low.as_ref(),
            self.close.as_ref(),
        ) else {
            return;
        };

        let height = self.plot_height(bounds);

        // X scale
        let Some(x) = self.x_scale(bounds) else {
            return;
        };
        let band_width = x.band_width();

        // Y scale
        let all_values: Vec<Y> = self
            .data
            .iter()
            .flat_map(|d| vec![high_fn(d), low_fn(d), open_fn(d), close_fn(d)])
            .collect();
        let y = ScaleLinear::new(all_values, [height, 10.]);

        // Draw X axis
        let mut axis = PlotAxis::new().stroke(cx.theme().border);
        if self.x_axis {
            let labels = build_band_labels(
                &self.data,
                x_fn.as_ref(),
                &x,
                band_width,
                &labeled_items(self.data.len(), None, self.tick_margin),
                cx.theme().muted_foreground,
            );
            axis = axis.x(height).x_label(labels);
        }
        axis.paint(&bounds, window, cx);

        // Draw grid
        if self.grid {
            Grid::new()
                .y((0..=3).map(|i| height * i as f32 / 4.0))
                .stroke(cx.theme().border)
                .dash_array(&[px(4.), px(2.)])
                .paint(&bounds, window);
        }

        // Draw candlesticks
        let (bullish, bearish) = self.candle_colors(cx);
        let origin = bounds.origin;
        let x_fn = x_fn.clone();
        let open_fn = open_fn.clone();
        let high_fn = high_fn.clone();
        let low_fn = low_fn.clone();
        let close_fn = close_fn.clone();

        // The candles draw in from the left under a mask.
        let reveal = reveal_mask(bounds, 0., self.appear.get().progress());
        window.with_content_mask(reveal, |window| {
            for d in &self.data {
                let x_tick = x.tick(&x_fn(d));
                let Some(x_tick) = x_tick else {
                    continue;
                };

                // Get OHLC values for the current data point
                let open = open_fn(d);
                let high = high_fn(d);
                let low = low_fn(d);
                let close = close_fn(d);

                // Convert values to pixel coordinates
                let open_y = y.tick(&open);
                let high_y = y.tick(&high);
                let low_y = y.tick(&low);
                let close_y = y.tick(&close);

                let (Some(open_y), Some(high_y), Some(low_y), Some(close_y)) =
                    (open_y, high_y, low_y, close_y)
                else {
                    continue;
                };

                // Determine if bullish (close > open) or bearish (close < open)
                let is_bullish = close > open;
                let color = if is_bullish { bullish } else { bearish };

                // Calculate candlestick body dimensions
                let center_x = x_tick + band_width / 2.;
                let body_width = band_width * self.body_width_ratio;
                let body_left = center_x - body_width / 2.;
                let body_right = center_x + body_width / 2.;

                // Draw wick (high to low line): a 1px quad, so no stroke to tessellate.
                let (wick_top, wick_bottom) = (high_y.min(low_y), high_y.max(low_y));
                let wick_bounds = Bounds::from_corners(
                    origin_point(px(center_x - 0.5), px(wick_top), origin),
                    origin_point(px(center_x + 0.5), px(wick_bottom), origin),
                );
                window.paint_quad(fill(wick_bounds, color));

                // Draw body (open to close rectangle)
                // For bullish: top is close, bottom is open
                // For bearish: top is open, bottom is close
                let (top, bottom) = if is_bullish {
                    (close_y, open_y)
                } else {
                    (open_y, close_y)
                };

                let body_bounds = Bounds::from_corners(
                    origin_point(px(body_left), px(top), origin),
                    origin_point(px(body_right), px(bottom), origin),
                );

                window.paint_quad(fill(body_bounds, color));
            }
        });
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
        let x_fn = self.x.as_ref()?;
        let x = self.x_scale(bounds)?;

        // Ignore the x-axis label gutter so hovering the labels doesn't show a tooltip.
        if position.y.as_f32() > self.plot_height(bounds) {
            return None;
        }

        let index = x.nearest_index(position.x.as_f32());
        let d = self.data.get(index)?;
        let center = x.tick(&x_fn(d))? + x.band_width() / 2.;

        Some(TooltipState::new(
            index,
            point(px(center), position.y),
            vec![],
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
        let (x_fn, open_fn, high_fn, low_fn, close_fn) = (
            self.x.as_ref()?,
            self.open.as_ref()?,
            self.high.as_ref()?,
            self.low.as_ref()?,
            self.close.as_ref()?,
        );
        let d = self.data.get(state.index)?;
        let (open, close) = (open_fn(d), close_fn(d));
        let (bullish, bearish) = self.candle_colors(cx);
        let color = if close > open { bullish } else { bearish };

        // Highlight the hovered candle with a translucent band the width of its
        // slot, which glides between candles, confined to the plot area above the
        // axis labels.
        let band_width = self.x_scale(bounds)?.band_width();
        let cross_line = CrossLine::new(state.cross_line)
            .span(0., self.plot_height(bounds))
            .band(px(band_width));

        let tooltip = Tooltip::new(cursor, bounds.size)
            .gap(px(8.))
            .cross_line(cross_line);
        let tooltip = self.tooltip_content.apply(
            tooltip,
            d,
            || Some(x_fn(d).into()),
            || {
                [
                    (t!("Chart.open"), open),
                    (t!("Chart.high"), high_fn(d)),
                    (t!("Chart.low"), low_fn(d)),
                    (t!("Chart.close"), close),
                ]
                .into_iter()
                .map(|(label, value)| Some((color, label.to_string().into(), value.to_f64()?)))
                .collect::<Option<Vec<_>>>()
            },
            window,
            cx,
        )?;

        Some(tooltip.into_any_element())
    }
}
