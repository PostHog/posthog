// @reference: https://github.com/d3/d3-sankey

use gpui::{Path, PathBuilder, Pixels, Point, px};

use crate::plot::origin_point;

/// Vertical offset, as a fraction of node height, applied to stagger runs of
/// equal-height single-node columns so their otherwise-flat ribbons curve.
const STAGGER_RATIO: f32 = 0.15;

/// Horizontal alignment of nodes across layers.
///
/// Mirrors d3-sankey's `sankeyLeft` / `sankeyRight` / `sankeyCenter` /
/// `sankeyJustify`.
#[derive(Clone, Copy, Debug, Default, Hash, PartialEq, Eq)]
pub enum SankeyAlign {
    Left,
    Right,
    Center,
    #[default]
    Justify,
}

/// An input link of a Sankey diagram.
///
/// `source` and `target` are indices into the node list (d3-sankey's default
/// `nodeId`), `value` is the flow amount.
#[derive(Clone, Copy, Debug, PartialEq)]
#[non_exhaustive]
pub struct SankeyLink {
    pub source: usize,
    pub target: usize,
    pub value: f64,
}

impl SankeyLink {
    /// Create a link from the `source` node index to the `target` node index
    /// carrying `value`.
    pub fn new(source: usize, target: usize, value: f64) -> Self {
        Self {
            source,
            target,
            value,
        }
    }
}

/// A node with computed layout (d3-sankey's computed node fields).
#[derive(Clone, Debug, Default)]
#[non_exhaustive]
pub struct SankeyNodeLayout {
    pub index: usize,
    /// The node's throughput in the layout's value space: max(sum of incoming,
    /// sum of outgoing). With a non-linear [`SankeyValueScale`] this is in
    /// scaled units, not raw values — read raw values from the input links.
    pub value: f64,
    /// Topological distance from any source node (longest path).
    pub depth: usize,
    /// Topological distance to any sink node (longest path).
    pub height: usize,
    /// Horizontal column index after alignment.
    pub layer: usize,
    pub x0: f32,
    pub x1: f32,
    pub y0: f32,
    pub y1: f32,
    /// Indices into [`SankeyGraph::links`] of the outgoing links.
    pub source_links: Vec<usize>,
    /// Indices into [`SankeyGraph::links`] of the incoming links.
    pub target_links: Vec<usize>,
}

/// A link with computed layout.
///
/// Like d3-sankey, `y0` and `y1` are the vertical centers of the ribbon at
/// the source and target end. Each end has its own width: the links of a
/// node's side share the node height in proportion to their values, so both
/// sides of every node are always fully covered. On a balanced graph
/// (incoming sum == outgoing sum everywhere) the two ends are equal; on an
/// imbalanced one (e.g. sqrt-compressed values) the ribbon transitions
/// smoothly between the two widths.
#[derive(Clone, Debug)]
#[non_exhaustive]
pub struct SankeyLinkLayout {
    pub index: usize,
    pub source: usize,
    pub target: usize,
    /// The flow value in the layout's value space (scaled by
    /// [`SankeyValueScale`]; equals the raw input value under `Linear`).
    pub value: f64,
    pub y0: f32,
    pub y1: f32,
    /// The nominal width from the global value scale, used by the layout
    /// relaxation; equals both end widths on a balanced graph.
    pub width: f32,
    /// The ribbon width at the source end.
    pub source_width: f32,
    /// The ribbon width at the target end.
    pub target_width: f32,
}

/// The computed Sankey layout.
#[derive(Clone, Debug, Default)]
#[non_exhaustive]
pub struct SankeyGraph {
    pub nodes: Vec<SankeyNodeLayout>,
    pub links: Vec<SankeyLinkLayout>,
}

impl SankeyGraph {
    /// Number of layers (max layer + 1), 0 for an empty graph.
    pub fn layer_count(&self) -> usize {
        self.nodes
            .iter()
            .map(|node| node.layer + 1)
            .max()
            .unwrap_or(0)
    }
}

/// A reason a Sankey layout could not be computed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SankeyError {
    /// A link references a node index out of range.
    MissingNode(usize),
    /// The graph contains a circular link.
    CircularLink,
}

impl std::fmt::Display for SankeyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::MissingNode(index) => write!(f, "missing node: {}", index),
            Self::CircularLink => write!(f, "circular link"),
        }
    }
}

impl std::error::Error for SankeyError {}

/// How flow values map to node heights and ribbon widths.
#[derive(Clone, Copy, Debug, Default, Hash, PartialEq, Eq)]
pub enum SankeyValueScale {
    /// Height is proportional to the value (standard sankey semantics).
    #[default]
    Linear,
    /// Height is proportional to the square root of the value, compressing a
    /// wide value range so a dominant flow doesn't dwarf the small ones (and
    /// the small ones stay visible) without the caller pre-transforming data.
    Sqrt,
}

impl SankeyValueScale {
    fn apply(self, value: f64) -> f64 {
        match self {
            Self::Linear => value,
            // Guard against tiny negatives from bad data.
            Self::Sqrt => value.max(0.).sqrt(),
        }
    }
}

/// The Sankey layout generator.
pub struct Sankey {
    node_width: f32,
    node_padding: f32,
    align: SankeyAlign,
    iterations: usize,
    value_scale: SankeyValueScale,
    x0: f32,
    y0: f32,
    x1: f32,
    y1: f32,
}

impl Default for Sankey {
    fn default() -> Self {
        Self {
            node_width: 24.,
            node_padding: 8.,
            align: SankeyAlign::default(),
            iterations: 6,
            value_scale: SankeyValueScale::default(),
            x0: 0.,
            y0: 0.,
            x1: 1.,
            y1: 1.,
        }
    }
}

