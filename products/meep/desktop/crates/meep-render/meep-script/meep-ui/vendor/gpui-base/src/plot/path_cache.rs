use std::hash::{DefaultHasher, Hash, Hasher};

use gpui::{App, ElementId, Entity, Path, Pixels, Point, Window};

/// A tessellated path reused across frames while its shape is unchanged.
///
/// A chart repaints on every frame it is on screen — a scrolling list moves
/// it — and tessellating its strokes (Catmull-Rom curves, dashes) is the bulk
/// of that work, while the vertices only depend on the projected points
/// relative to the chart's origin. A plot keeps one cache per shape and paints
/// through [`Line::paint_cached`](super::shape::Line::paint_cached) or
/// [`Area::paint_cached`](super::shape::Area::paint_cached): the path is built
/// once per shape key, at a zero origin, and moved to the frame's origin on
/// every paint.
#[derive(Default)]
pub struct PathCache {
    key: Option<u64>,
    /// Built relative to a zero origin.
    path: Option<Path<Pixels>>,
}

impl PathCache {
    /// The path for `key`, moved to `origin`. `build` runs only when the key
    /// differs from the last call's; it must build relative to a zero origin.
    pub fn get(
        &mut self,
        key: u64,
        origin: Point<Pixels>,
        build: impl FnOnce() -> Option<Path<Pixels>>,
    ) -> Option<Path<Pixels>> {
        if self.key != Some(key) {
            self.path = build();
            self.key = Some(key);
        }
        self.path.as_ref().map(|path| translated(path, origin))
    }

    /// Whether the last [`Self::get`] reused the path built by an earlier one.
    pub fn is_warm(&self) -> bool {
        self.key.is_some()
    }
}

/// `path` moved by `offset`. A finished path is only its bounds and vertices;
/// the builder cursor it keeps is not read again.
fn translated(path: &Path<Pixels>, offset: Point<Pixels>) -> Path<Pixels> {
    let mut path = path.clone();
    path.bounds.origin = path.bounds.origin + offset;
    for vertex in &mut path.vertices {
        vertex.xy_position = vertex.xy_position + offset;
    }
    path
}

/// The [`PathCache`]s of a plot that is rebuilt on every render, kept in the
/// window's element state so they outlive the plot value.
///
/// Plots are plain values built by `render` and painted once, so a cache
/// held by the plot would be empty every frame; this keeps them under the
/// element id the plot paints in (plus `key`), for as long as the plot is
/// painted on consecutive frames.
///
/// ```ignore
/// fn paint(&mut self, bounds: Bounds<Pixels>, window: &mut Window, cx: &mut App) {
///     let caches = PathCaches::for_paint("lines", window, cx);
///     caches.update(cx, |caches, _| {
///         for (ix, line) in lines.iter().enumerate() {
///             line.paint_cached(&bounds, caches.slot(ix), window);
///         }
///     });
/// }
/// ```
#[derive(Default)]
pub struct PathCaches {
    slots: Vec<PathCache>,
}

impl PathCaches {
    /// The caches for the plot painting under the window's current element
    /// id; `key` tells apart several groups of shapes in one plot.
    pub fn for_paint(key: impl Into<ElementId>, window: &mut Window, cx: &mut App) -> Entity<Self> {
        window.use_keyed_state(key, cx, |_, _| Self::default())
    }

    /// The `index`-th cache, created on first use. Paint each shape through
    /// the same index every frame.
    pub fn slot(&mut self, index: usize) -> &mut PathCache {
        if self.slots.len() <= index {
            self.slots.resize_with(index + 1, PathCache::default);
        }
        &mut self.slots[index]
    }

    /// Two caches for a shape that keeps a fill and a stroke, such as
    /// [`Area::paint_cached`](super::shape::Area::paint_cached), at
    /// `2 * index` and `2 * index + 1`.
    pub fn slot_pair(&mut self, index: usize) -> (&mut PathCache, &mut PathCache) {
        let first = 2 * index;
        if self.slots.len() <= first + 1 {
            self.slots.resize_with(first + 2, PathCache::default);
        }
        let (head, tail) = self.slots.split_at_mut(first + 1);
        (&mut head[first], &mut tail[0])
    }
}

/// A shape key from its projected points (origin-relative) and whatever else
/// shapes the tessellation (stroke width, curve style, dash pattern).
pub struct ShapeKey(DefaultHasher);

impl ShapeKey {
    pub fn new(extra: impl Hash) -> Self {
        let mut hasher = DefaultHasher::new();
        extra.hash(&mut hasher);
        Self(hasher)
    }

    pub fn point(&mut self, point: Point<Pixels>) -> &mut Self {
        point.x.as_f32().to_bits().hash(&mut self.0);
        point.y.as_f32().to_bits().hash(&mut self.0);
        self
    }

    pub fn f32(&mut self, value: f32) -> &mut Self {
        value.to_bits().hash(&mut self.0);
        self
    }

    pub fn finish(&self) -> u64 {
        self.0.finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{PathBuilder, point, px};

    fn diagonal() -> Option<Path<Pixels>> {
        let mut builder = PathBuilder::stroke(px(2.));
        builder.move_to(point(px(0.), px(0.)));
        builder.line_to(point(px(10.), px(10.)));
        builder.build().ok()
    }

    #[test]
    fn builds_once_per_key_and_moves_to_each_origin() {
        let mut cache = PathCache::default();
        let mut builds = 0;
        let first = cache
            .get(1, point(px(100.), px(50.)), || {
                builds += 1;
                diagonal()
            })
            .unwrap();
        let second = cache
            .get(1, point(px(200.), px(50.)), || {
                builds += 1;
                diagonal()
            })
            .unwrap();
        assert_eq!(builds, 1);
        assert_eq!(first.vertices.len(), second.vertices.len());
        for (a, b) in first.vertices.iter().zip(&second.vertices) {
            assert_eq!(b.xy_position.x - a.xy_position.x, px(100.));
            assert_eq!(b.xy_position.y, a.xy_position.y);
            assert_eq!(a.st_position, b.st_position);
        }
        assert_eq!(second.bounds.origin.x - first.bounds.origin.x, px(100.));
        assert_eq!(first.bounds.size, second.bounds.size);

        cache.get(2, point(px(0.), px(0.)), || {
            builds += 1;
            diagonal()
        });
        assert_eq!(builds, 2);
    }

    #[test]
    fn keys_follow_points_and_extras() {
        let a = ShapeKey::new(("linear", 1.0f32.to_bits()))
            .point(point(px(1.), px(2.)))
            .finish();
        let same = ShapeKey::new(("linear", 1.0f32.to_bits()))
            .point(point(px(1.), px(2.)))
            .finish();
        let moved = ShapeKey::new(("linear", 1.0f32.to_bits()))
            .point(point(px(1.), px(3.)))
            .finish();
        let thicker = ShapeKey::new(("linear", 2.0f32.to_bits()))
            .point(point(px(1.), px(2.)))
            .finish();
        assert_eq!(a, same);
        assert_ne!(a, moved);
        assert_ne!(a, thicker);
    }
}
