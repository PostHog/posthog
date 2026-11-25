use gpui::{
    AnyElement, App, Div, ElementId, Half as _, Hsla, IntoElement, ParentElement, Pixels, Point,
    RenderOnce, SharedString, Size, StyleRefinement, Styled, Window, deferred, div, point,
    prelude::FluentBuilder, px,
};
use gpui_base::motion::spring;
pub use gpui_base::plot::{PlotHover, TooltipState};
use gpui_base::plot::{hover_progress, is_hover_entering, pointer_spring};

use crate::ThemeStyled as _;
use crate::{ActiveTheme, Colorize, StyledExt, h_flex, v_flex};

/// The spring ids a tooltip glides its crosshair with, within the plot's scope.
const GLIDE: &str = "__plot-tooltip-glide";

#[derive(Default)]
pub enum CrossLineAxis {
    #[default]
    Vertical,
    Horizontal,
    Both,
}

impl CrossLineAxis {
    /// Returns true if the cross line axis is vertical or both.
    #[inline]
    pub fn show_vertical(&self) -> bool {
        matches!(self, CrossLineAxis::Vertical | CrossLineAxis::Both)
    }

    /// Returns true if the cross line axis is horizontal or both.
    #[inline]
    pub fn show_horizontal(&self) -> bool {
        matches!(self, CrossLineAxis::Horizontal | CrossLineAxis::Both)
    }
}

#[derive(IntoElement)]
pub struct CrossLine {
    point: Point<Pixels>,
    /// Span `(start, length)` of the vertical line along the y axis; `length` of `None`
    /// spans the full height.
    vertical: (f32, Option<f32>),
    /// Span `(start, length)` of the horizontal line along the x axis; `length` of `None`
    /// spans the full width.
    horizontal: (f32, Option<f32>),
    /// Band thickness perpendicular to the line (solid band mode only).
    thickness: Pixels,
    /// `true` (default) draws a dashed hairline; `false` a solid band of `thickness`.
    dashed: bool,
    direction: CrossLineAxis,
}

impl CrossLine {
    pub fn new(point: Point<Pixels>) -> Self {
        Self {
            point,
            vertical: (0., None),
            horizontal: (0., None),
            thickness: px(1.),
            dashed: true,
            direction: Default::default(),
        }
    }

    /// Render a solid translucent highlight band of `thickness` (centered on `point`)
    /// instead of the default dashed hairline. Use the bar/band width to highlight the
    /// hovered column or row.
    pub fn band(mut self, thickness: impl Into<Pixels>) -> Self {
        self.thickness = thickness.into();
        self.dashed = false;
        self
    }

    /// Set the cross line axis to horizontal.
    pub fn horizontal(mut self) -> Self {
        self.direction = CrossLineAxis::Horizontal;
        self
    }

    /// Set the cross line axis to both.
    pub fn both(mut self) -> Self {
        self.direction = CrossLineAxis::Both;
        self
    }

    /// Set the vertical line's length along the y axis (from the top edge).
    pub fn height(mut self, height: f32) -> Self {
        self.vertical.1 = Some(height);
        self
    }

    /// Set the horizontal line's length along the x axis (from the left edge).
    pub fn width(mut self, width: f32) -> Self {
        self.horizontal.1 = Some(width);
        self
    }

    /// Confine the vertical line to `[start, start + length]` along the y axis, so it
    /// stays within the plot area.
    pub fn span(mut self, start: f32, length: f32) -> Self {
        self.vertical = (start, Some(length));
        self
    }

    /// Confine the horizontal line to `[start, start + length]` along the x axis, so it
    /// stays within the plot area.
    pub fn h_span(mut self, start: f32, length: f32) -> Self {
        self.horizontal = (start, Some(length));
        self
    }
}

impl From<Point<Pixels>> for CrossLine {
    fn from(value: Point<Pixels>) -> Self {
        Self::new(value)
    }
}

