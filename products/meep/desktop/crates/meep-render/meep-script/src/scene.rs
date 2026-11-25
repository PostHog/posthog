//! Native scenes: large node-and-edge data for script views, held in typed
//! columns and indexed so drawing a frame costs what is visible, not what
//! exists.
//!
//! A script hands over `Float32Array`/`Uint32Array` columns once
//! (`host.scene.set`). The host copies them out of JavaScript without JSON,
//! then builds three indexes in O(n):
//! - a uniform spatial grid, for the nodes inside a viewport and hit tests;
//! - edge adjacency, so edges are found from the visible nodes outward;
//! - a density pyramid (counts per cell, finest 1024² down to 1²). A
//!   zoomed-out frame draws the level whose cells are a few points wide,
//!   baked once into a texture (`density_bgra`): one textured quad per
//!   frame, whatever the node count or zoom.
//!
//! No JavaScript runs while a scene pans, zooms or is hovered.
use std::collections::BTreeMap;

pub const MAX_NODES: usize = 4_000_000;
pub const MAX_EDGES: usize = 4_000_000;
pub const MAX_LABELS: usize = 200_000;
pub const MAX_GROUPS: usize = 16;
/// Finest density level: 1024 × 1024 cells (5 MB with dominant groups).
const PYRAMID_SIDE: usize = 1024;

/// One rectangle in data space.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rect {
    pub x0: f32,
    pub y0: f32,
    pub x1: f32,
    pub y1: f32,
}
impl Rect {
    pub fn contains(&self, x: f32, y: f32) -> bool {
        x >= self.x0 && x <= self.x1 && y >= self.y0 && y <= self.y1
    }
    pub fn width(&self) -> f32 {
        self.x1 - self.x0
    }
    pub fn height(&self) -> f32 {
        self.y1 - self.y0
    }
}

/// Columns a script provides. Only `x` and `y` are required.
#[derive(Default)]
pub struct Columns {
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    /// Per-node radius in screen points; empty means the scene default.
    pub size: Vec<f32>,
    /// Per-node index into the palette; empty means group 0.
    pub group: Vec<u8>,
    /// Theme tokens, one per group.
    pub palette: Vec<String>,
    /// Endpoint pairs: [a0, b0, a1, b1, ...].
    pub edges: Vec<u32>,
    pub labels: Vec<String>,
}

/// Cells of a uniform grid, each listing the items inside it (CSR layout).
struct Grid {
    side: usize,
    bounds: Rect,
    start: Vec<u32>,
    items: Vec<u32>,
}
impl Grid {
    fn build(x: &[f32], y: &[f32], bounds: Rect, side: usize) -> Self {
        let cells = side * side;
        let cell_of = |i: usize| cell(x[i], y[i], bounds, side);
        let mut count = vec![0u32; cells + 1];
        for i in 0..x.len() {
            count[cell_of(i) + 1] += 1;
        }
        for c in 0..cells {
            count[c + 1] += count[c];
        }
        let start = count.clone();
        let mut next = count;
        let mut items = vec![0u32; x.len()];
        for i in 0..x.len() {
            let c = cell_of(i);
            items[next[c] as usize] = i as u32;
            next[c] += 1;
        }
        Self {
            side,
            bounds,
            start,
            items,
        }
    }
    /// Cell index range covering `r`, clamped to the grid.
    fn span(&self, r: Rect) -> Option<(usize, usize, usize, usize)> {
        let b = self.bounds;
        if r.x1 < b.x0 || r.x0 > b.x1 || r.y1 < b.y0 || r.y0 > b.y1 {
            return None;
        }
        let s = self.side as f32;
        let fx =
            |x: f32| (((x - b.x0) / b.width().max(f32::EPSILON)) * s).clamp(0., s - 1.) as usize;
        let fy =
            |y: f32| (((y - b.y0) / b.height().max(f32::EPSILON)) * s).clamp(0., s - 1.) as usize;
        Some((fx(r.x0), fy(r.y0), fx(r.x1), fy(r.y1)))
    }
    fn each(&self, r: Rect, mut f: impl FnMut(u32) -> bool) {
        let Some((cx0, cy0, cx1, cy1)) = self.span(r) else {
            return;
        };
        for cy in cy0..=cy1 {
            for cx in cx0..=cx1 {
                let c = cy * self.side + cx;
                for &i in &self.items[self.start[c] as usize..self.start[c + 1] as usize] {
                    if !f(i) {
                        return;
                    }
                }
            }
        }
    }
}

fn cell(x: f32, y: f32, b: Rect, side: usize) -> usize {
    let s = side as f32;
    let cx = (((x - b.x0) / b.width().max(f32::EPSILON)) * s).clamp(0., s - 1.) as usize;
    let cy = (((y - b.y0) / b.height().max(f32::EPSILON)) * s).clamp(0., s - 1.) as usize;
    cy * side + cx
}

