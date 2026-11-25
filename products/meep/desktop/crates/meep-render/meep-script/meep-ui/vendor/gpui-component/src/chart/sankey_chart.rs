use std::{
    hash::{DefaultHasher, Hash, Hasher},
    rc::Rc,
};

use gpui::{
    AnyElement, App, Bounds, Corners, ElementId, Hsla, IntoElement, Pixels, Point, SharedString,
    TextAlign, Window, fill, linear_color_stop, linear_gradient, point, prelude::FluentBuilder, px,
};
use gpui_component_macros::IntoPlot;

use super::{ChartAppear, caller_id, reveal_mask};
use crate::{
    ActiveTheme,
    plot::{
        PathCaches, Plot, PlotAppear, ShapeKey,
        label::{PlotLabel, TEXT_GAP, TEXT_SIZE, Text, measure_text_width, truncate_text_to_width},
        origin_point,
        shape::{
            Sankey, SankeyAlign, SankeyGraph, SankeyLink, SankeyLinkLayout, SankeyValueScale,
            sankey_link_path,
        },
        tooltip::{PlotHover, Tooltip, TooltipState},
    },
};

const DEFAULT_NODE_WIDTH: f32 = 10.;
const DEFAULT_NODE_PADDING: f32 = 16.;
const DEFAULT_LINK_OPACITY: f32 = 0.3;
const DEFAULT_MIN_LINK_WIDTH: f32 = 1.;
const DEFAULT_LABEL_GAP: f32 = 6.;
/// Cap each side's label margin (as a fraction of width) so a long label is
/// truncated to a modest column beside the flow instead of dominating it.
const MAX_LABEL_WIDTH_RATIO: f32 = 0.2;
/// Cap the reserved top+bottom label band as a fraction of height.
const MAX_LABEL_MARGIN_RATIO: f32 = 0.6;
/// How much the links not attached to the hovered node fade, as a share of
/// their opacity.
const HOVER_DIM: f32 = 0.7;

/// The placement of a sankey chart for one bounds size: the graph plus the
/// label lines and margins it was laid out with.
///
/// Placing the graph relaxes the node order over several iterations, and the
/// label margins need every label measured, so a chart keeps the frame in
/// element state and reuses it while its key is unchanged.
struct SankeyFrame {
    graph: SankeyGraph,
    layer_count: usize,
    node_labels: Vec<Vec<SankeyLabel>>,
    /// The label margins reserved on the left and right of the flow.
    left: f32,
    right: f32,
}

/// The frame of the last placement with the key it was placed for.
#[derive(Default)]
struct SankeyFrameCache {
    key: Option<u64>,
    frame: Option<Rc<SankeyFrame>>,
}

/// The hover a sankey chart paints, sampled once per frame in [`Plot::hover`].
#[derive(Clone, Copy)]
struct SankeyHover {
    /// The hovered node.
    node: usize,
    /// How far the hover has faded in.
    focus: f32,
}

/// A styled line of a sankey node label.
#[derive(Clone)]
pub struct SankeyLabel {
    text: SharedString,
    color: Option<Hsla>,
    font_size: Option<f32>,
}

impl SankeyLabel {
    /// Create a label line with the default color and font size.
    pub fn new(text: impl Into<SharedString>) -> Self {
        Self {
            text: text.into(),
            color: None,
            font_size: None,
        }
    }

    /// Set the text color. Defaults to the theme foreground.
    pub fn color(mut self, color: impl Into<Hsla>) -> Self {
        self.color = Some(color.into());
        self
    }

    /// Set the font size. Defaults to 10.
    pub fn font_size(mut self, font_size: f32) -> Self {
        self.font_size = Some(font_size);
        self
    }

    fn line_height(&self) -> f32 {
        self.font_size.unwrap_or(TEXT_SIZE) + TEXT_GAP
    }
}

fn block_height(lines: &[SankeyLabel]) -> f32 {
    lines.iter().map(|line| line.line_height()).sum()
}

