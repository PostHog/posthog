//! Pointer, keyboard and drag interaction for script containers.
//!
//! Everything that can run at pointer rate stays native: hover, press and
//! focus styling, the dragged element following the pointer, drop-target
//! highlighting. JavaScript runs on discrete events (press, drop, drag end)
//! and, when a script asks for continuous values (`onPointerMove`, `onDrag`,
//! `onScroll`), at most once per frame with the latest value.
use super::{Build, Instant, Node, Shared, color, handler, length};
use crate::sdk::ui;
use gpui_kit::*;
use serde_json::{Value, json};
use std::rc::Rc;

/// The value GPUI carries while a script element is dragged.
pub(super) struct ScriptDrag {
    scope: Rc<str>,
    kind: String,
}

/// GPUI draws a drag preview at the pointer; script drags move the element
/// itself instead, so the preview is empty.
struct NoPreview;
impl Render for NoPreview {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        div()
    }
}

#[derive(Clone, Copy, PartialEq)]
pub(super) enum Axis {
    Both,
    X,
    Y,
}

/// A drag in progress, owned by the view rather than by any element so it
/// survives re-renders and the source moving under the pointer.
pub(super) struct ActiveDrag {
    pub key: String,
    /// The element that follows the pointer: the source, or the one its
    /// `moves` names (a sheet moved by its grabber).
    pub moves: String,
    start: Point<Pixels>,
    pub current: Point<Pixels>,
    axis: Axis,
    /// Travel past these resists, like a rubber band (`min`, `max`).
    limits: (Option<f32>, Option<f32>),
    pub follow: bool,
    payload: Value,
    dropped: Option<String>,
}
impl ActiveDrag {
    /// The `onDrag` argument for the current position.
    pub fn live(&self) -> Value {
        let d = self.delta();
        json!({"dx": f32::from(d.x).round(), "dy": f32::from(d.y).round(), "payload": self.payload})
    }
    /// Pointer travel since the drag started, constrained to its axis and
    /// resisted past its limits.
    pub fn delta(&self) -> Point<Pixels> {
        let d = self.current - self.start;
        let r = |v: Pixels| px(resist(f32::from(v), self.limits));
        match self.axis {
            Axis::Both => point(r(d.x), r(d.y)),
            Axis::X => point(r(d.x), px(0.)),
            Axis::Y => point(px(0.), r(d.y)),
        }
    }
}

/// Travel past a limit gives way less and less, to at most 24 points.
fn resist(v: f32, (min, max): (Option<f32>, Option<f32>)) -> f32 {
    let band = |over: f32| 24. * (1. - (-over / 80.).exp());
    match (min, max) {
        (Some(min), _) if v < min => min - band(min - v),
        (_, Some(max)) if v > max => max + band(v - max),
        _ => v,
    }
}

/// Named cursors. Only these exist, so a script can't pick something that
/// means nothing on macOS.
pub(super) fn cursor(name: &str) -> Option<CursorStyle> {
    Some(match name {
        "default" => CursorStyle::Arrow,
        "pointer" => CursorStyle::PointingHand,
        "text" => CursorStyle::IBeam,
        "crosshair" => CursorStyle::Crosshair,
        "grab" => CursorStyle::OpenHand,
        "grabbing" => CursorStyle::ClosedHand,
        "col-resize" => CursorStyle::ResizeColumn,
        "row-resize" => CursorStyle::ResizeRow,
        "ew-resize" => CursorStyle::ResizeLeftRight,
        "ns-resize" => CursorStyle::ResizeUpDown,
        "not-allowed" => CursorStyle::OperationNotAllowed,
        "copy" => CursorStyle::DragCopy,
        _ => return None,
    })
}

/// A `hover`, `active`, `focus`, `groupHover` or `dropOver` block applied to a
/// style refinement. The vocabulary is deliberately small: state feedback is
/// colour, opacity and elevation, never layout.
pub(super) fn refine(mut s: StyleRefinement, block: &Value) -> StyleRefinement {
    if let Some(c) = color(&block["bg"]) {
        s = s.bg(c);
    }
    if let Some(c) = color(&block["color"]) {
        s = s.text_color(c);
    }
    if let Some(c) = color(&block["borderColor"]) {
        s = s.border_color(c);
    }
    if let Some(o) = block["opacity"].as_f64() {
        s = s.opacity(o.clamp(0., 1.) as f32);
    }
    match block["shadow"].as_str() {
        Some("sm") => s = s.shadow_sm(),
        Some("md") => s = s.shadow_md(),
        Some("lg") => s = s.shadow_lg(),
        Some("none") => s = s.shadow_none(),
        _ => {}
    }
    s
}

