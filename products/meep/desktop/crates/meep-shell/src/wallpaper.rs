//! The window's base layer, the glass the panes rest on, wears a faint
//! wallpaper: Truchet arcs, the 1970s motif of quarter-circle ribbons that
//! join tile to tile into one meandering line. It shows only in the gutters
//! and under the sidebar, at a few percent of ink, so it gives the window a
//! material without ever sitting behind something you read closely.
use gpui_kit::*;

/// The tile edge. Large enough that the curves read as a pattern, small
/// enough that a gutter shows a whole turn of one.
const TILE: f32 = 36.;
/// The two ribbons each arc pair draws, as offsets from the tile's half.
const RIBBONS: [f32; 2] = [-4., 4.];

/// Which way a tile turns, fixed per tile so the pattern never shifts as
/// the window resizes.
fn flipped(column: i32, row: i32) -> bool {
    let mut h = (column as u32).wrapping_mul(0x9e37_79b1) ^ (row as u32).wrapping_mul(0x85eb_ca6b);
    h ^= h >> 15;
    h = h.wrapping_mul(0x2c1b_3c6d);
    h ^= h >> 12;
    h & 1 == 1
}

fn build(size: gpui_kit::Size<Pixels>) -> Option<Path<Pixels>> {
    let mut path = PathBuilder::stroke(px(1.));
    let columns = (f32::from(size.width) / TILE).ceil() as i32;
    let rows = (f32::from(size.height) / TILE).ceil() as i32;
    let half = TILE / 2.;
    for row in 0..rows {
        for column in 0..columns {
            let x = column as f32 * TILE;
            let y = row as f32 * TILE;
            // Two opposite corners of the tile; each gets concentric quarter
            // arcs from one edge's middle to the next.
            let corners = if flipped(column, row) {
                [(x, y), (x + TILE, y + TILE)]
            } else {
                [(x + TILE, y), (x, y + TILE)]
            };
            for (cx, cy) in corners {
                let dx = if cx == x { 1. } else { -1. };
                let dy = if cy == y { 1. } else { -1. };
                for offset in RIBBONS {
                    let r = half + offset;
                    path.move_to(point(px(cx + dx * r), px(cy)));
                    // Sweep direction depends on which corner the arc rounds.
                    path.arc_to(
                        point(px(r), px(r)),
                        px(0.),
                        false,
                        dx * dy > 0.,
                        point(px(cx), px(cy + dy * r)),
                    );
                }
            }
        }
    }
    path.build().ok()
}

/// Larger than any window, so the pattern is built once and every window
/// size shows a clipped piece of it: resizing never rebuilds it.
const EXTENT: f32 = 3600.;

/// The pattern, built once for the whole app.
pub fn layer() -> impl IntoElement {
    static PATTERN: std::sync::OnceLock<Option<Path<Pixels>>> = std::sync::OnceLock::new();
    canvas(
        |_, _, _| {},
        move |_, _, window, _| {
            let pattern = PATTERN.get_or_init(|| build(size(px(EXTENT), px(EXTENT))));
            if let Some(path) = pattern {
                // The layer fills the window from its origin, so the pattern
                // is already in place; the window clips what lies beyond.
                window.paint_path(
                    path.clone(),
                    rgba((meep_ui::components::theme::get(0) << 8) | 0x0a),
                );
            }
        },
    )
    .absolute()
    .inset_0()
}