impl CrossLine {
    /// Build a single line along one axis: `vertical` runs top→bottom at the data point's
    /// `x`; otherwise left→right at its `y`. A dashed hairline draws a 1px dashed border; a
    /// solid band fills a `thickness`-wide strip centered on the data point.
    fn line(&self, vertical: bool, cx: &App) -> Div {
        let color = if self.dashed {
            cx.theme().border.mix(cx.theme().foreground, 0.8)
        } else {
            cx.theme().foreground.opacity(0.08)
        };
        // The dashed hairline is a zero-width strip drawn entirely by its 1px border.
        let thickness = if self.dashed { px(0.) } else { self.thickness };
        // Each axis carries its own span so a `both` crosshair can confine the vertical
        // and horizontal lines independently.
        let (start, length) = if vertical {
            self.vertical
        } else {
            self.horizontal
        };

        let el = div().absolute();
        let el = if vertical {
            el.left(self.point.x - thickness * 0.5)
                .w(thickness)
                .top(px(start))
                .map(|el| match length {
                    Some(length) => el.h(px(length)),
                    None => el.h_full(),
                })
        } else {
            el.top(self.point.y - thickness * 0.5)
                .h(thickness)
                .left(px(start))
                .map(|el| match length {
                    Some(length) => el.w(px(length)),
                    None => el.w_full(),
                })
        };

        if self.dashed {
            let el = if vertical {
                el.border_l_1()
            } else {
                el.border_t_1()
            };
            el.border_dashed().border_color(color)
        } else {
            el.bg(color)
        }
    }
}

impl RenderOnce for CrossLine {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let vertical = self.direction.show_vertical().then(|| self.line(true, cx));
        let horizontal = self
            .direction
            .show_horizontal()
            .then(|| self.line(false, cx));

        div()
            .size_full()
            .absolute()
            .top_0()
            .left_0()
            .children(vertical)
            .children(horizontal)
    }
}

#[derive(IntoElement)]
pub struct Dot {
    point: Point<Pixels>,
    size: Pixels,
    stroke: Hsla,
    fill: Hsla,
    /// Diameter of the translucent ring behind the dot; `None` draws no ring.
    halo: Option<Pixels>,
}

impl Dot {
    pub fn new(point: Point<Pixels>) -> Self {
        Self {
            point,
            size: px(6.),
            stroke: gpui::transparent_black(),
            fill: gpui::transparent_black(),
            halo: None,
        }
    }

    /// Set the size of the dot.
    pub fn size(mut self, size: impl Into<Pixels>) -> Self {
        self.size = size.into();
        self
    }

    /// Draw a translucent ring of the fill color, `size` across, behind the dot,
    /// which marks the hovered point the way a chart marks its emphasized
    /// symbol.
    ///
    /// `size` is the ring at full hover progress: in a [`Tooltip`] the ring grows out of
    /// the dot as the hover fades in.
    pub fn halo(mut self, size: impl Into<Pixels>) -> Self {
        self.halo = Some(size.into());
        self
    }

    /// Set the stroke of the dot.
    pub fn stroke(mut self, stroke: Hsla) -> Self {
        self.stroke = stroke;
        self
    }

    /// Set the fill of the dot.
    pub fn fill(mut self, fill: Hsla) -> Self {
        self.fill = fill;
        self
    }
}

impl RenderOnce for Dot {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let border_width = px(1.);
        let offset = self.size / 2. - border_width / 2.;

        let dot = div()
            .absolute()
            .w(self.size)
            .h(self.size)
            .rounded_full()
            .border(border_width)
            .border_color(self.stroke)
            .bg(self.fill)
            .left(self.point.x - offset)
            .top(self.point.y - offset);

        // The ring paints first so it sits behind the dot, both centered on the
        // point.
        let halo = self.halo.map(|halo| {
            div()
                .absolute()
                .size(halo)
                .rounded_full()
                .bg(self.fill.opacity(0.2))
                .left(self.point.x - halo / 2.)
                .top(self.point.y - halo / 2.)
        });

        div().absolute().top_0().left_0().children(halo).child(dot)
    }
}