/// A Sankey diagram, layout modeled after [d3-sankey](https://github.com/d3/d3-sankey).
///
/// Links reference nodes by their index in the node list; map string ids to
/// indices before constructing.
#[derive(IntoPlot)]
pub struct SankeyChart<T: 'static> {
    nodes: Vec<T>,
    links: Vec<SankeyLink>,
    node_width: f32,
    node_padding: f32,
    align: SankeyAlign,
    iterations: usize,
    value_scale: SankeyValueScale,
    node_corner_radius: Option<Pixels>,
    node_color: Option<Rc<dyn Fn(&T) -> Hsla>>,
    node_label: Option<Rc<dyn Fn(&T) -> SharedString>>,
    value_label: Option<Rc<dyn Fn(&T, f64) -> SharedString>>,
    labels: Option<Rc<dyn Fn(&T, f64) -> Vec<SankeyLabel>>>,
    link_opacity: f32,
    min_link_width: f32,
    label_gap: f32,
    tooltip_name: Option<Rc<dyn Fn(&T) -> SharedString + 'static>>,
    tooltip_value: Option<Rc<dyn Fn(&T, f64) -> SharedString + 'static>>,
    id: ElementId,
    interactive: bool,
    appear: ChartAppear,
    /// The placement for this frame, resolved in `prepaint` (measuring labels
    /// needs the window) and read by `tooltip_state` and `paint`.
    frame: Option<Rc<SankeyFrame>>,
    hover: Option<SankeyHover>,
}