/// One density level: node counts and the most common group per cell.
pub struct Level {
    pub side: usize,
    pub count: Vec<u32>,
    pub group: Vec<u8>,
}

pub struct Scene {
    /// Unique per built scene, so caches of what it drew (density textures)
    /// never outlive it.
    pub id: u64,
    pub columns: Columns,
    pub bounds: Rect,
    grid: Grid,
    /// Node -> incident edge indices (CSR).
    adjacency_start: Vec<u32>,
    adjacency: Vec<u32>,
    /// Finest first.
    pub pyramid: Vec<Level>,
}

/// A data point in a density cell, ready to paint.
#[cfg(test)]
pub struct Cell {
    pub rect: Rect,
    pub count: u32,
    pub group: u8,
}

/// What one frame should draw.
#[cfg(test)]
pub enum Frame {
    /// Few enough nodes to draw individually, with edges when they fit.
    Nodes {
        nodes: Vec<u32>,
        edges: Option<Vec<u32>>,
    },
    /// Too many: density cells, sized a few pixels on screen.
    Density { cells: Vec<Cell>, max: u32 },
}

impl Scene {
    pub fn new(columns: Columns) -> Result<Self, String> {
        let n = columns.x.len();
        if n != columns.y.len() {
            return Err("Scene x and y need the same length".into());
        }
        if n > MAX_NODES {
            return Err(format!("A scene holds at most {MAX_NODES} nodes"));
        }
        if !columns.size.is_empty() && columns.size.len() != n {
            return Err("Scene size needs one value per node".into());
        }
        if !columns.group.is_empty() && columns.group.len() != n {
            return Err("Scene group needs one value per node".into());
        }
        if columns.palette.len() > MAX_GROUPS {
            return Err(format!("A scene palette has at most {MAX_GROUPS} colours"));
        }
        if let Some(g) = columns
            .group
            .iter()
            .find(|g| **g as usize >= columns.palette.len().max(1))
        {
            return Err(format!("Group {g} has no palette colour"));
        }
        if !columns.edges.len().is_multiple_of(2) || columns.edges.len() / 2 > MAX_EDGES {
            return Err(format!(
                "Scene edges are endpoint pairs, at most {MAX_EDGES}"
            ));
        }
        if let Some(e) = columns.edges.iter().find(|e| **e as usize >= n) {
            return Err(format!("Edge endpoint {e} is not a node"));
        }
        if columns.labels.len() > MAX_LABELS
            || (!columns.labels.is_empty() && columns.labels.len() != n)
        {
            return Err(format!(
                "Scene labels need one per node, at most {MAX_LABELS}"
            ));
        }
        if columns.x.iter().chain(&columns.y).any(|v| !v.is_finite()) {
            return Err("Scene positions must be finite numbers".into());
        }
        let bounds = bounds(&columns.x, &columns.y);
        // About eight nodes per grid cell keeps queries cheap at any density.
        let side = ((n as f32 / 8.).sqrt().ceil() as usize).clamp(1, 2048);
        let grid = Grid::build(&columns.x, &columns.y, bounds, side);
        let (adjacency_start, adjacency) = adjacency(n, &columns.edges);
        let pyramid = pyramid(&columns, bounds);
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
        let id = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Ok(Self {
            id,
            columns,
            bounds,
            grid,
            adjacency_start,
            adjacency,
            pyramid,
        })
    }

    pub fn len(&self) -> usize {
        self.columns.x.len()
    }
    pub fn is_empty(&self) -> bool {
        self.columns.x.is_empty()
    }
    pub fn edge_count(&self) -> usize {
        self.columns.edges.len() / 2
    }

    /// Moves, regroups or resizes some nodes and rebuilds the indexes.
    pub fn patch(
        &mut self,
        indices: &[u32],
        x: &[f32],
        y: &[f32],
        group: &[u8],
        size: &[f32],
    ) -> Result<(), String> {
        let n = self.len();
        for (column, len) in [(x.len(), indices.len()), (y.len(), indices.len())] {
            if column != 0 && column != len {
                return Err("Patch columns need one value per index".into());
            }
        }
        for (k, &i) in indices.iter().enumerate() {
            let i = i as usize;
            if i >= n {
                return Err(format!("Node {i} does not exist"));
            }
            if let Some(v) = x.get(k) {
                self.columns.x[i] = *v;
            }
            if let Some(v) = y.get(k) {
                self.columns.y[i] = *v;
            }
            if let Some(v) = group.get(k) {
                if self.columns.group.is_empty() {
                    self.columns.group = vec![0; n];
                }
                self.columns.group[i] = *v;
            }
            if let Some(v) = size.get(k) {
                if self.columns.size.is_empty() {
                    self.columns.size = vec![f32::NAN; n];
                }
                self.columns.size[i] = *v;
            }
        }
        let columns = std::mem::take(&mut self.columns);
        *self = Scene::new(columns)?;
        Ok(())
    }