impl Sankey {
    /// Create a generator with the d3-sankey defaults (see [`Sankey::default`]).
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the node rectangle width. Defaults to 24.
    pub fn node_width(mut self, node_width: f32) -> Self {
        self.node_width = node_width;
        self
    }

    /// Set the vertical gap between nodes in a column. Defaults to 8.
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

    /// Set how values map to heights. Defaults to [`SankeyValueScale::Linear`].
    pub fn value_scale(mut self, value_scale: SankeyValueScale) -> Self {
        self.value_scale = value_scale;
        self
    }

    /// Set the layout bounds as `[[x0, y0], [x1, y1]]`. Defaults to `[[0, 0], [1, 1]]`.
    pub fn extent(mut self, x0: f32, y0: f32, x1: f32, y1: f32) -> Self {
        self.x0 = x0;
        self.y0 = y0;
        self.x1 = x1;
        self.y1 = y1;
        self
    }

    /// Equivalent to `extent(0., 0., width, height)`.
    pub fn size(self, width: f32, height: f32) -> Self {
        self.extent(0., 0., width, height)
    }

    /// Compute the topology only: node `value`, `depth`, `height`, `layer`
    /// and horizontal positions, without the vertical placement. Much cheaper
    /// than [`Sankey::layout`] when only the column structure is needed
    /// (e.g. to measure labels before fixing the extent).
    ///
    /// `node_count` is the number of nodes; links reference nodes by index
    /// (d3-sankey's default `nodeId`). Returns an error if a link references
    /// a node out of range or the graph contains a cycle.
    pub fn topology(
        &self,
        node_count: usize,
        links: &[SankeyLink],
    ) -> Result<SankeyGraph, SankeyError> {
        for link in links {
            if link.source >= node_count {
                return Err(SankeyError::MissingNode(link.source));
            }
            if link.target >= node_count {
                return Err(SankeyError::MissingNode(link.target));
            }
        }

        let mut graph = SankeyGraph {
            nodes: (0..node_count)
                .map(|index| SankeyNodeLayout {
                    index,
                    ..Default::default()
                })
                .collect(),
            links: links
                .iter()
                .enumerate()
                .map(|(index, link)| SankeyLinkLayout {
                    index,
                    source: link.source,
                    target: link.target,
                    // Layout works in scaled value space; all downstream math
                    // (node values, widths, breadths) stays coherent because
                    // it is additive in this space, so nodes remain exactly
                    // filled by their ribbons regardless of the scale.
                    value: self.value_scale.apply(link.value),
                    y0: 0.,
                    y1: 0.,
                    width: 0.,
                    source_width: 0.,
                    target_width: 0.,
                })
                .collect(),
        };
        if node_count == 0 {
            return Ok(graph);
        }

        compute_node_links(&mut graph);
        compute_node_values(&mut graph);
        compute_node_ranks(&mut graph)?;
        self.compute_node_layers(&mut graph);

        Ok(graph)
    }

    /// Compute the full layout: [`Sankey::topology`] plus the vertical node
    /// placement and link breadths.
    pub fn layout(
        &self,
        node_count: usize,
        links: &[SankeyLink],
    ) -> Result<SankeyGraph, SankeyError> {
        Ok(self.layout_from(self.topology(node_count, links)?))
    }

    /// Complete the layout for a graph produced by [`Sankey::topology`],
    /// avoiding a second topology pass when the extent only becomes known
    /// after measuring against the column structure (e.g. label margins).
    ///
    /// The topological fields are extent-independent; the horizontal and
    /// vertical positions are recomputed for this generator's extent.
    pub fn layout_from(&self, mut graph: SankeyGraph) -> SankeyGraph {
        if graph.nodes.is_empty() {
            return graph;
        }

        self.compute_node_layers(&mut graph);

        let mut columns = vec![Vec::new(); graph.layer_count()];
        for node in &graph.nodes {
            columns[node.layer].push(node.index);
        }

        self.compute_node_breadths(&mut graph, &mut columns);
        compute_link_breadths(&mut graph);
        self.center_columns(&mut graph);
        self.stagger_flat_columns(&mut graph);

        graph
    }

    /// Vertically center each column's stack of nodes within the extent.
    ///
    /// When a crowded column forces a small scale, the sparser columns don't
    /// fill the height and the relaxation aligns them to their flows' weighted
    /// center, which leaves the trunk sitting high with empty space below.
    /// d3-sankey doesn't correct this; centering each column (translating it,
    /// so the relaxation's within-column arrangement and the ribbon fits are
    /// preserved) keeps the diagram balanced on the canvas.
    fn center_columns(&self, graph: &mut SankeyGraph) {
        let layers = graph.layer_count();
        if layers == 0 {
            return;
        }

        // Per-layer bounding box, then the offset that centers it.
        let mut lo = vec![f32::INFINITY; layers];
        let mut hi = vec![f32::NEG_INFINITY; layers];
        for node in &graph.nodes {
            lo[node.layer] = lo[node.layer].min(node.y0);
            hi[node.layer] = hi[node.layer].max(node.y1);
        }
        let offsets: Vec<f32> = (0..layers)
            .map(|l| {
                if lo[l].is_finite() && hi[l] > lo[l] {
                    (self.y0 + self.y1 - lo[l] - hi[l]) / 2.
                } else {
                    0.
                }
            })
            .collect();

        apply_layer_offsets(graph, &offsets);
    }