/// A single labelled row in a [`Tooltip`]: an optional colored swatch, a muted label, and a value.
struct TooltipRow {
    color: Option<Hsla>,
    label: SharedString,
    value: SharedString,
    value_color: Option<Hsla>,
}

#[derive(IntoElement)]
pub struct Tooltip {
    base: Div,
    gap: Pixels,
    cross_line: Option<CrossLine>,
    dots: Option<Vec<Dot>>,
    appearance: bool,
    title: Option<SharedString>,
    rows: Vec<TooltipRow>,
    /// Cursor position the box hugs (relative to the plot origin).
    cursor: Point<Pixels>,
    /// Plot size, used to flip the box toward the center near each edge so it never
    /// overflows the near side.
    within: Size<Pixels>,
    /// Opacity of the whole overlay when set; see [`Self::progress`].
    progress: Option<f32>,
    /// Whether the crosshair and dots glide between data; see [`Self::glide`].
    glide: bool,
}

impl Tooltip {
    /// Create a tooltip whose box follows the cursor at `cursor` within a `within`-sized plot.
    pub fn new(cursor: Point<Pixels>, within: Size<Pixels>) -> Self {
        Self {
            // The same row rhythm the structured content lays out with, so a
            // tooltip built from freeform children does not have to rediscover
            // it — and does not read as one solid block when it forgets.
            base: v_flex().gap_y_1(),
            gap: px(0.),
            cross_line: None,
            dots: None,
            appearance: true,
            title: None,
            rows: Vec::new(),
            cursor,
            within,
            progress: None,
            glide: true,
        }
    }

    /// Glide the crosshair and dots between data, or snap them to each datum.
    ///
    /// A tooltip returned from [`Plot::tooltip`](super::Plot::tooltip) slides
    /// them to the hovered datum on the pointer spring, adopting it on the
    /// frame the cursor lands instead of travelling from where the last hover
    /// ended. A crosshair glides along the axis it marks only, so a line that
    /// also follows the cursor keeps up with it. Turn this off for positions
    /// the plot already springs itself ([`PlotHover::glide`]).
    ///
    /// Default is true.
    pub fn glide(mut self, glide: bool) -> Self {
        self.glide = glide;
        self
    }

    /// Fade the whole overlay — crosshair, dots and box — to `progress` (`0..=1`).
    ///
    /// A tooltip returned from [`Plot::tooltip`](super::Plot::tooltip) already
    /// follows the plot's hover, easing in when the cursor lands on a datum and
    /// out after it leaves ([`PlotHover::progress`]); set this to override that,
    /// or to fade a tooltip rendered outside a plot.
    pub fn progress(mut self, progress: f32) -> Self {
        self.progress = Some(progress.clamp(0., 1.));
        self
    }

    #[deprecated(since = "0.7.0", note = "use `progress`")]
    pub fn focus(self, focus: f32) -> Self {
        self.progress(focus)
    }

    /// Set a bold title row shown at the top of the tooltip (e.g. the hovered x value).
    pub fn title(mut self, title: impl Into<SharedString>) -> Self {
        self.title = Some(title.into());
        self
    }

    /// Append a series row: a colored swatch, a muted `label`, and a right-aligned `value`.
    pub fn row(
        mut self,
        color: impl Into<Hsla>,
        label: impl Into<SharedString>,
        value: impl Into<SharedString>,
    ) -> Self {
        self.rows.push(TooltipRow {
            color: Some(color.into()),
            label: label.into(),
            value: value.into(),
            value_color: None,
        });
        self
    }

    /// Append a row without a swatch, for a figure no series on the plot draws,
    /// such as a total or a ratio.
    ///
    /// Among series rows its label lines up with theirs; without any, the
    /// labels sit at the start.
    pub fn plain_row(
        mut self,
        label: impl Into<SharedString>,
        value: impl Into<SharedString>,
    ) -> Self {
        self.rows.push(TooltipRow {
            color: None,
            label: label.into(),
            value: value.into(),
            value_color: None,
        });
        self
    }