    /// Whether a frame of `r` draws nodes one by one: at most `budget` are inside.
    pub fn draws_nodes(&self, r: Rect, budget: usize) -> bool {
        let (x, y) = (&self.columns.x, &self.columns.y);
        let mut count = 0;
        self.grid.each(r, |i| {
            if r.contains(x[i as usize], y[i as usize]) {
                count += 1;
            }
            count <= budget
        });
        count <= budget
    }

    /// The pyramid level a density frame at `scale` draws: the finest whose
    /// cells are at least 1.5 points wide on screen, fine enough to read as a
    /// smooth cloud on Retina, coarse enough that a full-screen frame stays
    /// around 100k cells.
    pub fn density_level(&self, scale: f32) -> usize {
        let extent = self.bounds.width().max(self.bounds.height());
        self.pyramid
            .iter()
            .position(|l| extent / l.side as f32 * scale >= 1.5)
            .unwrap_or(self.pyramid.len() - 1)
    }

    /// A pyramid level as a `side` × `side` BGRA image spanning `bounds`, one
    /// pixel per cell: each cell's majority group colour (`colors`, BGRA),
    /// with an opacity that rises with the log of its count. Drawn as one
    /// texture, a frame of any zoom costs one quad.
    pub fn density_bgra(&self, level: usize, colors: &[[u8; 4]]) -> Vec<u8> {
        let level = &self.pyramid[level];
        let max = level.count.iter().copied().max().unwrap_or(0);
        let ln_max = (max as f32).ln().max(1.);
        // Sparse cells barely glow, dense ones are solid: a log ramp from 6%,
        // so the edge of a cloud fades instead of ending in hard steps.
        let strength =
            |count: u32| 0.06 + 0.94 * ((count as f32).ln() / ln_max).clamp(0., 1.).powf(0.85);
        let ramp: Vec<f32> = (0..=max.min(4096)).map(strength).collect();
        let color = |g: u8| colors[(g as usize).min(colors.len().saturating_sub(1))];
        let side = level.side;
        let mut out = vec![0u8; side * side * 4];
        for (c, (&count, &group)) in level.count.iter().zip(&level.group).enumerate() {
            if count == 0 {
                continue;
            }
            let [b, g, r, a] = color(group);
            let s = ramp
                .get(count as usize)
                .copied()
                .unwrap_or_else(|| strength(count));
            out[c * 4..c * 4 + 4].copy_from_slice(&[b, g, r, (a as f32 * s).round() as u8]);
        }
        // Empty cells take a neighbour's colour at zero opacity, so filtering
        // between a cell and empty space fades it out instead of to black.
        for c in 0..side * side {
            if level.count[c] != 0 {
                continue;
            }
            let (cx, cy) = (c % side, c / side);
            let near = [
                (cx > 0).then(|| c - 1),
                (cx + 1 < side).then(|| c + 1),
                (cy > 0).then(|| c - side),
                (cy + 1 < side).then(|| c + side),
            ];
            if let Some(n) = near.into_iter().flatten().find(|n| level.count[*n] != 0) {
                let [b, g, r, _] = color(level.group[n]);
                out[c * 4..c * 4 + 3].copy_from_slice(&[b, g, r]);
            }
        }
        out
    }

    /// Nodes inside `r`, stopping (and returning None) past `budget`.
    pub fn visible(&self, r: Rect, budget: usize) -> Option<Vec<u32>> {
        let (x, y) = (&self.columns.x, &self.columns.y);
        let mut out = Vec::new();
        let mut over = false;
        self.grid.each(r, |i| {
            if r.contains(x[i as usize], y[i as usize]) {
                if out.len() == budget {
                    over = true;
                    return false;
                }
                out.push(i);
            }
            true
        });
        (!over).then_some(out)
    }

    /// Edges touching any of `nodes`, each once, or None past `budget`.
    pub fn edges_of(&self, nodes: &[u32], budget: usize) -> Option<Vec<u32>> {
        let mut seen = std::collections::HashSet::new();
        let mut out = Vec::new();
        for &i in nodes {
            let i = i as usize;
            for &e in &self.adjacency
                [self.adjacency_start[i] as usize..self.adjacency_start[i + 1] as usize]
            {
                if seen.insert(e) {
                    if out.len() == budget {
                        return None;
                    }
                    out.push(e);
                }
            }
        }
        Some(out)
    }

    /// Endpoints of edge `e`.
    pub fn edge(&self, e: u32) -> (u32, u32) {
        let e = e as usize * 2;
        (self.columns.edges[e], self.columns.edges[e + 1])
    }