    /// Nudge runs of adjacent single-node columns of (near-)equal height off
    /// the shared center line. Centering aligns such columns exactly, so the
    /// ribbon between them is a flat rectangle; a small alternating stagger
    /// turns it into a gentle S-curve. Only the flat single-node case is
    /// touched, so multi-node or unequal columns (which already curve) are
    /// left alone.
    fn stagger_flat_columns(&self, graph: &mut SankeyGraph) {
        let layers = graph.layer_count();
        if layers < 2 {
            return;
        }

        let mut count = vec![0usize; layers];
        let mut single = vec![usize::MAX; layers];
        for node in &graph.nodes {
            count[node.layer] += 1;
            single[node.layer] = node.index;
        }
        let heights: Vec<f32> = (0..layers)
            .map(|l| {
                if count[l] == 1 {
                    let n = &graph.nodes[single[l]];
                    n.y1 - n.y0
                } else {
                    0.
                }
            })
            .collect();

        // Offset the odd columns of each flat run, leaving the even ones on
        // the center line, so consecutive ribbons bend down then back up.
        let mut offsets = vec![0f32; layers];
        let mut run = 0usize;
        for l in 1..layers {
            let flat =
                count[l] == 1 && count[l - 1] == 1 && (heights[l] - heights[l - 1]).abs() < 1e-3;
            if flat {
                run += 1;
                if run % 2 == 1 {
                    // Bound the nudge by the slack so the node stays inside
                    // the extent (a column that fills the height can't move).
                    let slack = (self.y1 - self.y0 - heights[l]).max(0.);
                    offsets[l] = (heights[l] * STAGGER_RATIO).min(slack / 2.);
                }
            } else {
                run = 0;
            }
        }

        apply_layer_offsets(graph, &offsets);
    }

    fn align_layer(&self, graph: &SankeyGraph, index: usize, n: usize) -> usize {
        let node = &graph.nodes[index];
        match self.align {
            SankeyAlign::Left => node.depth,
            SankeyAlign::Right => n - 1 - node.height,
            SankeyAlign::Justify => {
                if node.source_links.is_empty() {
                    n - 1
                } else {
                    node.depth
                }
            }
            SankeyAlign::Center => {
                if !node.target_links.is_empty() {
                    node.depth
                } else if !node.source_links.is_empty() {
                    node.source_links
                        .iter()
                        .map(|&link| graph.nodes[graph.links[link].target].depth)
                        .min()
                        .unwrap_or(1)
                        .saturating_sub(1)
                } else {
                    0
                }
            }
        }
    }

    fn compute_node_layers(&self, graph: &mut SankeyGraph) {
        let n = graph
            .nodes
            .iter()
            .map(|node| node.depth + 1)
            .max()
            .unwrap_or(0);
        let kx = if n > 1 {
            (self.x1 - self.x0 - self.node_width) / (n - 1) as f32
        } else {
            0.
        };

        let layers: Vec<usize> = (0..graph.nodes.len())
            .map(|index| self.align_layer(graph, index, n).min(n - 1))
            .collect();

        for (index, layer) in layers.into_iter().enumerate() {
            let node = &mut graph.nodes[index];
            node.layer = layer;
            node.x0 = self.x0 + layer as f32 * kx;
            node.x1 = node.x0 + self.node_width;
        }
    }

    fn compute_node_breadths(&self, graph: &mut SankeyGraph, columns: &mut [Vec<usize>]) {
        let max_column_len = columns.iter().map(|column| column.len()).max().unwrap_or(0);
        let py = if max_column_len > 1 {
            self.node_padding
                .min((self.y1 - self.y0) / (max_column_len - 1) as f32)
        } else {
            self.node_padding
        };

        self.initialize_node_breadths(graph, columns, py);

        for i in 0..self.iterations {
            let alpha = 0.99_f32.powi(i as i32);
            let beta = (1. - alpha).max((i + 1) as f32 / self.iterations as f32);
            self.relax_right_to_left(graph, columns, alpha, beta, py);
            self.relax_left_to_right(graph, columns, alpha, beta, py);
        }
    }

    fn initialize_node_breadths(&self, graph: &mut SankeyGraph, columns: &[Vec<usize>], py: f32) {
        // Scale factor between flow value and pixels. d3 lets an over-crowded
        // column produce a negative ky; clamp to zero so heights never invert.
        let mut ky = f32::INFINITY;
        for column in columns {
            let value_sum: f64 = column.iter().map(|&index| graph.nodes[index].value).sum();
            if value_sum > 0. {
                let k = (self.y1 - self.y0 - (column.len() - 1) as f32 * py) / value_sum as f32;
                ky = ky.min(k);
            }
        }
        if !ky.is_finite() {
            ky = 0.;
        }
        ky = ky.max(0.);

        for column in columns {
            let mut y = self.y0;
            for &index in column {
                let node_height = graph.nodes[index].value as f32 * ky;
                let node = &mut graph.nodes[index];
                node.y0 = y;
                node.y1 = y + node_height;
                y = node.y1 + py;
            }

            // Distribute the leftover vertical space evenly (d3 keeps this
            // signed: an over-crowded column shifts nodes back up).
            let leftover = (self.y1 - y + py) / (column.len() + 1) as f32;
            for (i, &index) in column.iter().enumerate() {
                let node = &mut graph.nodes[index];
                let dy = leftover * (i + 1) as f32;
                node.y0 += dy;
                node.y1 += dy;
            }
        }

        for link in &mut graph.links {
            link.width = link.value as f32 * ky;
        }

        for column in columns {
            for &index in column {
                sort_source_links(graph, index);
                sort_target_links(graph, index);
            }
        }
    }