    /// Color the value of the row added last — by [`row`](Self::row) or
    /// [`plain_row`](Self::plain_row) — such as green or red by its sign. The
    /// value reads in the tooltip's text color otherwise.
    ///
    /// Call it right after the row it colors; before any row it does nothing.
    pub fn value_color(mut self, color: impl Into<Hsla>) -> Self {
        if let Some(row) = self.rows.last_mut() {
            row.value_color = Some(color.into());
        }
        self
    }

    /// Set the gap of the tooltip.
    pub fn gap(mut self, gap: impl Into<Pixels>) -> Self {
        self.gap = gap.into();
        self
    }

    /// Set the cross line of the tooltip.
    pub fn cross_line(mut self, cross_line: CrossLine) -> Self {
        self.cross_line = Some(cross_line);
        self
    }

    /// Set the dots of the tooltip.
    pub fn dots(mut self, dots: impl IntoIterator<Item = Dot>) -> Self {
        self.dots = Some(dots.into_iter().collect());
        self
    }

    /// Set the appearance of the tooltip.
    pub fn appearance(mut self, appearance: bool) -> Self {
        self.appearance = appearance;
        self
    }
}

impl Styled for Tooltip {
    fn style(&mut self) -> &mut StyleRefinement {
        self.base.style()
    }
}

impl ParentElement for Tooltip {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.base.extend(elements);
    }
}

/// Whether the rows keep a swatch slot: when any has a swatch, so a plain row's
/// label lines up with the series labels, and not when every row is plain.
fn has_swatches(rows: &[TooltipRow]) -> bool {
    rows.iter().any(|row| row.color.is_some())
}

#[cfg(test)]
impl Tooltip {
    pub(crate) fn title_for_test(&self) -> Option<&SharedString> {
        self.title.as_ref()
    }

    pub(crate) fn rows_for_test(&self) -> Vec<(SharedString, Option<Hsla>)> {
        self.rows
            .iter()
            .map(|row| (row.value.clone(), row.value_color))
            .collect()
    }
}

impl RenderOnce for Tooltip {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        // Rendered within the plot's element scope, so this is the fade the
        // plot tracked for it this frame; fully opaque outside a plot.
        let tracked_progress = hover_progress(window, cx);
        let entering = is_hover_entering(window, cx);
        let Tooltip {
            base,
            gap,
            mut cross_line,
            mut dots,
            appearance,
            title,
            rows,
            cursor,
            within,
            progress,
            glide,
        } = self;
        let progress = progress.unwrap_or(tracked_progress);

        if glide {
            let policy = pointer_spring(cx).with_travel(!entering);
            if let Some(line) = cross_line.as_mut() {
                if line.direction.show_vertical() {
                    line.point.x = spring((GLIDE, "x"), line.point.x, policy, window, cx);
                }
                if line.direction.show_horizontal() {
                    line.point.y = spring((GLIDE, "y"), line.point.y, policy, window, cx);
                }
            }
            for (i, dot) in dots.iter_mut().flatten().enumerate() {
                dot.point = point(
                    spring(
                        ElementId::named_usize("__plot-hover-dot-x", i),
                        dot.point.x,
                        policy,
                        window,
                        cx,
                    ),
                    spring(
                        ElementId::named_usize("__plot-hover-dot-y", i),
                        dot.point.y,
                        policy,
                        window,
                        cx,
                    ),
                );
            }
        }
        // The ring grows out of the dot as the hover fades in.
        for dot in dots.iter_mut().flatten() {
            dot.halo = dot.halo.map(|halo| halo * progress);
        }

