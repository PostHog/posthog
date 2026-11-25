//! `Scene`: a native canvas for `host.scene` data. Pan, zoom, hover and the
//! dragged camera are all Rust; the script hears only `onHover(index)` and
//! `onSelect({ index })`. Each frame asks the scene index for the visible
//! nodes, or draws a baked density texture when too many are visible, so the
//! cost follows the screen, not the data.
use super::{Build, Node, color, handler, style};
use crate::scene::{Rect, Scene};
use crate::sdk::ui;
use gpui_kit::*;
use serde_json::{Value, json};
use std::{cell::RefCell, collections::HashMap, rc::Rc, sync::Arc};

/// Most nodes drawn one by one; past this a frame draws density.
const NODE_BUDGET: usize = 30_000;
/// Most edges drawn in one frame; past this edges wait for a closer zoom.
const EDGE_BUDGET: usize = 20_000;
/// Labels draw when this few nodes are on screen.
const LABEL_BUDGET: usize = 250;
/// Line segments per path: GPUI tessellates with 16-bit indices.
const SEGMENTS_PER_PATH: usize = 4_000;

/// Where the scene's camera is, kept per element across renders.
#[derive(Default, Clone)]
struct Camera {
    /// Screen points per data unit.
    scale: f32,
    /// Data coordinates at the element's top-left corner.
    ox: f32,
    oy: f32,
    /// The scene and `fit` value the camera last fitted, so a new scene or a
    /// changed `fit` frames everything again.
    fitted: Option<(usize, String)>,
    fit_scale: f32,
    /// The `focus` index last centred on.
    focused: Option<u64>,
    /// The `zoom` (relative to fit) last applied.
    zoomed: Option<f32>,
    bounds: Bounds<Pixels>,
    /// Pointer and camera origin when a pan began.
    pan: Option<(Point<Pixels>, f32, f32, bool)>,
    hover: Option<u32>,
}

impl Camera {
    fn view(&self) -> Rect {
        let (w, h) = (
            f32::from(self.bounds.size.width),
            f32::from(self.bounds.size.height),
        );
        Rect {
            x0: self.ox,
            y0: self.oy,
            x1: self.ox + w / self.scale,
            y1: self.oy + h / self.scale,
        }
    }
    fn to_screen(&self, x: f32, y: f32) -> Point<Pixels> {
        self.bounds.origin
            + point(
                px((x - self.ox) * self.scale),
                px((y - self.oy) * self.scale),
            )
    }
    fn to_data(&self, at: Point<Pixels>) -> (f32, f32) {
        let local = at - self.bounds.origin;
        (
            self.ox + f32::from(local.x) / self.scale,
            self.oy + f32::from(local.y) / self.scale,
        )
    }
    fn fit(&mut self, b: Rect) {
        let (w, h) = (
            f32::from(self.bounds.size.width),
            f32::from(self.bounds.size.height),
        );
        if w <= 0. || h <= 0. {
            return;
        }
        self.scale = (w / b.width()).min(h / b.height()) * 0.92;
        self.fit_scale = self.scale;
        self.ox = (b.x0 + b.x1) / 2. - w / 2. / self.scale;
        self.oy = (b.y0 + b.y1) / 2. - h / 2. / self.scale;
    }
    /// Zooms by `factor` keeping the data point under `at` still.
    fn zoom(&mut self, factor: f32, at: Point<Pixels>) {
        let (dx, dy) = self.to_data(at);
        let scale = (self.scale * factor).clamp(self.fit_scale / 4., self.fit_scale * 100_000.);
        let local = at - self.bounds.origin;
        self.scale = scale;
        self.ox = dx - f32::from(local.x) / scale;
        self.oy = dy - f32::from(local.y) / scale;
    }
    fn center_on(&mut self, x: f32, y: f32) {
        let (w, h) = (
            f32::from(self.bounds.size.width),
            f32::from(self.bounds.size.height),
        );
        self.ox = x - w / 2. / self.scale;
        self.oy = y - h / 2. / self.scale;
    }
}

/// Theme colours for each palette entry, resolved at paint time so a theme
/// change recolours the scene without the script.
fn palette(scene: &Scene) -> Vec<Hsla> {
    let tokens: Vec<&str> = if scene.columns.palette.is_empty() {
        vec!["accent"]
    } else {
        scene.columns.palette.iter().map(String::as_str).collect()
    };
    tokens
        .iter()
        .map(|t| color(&json!(t)).unwrap_or_else(|| rgb(ui::theme::color(ui::INK)).into()))
        .collect()
}