impl<T> SankeyChart<T> {
    /// Create a chart from nodes and links; links reference nodes by their
    /// index in `nodes` (map string ids to indices before constructing).
    #[track_caller]
    pub fn new<I, L>(nodes: I, links: L) -> Self
    where
        I: IntoIterator<Item = T>,
        L: IntoIterator<Item = SankeyLink>,
    {
        Self {
            nodes: nodes.into_iter().collect(),
            links: links.into_iter().collect(),
            node_width: DEFAULT_NODE_WIDTH,
            node_padding: DEFAULT_NODE_PADDING,
            align: SankeyAlign::default(),
            iterations: 6,
            value_scale: SankeyValueScale::default(),
            node_corner_radius: None,
            node_color: None,
            node_label: None,
            value_label: None,
            labels: None,
            link_opacity: DEFAULT_LINK_OPACITY,
            min_link_width: DEFAULT_MIN_LINK_WIDTH,
            label_gap: DEFAULT_LABEL_GAP,
            tooltip_name: None,
            tooltip_value: None,
            id: caller_id(),
            interactive: true,
            appear: ChartAppear::default(),
            frame: None,
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
    /// The layer is the hitbox under the cursor and what it drives: the hovered
    /// node's links stand out from the rest, and a tooltip shows its label and
    /// throughput. Turn it off for a chart that only decorates, or one an element
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

    /// Set the node rectangle width. Defaults to 10.
    pub fn node_width(mut self, node_width: f32) -> Self {
        self.node_width = node_width;
        self
    }

    /// Set the vertical gap between nodes in a column. Defaults to 16.
    pub fn node_padding(mut self, node_padding: f32) -> Self {
        self.node_padding = node_padding;
        self
    }

    /// Set the node alignment. Defaults to [`SankeyAlign::Justify`].
    pub fn node_align(mut self, align: SankeyAlign) -> Self {
        self.align = align;
        self
    }

    /// Set the number of relaxation passes. Defaults to 6.
    pub fn iterations(mut self, iterations: usize) -> Self {
        self.iterations = iterations;
        self
    }

    /// Set how flow values map to node heights.
    ///
    /// Defaults to [`SankeyValueScale::Linear`]. Use [`SankeyValueScale::Sqrt`]
    /// to keep a dominant flow from dwarfing the small ones without
    /// pre-transforming the data; labels still receive the raw values.
    pub fn value_scale(mut self, value_scale: SankeyValueScale) -> Self {
        self.value_scale = value_scale;
        self
    }

    /// Set the corner radius of the node rectangles. Defaults to 0.
    pub fn node_corner_radius(mut self, radius: impl Into<Pixels>) -> Self {
        self.node_corner_radius = Some(radius.into());
        self
    }

    /// Set the color of each node.
    ///
    /// Defaults to cycling the theme chart palette by node index.
    pub fn node_color<H>(mut self, color: impl Fn(&T) -> H + 'static) -> Self
    where
        H: Into<Hsla> + 'static,
    {
        self.node_color = Some(Rc::new(move |t| color(t).into()));
        self
    }

    /// Set the name label of each node, drawn in muted foreground. No name
    /// label is drawn unless set.
    pub fn node_label(mut self, label: impl Fn(&T) -> SharedString + 'static) -> Self {
        self.node_label = Some(Rc::new(label));
        self
    }

    /// Set the value label of each node, drawn above the name label. No value
    /// label is drawn unless set.
    ///
    /// The closure receives the datum and the node's raw computed throughput
    /// (max of incoming and outgoing flow, in unscaled units).
    pub fn value_label(mut self, label: impl Fn(&T, f64) -> SharedString + 'static) -> Self {
        self.value_label = Some(Rc::new(label));
        self
    }

    /// Set fully custom node labels, one [`SankeyLabel`] per line, top to
    /// bottom. Takes precedence over `node_label`/`value_label` when set;
    /// unset by default.
    ///
    /// The closure receives the datum and the node's raw computed throughput
    /// (max of incoming and outgoing flow, in unscaled units).
    pub fn labels(mut self, labels: impl Fn(&T, f64) -> Vec<SankeyLabel> + 'static) -> Self {
        self.labels = Some(Rc::new(labels));
        self
    }

    /// Name the node under the cursor in the hover tooltip's row, beside its
    /// throughput. Unset, the row carries no name at all.
    ///
    /// A sankey shows one number per node, so the node's own name is what the
    /// row wants; without it the row reads as a swatch and a number with a gap
    /// between them. The alternative was to title the tooltip from
    /// `node_label`, but that also draws the name beside the node — and a chart
    /// drawing its text through `labels` sets neither.
    pub fn tooltip_name(mut self, name: impl Fn(&T) -> SharedString + 'static) -> Self {
        self.tooltip_name = Some(Rc::new(name));
        self
    }

    /// Set the text of the hover tooltip's row, the node's throughput.
    ///
    /// `value_label` supplies it when this is unset, and the raw number when
    /// neither is set — which is what a chart drawing its text through `labels`
    /// gets, however carefully it formats the value it draws.
    pub fn tooltip_value(mut self, value: impl Fn(&T, f64) -> SharedString + 'static) -> Self {
        self.tooltip_value = Some(Rc::new(value));
        self
    }

    /// Set the opacity of the link ribbons. Defaults to 0.3.
    pub fn link_opacity(mut self, opacity: f32) -> Self {
        self.link_opacity = opacity;
        self
    }

    /// Set the minimum ribbon thickness, so tiny flows stay visible. Defaults to 1.
    pub fn min_link_width(mut self, width: f32) -> Self {
        self.min_link_width = width;
        self
    }

    /// Set the gap between a node and its labels. Defaults to 6.
    pub fn label_gap(mut self, gap: f32) -> Self {
        self.label_gap = gap;
        self
    }

    fn sankey(&self) -> Sankey {
        Sankey::new()
            .node_width(self.node_width)
            .node_padding(self.node_padding)
            .node_align(self.align)
            .iterations(self.iterations)
            .value_scale(self.value_scale)
    }

    /// Raw per-node throughput (max of raw incoming and outgoing sums), for
    /// labels — the layout's `node.value` is in scaled units under a
    /// non-linear value scale, so labels must not use it.
    fn raw_throughput(&self) -> Vec<f64> {
        let mut incoming = vec![0f64; self.nodes.len()];
        let mut outgoing = vec![0f64; self.nodes.len()];
        for link in &self.links {
            if let (Some(o), Some(i)) =
                (outgoing.get_mut(link.source), incoming.get_mut(link.target))
            {
                *o += link.value;
                *i += link.value;
            }
        }
        incoming
            .into_iter()
            .zip(outgoing)
            .map(|(i, o)| i.max(o))
            .collect()
    }
}

impl<T> SankeyChart<T> {
    /// Each node's label lines: the custom `labels` closure wins, otherwise the
    /// value/name lines with the default styles. Labels get the raw throughput,
    /// not the layout's (possibly scaled) value.
    fn node_labels(&self, cx: &App) -> Vec<Vec<SankeyLabel>> {
        let raw_value = self.raw_throughput();
        self.nodes
            .iter()
            .zip(raw_value)
            .map(|(datum, value)| {
                if let Some(labels) = &self.labels {
                    labels(datum, value)
                } else {
                    let mut lines = Vec::new();
                    if let Some(value_label) = &self.value_label {
                        lines.push(SankeyLabel::new(value_label(datum, value)));
                    }
                    if let Some(node_label) = &self.node_label {
                        lines.push(
                            SankeyLabel::new(node_label(datum)).color(cx.theme().muted_foreground),
                        );
                    }
                    lines
                }
            })
            .collect()
    }

    /// The key a placement is reused under: everything that shapes it, which is
    /// the bounds size, the graph, the placement settings and the label lines.
    fn frame_key(&self, bounds: Bounds<Pixels>, node_labels: &[Vec<SankeyLabel>]) -> u64 {
        let mut hasher = DefaultHasher::new();
        bounds.size.width.as_f32().to_bits().hash(&mut hasher);
        bounds.size.height.as_f32().to_bits().hash(&mut hasher);
        self.nodes.len().hash(&mut hasher);
        for link in &self.links {
            link.source.hash(&mut hasher);
            link.target.hash(&mut hasher);
            link.value.to_bits().hash(&mut hasher);
        }
        self.node_width.to_bits().hash(&mut hasher);
        self.node_padding.to_bits().hash(&mut hasher);
        self.align.hash(&mut hasher);
        self.iterations.hash(&mut hasher);
        self.value_scale.hash(&mut hasher);
        self.label_gap.to_bits().hash(&mut hasher);
        for lines in node_labels {
            lines.len().hash(&mut hasher);
            for line in lines {
                line.text.hash(&mut hasher);
                line.font_size.map(f32::to_bits).hash(&mut hasher);
                line.color
                    .map(|color| [color.h, color.s, color.l, color.a].map(f32::to_bits))
                    .hash(&mut hasher);
            }
        }
        hasher.finish()
    }

    /// Place the graph within `bounds`, reserving margins for the labels.
    fn place(
        &self,
        bounds: Bounds<Pixels>,
        node_labels: Vec<Vec<SankeyLabel>>,
        window: &mut Window,
    ) -> Option<SankeyFrame> {
        let width = bounds.size.width.as_f32();
        let height = bounds.size.height.as_f32();

        // First pass: only the topology (each node's `layer`) is needed to
        // measure the label margins.
        let topology = self.sankey().topology(self.nodes.len(), &self.links).ok()?;
        let layer_count = topology.layer_count();
        let has_labels = node_labels.iter().any(|lines| !lines.is_empty());

        // Reserve margins so the labels beside the first/last columns and
        // above the middle columns are not clipped.
        let mut left = 0f32;
        let mut right = 0f32;
        if has_labels {
            for node in &topology.nodes {
                if node.layer != 0 && node.layer + 1 != layer_count {
                    continue;
                }
                let mut label_width = 0f32;
                for line in &node_labels[node.index] {
                    label_width = label_width.max(measure_text_width(
                        &line.text,
                        px(line.font_size.unwrap_or(TEXT_SIZE)),
                        window,
                    ));
                }
                if node.layer == 0 {
                    left = left.max(label_width + self.label_gap);
                } else {
                    right = right.max(label_width + self.label_gap);
                }
            }

            // Cap each side independently so one long label is truncated to a
            // modest column rather than eating into the flow area.
            let side_cap = width * MAX_LABEL_WIDTH_RATIO;
            left = left.min(side_cap);
            right = right.min(side_cap);
        }
        // Above-node labels are only emitted for middle columns, so reserve
        // the top band for the tallest such label block. Cap the vertical
        // margins like the horizontal ones so a short chart doesn't collapse
        // the flow.
        let mut top = 0f32;
        if has_labels && layer_count > 2 {
            for node in &topology.nodes {
                if node.layer == 0 || node.layer + 1 == layer_count {
                    continue;
                }
                let block = block_height(&node_labels[node.index]);
                if block > 0. {
                    top = top.max(block + TEXT_GAP);
                }
            }
        }
        let mut bottom = if has_labels { TEXT_GAP } else { 0. };
        let max_vertical = height * MAX_LABEL_MARGIN_RATIO;
        if top + bottom > max_vertical {
            let k = max_vertical / (top + bottom);
            top *= k;
            bottom *= k;
        }

        // Second pass: complete the placement on the final extent, reusing
        // the first pass's topology.
        let graph = self
            .sankey()
            .extent(
                left,
                top,
                (width - right).max(left + 1.),
                (height - bottom).max(top + 1.),
            )
            .layout_from(topology);

        Some(SankeyFrame {
            graph,
            layer_count,
            node_labels,
            left,
            right,
        })
    }

    /// Whether `link` starts or ends at `node`.
    fn is_attached(link: &SankeyLinkLayout, node: usize) -> bool {
        link.source == node || link.target == node
    }
}

impl<T> Plot for SankeyChart<T> {
    /// Resolve the placement for the frame, reusing the last one while nothing
    /// that shapes it has changed. Measuring the labels needs the window, which
    /// `tooltip_state` does not have, so this runs here rather than in `paint`.
    fn prepaint(
        &mut self,
        bounds: Bounds<Pixels>,
        window: &mut Window,
        cx: &mut App,
    ) -> Vec<AnyElement> {
        self.frame = None;
        let width = bounds.size.width.as_f32();
        let height = bounds.size.height.as_f32();
        if self.nodes.is_empty() || self.links.is_empty() || width <= 0. || height <= 0. {
            return vec![];
        }

        let node_labels = self.node_labels(cx);

        let key = self.frame_key(bounds, &node_labels);
        let cache = window.use_keyed_state("sankey-frame", cx, |_, _| SankeyFrameCache::default());
        let cached = cache.read(cx);
        self.frame = if cached.key == Some(key) {
            cached.frame.clone()
        } else {
            let frame = self.place(bounds, node_labels, window).map(Rc::new);
            cache.update(cx, |cache, _| {
                cache.key = Some(key);
                cache.frame = frame.clone();
            });
            frame
        };

        vec![]
    }

    fn paint(&mut self, bounds: Bounds<Pixels>, window: &mut Window, cx: &mut App) {
        let Some(frame) = self.frame.clone() else {
            return;
        };
        let SankeyFrame {
            graph,
            layer_count,
            node_labels,
            left,
            right,
        } = &*frame;
        let (layer_count, left, right) = (*layer_count, *left, *right);
        let width = bounds.size.width.as_f32();
        let height = bounds.size.height.as_f32();

        let palette = [
            cx.theme().chart_1,
            cx.theme().chart_2,
            cx.theme().chart_3,
            cx.theme().chart_4,
            cx.theme().chart_5,
        ];
        let colors: Vec<Hsla> = self
            .nodes
            .iter()
            .enumerate()
            .map(|(index, datum)| match &self.node_color {
                Some(color) => color(datum),
                None => palette[index % palette.len()],
            })
            .collect();

        // Links first, under the nodes. The links of the hovered node keep their
        // opacity while the rest fade behind them.
        //
        // Hovering changes only a ribbon's opacity, so the chart keeps each
        // tessellated ribbon, slotted by the link's index in the graph so a
        // skipped zero-value link doesn't shift the others.
        //
        // Links and nodes draw in from the left under a mask as the chart
        // appears, which leaves the cached ribbons whole; the labels fade in.
        let min_width = self.min_link_width;
        let caches = PathCaches::for_paint("links", window, cx);
        let appear = self.appear.get().progress();
        window.with_content_mask(reveal_mask(bounds, 0., appear), |window| {
            for (ix, link) in graph.links.iter().enumerate() {
                if link.value <= 0. {
                    continue;
                }
                let source = &graph.nodes[link.source];
                let target = &graph.nodes[link.target];
                let path = caches.update(cx, |caches, _| {
                    let key = ShapeKey::new(())
                        .f32(source.x1)
                        .f32(target.x0)
                        .f32(link.y0)
                        .f32(link.y1)
                        .f32(link.source_width.max(min_width))
                        .f32(link.target_width.max(min_width))
                        .finish();
                    caches.slot(ix).get(key, bounds.origin, || {
                        sankey_link_path(source, target, link, min_width, Point::default())
                    })
                });
                let Some(path) = path else {
                    continue;
                };
                let opacity = match self.hover {
                    Some(hover) if !Self::is_attached(link, hover.node) => {
                        self.link_opacity * (1. - HOVER_DIM * hover.focus)
                    }
                    _ => self.link_opacity,
                };
                window.paint_path(
                    path,
                    linear_gradient(
                        90.,
                        linear_color_stop(colors[link.source].opacity(opacity), 0.),
                        linear_color_stop(colors[link.target].opacity(opacity), 1.),
                    ),
                );
            }

            let corner_radii = Corners::all(self.node_corner_radius.unwrap_or_default());
            for node in &graph.nodes {
                let node_bounds = Bounds::from_corners(
                    origin_point(px(node.x0), px(node.y0), bounds.origin),
                    // Keep tiny nodes visible with a minimum 1px height.
                    origin_point(px(node.x1), px(node.y1.max(node.y0 + 1.)), bounds.origin),
                );
                window.paint_quad(fill(node_bounds, colors[node.index]).corner_radii(corner_radii));
            }
        });

        let mut texts = Vec::new();
        for node in &graph.nodes {
            let lines = &node_labels[node.index];
            if lines.is_empty() {
                continue;
            }

            let is_first = node.layer == 0;
            let is_last = node.layer + 1 == layer_count;
            // `x`/`align` place the label beside (first/last) or centered above
            // (middle) the node, and `max_width` bounds it so a long label is
            // truncated with an ellipsis instead of drawn outside the plot:
            // first/last to their reserved margin, middle to twice the smaller
            // gap to the plot edge (generous for interior nodes, only bites a
            // label long enough to actually run off-plot).
            let (x, align, max_width) = if is_first {
                (
                    node.x0 - self.label_gap,
                    TextAlign::Right,
                    left - self.label_gap,
                )
            } else if is_last {
                (
                    node.x1 + self.label_gap,
                    TextAlign::Left,
                    right - self.label_gap,
                )
            } else {
                let center = (node.x0 + node.x1) / 2.;
                let edge_budget = 2. * center.min(width - center);
                (center, TextAlign::Center, edge_budget)
            };

            let block = block_height(lines);
            let mut y = if is_first || is_last {
                // Block vertically centered beside the node, clamped into
                // the plot area so labels of nodes near the top or bottom
                // edge are not clipped.
                ((node.y0 + node.y1) / 2. - block / 2.)
                    .min(height - block)
                    .max(0.)
            } else {
                // Block above the node.
                node.y0 - block - TEXT_GAP
            };

            for line in lines {
                let font_size = px(line.font_size.unwrap_or(TEXT_SIZE));
                let text = truncate_text_to_width(&line.text, font_size, max_width, window);
                texts.push(
                    Text::new(
                        text,
                        point(px(x), px(y)),
                        line.color.unwrap_or(cx.theme().foreground).opacity(appear),
                    )
                    .font_size(font_size)
                    .align(align),
                );
                y += line.line_height();
            }
        }
        PlotLabel::new(texts).paint(&bounds, window, cx);
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
        _bounds: Bounds<Pixels>,
        _cx: &App,
    ) -> Option<TooltipState> {
        let frame = self.frame.as_ref()?;
        let (x, y) = (position.x.as_f32(), position.y.as_f32());
        let node = frame.graph.nodes.iter().find(|node| {
            (node.x0..=node.x1).contains(&x) && (node.y0..=node.y1.max(node.y0 + 1.)).contains(&y)
        })?;
        Some(TooltipState::new(node.index, position, vec![]))
    }

    fn hover(&mut self, hover: Option<&PlotHover>, _window: &mut Window, _cx: &mut App) {
        self.hover = hover.map(|hover| SankeyHover {
            node: hover.state().index,
            focus: hover.progress(),
        });
    }

    fn tooltip(
        &self,
        state: &TooltipState,
        cursor: Point<Pixels>,
        bounds: Bounds<Pixels>,
        _window: &mut Window,
        cx: &mut App,
    ) -> Option<AnyElement> {
        let datum = self.nodes.get(state.index)?;
        let value = self.raw_throughput().get(state.index).copied()?;
        let color = match &self.node_color {
            Some(color) => color(datum),
            None => {
                let palette = [
                    cx.theme().chart_1,
                    cx.theme().chart_2,
                    cx.theme().chart_3,
                    cx.theme().chart_4,
                    cx.theme().chart_5,
                ];
                palette[state.index % palette.len()]
            }
        };
        let value_text = match self.tooltip_value.as_ref().or(self.value_label.as_ref()) {
            Some(value_text) => value_text(datum, value),
            None => format!("{value}").into(),
        };

        Some(
            // Follow the cursor; the node's links mark it.
            Tooltip::new(cursor, bounds.size)
                .gap(px(8.))
                .when_some(self.node_label.as_ref(), |this, label| {
                    this.title(label(datum))
                })
                .row(
                    color,
                    match self.tooltip_name.as_ref() {
                        Some(tooltip_name) => tooltip_name(datum),
                        None => SharedString::default(),
                    },
                    value_text,
                )
                .into_any_element(),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sankey_chart_builder() {
        let chart = SankeyChart::new(vec!["a", "b"], vec![SankeyLink::new(0, 1, 5.)]);
        assert_eq!(chart.nodes.len(), 2);
        assert_eq!(chart.links.len(), 1);
        assert_eq!(chart.node_width, DEFAULT_NODE_WIDTH);
        assert_eq!(chart.node_padding, DEFAULT_NODE_PADDING);
        assert_eq!(chart.align, SankeyAlign::Justify);
        assert_eq!(chart.iterations, 6);
        assert_eq!(chart.node_corner_radius, None);
        assert_eq!(chart.link_opacity, DEFAULT_LINK_OPACITY);
        assert_eq!(chart.min_link_width, DEFAULT_MIN_LINK_WIDTH);
        assert_eq!(chart.label_gap, DEFAULT_LABEL_GAP);
        assert!(chart.node_color.is_none());
        assert!(chart.node_label.is_none());
        assert!(chart.value_label.is_none());
        assert!(chart.labels.is_none());

        let chart = chart
            .node_width(8.)
            .node_padding(20.)
            .node_align(SankeyAlign::Left)
            .iterations(10)
            .node_corner_radius(px(2.))
            .node_color(|_| gpui::red())
            .node_label(|d| SharedString::from(d.to_string()))
            .value_label(|_, value| SharedString::from(format!("{}", value)))
            .labels(|d, value| {
                vec![
                    SankeyLabel::new(format!("{}", value)),
                    SankeyLabel::new(d.to_string()),
                ]
            })
            .link_opacity(0.5)
            .min_link_width(2.)
            .label_gap(10.);
        assert_eq!(chart.node_width, 8.);
        assert_eq!(chart.node_padding, 20.);
        assert_eq!(chart.align, SankeyAlign::Left);
        assert_eq!(chart.iterations, 10);
        assert_eq!(chart.node_corner_radius, Some(px(2.)));
        assert_eq!(chart.link_opacity, 0.5);
        assert_eq!(chart.min_link_width, 2.);
        assert_eq!(chart.label_gap, 10.);
        assert!(chart.node_color.is_some());
        assert!(chart.node_label.is_some());
        assert!(chart.value_label.is_some());
        assert!(chart.labels.is_some());
    }

    #[test]
    fn test_sankey_label_builder() {
        let label = SankeyLabel::new("a");
        assert_eq!(label.text, "a");
        assert_eq!(label.color, None);
        assert_eq!(label.font_size, None);
        assert_eq!(label.line_height(), TEXT_SIZE + TEXT_GAP);

        let label = SankeyLabel::new("b").color(gpui::red()).font_size(14.);
        assert_eq!(label.color, Some(gpui::red()));
        assert_eq!(label.font_size, Some(14.));
        assert_eq!(label.line_height(), 14. + TEXT_GAP);

        assert_eq!(
            block_height(&[SankeyLabel::new("a"), SankeyLabel::new("b").font_size(14.)]),
            TEXT_SIZE + TEXT_GAP + 14. + TEXT_GAP
        );
        assert_eq!(block_height(&[]), 0.);
    }

    #[test]
    fn test_sankey_chart_raw_throughput() {
        // A(out 30) -> B, B -> C(20) + D(10): B's throughput is max(in, out).
        let chart = SankeyChart::new(
            vec!["a", "b", "c", "d"],
            vec![
                SankeyLink::new(0, 1, 30.),
                SankeyLink::new(1, 2, 20.),
                SankeyLink::new(1, 3, 10.),
            ],
        );
        let raw = chart.raw_throughput();
        assert_eq!(raw, vec![30., 30., 20., 10.]);

        // Under Sqrt the layout's node value is scaled, but raw_throughput
        // (used for labels) must stay in raw units — the two must differ.
        let sqrt = chart
            .value_scale(SankeyValueScale::Sqrt)
            .sankey()
            .layout(4, &chart_links())
            .unwrap();
        // Node A: layout value is sqrt-scaled (30 -> sqrt(30)), raw is 30.
        assert!((sqrt.nodes[0].value - 30f64.sqrt()).abs() < 1e-6);
        assert!((raw[0] - 30.).abs() < 1e-6);
        assert!(raw[0] != sqrt.nodes[0].value);
    }

    fn chart_links() -> Vec<SankeyLink> {
        vec![
            SankeyLink::new(0, 1, 30.),
            SankeyLink::new(1, 2, 20.),
            SankeyLink::new(1, 3, 10.),
        ]
    }

    /// A chart drawing its text through `labels` sets neither `node_label` nor
    /// `value_label`, so its tooltip row had no name and an unformatted number.
    #[test]
    fn test_tooltip_text_is_settable_without_drawing_labels() {
        let chart = SankeyChart::new(vec!["Revenue"], Vec::<SankeyLink>::new())
            .tooltip_name(|_| "Revenue".into())
            .tooltip_value(|_, value| format!("{value:.0}M").into());
        assert!(chart.tooltip_name.is_some());
        assert!(chart.tooltip_value.is_some());
        assert!(chart.node_label.is_none());
        assert!(chart.value_label.is_none());
    }
}