        // Structured content (title + rows) takes precedence over freeform `base` children.
        let content = if title.is_some() || !rows.is_empty() {
            let swatched = has_swatches(&rows);
            v_flex()
                .gap_1()
                .when_some(title, |this, title| {
                    this.child(div().font_semibold().child(title))
                })
                .children(rows.into_iter().map(|row| {
                    h_flex()
                        .items_center()
                        .justify_between()
                        .gap_3()
                        .child(
                            h_flex()
                                .items_center()
                                .gap_1p5()
                                .when(swatched, |this| {
                                    this.child(
                                        div()
                                            .size_2()
                                            .rounded(cx.theme().radius.half())
                                            .when_some(row.color, |this, color| this.bg(color)),
                                    )
                                })
                                .child(
                                    div()
                                        .text_color(cx.theme().muted_foreground)
                                        .child(row.label),
                                ),
                        )
                        .child(
                            div()
                                .when_some(row.value_color, |this, color| this.text_color(color))
                                .child(row.value),
                        )
                }))
        } else {
            base
        };
        // One size for every tooltip, structured or freeform, boxed or bare: a
        // transient overlay over dense data reads at the compact tier, and a
        // per-call-site size is how a dozen charts end up at a dozen sizes.
        // Content that wants a hierarchy sets it on its own children.
        let content = content.text_xs();

        div()
            .size_full()
            .absolute()
            .top_0()
            .left_0()
            .opacity(progress)
            .when_some(cross_line, |this, cross_line| this.child(cross_line))
            .when_some(dots, |this, dots| this.children(dots))
            // Only the box is deferred: it can overflow the plot bounds and must paint above
            // sibling content, while the crosshair and dots stay in the plot's own layer so
            // they don't cover elements drawn over the plot. A deferred draw paints outside
            // this element's opacity, so the box carries the fade itself.
            .child(deferred(content.map(|mut this| {
                if !appearance {
                    return this.size_full().relative().opacity(progress);
                }

                // Default min width only applies when the caller hasn't set one, so a
                // custom `min_w` isn't clobbered here.
                let min_w_unset = this.style().min_size.width.is_none();

                // The box hugs the cursor, flipping toward the center near each edge so it
                // never overflows the near side.
                this.absolute()
                    .opacity(progress)
                    .when(min_w_unset, |c| c.min_w(px(150.)))
                    .popover_style(cx)
                    .p_2()
                    .map(|c| {
                        if cursor.x < within.width * 0.5 {
                            c.left(cursor.x + gap)
                        } else {
                            c.right(within.width - cursor.x + gap)
                        }
                    })
                    .map(|c| {
                        if cursor.y < within.height * 0.5 {
                            c.top(cursor.y + gap)
                        } else {
                            c.bottom(within.height - cursor.y + gap)
                        }
                    })
            })))
    }
}

#[cfg(test)]
mod tests {
    use gpui::{point, px};

    use super::*;

    #[test]
    fn a_value_color_colors_only_the_row_added_last() {
        let tooltip = Tooltip::new(point(px(0.), px(0.)), gpui::size(px(100.), px(100.)))
            .value_color(gpui::red())
            .row(gpui::blue(), "Open", "1")
            .row(gpui::blue(), "Close", "2")
            .value_color(gpui::green());
        let colors: Vec<_> = tooltip.rows.iter().map(|row| row.value_color).collect();
        assert_eq!(colors, vec![None, Some(gpui::green())]);
    }

    #[test]
    fn a_plain_row_has_no_swatch_and_takes_a_value_color() {
        let tooltip = Tooltip::new(point(px(0.), px(0.)), gpui::size(px(100.), px(100.)))
            .row(gpui::blue(), "Call", "1")
            .plain_row("Total", "3")
            .value_color(gpui::red());
        let rows: Vec<_> = tooltip
            .rows
            .iter()
            .map(|row| (row.color, row.value_color))
            .collect();
        assert_eq!(
            rows,
            vec![(Some(gpui::blue()), None), (None, Some(gpui::red()))]
        );
    }

    #[test]
    fn plain_rows_keep_a_swatch_slot_only_beside_series_rows() {
        let tooltip = || Tooltip::new(point(px(0.), px(0.)), gpui::size(px(100.), px(100.)));
        let mixed = tooltip()
            .row(gpui::blue(), "Call", "1")
            .plain_row("Total", "3");
        let plain = tooltip().plain_row("Total", "3").plain_row("Ratio", "0.5");
        assert!(has_swatches(&mixed.rows));
        assert!(!has_swatches(&plain.rows));
    }
}