/// A scene's density level baked into a texture for some palette.
pub(super) struct DensityImage {
    scene: u64,
    level: usize,
    colors: Vec<Hsla>,
    image: Arc<RenderImage>,
}

/// The texture for one density level, baked on first use and kept while the
/// scene and its colours stay the same. Textures of a replaced scene leave
/// the GPU atlas when the next one is baked.
fn density_image(
    cache: &RefCell<HashMap<String, Vec<DensityImage>>>,
    name: &str,
    scene: &Scene,
    level: usize,
    colors: &[Hsla],
    window: &mut Window,
) -> Arc<RenderImage> {
    let mut cache = cache.borrow_mut();
    let images = cache.entry(name.to_owned()).or_default();
    if let Some(d) = images
        .iter()
        .find(|d| d.scene == scene.id && d.level == level && d.colors == colors)
    {
        return d.image.clone();
    }
    for stale in images.extract_if(.., |d| d.scene != scene.id || d.colors != colors) {
        let _ = window.drop_image(stale.image);
    }
    let bgra: Vec<[u8; 4]> = colors
        .iter()
        .map(|c| {
            let c = c.to_rgb();
            let byte = |v: f32| (v.clamp(0., 1.) * 255.).round() as u8;
            [byte(c.b), byte(c.g), byte(c.r), byte(c.a)]
        })
        .collect();
    let side = scene.pyramid[level].side as u32;
    let buffer = image::RgbaImage::from_raw(side, side, scene.density_bgra(level, &bgra))
        .expect("one BGRA pixel per cell");
    let image = Arc::new(RenderImage::new(vec![image::Frame::new(buffer)]));
    images.push(DensityImage {
        scene: scene.id,
        level,
        colors: colors.to_vec(),
        image: image.clone(),
    });
    image
}