    /// What to draw for viewport `r` at `scale` screen points per data unit.
    #[cfg(test)]
    pub fn frame(&self, r: Rect, scale: f32, node_budget: usize, edge_budget: usize) -> Frame {
        if let Some(nodes) = self.visible(r, node_budget) {
            let edges = self.edges_of(&nodes, edge_budget);
            return Frame::Nodes { nodes, edges };
        }
        let level = &self.pyramid[self.density_level(scale)];
        let (w, h) = (
            self.bounds.width().max(f32::EPSILON) / level.side as f32,
            self.bounds.height().max(f32::EPSILON) / level.side as f32,
        );
        let s = level.side as f32;
        let span = |lo: f32, hi: f32, origin: f32, step: f32| {
            (
                (((lo - origin) / step).floor().max(0.) as usize).min(level.side - 1),
                (((hi - origin) / step).ceil().min(s) as usize).max(1),
            )
        };
        let (cx0, cx1) = span(r.x0, r.x1, self.bounds.x0, w);
        let (cy0, cy1) = span(r.y0, r.y1, self.bounds.y0, h);
        let mut cells = Vec::new();
        let mut max = 0;
        for cy in cy0..cy1 {
            for cx in cx0..cx1 {
                let c = cy * level.side + cx;
                let count = level.count[c];
                if count == 0 {
                    continue;
                }
                max = max.max(count);
                let x0 = self.bounds.x0 + cx as f32 * w;
                let y0 = self.bounds.y0 + cy as f32 * h;
                cells.push(Cell {
                    rect: Rect {
                        x0,
                        y0,
                        x1: x0 + w,
                        y1: y0 + h,
                    },
                    count,
                    group: level.group[c],
                });
            }
        }
        Frame::Density { cells, max }
    }

    /// The node nearest (x, y) within `radius` data units.
    pub fn hit(&self, x: f32, y: f32, radius: f32) -> Option<u32> {
        let r = Rect {
            x0: x - radius,
            y0: y - radius,
            x1: x + radius,
            y1: y + radius,
        };
        let (xs, ys) = (&self.columns.x, &self.columns.y);
        let mut best: Option<(f32, u32)> = None;
        self.grid.each(r, |i| {
            let (dx, dy) = (xs[i as usize] - x, ys[i as usize] - y);
            let d = dx * dx + dy * dy;
            if d <= radius * radius && best.is_none_or(|(b, _)| d < b) {
                best = Some((d, i));
            }
            true
        });
        best.map(|(_, i)| i)
    }
}

fn bounds(x: &[f32], y: &[f32]) -> Rect {
    if x.is_empty() {
        return Rect {
            x0: 0.,
            y0: 0.,
            x1: 1.,
            y1: 1.,
        };
    }
    let (mut b, pad) = (
        Rect {
            x0: f32::MAX,
            y0: f32::MAX,
            x1: f32::MIN,
            y1: f32::MIN,
        },
        1e-3,
    );
    for (&x, &y) in x.iter().zip(y) {
        b.x0 = b.x0.min(x);
        b.y0 = b.y0.min(y);
        b.x1 = b.x1.max(x);
        b.y1 = b.y1.max(y);
    }
    // A single point or a straight line still has an area to fit.
    if b.width() < pad {
        b.x0 -= 0.5;
        b.x1 += 0.5;
    }
    if b.height() < pad {
        b.y0 -= 0.5;
        b.y1 += 0.5;
    }
    b
}

fn adjacency(n: usize, edges: &[u32]) -> (Vec<u32>, Vec<u32>) {
    let mut start = vec![0u32; n + 1];
    for pair in edges.as_chunks::<2>().0 {
        start[pair[0] as usize + 1] += 1;
        if pair[1] != pair[0] {
            start[pair[1] as usize + 1] += 1;
        }
    }
    for i in 0..n {
        start[i + 1] += start[i];
    }
    let mut next = start.clone();
    let mut list = vec![0u32; start[n] as usize];
    for (e, pair) in edges.as_chunks::<2>().0.iter().enumerate() {
        for (k, &v) in pair.iter().enumerate() {
            if k == 1 && pair[1] == pair[0] {
                break;
            }
            list[next[v as usize] as usize] = e as u32;
            next[v as usize] += 1;
        }
    }
    (start, list)
}