/// A visible keyboard focus ring that never changes layout.
fn focus_ring(s: StyleRefinement) -> StyleRefinement {
    let accent = ui::theme::named("accent").unwrap_or(0x0a66d8);
    s.shadow(vec![BoxShadow {
        color: rgba((accent << 8) | 0x99).into(),
        offset: point(px(0.), px(0.)),
        blur_radius: px(0.),
        spread_radius: px(2.),
        inset: false,
    }])
}

fn accepts(spec: &Value, kind: &str) -> bool {
    match spec {
        Value::String(s) => s == kind || s == "*",
        Value::Array(list) => list.iter().any(|k| k == kind || k == "*"),
        _ => true,
    }
}

/// Does this element need an identity and interactive wiring?
pub(super) fn interactive(p: &Value) -> bool {
    const KEYS: [&str; 14] = [
        "onClick",
        "onDoubleClick",
        "onPress",
        "onRelease",
        "onHover",
        "onPointerMove",
        "onLayout",
        "onNudge",
        "drag",
        "drop",
        "tooltip",
        "hover",
        "active",
        "groupHover",
    ];
    // A layer always takes the interactive path: it must block clicks to
    // what's beneath it even when it handles none itself.
    KEYS.iter().any(|k| p.get(*k).is_some())
        || p["overflow"] == "scroll-x"
        || p["layer"].as_u64().is_some()
}

/// Handlers that run after the event that caused them (next frame, after
/// layout, mid-drag). They're looked up by element and name when they run,
/// because every script render issues new handler IDs.
pub(super) const LATE: [&str; 10] = [
    "onDragStart",
    "onDrag",
    "onDragEnd",
    "onLayout",
    "onPointerMove",
    "onScroll",
    // Native components that report from their own event subscriptions.
    "onChange",
    "onCommit",
    "onClose",
    "onEdit",
];

impl Shared {
    /// How far an element a drag let go of still sits from its place. It
    /// settles back on View's curve; while it leaves (`show: false`) it keeps
    /// the offset, so its exit carries on from where it was let go.
    pub(super) fn settling(
        &self,
        node: &Node,
        window: &mut Window,
        cx: &App,
    ) -> Option<(f32, f32)> {
        const SETTLE: f32 = 0.28;
        let mut settle = self.settle.borrow_mut();
        let (delta, at) = *settle.get(&*node.key)?;
        let k = if node.p["show"] == false {
            1.
        } else {
            let t = at.elapsed().as_secs_f32() / SETTLE;
            if t >= 1. || cx.reduce_motion() {
                settle.remove(&*node.key);
                return None;
            }
            1. - ui::motion::ease_out().sample(t)
        };
        window.request_animation_frame();
        Some((f32::from(delta.x) * k, f32::from(delta.y) * k))
    }
    /// The element's current handler for a late event.
    pub(super) fn late(&self, key: &str, event: &'static str) -> Option<u32> {
        self.late.borrow().get(&(key.to_owned(), event)).copied()
    }
    /// Runs the element's `event` handler with the latest `argument` once,
    /// before the next frame. Pointer-rate events call this; a burst of moves
    /// costs one JS call. `argument` is read at frame time, so values that
    /// settle during event dispatch (a scroll offset) are current.
    pub(super) fn coalesce(
        self: &Rc<Self>,
        weak: WeakEntity<super::ScriptView>,
        key: &str,
        event: &'static str,
        argument: Rc<dyn Fn() -> Value>,
        window: &mut Window,
    ) {
        self.coalesced
            .borrow_mut()
            .insert((key.to_owned(), event), argument);
        if self.frame_scheduled.replace(true) {
            return;
        }
        let shared = self.clone();
        window.on_next_frame(move |_, cx| {
            shared.frame_scheduled.set(false);
            let pending: Vec<_> = shared.coalesced.borrow_mut().drain().collect();
            let _ = weak.update(cx, |view, cx| {
                for ((key, event), argument) in pending {
                    if let Some(h) = shared.late(&key, event) {
                        view.invoke(h, argument(), false, cx);
                    }
                }
            });
        });
    }
    /// Pointer position relative to the element, from its last painted bounds.
    fn local(&self, key: &str, position: Point<Pixels>) -> Value {
        let origin = self
            .bounds
            .borrow()
            .get(key)
            .map(|b| b.origin)
            .unwrap_or_default();
        let at = position - origin;
        json!({"x": f32::from(at.x).round(), "y": f32::from(at.y).round()})
    }
    /// Ends the drag: the `onDragEnd` call to make, if the script wants one.
    pub(super) fn end_drag(&self, cancelled: bool) -> Option<(u32, Value)> {
        let drag = self.drag.borrow_mut().take()?;
        let delta = drag.delta();
        if drag.follow {
            self.settle
                .borrow_mut()
                .insert(drag.moves.clone(), (delta, Instant::now()));
        }
        self.late(&drag.key, "onDragEnd").map(|h| {
            (
                h,
                json!({
                    "dx": f32::from(delta.x).round(),
                    "dy": f32::from(delta.y).round(),
                    "dropped": drag.dropped.is_some(),
                    "target": drag.dropped,
                    "cancelled": cancelled,
                    "payload": drag.payload,
                }),
            )
        })
    }
    /// Finishes the drag from outside the view, after the release has been
    /// dispatched, so a drop target that accepted it is already recorded.
    pub(super) fn finish_drag(&self, weak: &WeakEntity<super::ScriptView>, cx: &mut App) {
        let was_dragging = self.drag.borrow().is_some();
        let end = self.end_drag(false);
        if !was_dragging {
            return;
        }
        let _ = weak.update(cx, |view, cx| {
            if let Some((h, argument)) = end {
                view.invoke(h, argument, true, cx);
            }
            cx.notify();
        });
    }
}