impl Build {
    #[inline(never)]
    pub(super) fn scene(&self, node: &Node, window: &mut Window, cx: &mut App) -> AnyElement {
        let p = &node.p;
        let key = node.key.to_string();
        let name = p["scene"].as_str().unwrap_or("").to_owned();
        let Some(scene) = self
            .shared
            .engine
            .scenes
            .borrow()
            .scenes
            .get(&name)
            .cloned()
        else {
            return style(div(), node)
                .flex()
                .items_center()
                .justify_center()
                .child(ui::caption(if name.is_empty() {
                    "Scene needs `scene`: the name given to host.scene.set".to_owned()
                } else {
                    "Loading…".to_owned()
                }))
                .into_any_element();
        };
        let camera = window.use_keyed_state(
            ElementId::Name(format!("{}:{key}:camera", self.scope).into()),
            cx,
            |_, _| Camera::default(),
        );
        let focus = window
            .use_keyed_state(
                ElementId::Name(format!("{}:{key}:focus", self.scope).into()),
                cx,
                |_, cx| cx.focus_handle(),
            )
            .read(cx)
            .clone();
        let fit_token = p["fit"].to_string();
        let focus_index = p["focus"].as_u64();
        let zoom = p["zoom"].as_f64().map(|z| (z as f32).clamp(0.25, 100_000.));
        let node_size = p["nodeSize"].as_f64().unwrap_or(3.).clamp(0.5, 40.) as f32;
        let edge_color = color(&p.get("edgeColor").cloned().unwrap_or(json!("tertiary")))
            .unwrap_or_else(|| rgb(ui::theme::color(ui::TERTIARY)).into())
            .opacity(p["edgeOpacity"].as_f64().unwrap_or(0.5).clamp(0.05, 1.) as f32);
        let selected: Rc<Vec<u32>> = Rc::new(
            p["selected"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|v| v.as_u64().map(|i| i as u32))
                .filter(|i| (*i as usize) < scene.len())
                .take(1_000)
                .collect(),
        );
        let (on_hover, on_select) = (handler(p, "onHover"), handler(p, "onSelect"));
        let send = {
            let weak = self.weak.clone();
            // Selection comes from a press or release (a gesture); hover does not.
            move |h: Option<u32>, argument: Value, gesture: bool, cx: &mut App| {
                if let Some(h) = h {
                    let _ = weak.update(cx, |view, cx| view.invoke(h, argument, gesture, cx));
                }
            }
        };
        // Redraw the view this scene is built in: the script view, or the
        // cached region holding it (see `regions`).
        let redraw = {
            let view = window.current_view();
            move |cx: &mut App| cx.notify(view)
        };
        let scene_id = Rc::as_ptr(&scene) as usize;

        // Frame on first layout, on a new scene, or when `fit` changes; then
        // centre on `focus` when it changes.
        let prepaint = {
            let (camera, scene) = (camera.clone(), scene.clone());
            move |bounds: Bounds<Pixels>, _: &mut Window, cx: &mut App| {
                camera.update(cx, |c, _| {
                    c.bounds = bounds;
                    if c.fitted.as_ref() != Some(&(scene_id, fit_token.clone())) {
                        c.fit(scene.bounds);
                        c.fitted = Some((scene_id, fit_token.clone()));
                    }
                    // `zoom` scales from the fitted view about the centre,
                    // before `focus` centres, so the two compose.
                    if zoom != c.zoomed {
                        c.zoomed = zoom;
                        if let Some(z) = zoom {
                            let center = c.bounds.center();
                            c.zoom(z * c.fit_scale / c.scale, center);
                        }
                        c.focused = None;
                    }
                    if focus_index != c.focused {
                        c.focused = focus_index;
                        if let Some(i) = focus_index.filter(|i| (*i as usize) < scene.len()) {
                            let i = i as usize;
                            c.center_on(scene.columns.x[i], scene.columns.y[i]);
                        }
                    }
                });
            }
        };

        let paint = {
            let (camera, scene, selected) = (camera.clone(), scene.clone(), selected.clone());
            let (send, redraw) = (send.clone(), redraw);
            let (shared, name) = (self.shared.clone(), name.clone());
            move |_: Bounds<Pixels>, _: (), window: &mut Window, cx: &mut App| {
                // A snapshot: painting needs `cx` for text while reading it.
                let c = camera.read(cx).clone();
                let colors = palette(&scene);
                let view = c.view();
                let nodes = scene.visible(view, NODE_BUDGET);
                window.with_content_mask(Some(ContentMask { bounds: c.bounds }), |window| {
                    match nodes {
                        // Too many nodes to draw one by one: the density level as
                        // one texture, whatever the zoom or the node count.
                        None => {
                            let level = scene.density_level(c.scale);
                            let image = density_image(
                                &shared.scene_images,
                                &name,
                                &scene,
                                level,
                                &colors,
                                window,
                            );
                            let b = scene.bounds;
                            let image_bounds = Bounds::from_corners(
                                c.to_screen(b.x0, b.y0),
                                c.to_screen(b.x1, b.y1),
                            );
                            let _ = window.paint_image(
                                c.bounds,
                                image_bounds,
                                Corners::default(),
                                image,
                                0,
                                false,
                            );
                        }
                        Some(nodes) => {
                            // Two layers, edges under nodes. Inside a layer every
                            // primitive takes the layer's draw order, so tens of
                            // thousands of dots skip GPUI's per-primitive overlap
                            // search (about 0.6 µs each, most of such a frame).
                            let edges = scene.edges_of(&nodes, EDGE_BUDGET);
                            if let Some(edges) = edges {
                                window.paint_layer(c.bounds, |window| {
                                    for batch in edges.chunks(SEGMENTS_PER_PATH) {
                                        let mut path = PathBuilder::stroke(px(1.));
                                        for &e in batch {
                                            let (a, b) = scene.edge(e);
                                            let (a, b) = (a as usize, b as usize);
                                            path.move_to(
                                                c.to_screen(scene.columns.x[a], scene.columns.y[a]),
                                            );
                                            path.line_to(
                                                c.to_screen(scene.columns.x[b], scene.columns.y[b]),
                                            );
                                        }
                                        if let Ok(path) = path.build() {
                                            window.paint_path(path, edge_color);
                                        }
                                    }
                                });
                            }
                            let ring = ui::theme::named("accent")
                                .map(|c| rgb(c).into())
                                .unwrap_or(edge_color);
                            let radius = |i: usize| {
                                scene
                                    .columns
                                    .size
                                    .get(i)
                                    .copied()
                                    .filter(|s| s.is_finite())
                                    .unwrap_or(node_size)
                            };
                            let dot = |window: &mut Window, i: usize, r: f32, color: Hsla| {
                                let at = c.to_screen(scene.columns.x[i], scene.columns.y[i]);
                                let bounds = Bounds::new(
                                    at - point(px(r), px(r)),
                                    size(px(r * 2.), px(r * 2.)),
                                );
                                window.paint_quad(fill(bounds, color).corner_radii(px(r)));
                            };
                            window.paint_layer(c.bounds, |window| {
                                for &i in &nodes {
                                    let i = i as usize;
                                    let g =
                                        scene.columns.group.get(i).copied().unwrap_or(0) as usize;
                                    dot(window, i, radius(i), colors[g.min(colors.len() - 1)]);
                                }
                                // Later in the layer, so on top of the nodes.
                                for &i in selected.iter().chain(c.hover.iter()) {
                                    let i = i as usize;
                                    if view.contains(scene.columns.x[i], scene.columns.y[i]) {
                                        let r = radius(i);
                                        dot(window, i, r + 2.5, ring);
                                        let g = scene.columns.group.get(i).copied().unwrap_or(0)
                                            as usize;
                                        dot(window, i, r, colors[g.min(colors.len() - 1)]);
                                    }
                                }
                            });
                            // Labels when few enough nodes are on screen to read
                            // them, and always the one under the pointer.
                            if !scene.columns.labels.is_empty() {
                                let ink: Hsla = rgb(ui::theme::color(ui::INK)).into();
                                let shown: Vec<u32> = if nodes.len() <= LABEL_BUDGET {
                                    nodes.clone()
                                } else {
                                    c.hover.into_iter().collect()
                                };
                                for i in shown {
                                    let i = i as usize;
                                    let text: SharedString = scene.columns.labels[i].clone().into();
                                    if text.is_empty() {
                                        continue;
                                    }
                                    let run = TextRun {
                                        len: text.len(),
                                        font: font(ui::system_font()),
                                        color: ink,
                                        background_color: None,
                                        underline: None,
                                        strikethrough: None,
                                    };
                                    let line = window.text_system().shape_line(
                                        text,
                                        px(ui::SMALL),
                                        &[run],
                                        None,
                                    );
                                    let at = c.to_screen(scene.columns.x[i], scene.columns.y[i])
                                        + point(px(radius(i) + 4.), px(-7.));
                                    let _ =
                                        line.paint(at, px(14.), TextAlign::Left, None, window, cx);
                                }
                            }
                        }
                    }
                });
                // While panning, follow the pointer anywhere in the window.
                if c.pan.is_some() {
                    let (moves, ends) = (camera.clone(), camera.clone());
                    let (redraw_move, redraw_end) = (redraw, redraw);
                    let (scene_end, send_end) = (scene.clone(), send.clone());
                    window.on_mouse_event(move |e: &MouseMoveEvent, phase, _, cx| {
                        if phase != DispatchPhase::Capture {
                            return;
                        }
                        moves.update(cx, |c, _| {
                            if let Some((start, ox, oy, _)) = c.pan {
                                let d = e.position - start;
                                let moved = f32::from(d.x).abs() + f32::from(d.y).abs() > 3.;
                                c.ox = ox - f32::from(d.x) / c.scale;
                                c.oy = oy - f32::from(d.y) / c.scale;
                                c.pan = Some((start, ox, oy, moved || c.pan.unwrap().3));
                            }
                        });
                        redraw_move(cx);
                    });
                    window.on_mouse_event(move |e: &MouseUpEvent, phase, _, cx| {
                        if phase != DispatchPhase::Capture || e.button != MouseButton::Left {
                            return;
                        }
                        let clicked = ends.update(cx, |c, _| c.pan.take().is_some_and(|p| !p.3));
                        // A click on empty space clears the selection.
                        if clicked && !scene_end.is_empty() {
                            send_end(on_select, Value::Null, true, cx);
                        }
                        redraw_end(cx);
                    });
                }
            }
        };

        let label = p["label"].as_str().unwrap_or("Scene").to_owned();
        let el = style(div(), node)
            .id(ElementId::Name(key.clone().into()))
            .relative()
            .overflow_hidden()
            .aria_label(label)
            .track_focus(&focus)
            .tab_index(0)
            .cursor(CursorStyle::Crosshair);
        let el = {
            let (camera, redraw) = (camera.clone(), redraw);
            el.on_scroll(move |e, _, cx| {
                let delta = e.delta.pixel_delta(px(20.));
                camera.update(cx, |c, _| {
                    if e.modifiers.platform || e.modifiers.control {
                        c.zoom((f32::from(delta.y) * 0.01).exp(), e.position);
                    } else {
                        c.ox -= f32::from(delta.x) / c.scale;
                        c.oy -= f32::from(delta.y) / c.scale;
                    }
                });
                redraw(cx);
            })
        };
        let el = {
            let (camera, redraw) = (camera.clone(), redraw);
            el.on_pinch(move |e, _, cx| {
                camera.update(cx, |c, _| c.zoom(1. + e.delta, e.position));
                redraw(cx);
            })
        };
        let el = {
            let (camera, scene, send, focus, redraw) = (
                camera.clone(),
                scene.clone(),
                send.clone(),
                focus.clone(),
                redraw,
            );
            el.on_mouse_down(MouseButton::Left, move |e, window, cx| {
                window.focus(&focus, cx);
                let hit = camera.update(cx, |c, _| {
                    let (x, y) = c.to_data(e.position);
                    // Only drawn nodes can be picked: in density view no
                    // single node is on screen to click.
                    let drawn = scene.draws_nodes(c.view(), NODE_BUDGET);
                    let hit = drawn.then(|| scene.hit(x, y, (node_size + 4.) / c.scale)).flatten();
                    if hit.is_none() {
                        c.pan = Some((e.position, c.ox, c.oy, false));
                    }
                    hit
                });
                if hit.is_none() {
                    redraw(cx);
                }
                if let Some(i) = hit {
                    send(
                        on_select,
                        json!({"index": i, "shift": e.modifiers.shift, "cmd": e.modifiers.platform}),
                        true,
                        cx,
                    );
                }
            })
        };
        // A release over the scene ends a pan at once (a quick click may
        // never repaint, so the window-level listener isn't registered yet);
        // the window listener covers releases outside it. Ending is
        // idempotent, so the two never both report.
        let el = {
            let (camera, send, redraw) = (camera.clone(), send.clone(), redraw);
            el.on_mouse_up(MouseButton::Left, move |_, _, cx| {
                let clicked = camera.update(cx, |c, _| c.pan.take().map(|p| !p.3));
                if clicked == Some(true) {
                    send(on_select, Value::Null, true, cx);
                }
                if clicked.is_some() {
                    redraw(cx);
                }
            })
        };
        let el = {
            let (camera, scene, send, redraw) =
                (camera.clone(), scene.clone(), send.clone(), redraw);
            let wants_hover = on_hover.is_some() || !scene.columns.labels.is_empty();
            el.on_mouse_move(move |e, _, cx| {
                if !wants_hover {
                    return;
                }
                let changed = camera.update(cx, |c, _| {
                    if c.pan.is_some() {
                        return None;
                    }
                    let (x, y) = c.to_data(e.position);
                    // Hovering individual nodes only: in density there is no node to name.
                    let visible = scene.draws_nodes(c.view(), NODE_BUDGET);
                    let hit = visible
                        .then(|| scene.hit(x, y, (node_size + 4.) / c.scale))
                        .flatten();
                    (hit != c.hover).then(|| {
                        c.hover = hit;
                        hit
                    })
                });
                if let Some(hit) = changed {
                    send(on_hover, json!(hit), false, cx);
                    redraw(cx);
                }
            })
        };
        let el = {
            let (camera, scene, redraw) = (camera.clone(), scene.clone(), redraw);
            el.on_key_down(move |e, _, cx| {
                let handled = camera.update(cx, |c, _| {
                    let center = c.bounds.center();
                    let (w, h) = (
                        f32::from(c.bounds.size.width),
                        f32::from(c.bounds.size.height),
                    );
                    match e.keystroke.key.as_str() {
                        "=" | "+" => c.zoom(1.25, center),
                        "-" => c.zoom(0.8, center),
                        "0" => c.fit(scene.bounds),
                        "left" => c.ox -= w * 0.1 / c.scale,
                        "right" => c.ox += w * 0.1 / c.scale,
                        "up" => c.oy -= h * 0.1 / c.scale,
                        "down" => c.oy += h * 0.1 / c.scale,
                        _ => return false,
                    }
                    true
                });
                if handled {
                    cx.stop_propagation();
                    redraw(cx);
                }
            })
        };
        el.child(canvas(prepaint, paint).absolute().inset_0())
            .into_any_element()
    }
}