    /// Reposition each node based on its incoming links.
    fn relax_left_to_right(
        &self,
        graph: &mut SankeyGraph,
        columns: &mut [Vec<usize>],
        alpha: f32,
        beta: f32,
        py: f32,
    ) {
        for i in 1..columns.len() {
            for &target in &columns[i] {
                let mut y = 0.;
                let mut w = 0.;
                for &link_index in &graph.nodes[target].target_links {
                    let link = &graph.links[link_index];
                    let v = link.value as f32
                        * (graph.nodes[target].layer as f32
                            - graph.nodes[link.source].layer as f32);
                    y += target_top(graph, link.source, target, py) * v;
                    w += v;
                }
                if w <= 0. {
                    continue;
                }
                let dy = (y / w - graph.nodes[target].y0) * alpha;
                graph.nodes[target].y0 += dy;
                graph.nodes[target].y1 += dy;
                reorder_node_links(graph, target);
            }
            sort_column(graph, &mut columns[i]);
            self.resolve_collisions(graph, &columns[i], beta, py);
        }
    }

    /// Reposition each node based on its outgoing links.
    fn relax_right_to_left(
        &self,
        graph: &mut SankeyGraph,
        columns: &mut [Vec<usize>],
        alpha: f32,
        beta: f32,
        py: f32,
    ) {
        for i in (0..columns.len().saturating_sub(1)).rev() {
            for &source in &columns[i] {
                let mut y = 0.;
                let mut w = 0.;
                for &link_index in &graph.nodes[source].source_links {
                    let link = &graph.links[link_index];
                    let v = link.value as f32
                        * (graph.nodes[link.target].layer as f32
                            - graph.nodes[source].layer as f32);
                    y += source_top(graph, source, link.target, py) * v;
                    w += v;
                }
                if w <= 0. {
                    continue;
                }
                let dy = (y / w - graph.nodes[source].y0) * alpha;
                graph.nodes[source].y0 += dy;
                graph.nodes[source].y1 += dy;
                reorder_node_links(graph, source);
            }
            sort_column(graph, &mut columns[i]);
            self.resolve_collisions(graph, &columns[i], beta, py);
        }
    }

    /// d3's middle-out collision resolution: push nodes away from the middle
    /// node, then clamp the column against the extent edges.
    fn resolve_collisions(&self, graph: &mut SankeyGraph, column: &[usize], beta: f32, py: f32) {
        if column.is_empty() {
            return;
        }

        let i = column.len() >> 1;
        let subject_y0 = graph.nodes[column[i]].y0;
        let subject_y1 = graph.nodes[column[i]].y1;
        push_up(graph, &column[..i], subject_y0 - py, beta, py);
        push_down(graph, &column[i + 1..], subject_y1 + py, beta, py);
        push_up(graph, column, self.y1, beta, py);
        push_down(graph, column, self.y0, beta, py);
    }
}

/// Shift every node (and its attached link ends) by its layer's offset.
/// Used by both column centering and flat-run staggering.
fn apply_layer_offsets(graph: &mut SankeyGraph, offsets: &[f32]) {
    // Precompute per-node offsets so the link loop doesn't borrow `nodes`
    // while mutating `links`.
    let node_offset: Vec<f32> = graph.nodes.iter().map(|n| offsets[n.layer]).collect();
    for node in &mut graph.nodes {
        let dy = node_offset[node.index];
        node.y0 += dy;
        node.y1 += dy;
    }
    for link in &mut graph.links {
        link.y0 += node_offset[link.source];
        link.y1 += node_offset[link.target];
    }
}

fn compute_node_links(graph: &mut SankeyGraph) {
    for index in 0..graph.links.len() {
        let (source, target) = (graph.links[index].source, graph.links[index].target);
        graph.nodes[source].source_links.push(index);
        graph.nodes[target].target_links.push(index);
    }
}

fn compute_node_values(graph: &mut SankeyGraph) {
    for index in 0..graph.nodes.len() {
        let outgoing: f64 = graph.nodes[index]
            .source_links
            .iter()
            .map(|&link| graph.links[link].value)
            .sum();
        let incoming: f64 = graph.nodes[index]
            .target_links
            .iter()
            .map(|&link| graph.links[link].value)
            .sum();
        graph.nodes[index].value = outgoing.max(incoming);
    }
}

/// Assign the longest-path `depth` (from any source) and `height` (to any
/// sink) from a single topological ordering. A node left unordered means its
/// incoming links never resolved, i.e. a cycle.
fn compute_node_ranks(graph: &mut SankeyGraph) -> Result<(), SankeyError> {
    let n = graph.nodes.len();
    let mut incoming: Vec<usize> = graph
        .nodes
        .iter()
        .map(|node| node.target_links.len())
        .collect();
    // Doubles as the traversal queue and, once drained, the topological order.
    let mut order: Vec<usize> = (0..n).filter(|&index| incoming[index] == 0).collect();

    // Ranks live in their own arrays rather than in the nodes: the traversal
    // hops between them by index, and the node struct is an order of magnitude
    // wider than a `usize`.
    let mut depths = vec![0usize; n];
    let mut visited = 0;
    while visited < order.len() {
        let index = order[visited];
        visited += 1;
        let depth = depths[index] + 1;
        for &link in &graph.nodes[index].source_links {
            let target = graph.links[link].target;
            depths[target] = depths[target].max(depth);
            incoming[target] -= 1;
            if incoming[target] == 0 {
                order.push(target);
            }
        }
    }
    if order.len() != n {
        return Err(SankeyError::CircularLink);
    }

    // Walking the order backwards means every target's height is already final
    // when its sources are visited.
    let mut heights = vec![0usize; n];
    for &index in order.iter().rev() {
        for &link in &graph.nodes[index].source_links {
            heights[index] = heights[index].max(heights[graph.links[link].target] + 1);
        }
    }

    for (node, (depth, height)) in graph.nodes.iter_mut().zip(depths.into_iter().zip(heights)) {
        node.depth = depth;
        node.height = height;
    }
    Ok(())
}

