use std::rc::Rc;

use gpui::{
    App, Bounds, Hitbox, HitboxBehavior, IntoElement, MouseButton, MouseDownEvent, MouseMoveEvent,
    MouseUpEvent, Pixels, Point, RenderOnce, Styled as _, TouchDragEvent, TouchPhase, Window,
    canvas, deferred,
};
use gpui_base::{SelectionEdge, TouchHandle, TouchSelectionSnapshot};

use crate::ActiveTheme as _;

/// Reads the touch selection as laid out by the time the handles paint.
pub(crate) type SnapshotSource = Rc<dyn Fn(&Window, &App) -> Option<TouchSelectionSnapshot>>;
/// What a handle's owner gets told as the finger moves it.
pub(crate) type DragHandler =
    Rc<dyn Fn(SelectionEdge, TouchPhase, Point<Pixels>, &mut Window, &mut App)>;
/// Where a surface was painted this frame, for owners that must protect it.
pub(crate) type SurfaceHandler = Rc<dyn Fn(Bounds<Pixels>, &mut Window, &mut App)>;

/// The grab handles at the ends of an input's touch selection, floating
/// above the input: its knobs reach past the field's edge, where the input's
/// own clip would cut them off. (Text that takes part in the window selection
/// paints its handles itself, in place; see
/// [`gpui_base::TextSelectionHandle::paint_touch_handles`].)
///
/// The handles read the selection's geometry as they paint, after the input
/// has painted this frame, so they sit on the text as it is now rather than
/// as it was a frame ago while it scrolls.
///
/// A handle claims the touch drag that begins on it before the window can
/// take the drag for panning, and blocks the mouse so a stray tap on it does
/// not reach the text underneath. A mouse can drag it too, which is how it is
/// exercised without a touch screen.
#[derive(IntoElement)]
pub(crate) struct SelectionHandles {
    source: SnapshotSource,
    on_drag: DragHandler,
    on_paint: Option<SurfaceHandler>,
}

/// One handle laid out for this frame.
struct LaidOutHandle {
    edge: SelectionEdge,
    caret: Bounds<Pixels>,
    hitbox: Hitbox,
}

impl SelectionHandles {
    pub(crate) fn new(source: SnapshotSource, on_drag: DragHandler) -> Self {
        Self {
            source,
            on_drag,
            on_paint: None,
        }
    }

    pub(crate) fn on_paint(mut self, on_paint: SurfaceHandler) -> Self {
        self.on_paint = Some(on_paint);
        self
    }

    /// Lays out a handle for each end of a non-empty selection that is in
    /// view.
    fn layout(source: &SnapshotSource, window: &mut Window, cx: &mut App) -> Vec<LaidOutHandle> {
        let Some(snapshot) = source(window, cx) else {
            return Vec::new();
        };
        let window_bounds = Bounds::new(Point::default(), window.viewport_size());
        let mut handles = Vec::with_capacity(2);
        if !snapshot.is_empty() {
            for edge in [SelectionEdge::Start, SelectionEdge::End] {
                // No handle for an end scrolled out of its owner, nor for one
                // outside the window.
                let caret = snapshot.edge(edge);
                if !snapshot.is_edge_visible(edge) || !window_bounds.contains(&caret.origin) {
                    continue;
                }
                let hitbox = window.insert_hitbox(
                    TouchHandle::hit_bounds(edge, caret),
                    HitboxBehavior::BlockMouse,
                );
                handles.push(LaidOutHandle {
                    edge,
                    caret,
                    hitbox,
                });
            }
        }
        handles
    }

    fn paint_handle(handle: &LaidOutHandle, window: &mut Window, cx: &mut App) {
        TouchHandle::paint(
            handle.edge,
            handle.caret,
            cx.theme().selection.alpha(1.),
            window,
        );
    }

    /// The drag begins on whichever handle is under the finger or pointer;
    /// its moves and its end are routed by which end is being dragged, so
    /// they keep coming even if that handle is not laid out for a frame.
    fn listen(
        handles: &[LaidOutHandle],
        source: &SnapshotSource,
        on_drag: &DragHandler,
        window: &mut Window,
    ) {
        for handle in handles {
            // Touch: the drag is offered on the first touch, before it can
            // become a tap, a long press or a pan.
            window.on_mouse_event({
                let hitbox = handle.hitbox.clone();
                let edge = handle.edge;
                let on_drag = on_drag.clone();
                move |event: &TouchDragEvent, phase, window, cx| {
                    if !phase.bubble()
                        || event.phase != TouchPhase::Started
                        || window.default_prevented()
                        || !hitbox.is_hovered(window)
                    {
                        return;
                    }
                    window.prevent_default();
                    cx.stop_propagation();
                    on_drag(edge, TouchPhase::Started, event.position, window, cx);
                }
            });
            // Mouse: the same drag for a pointer.
            window.on_mouse_event({
                let hitbox = handle.hitbox.clone();
                let edge = handle.edge;
                let on_drag = on_drag.clone();
                move |event: &MouseDownEvent, phase, window, cx| {
                    if !phase.bubble()
                        || event.button != MouseButton::Left
                        || !hitbox.is_hovered(window)
                    {
                        return;
                    }
                    cx.stop_propagation();
                    on_drag(edge, TouchPhase::Started, event.position, window, cx);
                }
            });
        }

        // The drag in progress is read live: it may have begun after this
        // frame painted, and its first moves must not be lost.
        let dragging = {
            let source = source.clone();
            move |window: &Window, cx: &App| source(window, cx).and_then(|s| s.dragging())
        };
        window.on_mouse_event({
            let on_drag = on_drag.clone();
            let dragging = dragging.clone();
            move |event: &TouchDragEvent, phase, window, cx| {
                if !phase.bubble() || event.phase == TouchPhase::Started {
                    return;
                }
                let Some(edge) = dragging(window, cx) else {
                    return;
                };
                cx.stop_propagation();
                on_drag(edge, event.phase, event.position, window, cx);
            }
        });
        window.on_mouse_event({
            let on_drag = on_drag.clone();
            let dragging = dragging.clone();
            move |event: &MouseMoveEvent, phase, window, cx| {
                if !phase.bubble() || event.pressed_button != Some(MouseButton::Left) {
                    return;
                }
                let Some(edge) = dragging(window, cx) else {
                    return;
                };
                on_drag(edge, TouchPhase::Moved, event.position, window, cx);
            }
        });
        window.on_mouse_event({
            let on_drag = on_drag.clone();
            move |event: &MouseUpEvent, phase, window, cx| {
                if !phase.bubble() || event.button != MouseButton::Left {
                    return;
                }
                let Some(edge) = dragging(window, cx) else {
                    return;
                };
                on_drag(edge, TouchPhase::Ended, event.position, window, cx);
            }
        });
    }
}

impl RenderOnce for SelectionHandles {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let source = self.source;
        let on_drag = self.on_drag;
        let on_paint = self.on_paint;
        deferred(
            canvas(
                {
                    let source = source.clone();
                    move |_, window, cx| Self::layout(&source, window, cx)
                },
                move |_, handles, window, cx| {
                    for handle in &handles {
                        Self::paint_handle(handle, window, cx);
                        if let Some(on_paint) = on_paint.as_ref() {
                            on_paint(handle.hitbox.bounds, window, cx);
                        }
                    }
                    Self::listen(&handles, &source, &on_drag, window);
                },
            )
            .absolute()
            .size_0(),
        )
        .with_priority(gpui_base::POPUP_PRIORITY)
    }
}