fn pyramid(c: &Columns, b: Rect) -> Vec<Level> {
    // Small scenes need no finer level than about two cells per node.
    let side = ((c.x.len() as f32 * 2.).sqrt().ceil() as usize)
        .next_power_of_two()
        .clamp(1, PYRAMID_SIDE);
    let mut finest = Level {
        side,
        count: vec![0; side * side],
        group: vec![0; side * side],
    };
    // The cell's colour is its majority group, found with a Boyer–Moore vote
    // (one candidate and one counter per cell) instead of per-group tallies.
    let mut votes = vec![0u32; if c.group.is_empty() { 0 } else { side * side }];
    for i in 0..c.x.len() {
        let k = cell(c.x[i], c.y[i], b, side);
        finest.count[k] += 1;
        if let Some(&g) = c.group.get(i) {
            if votes[k] == 0 {
                finest.group[k] = g;
                votes[k] = 1;
            } else if finest.group[k] == g {
                votes[k] += 1;
            } else {
                votes[k] -= 1;
            }
        }
    }
    let mut levels = vec![finest];
    while levels.last().unwrap().side > 1 {
        let fine = levels.last().unwrap();
        let side = fine.side / 2;
        let mut level = Level {
            side,
            count: vec![0; side * side],
            group: vec![0; side * side],
        };
        for cy in 0..side {
            for cx in 0..side {
                let mut t = [0u32; MAX_GROUPS];
                let mut total = 0;
                for (dx, dy) in [(0, 0), (1, 0), (0, 1), (1, 1)] {
                    let f = (cy * 2 + dy) * fine.side + cx * 2 + dx;
                    total += fine.count[f];
                    t[fine.group[f] as usize] += fine.count[f];
                }
                level.count[cy * side + cx] = total;
                level.group[cy * side + cx] = dominant(&t);
            }
        }
        levels.push(level);
    }
    levels
}

fn dominant(t: &[u32; MAX_GROUPS]) -> u8 {
    t.iter()
        .enumerate()
        .max_by_key(|(_, n)| **n)
        .map(|(g, _)| g as u8)
        .unwrap_or(0)
}

/// Every scene a view holds, by name. Not saved: a view rebuilds its scenes
/// in `init`, the way it fetches its data.
#[derive(Default)]
pub struct Scenes {
    pub scenes: BTreeMap<String, std::rc::Rc<Scene>>,
    pub version: u64,
}

#[cfg(any(test, feature = "test-support"))]
/// The Showcase galaxy: a million stars in spiral arms, plus 2,500
/// constellations of 8 linked stars.
pub fn galaxy() -> Columns {
    const N: usize = 1_000_000;
    let mut seed: u32 = 42;
    let rand = |seed: &mut u32| {
        *seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
        *seed as f32 / 4294967296.
    };
    let mut c = Columns {
        palette: vec![
            "accent".into(),
            "positive".into(),
            "orange".into(),
            "danger".into(),
        ],
        ..Default::default()
    };
    let (arms, twist) = (4, 1.6f32);
    for i in 0..N {
        let gauss = |seed: &mut u32| (rand(seed) + rand(seed) + rand(seed) - 1.5) * 2.;
        if i % 8 == 0 {
            let (gx, gy) = (gauss(&mut seed) * 55., gauss(&mut seed) * 40.);
            c.x.push(gx);
            c.y.push(gy);
            c.group.push(0);
            continue;
        }
        let r = rand(&mut seed).powf(0.55) * 620. + 30.;
        let spread = gauss(&mut seed) * 0.32 / (0.6 + r / 400.);
        let a = (i % arms) as f32 * std::f32::consts::TAU / arms as f32
            + (r / 30.).ln() * twist
            + spread;
        let (jx, jy) = (gauss(&mut seed) * 6., gauss(&mut seed) * 6.);
        c.x.push(a.cos() * r + jx);
        c.y.push(a.sin() * r + jy);
        c.group.push(if spread.abs() > 0.42 { 2 } else { 1 });
    }
    for k in 0..2500 * 7 {
        let a = (N - 20_000 + k / 7 * 8 + k % 7) as u32;
        c.edges.extend([a, a + 1]);
    }
    c
}

#[cfg(test)]
mod tests {
    use super::*;

    fn grid_scene(side: usize) -> Scene {
        let mut c = Columns::default();
        for y in 0..side {
            for x in 0..side {
                c.x.push(x as f32);
                c.y.push(y as f32);
            }
        }
        // A chain along each row.
        for y in 0..side {
            for x in 0..side - 1 {
                c.edges
                    .extend([(y * side + x) as u32, (y * side + x + 1) as u32]);
            }
        }
        Scene::new(c).unwrap()
    }

    #[::core::prelude::v1::test]
    fn visible_nodes_and_their_edges_come_from_the_viewport() {
        let s = grid_scene(100);
        let r = Rect {
            x0: 10.,
            y0: 10.,
            x1: 19.5,
            y1: 19.5,
        };
        let nodes = s.visible(r, 10_000).unwrap();
        assert_eq!(nodes.len(), 100);
        assert!(
            nodes
                .iter()
                .all(|&i| r.contains(s.columns.x[i as usize], s.columns.y[i as usize]))
        );
        // 10 rows × 9 inner edges, plus each row's edges leaving the viewport on both sides.
        let edges = s.edges_of(&nodes, 10_000).unwrap();
        assert_eq!(edges.len(), 10 * 11);
        assert!(s.visible(r, 99).is_none(), "budget must stop the query");
    }