/// Sort a node's outgoing links by the target node's `y0` (then link index).
fn sort_source_links(graph: &mut SankeyGraph, index: usize) {
    let mut links = std::mem::take(&mut graph.nodes[index].source_links);
    // The link-index tie-break makes the order total, so an unstable sort
    // is deterministic and avoids the stable sort's scratch allocation.
    links.sort_unstable_by(|&a, &b| {
        let ya = graph.nodes[graph.links[a].target].y0;
        let yb = graph.nodes[graph.links[b].target].y0;
        ya.partial_cmp(&yb)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.cmp(&b))
    });
    graph.nodes[index].source_links = links;
}

/// Sort a node's incoming links by the source node's `y0` (then link index).
fn sort_target_links(graph: &mut SankeyGraph, index: usize) {
    let mut links = std::mem::take(&mut graph.nodes[index].target_links);
    links.sort_unstable_by(|&a, &b| {
        let ya = graph.nodes[graph.links[a].source].y0;
        let yb = graph.nodes[graph.links[b].source].y0;
        ya.partial_cmp(&yb)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.cmp(&b))
    });
    graph.nodes[index].target_links = links;
}

/// After a node moved, re-sort the link lists of its neighbors on the
/// opposite ends (d3's reorderNodeLinks).
///
/// Iterates by position to avoid cloning the link lists on this hot path;
/// the sorts only mutate the neighbors' lists, never the one being walked.
fn reorder_node_links(graph: &mut SankeyGraph, index: usize) {
    for i in 0..graph.nodes[index].target_links.len() {
        let link = graph.nodes[index].target_links[i];
        let source = graph.links[link].source;
        sort_source_links(graph, source);
    }
    for i in 0..graph.nodes[index].source_links.len() {
        let link = graph.nodes[index].source_links[i];
        let target = graph.links[link].target;
        sort_target_links(graph, target);
    }
}