impl Build {
    fn send_value(&self, handler: u32, gesture: bool) -> impl Fn(Value, &mut App) + 'static {
        let weak = self.weak.clone();
        move |argument, cx| {
            let _ = weak.update(cx, |view, cx| view.invoke(handler, argument, gesture, cx));
        }
    }

    /// Wires everything interactive on a container. Plain containers never
    /// reach here, so they stay plain `Div`s with no hitbox cost.
    pub(super) fn interact(
        &self,
        el: Div,
        node: &Node,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let p = &node.p;
        let key = node.key.to_string();
        let scope = self.scope.clone();
        self.register_late(&key, p);
        let mut el = el.id(ElementId::Name(key.clone().into()));
        let measured = ["onPress", "onRelease", "onPointerMove", "onLayout"]
            .iter()
            .any(|k| p.get(*k).is_some());

        // The accessible name the design check requires of controls.
        if let Some(label) = p["label"].as_str().filter(|l| !l.trim().is_empty()) {
            el = el.aria_label(label.to_owned());
        }
        if ["onClick", "onPress", "onDoubleClick"]
            .iter()
            .any(|k| p.get(*k).is_some())
        {
            el = el.role(Role::Button);
        }

        // State styling, all native.
        if p.get("hover").is_some() || color(&p["hoverBg"]).is_some() {
            let block = p["hover"].clone();
            let legacy = color(&p["hoverBg"]);
            el = el.hover(move |s| {
                let s = legacy.map_or(s.clone(), |c| s.bg(c));
                refine(s, &block)
            });
        }
        if let Some(block) = p.get("active").cloned() {
            el = el.active(move |s| refine(s, &block));
        }
        if let Some(name) = p["group"].as_str() {
            el = el.group(format!("{scope}:{name}"));
        }
        if let Some(block) = p.get("groupHover").cloned()
            && let Some(name) = block["group"].as_str()
        {
            el = el.group_hover(format!("{scope}:{name}"), move |s| refine(s, &block));
        }
        if let Some(text) = p["tooltip"].as_str().filter(|t| !t.is_empty()) {
            let text: SharedString = text.to_owned().into();
            el = el.tooltip(move |window, cx| {
                gpui_kit::component::tooltip::Tooltip::new(text.clone()).build(window, cx)
            });
        }
        if p["overflow"] == "scroll-x" {
            el = el.overflow_x_scroll();
        }

        // Clicks: single and double share one listener so a double click
        // never also counts as two singles to the script.
        let click = handler(p, "onClick");
        let double = handler(p, "onDoubleClick");
        if click.is_some() || double.is_some() {
            let (click, double) = (
                click.map(|h| self.send_value(h, true)),
                double.map(|h| self.send_value(h, true)),
            );
            el = el.cursor_pointer().on_click(move |event, _, cx| {
                match (&double, event.click_count()) {
                    (Some(send), n) if n >= 2 => send(Value::Null, cx),
                    _ => {
                        if let Some(send) = &click {
                            send(Value::Null, cx)
                        }
                    }
                }
            });
        }
        if let Some(h) = handler(p, "onPress") {
            let (send, shared, key) = (self.send_value(h, true), self.shared.clone(), key.clone());
            el = el.on_mouse_down(MouseButton::Left, move |e, _, cx| {
                let mut at = shared.local(&key, e.position);
                at["shift"] = json!(e.modifiers.shift);
                at["alt"] = json!(e.modifiers.alt);
                at["cmd"] = json!(e.modifiers.platform);
                send(at, cx);
            });
        }
        if let Some(h) = handler(p, "onRelease") {
            let (send, shared, key) = (self.send_value(h, true), self.shared.clone(), key.clone());
            el = el.on_mouse_up(MouseButton::Left, move |e, _, cx| {
                send(shared.local(&key, e.position), cx)
            });
        }
        if let Some(h) = handler(p, "onHover") {
            // Hovering is not a decision: no clipboard or URL from it.
            let send = self.send_value(h, false);
            el = el.on_hover(move |hovered, _, cx| send(json!(*hovered), cx));
        }
        if p.get("onPointerMove").is_some() {
            let (shared, weak, key) = (self.shared.clone(), self.weak.clone(), key.clone());
            el = el.on_mouse_move(move |e, window, _| {
                let at = shared.local(&key, e.position);
                shared.coalesce(
                    weak.clone(),
                    &key,
                    "onPointerMove",
                    Rc::new(move || at.clone()),
                    window,
                );
            });
        }

        // Keyboard: a focusable element answers arrow keys, so anything that
        // can be dragged can also be moved without a pointer. Draggable
        // elements are always focusable, and take focus when pressed, so
        // Escape reaches the view mid-drag and arrows work right after.
        let nudge = handler(p, "onNudge");
        let draggable = p.get("drag").is_some_and(|d| d.is_object() || *d == true);
        let focus = (nudge.is_some() || draggable).then(|| {
            window
                .use_keyed_state(
                    ElementId::Name(format!("{scope}:{key}:focus").into()),
                    cx,
                    |_, cx| cx.focus_handle(),
                )
                .read(cx)
                .clone()
        });
        if let Some(focus) = &focus {
            el = el.track_focus(focus).tab_index(0).focus_visible(focus_ring);
        }
        if let Some(h) = nudge {
            let send = self.send_value(h, true);
            el = el.on_key_down(move |e, _, cx| {
                let dir = match e.keystroke.key.as_str() {
                    "up" => "up",
                    "down" => "down",
                    "left" => "left",
                    "right" => "right",
                    _ => return,
                };
                cx.stop_propagation();
                send(json!({"dir": dir, "big": e.keystroke.modifiers.shift}), cx);
            });
        }

        // Drag source. GPUI applies its own movement threshold before the
        // drag starts, so a click on a draggable element is still a click.
        if let Some(spec) = p.get("drag").filter(|_| draggable) {
            let kind = spec["type"].as_str().unwrap_or("item").to_owned();
            let axis = match spec["axis"].as_str() {
                Some("x") => Axis::X,
                Some("y") => Axis::Y,
                _ => Axis::Both,
            };
            let follow = spec["follow"] != false;
            let moves = spec["moves"].as_str().unwrap_or(&key).to_owned();
            let limits = (
                spec["min"].as_f64().map(|v| v as f32),
                spec["max"].as_f64().map(|v| v as f32),
            );
            let payload = spec.get("payload").cloned().unwrap_or(Value::Null);
            let (shared, weak, drag_key) = (self.shared.clone(), self.weak.clone(), key.clone());
            let value = ScriptDrag {
                scope: scope.clone(),
                kind,
            };
            if p.get("cursor").is_none() {
                el = el.cursor(if follow {
                    CursorStyle::OpenHand
                } else {
                    cursor_for(axis)
                });
            }
            // GPUI starts the drag past its threshold; travel is measured
            // from where the button went down, so the element stays under
            // the pointer exactly.
            let (pressed, focused) = (self.shared.clone(), focus.clone());
            el = el.on_mouse_down(MouseButton::Left, move |e, window, cx| {
                pressed.pressed.set(Some(e.position));
                if let Some(focus) = &focused {
                    window.focus(focus, cx);
                }
            });
            el = el.on_drag(value, move |_, _, window, cx| {
                let at = shared
                    .pressed
                    .take()
                    .unwrap_or_else(|| window.mouse_position());
                shared.drag.replace(Some(ActiveDrag {
                    key: drag_key.clone(),
                    moves: moves.clone(),
                    start: at,
                    current: window.mouse_position(),
                    axis,
                    limits,
                    follow,
                    payload: payload.clone(),
                    dropped: None,
                }));
                let (argument, weak, starts, key) = (
                    payload.clone(),
                    weak.clone(),
                    shared.clone(),
                    drag_key.clone(),
                );
                cx.defer(move |cx| {
                    if let Some(h) = starts.late(&key, "onDragStart") {
                        let _ = weak.update(cx, |view, cx| view.invoke(h, argument, false, cx));
                    }
                });
                cx.new(|_| NoPreview)
            });
        }

        // Drop target: highlighted natively while an accepted drag is over it.
        if let Some(spec) = p.get("drop") {
            let accept = spec.get("accepts").cloned().unwrap_or(Value::Null);
            let over = p.get("dropOver").cloned();
            let check_scope = scope.clone();
            el = el
                .can_drop(move |value, _, _| {
                    value
                        .downcast_ref::<ScriptDrag>()
                        .is_some_and(|d| d.scope == check_scope && accepts(&accept, &d.kind))
                })
                .drag_over::<ScriptDrag>(move |s, _, _, _| match &over {
                    Some(block) => refine(s, block),
                    None => s.bg(rgb(ui::theme::color(ui::SELECTED))),
                });
            let (on_drop, shared, target) =
                (handler(p, "onDrop"), self.shared.clone(), key.clone());
            let send = on_drop.map(|h| self.send_value(h, true));
            el = el.on_drop::<ScriptDrag>(move |_, _, cx| {
                let payload = shared.drag.borrow_mut().as_mut().map(|d| {
                    d.dropped = Some(target.clone());
                    (d.payload.clone(), d.key.clone())
                });
                if let (Some(send), Some((payload, from))) = (&send, payload) {
                    send(json!({"payload": payload, "from": from}), cx);
                }
            });
        }

        // The element follows the pointer while it is the one being dragged.
        let dragging = self
            .shared
            .drag
            .borrow()
            .as_ref()
            .filter(|d| d.moves == key && d.follow)
            .map(|d| d.delta());
        if let Some(delta) = dragging {
            el = crate::script_motion::offset(el, p, f32::from(delta.x), f32::from(delta.y))
                .shadow_lg()
                .cursor(CursorStyle::ClosedHand);
        }

        if measured {
            el = el.child(self.measure(&key, p.get("onLayout").is_some()));
        }
        if p["layer"].as_u64().is_some() {
            el = el.occlude();
        }
        let element = el.into_any_element();
        if dragging.is_some() {
            // Paint above its siblings while it travels over them.
            deferred(element).with_priority(4).into_any_element()
        } else {
            element
        }
    }

    /// A zero-cost child that records the element's painted bounds, for
    /// element-relative pointer positions and `onLayout`.
    fn measure(&self, key: &str, on_layout: bool) -> impl IntoElement {
        let (shared, weak, key) = (self.shared.clone(), self.weak.clone(), key.to_owned());
        canvas(
            move |bounds, _, cx| {
                let previous = shared.bounds.borrow_mut().insert(key.clone(), bounds);
                if !on_layout {
                    return;
                }
                let rounded = |b: Bounds<Pixels>| {
                    (
                        f32::from(b.size.width).round(),
                        f32::from(b.size.height).round(),
                    )
                };
                if previous.map(rounded) == Some(rounded(bounds)) {
                    return;
                }
                // A view that resizes itself in answer to its own size could
                // loop; after 20 changes in a second further reports wait.
                if !shared.layout_budget(&key) {
                    return;
                }
                let (w, h) = rounded(bounds);
                let (weak, shared, key) = (weak.clone(), shared.clone(), key.clone());
                cx.defer(move |cx| {
                    if let Some(handler) = shared.late(&key, "onLayout") {
                        let _ = weak.update(cx, |view, cx| {
                            // Fires on first paint with no user action.
                            view.invoke(handler, json!({"width": w, "height": h}), false, cx)
                        });
                    }
                });
            },
            |_, _, _, _| {},
        )
        .absolute()
        .inset_0()
    }

    /// `onScroll` for a `Scroll` container: offset and range once per frame.
    pub(super) fn scroll_events(&self, el: Stateful<Div>, node: &Node) -> Stateful<Div> {
        let p = &node.p;
        if p.get("onScroll").is_none() && p.get("scrollTo").is_none() {
            return el;
        }
        let key = node.key.to_string();
        self.register_late(&key, p);
        let handle = self
            .shared
            .scroll_handles
            .borrow_mut()
            .entry(key.clone())
            .or_default()
            .clone();
        if let Some(target) = p.get("scrollTo") {
            let stamp = json!([target, p["scrollRevision"]]);
            let changed = self.shared.scroll_targets.borrow().get(&key) != Some(&stamp);
            if changed {
                self.shared
                    .scroll_targets
                    .borrow_mut()
                    .insert(key.clone(), stamp);
                if target == "end" {
                    handle.scroll_to_bottom();
                } else if let Some(y) = target.as_f64() {
                    handle.set_offset(point(px(0.), px(-(y.max(0.) as f32))));
                }
            }
        }
        let (shared, weak) = (self.shared.clone(), self.weak.clone());
        let reader = handle.clone();
        el.track_scroll(&handle).on_scroll(move |_, window, _| {
            let reader = reader.clone();
            let argument = Rc::new(move || {
                let (offset, max) = (reader.offset(), reader.max_offset());
                json!({
                    "y": (-f32::from(offset.y)).round(),
                    "max": f32::from(max.y).round(),
                })
            });
            shared.coalesce(weak.clone(), &key, "onScroll", argument, window);
        })
    }

    /// Records this render's handler IDs for events that run later.
    pub(super) fn register_late(&self, key: &str, p: &Value) {
        let mut late = self.shared.late.borrow_mut();
        for event in LATE {
            match handler(p, event) {
                Some(h) => late.insert((key.to_owned(), event), h),
                None => late.remove(&(key.to_owned(), event)),
            };
        }
    }
}