    #[::core::prelude::v1::test]
    fn zoomed_out_frames_draw_density_not_nodes() {
        let s = grid_scene(1000); // a million nodes
        let all = s.bounds;
        match s.frame(all, 1.0, 50_000, 50_000) {
            Frame::Density { cells, max } => {
                // At 1.5-point cells a full million-node view is ~262k cells:
                // bounded by the screen, far below the node count.
                assert!(cells.len() <= 1_000_000 / 3, "{} cells", cells.len());
                assert!(max >= 1);
                let total: u32 = cells.iter().map(|c| c.count).sum();
                assert_eq!(
                    total, 1_000_000,
                    "density cells must account for every node"
                );
            }
            Frame::Nodes { .. } => panic!("a million nodes should not draw individually"),
        }
        let close = Rect {
            x0: 500.,
            y0: 500.,
            x1: 520.,
            y1: 520.,
        };
        assert!(matches!(
            s.frame(close, 40., 50_000, 50_000),
            Frame::Nodes { .. }
        ));
    }

    #[::core::prelude::v1::test]
    fn density_texture_has_one_pixel_per_cell_and_fades_empty_ones() {
        // Three nodes in one corner cell, one node in the opposite corner, groups 1 and 0.
        let c = Columns {
            x: vec![0., 0.01, 0.02, 10.],
            y: vec![0., 0.01, 0.02, 10.],
            group: vec![1, 1, 1, 0],
            palette: vec!["accent".into(), "positive".into()],
            ..Default::default()
        };
        let s = Scene::new(c).unwrap();
        let level = s.pyramid.len() - 2; // 2 × 2 cells
        assert_eq!(s.pyramid[level].side, 2);
        let colors = [[10, 20, 30, 255], [40, 50, 60, 255]];
        let px = s.density_bgra(level, &colors);
        assert_eq!(px.len(), 2 * 2 * 4);
        let pixel = |cx: usize, cy: usize| &px[(cy * 2 + cx) * 4..][..4];
        // The densest cell is solid in its group's colour; a sparser one is fainter.
        assert_eq!(pixel(0, 0), &[40, 50, 60, 255]);
        assert_eq!(&pixel(1, 1)[..3], &[10, 20, 30]);
        assert!(pixel(1, 1)[3] > 0 && pixel(1, 1)[3] < 255);
        // Empty cells are transparent but carry a neighbour's colour, not black.
        assert_eq!(pixel(1, 0)[3], 0);
        assert_ne!(&pixel(1, 0)[..3], &[0, 0, 0]);
        // The level for a scale is the finest whose cells are at least 1.5 points.
        let extent = s.bounds.width().max(s.bounds.height());
        let chosen = s.density_level(3.);
        assert!(extent / s.pyramid[chosen].side as f32 * 3. >= 1.5);
        assert!(chosen == 0 || extent / s.pyramid[chosen - 1].side as f32 * 3. < 1.5);
    }

    #[::core::prelude::v1::test]
    fn hits_the_nearest_node_within_reach() {
        let s = grid_scene(50);
        assert_eq!(s.hit(10.1, 20.2, 0.5), Some(20 * 50 + 10));
        assert_eq!(s.hit(10.5, 20.5, 0.3), None);
    }

    #[::core::prelude::v1::test]
    fn bad_columns_are_rejected_with_a_reason() {
        let bad = |c: Columns| Scene::new(c).err().unwrap();
        assert!(
            bad(Columns {
                x: vec![0.],
                y: vec![],
                ..Default::default()
            })
            .contains("same length")
        );
        assert!(
            bad(Columns {
                x: vec![0.],
                y: vec![0.],
                edges: vec![0, 5],
                ..Default::default()
            })
            .contains("not a node")
        );
        assert!(
            bad(Columns {
                x: vec![f32::NAN],
                y: vec![0.],
                ..Default::default()
            })
            .contains("finite")
        );
        assert!(
            bad(Columns {
                x: vec![0.],
                y: vec![0.],
                group: vec![2],
                palette: vec!["accent".into()],
                ..Default::default()
            })
            .contains("palette")
        );
    }

    #[::core::prelude::v1::test]
    fn a_million_node_frame_is_fast() {
        let built = std::time::Instant::now();
        let s = grid_scene(1000);
        eprintln!("1M nodes + 1M edges indexed in {:?}", built.elapsed());
        let started = std::time::Instant::now();
        for _ in 0..20 {
            let _ = s.frame(s.bounds, 1.4, 50_000, 50_000);
        }
        let per_frame = started.elapsed() / 20;
        eprintln!("1M-node density frame: {per_frame:?}");
        assert!(
            per_frame < std::time::Duration::from_millis(40),
            "{per_frame:?} per frame"
        );
    }