fn sort_column(graph: &SankeyGraph, column: &mut [usize]) {
    column.sort_by(|&a, &b| {
        graph.nodes[a]
            .y0
            .partial_cmp(&graph.nodes[b].y0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
}

/// Push overlapping nodes down (d3's resolveCollisionsTopToBottom).
fn push_down(graph: &mut SankeyGraph, column: &[usize], mut y: f32, alpha: f32, py: f32) {
    for &index in column {
        let node = &mut graph.nodes[index];
        let dy = (y - node.y0) * alpha;
        if dy > 1e-6 {
            node.y0 += dy;
            node.y1 += dy;
        }
        y = node.y1 + py;
    }
}

/// Push overlapping nodes up (d3's resolveCollisionsBottomToTop).
fn push_up(graph: &mut SankeyGraph, column: &[usize], mut y: f32, alpha: f32, py: f32) {
    for &index in column.iter().rev() {
        let node = &mut graph.nodes[index];
        let dy = (node.y1 - y) * alpha;
        if dy > 1e-6 {
            node.y0 -= dy;
            node.y1 -= dy;
        }
        y = node.y0 - py;
    }
}

/// The ideal `y0` for `target` so that its ribbon from `source` lines up
/// with the slot the ribbon occupies in the source's outgoing stack
/// (d3's targetTop).
fn target_top(graph: &SankeyGraph, source: usize, target: usize, py: f32) -> f32 {
    let source_node = &graph.nodes[source];
    let mut y = source_node.y0 - source_node.source_links.len().saturating_sub(1) as f32 * py / 2.;
    for &link_index in &source_node.source_links {
        let link = &graph.links[link_index];
        if link.target == target {
            break;
        }
        y += link.width + py;
    }
    for &link_index in &graph.nodes[target].target_links {
        let link = &graph.links[link_index];
        if link.source == source {
            break;
        }
        y -= link.width;
    }
    y
}

/// The ideal `y0` for `source` so that its ribbon to `target` lines up with
/// the slot the ribbon occupies in the target's incoming stack
/// (d3's sourceTop).
fn source_top(graph: &SankeyGraph, source: usize, target: usize, py: f32) -> f32 {
    let target_node = &graph.nodes[target];
    let mut y = target_node.y0 - target_node.target_links.len().saturating_sub(1) as f32 * py / 2.;
    for &link_index in &target_node.target_links {
        let link = &graph.links[link_index];
        if link.source == source {
            break;
        }
        y += link.width + py;
    }
    for &link_index in &graph.nodes[source].source_links {
        let link = &graph.links[link_index];
        if link.target == target {
            break;
        }
        y -= link.width;
    }
    y
}

/// Assign each link's `y0`/`y1` (ribbon centers) and per-end widths by
/// stacking the sorted link lists within each node. Each side shares the
/// node height in proportion to the link values, so both sides of a node
/// are fully covered even when the graph is imbalanced (equivalent to the
/// nominal `width` stacking when it is balanced).
fn compute_link_breadths(graph: &mut SankeyGraph) {
    for index in 0..graph.nodes.len() {
        let node = &graph.nodes[index];
        let node_y0 = node.y0;
        let node_height = node.y1 - node.y0;

        let outgoing: f64 = node
            .source_links
            .iter()
            .map(|&link| graph.links[link].value)
            .sum();
        let mut y0 = node_y0;
        for i in 0..graph.nodes[index].source_links.len() {
            let link = &mut graph.links[graph.nodes[index].source_links[i]];
            let width = if outgoing > 0. {
                (link.value / outgoing) as f32 * node_height
            } else {
                0.
            };
            link.source_width = width;
            link.y0 = y0 + width / 2.;
            y0 += width;
        }

        let node = &graph.nodes[index];
        let incoming: f64 = node
            .target_links
            .iter()
            .map(|&link| graph.links[link].value)
            .sum();
        let mut y1 = node_y0;
        for i in 0..graph.nodes[index].target_links.len() {
            let link = &mut graph.links[graph.nodes[index].target_links[i]];
            let width = if incoming > 0. {
                (link.value / incoming) as f32 * node_height
            } else {
                0.
            };
            link.target_width = width;
            link.y1 = y1 + width / 2.;
            y1 += width;
        }
    }
}

/// Build the filled ribbon path for a link — the equivalent of d3-sankey's
/// `sankeyLinkHorizontal()`: a horizontal cubic bezier with control points at
/// the horizontal midpoint, thickened to the per-end link widths (clamped to
/// `min_width` so tiny flows stay visible).
pub fn sankey_link_path(
    source: &SankeyNodeLayout,
    target: &SankeyNodeLayout,
    link: &SankeyLinkLayout,
    min_width: f32,
    origin: Point<Pixels>,
) -> Option<Path<Pixels>> {
    let source_half = link.source_width.max(min_width) / 2.;
    let target_half = link.target_width.max(min_width) / 2.;
    let sx = source.x1;
    let tx = target.x0;
    let mx = (sx + tx) / 2.;

    let mut builder = PathBuilder::fill();
    builder.move_to(origin_point(px(sx), px(link.y0 - source_half), origin));
    builder.cubic_bezier_to(
        origin_point(px(tx), px(link.y1 - target_half), origin),
        origin_point(px(mx), px(link.y0 - source_half), origin),
        origin_point(px(mx), px(link.y1 - target_half), origin),
    );
    builder.line_to(origin_point(px(tx), px(link.y1 + target_half), origin));
    builder.cubic_bezier_to(
        origin_point(px(sx), px(link.y0 + source_half), origin),
        origin_point(px(mx), px(link.y1 + target_half), origin),
        origin_point(px(mx), px(link.y0 + source_half), origin),
    );
    builder.close();
    builder.build().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    const EPSILON: f32 = 1e-3;

    fn links(links: &[(usize, usize, f64)]) -> Vec<SankeyLink> {
        links
            .iter()
            .map(|&(source, target, value)| SankeyLink::new(source, target, value))
            .collect()
    }

    #[test]
    fn test_sankey_builder() {
        let sankey = Sankey::new();
        assert_eq!(sankey.node_width, 24.);
        assert_eq!(sankey.node_padding, 8.);
        assert_eq!(sankey.align, SankeyAlign::Justify);
        assert_eq!(sankey.iterations, 6);
        assert_eq!(
            (sankey.x0, sankey.y0, sankey.x1, sankey.y1),
            (0., 0., 1., 1.)
        );

        let sankey = Sankey::new()
            .node_width(12.)
            .node_padding(10.)
            .node_align(SankeyAlign::Left)
            .iterations(10)
            .size(400., 300.);
        assert_eq!(sankey.node_width, 12.);
        assert_eq!(sankey.node_padding, 10.);
        assert_eq!(sankey.align, SankeyAlign::Left);
        assert_eq!(sankey.iterations, 10);
        assert_eq!(
            (sankey.x0, sankey.y0, sankey.x1, sankey.y1),
            (0., 0., 400., 300.)
        );

        let sankey = Sankey::new().extent(10., 20., 30., 40.);
        assert_eq!(
            (sankey.x0, sankey.y0, sankey.x1, sankey.y1),
            (10., 20., 30., 40.)
        );
    }

    #[test]
    fn test_sankey_layout_chain() {
        // A -> B -> C
        let graph = Sankey::new()
            .node_width(10.)
            .size(100., 100.)
            .layout(3, &links(&[(0, 1, 5.), (1, 2, 5.)]))
            .unwrap();

        let depths: Vec<usize> = graph.nodes.iter().map(|n| n.depth).collect();
        let heights: Vec<usize> = graph.nodes.iter().map(|n| n.height).collect();
        let layers: Vec<usize> = graph.nodes.iter().map(|n| n.layer).collect();
        assert_eq!(depths, vec![0, 1, 2]);
        assert_eq!(heights, vec![2, 1, 0]);
        assert_eq!(layers, vec![0, 1, 2]);
        assert_eq!(graph.layer_count(), 3);

        assert_eq!(graph.nodes[0].x0, 0.);
        assert_eq!(graph.nodes[1].x0, 45.);
        assert_eq!(graph.nodes[2].x0, 90.);
        for node in &graph.nodes {
            assert_eq!(node.x1 - node.x0, 10.);
            assert_eq!(node.value, 5.);
            // Every node carries the full flow, so all span the full height.
            assert!((node.y1 - node.y0 - 100.).abs() < EPSILON);
        }
        for link in &graph.links {
            assert!((link.width - 100.).abs() < EPSILON);
            // The chain is balanced, so both ribbon ends span the nodes.
            assert!((link.source_width - 100.).abs() < EPSILON);
            assert!((link.target_width - 100.).abs() < EPSILON);
        }

        // `topology` agrees with `layout` on the topological fields.
        let topology = Sankey::new()
            .node_width(10.)
            .size(100., 100.)
            .topology(3, &links(&[(0, 1, 5.), (1, 2, 5.)]))
            .unwrap();
        assert_eq!(topology.layer_count(), 3);
        for (a, b) in topology.nodes.iter().zip(&graph.nodes) {
            assert_eq!(a.depth, b.depth);
            assert_eq!(a.height, b.height);
            assert_eq!(a.layer, b.layer);
            assert_eq!(a.value, b.value);
            assert_eq!(a.x0, b.x0);
        }

        // Completing a unit-extent topology on the final extent (the chart's
        // two-pass flow) matches a direct layout on that extent.
        let topology = Sankey::new()
            .node_width(10.)
            .topology(3, &links(&[(0, 1, 5.), (1, 2, 5.)]))
            .unwrap();
        let completed = Sankey::new()
            .node_width(10.)
            .size(100., 100.)
            .layout_from(topology);
        for (a, b) in completed.nodes.iter().zip(&graph.nodes) {
            assert_eq!((a.x0, a.y0, a.x1, a.y1), (b.x0, b.y0, b.x1, b.y1));
        }
        for (a, b) in completed.links.iter().zip(&graph.links) {
            assert_eq!((a.y0, a.y1, a.width), (b.y0, b.y1, b.width));
        }
    }

    #[test]
    fn test_sankey_topology_large_chain() {
        const NODE_COUNT: usize = 50_000;
        let links: Vec<SankeyLink> = (0..NODE_COUNT - 1)
            .map(|source| SankeyLink::new(source, source + 1, 1.))
            .collect();
        let graph = Sankey::new().topology(NODE_COUNT, &links).unwrap();

        assert_eq!(graph.nodes[0].height, NODE_COUNT - 1);
        assert_eq!(graph.nodes[NODE_COUNT - 1].depth, NODE_COUNT - 1);
    }

    #[test]
    fn test_sankey_alignment() {
        // A -> B -> C, plus a short branch A -> D.
        let links = links(&[(0, 1, 1.), (1, 2, 1.), (0, 3, 1.)]);
        let layers = |align: SankeyAlign| -> Vec<usize> {
            Sankey::new()
                .node_align(align)
                .size(100., 100.)
                .layout(4, &links)
                .unwrap()
                .nodes
                .iter()
                .map(|n| n.layer)
                .collect()
        };

        assert_eq!(layers(SankeyAlign::Left), vec![0, 1, 2, 1]);
        assert_eq!(layers(SankeyAlign::Right), vec![0, 1, 2, 2]);
        assert_eq!(layers(SankeyAlign::Justify), vec![0, 1, 2, 2]);
        assert_eq!(layers(SankeyAlign::Center), vec![0, 1, 2, 1]);
    }

    #[test]
    fn test_sankey_link_offsets() {
        // One source fanning out into two targets.
        let graph = Sankey::new()
            .node_width(10.)
            .size(100., 100.)
            .layout(3, &links(&[(0, 1, 30.), (0, 2, 10.)]))
            .unwrap();

        let source = &graph.nodes[0];
        let source_height = source.y1 - source.y0;
        let total_width: f32 = graph.links.iter().map(|l| l.width).sum();
        assert!((total_width - source_height).abs() < EPSILON);

        // Widths are proportional to values.
        assert!((graph.links[0].width / graph.links[1].width - 3.).abs() < EPSILON);

        // Outgoing ribbons stack contiguously within the source node.
        let (first, second) = if graph.links[0].y0 < graph.links[1].y0 {
            (&graph.links[0], &graph.links[1])
        } else {
            (&graph.links[1], &graph.links[0])
        };
        assert!((first.y0 - first.source_width / 2. - source.y0).abs() < EPSILON);
        assert!(
            (first.y0 + first.source_width / 2. - (second.y0 - second.source_width / 2.)).abs()
                < EPSILON
        );

        // Each target has a single incoming ribbon filling its full height.
        for link in &graph.links {
            let target = &graph.nodes[link.target];
            assert!((link.y1 - link.target_width / 2. - target.y0).abs() < EPSILON);
            assert!((link.y1 + link.target_width / 2. - target.y1).abs() < EPSILON);
        }
    }

    #[test]
    fn test_sankey_imbalanced_link_widths() {
        // A -> B (10) but B -> C (7): B is sized by its incoming flow, and
        // its single outgoing ribbon is stretched to cover its outgoing side
        // while the ribbon's target end matches C's height.
        let graph = Sankey::new()
            .size(100., 100.)
            .layout(3, &links(&[(0, 1, 10.), (1, 2, 7.)]))
            .unwrap();

        let node_b = &graph.nodes[1];
        let node_c = &graph.nodes[2];
        let out_link = &graph.links[1];
        assert!((out_link.source_width - (node_b.y1 - node_b.y0)).abs() < EPSILON);
        assert!((out_link.target_width - (node_c.y1 - node_c.y0)).abs() < EPSILON);
        // The two ends differ: B is taller (value 10) than C (value 7).
        assert!(out_link.source_width > out_link.target_width);

        // Both ends stay centered on their nodes' filled ranges.
        assert!((out_link.y0 - (node_b.y0 + node_b.y1) / 2.).abs() < EPSILON);
        assert!((out_link.y1 - (node_c.y0 + node_c.y1) / 2.).abs() < EPSILON);
    }

    #[test]
    fn test_sankey_sqrt_scale_fills_nodes() {
        // With the sqrt scale, a node's children must still exactly fill it:
        // the incoming and outgoing ribbon widths each sum to the node height
        // (no gaps), and the diagram is compressed vs linear.
        let links = links(&[(0, 1, 90.), (1, 2, 40.), (1, 3, 50.)]);
        let sqrt = Sankey::new()
            .value_scale(SankeyValueScale::Sqrt)
            .size(100., 100.)
            .layout(4, &links)
            .unwrap();

        for node in &sqrt.nodes {
            let node_height = node.y1 - node.y0;
            let incoming: f32 = node
                .target_links
                .iter()
                .map(|&l| sqrt.links[l].target_width)
                .sum();
            let outgoing: f32 = node
                .source_links
                .iter()
                .map(|&l| sqrt.links[l].source_width)
                .sum();
            if !node.target_links.is_empty() {
                assert!((incoming - node_height).abs() < EPSILON);
            }
            if !node.source_links.is_empty() {
                assert!((outgoing - node_height).abs() < EPSILON);
            }
        }

        // Two leaf nodes (50 and 40) show the sqrt compression directly:
        // their height ratio is sqrt(50/40), not the linear 50/40.
        let ratio = (sqrt.nodes[3].y1 - sqrt.nodes[3].y0) / (sqrt.nodes[2].y1 - sqrt.nodes[2].y0);
        assert!((ratio - (50f32 / 40.).sqrt()).abs() < 0.02);
    }

    #[test]
    fn test_sankey_value_conservation() {
        // Incoming 10, outgoing 7: node value takes the max.
        let graph = Sankey::new()
            .size(100., 100.)
            .layout(3, &links(&[(0, 1, 10.), (1, 2, 7.)]))
            .unwrap();

        assert_eq!(graph.nodes[1].value, 10.);

        for node in &graph.nodes {
            assert!(node.y0 <= node.y1);
            assert!(node.y0 >= -EPSILON);
            assert!(node.y1 <= 100. + EPSILON);
        }
    }

    #[test]
    fn test_sankey_vertical_centering() {
        // Each column's stack is centered in the extent: its midpoint equals
        // the extent midpoint. Uses multi-node columns so the flat-run stagger
        // (which only touches equal single-node columns) does not apply.
        let graph = Sankey::new()
            .node_padding(20.)
            .extent(0., 10., 100., 90.)
            .layout(
                5,
                &links(&[(0, 2, 40.), (1, 2, 10.), (2, 3, 25.), (2, 4, 25.)]),
            )
            .unwrap();

        let layers = graph.layer_count();
        let mut lo = vec![f32::INFINITY; layers];
        let mut hi = vec![f32::NEG_INFINITY; layers];
        for node in &graph.nodes {
            lo[node.layer] = lo[node.layer].min(node.y0);
            hi[node.layer] = hi[node.layer].max(node.y1);
        }
        // Extent is [10, 90], midpoint 50; every column's midpoint matches.
        for l in 0..layers {
            assert!(((lo[l] + hi[l]) / 2. - 50.).abs() < EPSILON);
        }
        // Centering keeps every node within the extent.
        for node in &graph.nodes {
            assert!(node.y0 >= 10. - EPSILON);
            assert!(node.y1 <= 90. + EPSILON);
        }
    }

    #[test]
    fn test_sankey_stagger_flat_columns() {
        // Two equal single-node columns feeding a fan-out: the sparse trunk
        // columns don't fill the height, so the equal pair is staggered off
        // the center line to curve the otherwise-flat ribbon between them.
        let graph = Sankey::new()
            .node_padding(20.)
            .size(100., 100.)
            .layout(
                6,
                &links(&[
                    (0, 1, 100.),
                    (1, 2, 40.),
                    (1, 3, 30.),
                    (1, 4, 20.),
                    (1, 5, 10.),
                ]),
            )
            .unwrap();

        // Nodes 0 and 1 are the equal single-node columns; one is nudged off
        // center so their centers differ (the ribbon is no longer flat), but
        // both stay within the extent.
        let c0 = (graph.nodes[0].y0 + graph.nodes[0].y1) / 2.;
        let c1 = (graph.nodes[1].y0 + graph.nodes[1].y1) / 2.;
        assert!((c0 - c1).abs() > EPSILON);
        for node in &graph.nodes {
            assert!(node.y0 >= -EPSILON);
            assert!(node.y1 <= 100. + EPSILON);
        }

        // After the stagger's per-layer shift, each ribbon end must still be
        // attached to its node: `y0` centered on the source node's outgoing
        // stack, `y1` on the target node's incoming stack. (Guards against a
        // source/target mix-up in `apply_layer_offsets`.)
        for node in &graph.nodes {
            let mut y = node.y0;
            for &l in &node.source_links {
                let link = &graph.links[l];
                assert!((link.y0 - (y + link.source_width / 2.)).abs() < EPSILON);
                y += link.source_width;
            }
            let mut y = node.y0;
            for &l in &node.target_links {
                let link = &graph.links[l];
                assert!((link.y1 - (y + link.target_width / 2.)).abs() < EPSILON);
                y += link.target_width;
            }
        }
    }

    #[test]
    fn test_sankey_circular_link() {
        let sankey = Sankey::new().size(100., 100.);

        assert_eq!(
            sankey
                .layout(2, &links(&[(0, 1, 1.), (1, 0, 1.)]))
                .unwrap_err(),
            SankeyError::CircularLink
        );
        assert_eq!(
            sankey.layout(1, &links(&[(0, 0, 1.)])).unwrap_err(),
            SankeyError::CircularLink
        );
        assert_eq!(
            sankey.layout(2, &links(&[(0, 5, 1.)])).unwrap_err(),
            SankeyError::MissingNode(5)
        );
    }

    #[test]
    fn test_sankey_degenerate() {
        // Empty graph.
        let graph = Sankey::new().size(100., 100.).layout(0, &[]).unwrap();
        assert!(graph.nodes.is_empty());
        assert!(graph.links.is_empty());
        assert_eq!(graph.layer_count(), 0);

        // All-zero link values must not produce NaN coordinates.
        let graph = Sankey::new()
            .size(100., 100.)
            .layout(2, &links(&[(0, 1, 0.)]))
            .unwrap();
        for node in &graph.nodes {
            assert!((node.y1 - node.y0).abs() < EPSILON);
            assert!(node.x0.is_finite() && node.x1.is_finite());
            assert!(node.y0.is_finite() && node.y1.is_finite());
        }

        // Isolated nodes collapse into a single column without dividing by zero.
        let graph = Sankey::new().size(100., 100.).layout(2, &[]).unwrap();
        assert_eq!(graph.layer_count(), 1);
        for node in &graph.nodes {
            assert_eq!(node.x0, 0.);
            assert!(node.y0.is_finite() && node.y1.is_finite());
        }
    }
}