fn cursor_for(axis: Axis) -> CursorStyle {
    match axis {
        Axis::X => CursorStyle::ResizeColumn,
        Axis::Y => CursorStyle::ResizeRow,
        Axis::Both => CursorStyle::OpenHand,
    }
}

/// Layout props for any styled element: positioning, grid, aspect, elevation
/// and cursor.
pub(super) fn layout<E: Styled>(mut e: E, p: &Value) -> E {
    if p["position"] == "absolute" {
        e = e.absolute();
    }
    if let Some(n) = p["inset"].as_f64() {
        let v = px(n as f32);
        e = e.top(v).right(v).bottom(v).left(v);
    }
    for (key, apply) in [
        ("top", Styled::top as fn(E, Length) -> E),
        ("right", Styled::right),
        ("bottom", Styled::bottom),
        ("left", Styled::left),
    ] {
        if let Some(v) = length(&p[key]) {
            e = apply(e, v);
        }
    }
    let cols = match &p["grid"] {
        Value::Number(n) => n.as_u64(),
        Value::Object(o) => o.get("cols").and_then(Value::as_u64),
        _ => None,
    };
    if let Some(cols) = cols {
        e = e.grid().grid_cols(cols.clamp(1, 24) as u16);
        if let Some(rows) = p["grid"]["rows"].as_u64() {
            e = e.grid_rows(rows.clamp(1, 64) as u16);
        }
    }
    if let Some(span) = p["span"].as_u64() {
        e = e.col_span(span.clamp(1, 24) as u16);
    }
    if let Some(span) = p["rowSpan"].as_u64() {
        e = e.row_span(span.clamp(1, 64) as u16);
    }
    if let Some(ratio) = p["aspect"].as_f64().filter(|r| *r > 0.) {
        e = e.aspect_ratio(ratio as f32);
    }
    match p["shadow"].as_str() {
        Some("sm") => e = e.shadow_sm(),
        Some("md") => e = e.shadow_md(),
        Some("lg") => e = e.shadow_lg(),
        _ => {}
    }
    if let Some(c) = p["cursor"].as_str().and_then(cursor) {
        e = e.cursor(c);
    }
    e
}