    /// `cargo test -p meep-script density_preview -- --ignored --nocapture`
    /// writes the galaxy's density as the old per-cell quads drew it and as
    /// the baked texture draws it (bilinear, like the GPU sampler), at 2x.
    #[::core::prelude::v1::test]
    #[ignore]
    fn density_preview() {
        let s = Scene::new(galaxy()).unwrap();
        let dir = std::env::var_os("MEEP_PREVIEW_DIR").map_or_else(
            || {
                // This crate also runs as a standalone workspace.
                let manifest = std::process::Command::new(env!("CARGO"))
                    .args(["locate-project", "--workspace", "--message-format", "plain"])
                    .output()
                    .expect("locate the preview workspace");
                assert!(
                    manifest.status.success(),
                    "cannot locate the preview workspace"
                );
                let path = std::str::from_utf8(&manifest.stdout).expect("workspace manifest path");
                std::path::Path::new(path.trim_end())
                    .with_file_name(".scratch")
                    .join("density")
            },
            std::path::PathBuf::from,
        );
        std::fs::create_dir_all(&dir).expect("create density preview directory");
        let palette: [[u8; 3]; 4] = [
            [0x25, 0x63, 0xeb],
            [0x16, 0xa3, 0x4a],
            [0xea, 0x58, 0x0c],
            [0xdc, 0x26, 0x26],
        ];
        let bgra: Vec<[u8; 4]> = palette.iter().map(|[r, g, b]| [*b, *g, *r, 255]).collect();
        for (name, zoom, (w, h)) in [
            ("fit", 1.0f32, (878usize, 742usize)),
            ("zoom4", 4.0, (878, 742)),
        ] {
            let fit = (w as f32 / s.bounds.width()).min(h as f32 / s.bounds.height()) * 0.92;
            let scale = fit * zoom;
            let (cx, cy) = if zoom > 1. {
                (200., 100.)
            } else {
                (
                    (s.bounds.x0 + s.bounds.x1) / 2.,
                    (s.bounds.y0 + s.bounds.y1) / 2.,
                )
            };
            let (ox, oy) = (cx - w as f32 / 2. / scale, cy - h as f32 / 2. / scale);
            let dpr = 2usize;
            let (pw, ph) = (w * dpr, h * dpr);
            let level = s.density_level(scale);
            let l = &s.pyramid[level];
            let (cw, ch) = (
                s.bounds.width() / l.side as f32,
                s.bounds.height() / l.side as f32,
            );
            let view = Rect {
                x0: ox,
                y0: oy,
                x1: ox + w as f32 / scale,
                y1: oy + h as f32 / scale,
            };
            let blend = |dst: &mut [f32; 3], rgb: [f32; 3], a: f32| {
                for k in 0..3 {
                    dst[k] = dst[k] * (1. - a) + rgb[k] * a;
                }
            };
            // Old: one quad per non-empty visible cell, opacity from the visible max.
            let mut old = vec![[1f32; 3]; pw * ph];
            let Frame::Density { cells, max } = s.frame(view, scale, 30_000, 0) else {
                panic!("density")
            };
            let ln_max = (max as f32).ln().max(1.);
            for cell in &cells {
                let st = 0.06 + 0.94 * ((cell.count as f32).ln() / ln_max).clamp(0., 1.).powf(0.85);
                let [r, g, b] = palette[cell.group as usize % 4].map(|v| v as f32 / 255.);
                let px = |x: f32, o: f32| (x - o) * scale * dpr as f32;
                let (x0, x1) = (
                    px(cell.rect.x0, ox).max(0.),
                    px(cell.rect.x1, ox).min(pw as f32),
                );
                let (y0, y1) = (
                    px(cell.rect.y0, oy).max(0.),
                    px(cell.rect.y1, oy).min(ph as f32),
                );
                for y in y0.round() as usize..y1.round() as usize {
                    for x in x0.round() as usize..x1.round() as usize {
                        blend(&mut old[y * pw + x], [r, g, b], st);
                    }
                }
            }
            // New: the baked level, sampled bilinearly at each device pixel centre.
            let tex = s.density_bgra(level, &bgra);
            let side = l.side;
            let texel = |x: isize, y: isize| -> [f32; 4] {
                let (x, y) = (
                    x.clamp(0, side as isize - 1) as usize,
                    y.clamp(0, side as isize - 1) as usize,
                );
                let p = &tex[(y * side + x) * 4..][..4];
                [
                    p[2] as f32 / 255.,
                    p[1] as f32 / 255.,
                    p[0] as f32 / 255.,
                    p[3] as f32 / 255.,
                ]
            };
            let mut new = vec![[1f32; 3]; pw * ph];
            for y in 0..ph {
                for x in 0..pw {
                    let dx = ox + (x as f32 + 0.5) / dpr as f32 / scale;
                    let dy = oy + (y as f32 + 0.5) / dpr as f32 / scale;
                    let u = (dx - s.bounds.x0) / cw - 0.5;
                    let v = (dy - s.bounds.y0) / ch - 0.5;
                    if u < -0.5 || v < -0.5 || u > side as f32 - 0.5 || v > side as f32 - 0.5 {
                        continue;
                    }
                    let (fu, fv) = (u.floor(), v.floor());
                    let (tu, tv) = (u - fu, v - fv);
                    let (iu, iv) = (fu as isize, fv as isize);
                    let mut c = [0f32; 4];
                    for (wx, wy, sx, sy) in [
                        (1. - tu, 1. - tv, 0, 0),
                        (tu, 1. - tv, 1, 0),
                        (1. - tu, tv, 0, 1),
                        (tu, tv, 1, 1),
                    ] {
                        let t = texel(iu + sx, iv + sy);
                        for k in 0..4 {
                            c[k] += t[k] * wx * wy;
                        }
                    }
                    blend(&mut new[y * pw + x], [c[0], c[1], c[2]], c[3]);
                }
            }
            for (label, px) in [("old", &old), ("new", &new)] {
                let bytes: Vec<u8> = px
                    .iter()
                    .flat_map(|p| p.map(|v| (v * 255.).round() as u8))
                    .collect();
                image::RgbImage::from_raw(pw as u32, ph as u32, bytes)
                    .unwrap()
                    .save(dir.join(format!("density-{name}-{label}.png")))
                    .unwrap();
            }
            let diff: f32 = old
                .iter()
                .zip(&new)
                .map(|(a, b)| (0..3).map(|k| (a[k] - b[k]).abs()).sum::<f32>())
                .sum::<f32>()
                / (pw * ph * 3) as f32;
            eprintln!(
                "{name}: level {} ({} cells across), {} visible cells, mean abs difference {:.4}",
                level,
                side,
                cells.len(),
                diff
            );
        }
    }

    /// `cargo test -p meep-script scene_bench -- --ignored --nocapture`
    #[::core::prelude::v1::test]
    #[ignore]
    fn scene_bench() {
        use std::time::Instant;
        let ms = |t: Instant| t.elapsed().as_secs_f64() * 1000.;
        let columns = galaxy();
        let t = Instant::now();
        let s = Scene::new(columns).unwrap();
        eprintln!("\nSCENE BENCH debug_assertions={}", cfg!(debug_assertions));
        eprintln!("  index 1M stars:                 {:8.1} ms", ms(t));
        // A 1200 × 800 point viewport fitted to the galaxy.
        let scale = (1200. / s.bounds.width()).min(800. / s.bounds.height());
        let fitted = s.bounds;
        let time = |label: &str, f: &dyn Fn() -> String| {
            let t = Instant::now();
            let mut n = 0;
            let mut out = String::new();
            while n < 3 || t.elapsed().as_millis() < 300 {
                out = f();
                n += 1;
            }
            eprintln!("  {label:<32}{:8.3} ms  {out}", ms(t) / n as f64);
        };
        let describe = |f: Frame| match f {
            Frame::Density { cells, .. } => format!("density, {} cells", cells.len()),
            Frame::Nodes { nodes, edges } => {
                format!("{} nodes, {:?} edges", nodes.len(), edges.map(|e| e.len()))
            }
        };
        time("frame, fitted (zoomed out):", &|| {
            describe(s.frame(fitted, scale, 30_000, 20_000))
        });
        time("hover check, fitted:", &|| {
            describe(s.frame(fitted, scale, 30_000, 0))
        });
        let zoom = scale * 20.;
        let (cx, cy) = (200., 100.);
        let close = Rect {
            x0: cx - 600. / zoom,
            y0: cy - 400. / zoom,
            x1: cx + 600. / zoom,
            y1: cy + 400. / zoom,
        };
        time("frame, 20x zoom:", &|| {
            describe(s.frame(close, zoom, 30_000, 20_000))
        });
        let mid = Rect {
            x0: cx - 600. / (scale * 4.),
            y0: cy - 400. / (scale * 4.),
            x1: cx + 600. / (scale * 4.),
            y1: cy + 400. / (scale * 4.),
        };
        time("frame, 4x zoom:", &|| {
            describe(s.frame(mid, scale * 4., 30_000, 20_000))
        });
        time("hit test:", &|| format!("{:?}", s.hit(cx, cy, 5. / zoom)));
    }
}
