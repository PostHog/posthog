//! Reading text that joins the window's text selection: a drag selects it
//! and Cmd-C copies it as written, including the part a `truncate` hides.
//!
//! Text is selectable unless it is, or sits inside, a control: something a
//! press or a drag already means something on. There a drag moves the item
//! or a click acts, and a highlight on a label would only get in the way.
use super::*;
use gpui_kit::base::{
    TextSelectionEvent, TextSelectionHandle, TextSelectionRegistration, TextSelectionRun,
};
use std::borrow::Cow;
use std::cell::{Cell, RefCell};
use std::ops::Range;

/// Handlers that make an element a control: a press or a drag on it acts.
const CONTROL: [&str; 5] = ["onClick", "onDoubleClick", "onPress", "onRelease", "drag"];

/// Whether an element with these props is a control.
fn is_control(p: &Value) -> bool {
    CONTROL
        .iter()
        .any(|k| p.get(*k).is_some_and(|v| !v.is_null()))
}

/// The truncation mark gpui lays out in place of the hidden text.
const ELLIPSIS: &str = "…";

impl Build {
    /// Whether this reading text is selectable: as its `selectable` prop
    /// says, else unless it is, or sits inside, a control.
    pub(super) fn selects(&self, p: &Value) -> bool {
        p["selectable"]
            .as_bool()
            .unwrap_or(!self.control && !is_control(p))
    }
    /// The build for the children of an element with props `p`: inside a
    /// control once `p` is one.
    pub(super) fn within(&self, p: &Value) -> Cow<'_, Build> {
        if self.control || !is_control(p) {
            Cow::Borrowed(self)
        } else {
            Cow::Owned(self.in_control())
        }
    }
    /// This build, for content that is a control's (a popover trigger, a
    /// table's cells).
    pub(super) fn in_control(&self) -> Build {
        Build {
            control: true,
            ..self.clone()
        }
    }

    /// Selectable reading text: `node`'s text in the type of `base`, read
    /// by accessibility as `role`.
    ///
    /// Its selection handle lives in keyed state, so it goes when the text
    /// leaves the tree. While a drag moves, nothing else redraws the view
    /// holding the text (the script view, or a cached region), so the handle
    /// notifies that view itself; otherwise the highlight would only appear
    /// once the pointer is released.
    #[inline(never)]
    pub(super) fn selectable_text(
        &self,
        node: &Rc<Node>,
        base: Div,
        role: Role,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        struct Selection {
            handle: TextSelectionHandle,
            /// The view building the text now; it can move into a region.
            owner: Rc<Cell<EntityId>>,
            /// What Cmd-C takes from this text, set as it paints.
            copy: Rc<RefCell<String>>,
            _redraw: Subscription,
        }
        let body: SharedString = text(&node.p, "text").into();
        let owner = window.current_view();
        let state = window.use_keyed_state(
            ElementId::Name(format!("{}:{}:selection", self.scope, node.key).into()),
            cx,
            {
                let body = body.clone();
                move |_, cx| {
                    let handle = TextSelectionHandle::new(body, cx);
                    let copy = Rc::new(RefCell::new(String::new()));
                    handle.copy_with(
                        {
                            let copy = copy.clone();
                            move |_| copy.borrow().clone()
                        },
                        cx,
                    );
                    let shared = Rc::new(Cell::new(owner));
                    let redraw = handle.subscribe(
                        {
                            let owner = shared.clone();
                            move |event, cx| {
                                if matches!(event, TextSelectionEvent::SelectionChanged(_)) {
                                    cx.notify(owner.get());
                                }
                            }
                        },
                        cx,
                    );
                    Selection {
                        handle,
                        owner: shared,
                        copy,
                        _redraw: redraw,
                    }
                }
            },
        );
        let state = state.read(cx);
        state.owner.set(owner);
        let run = SelectableRun {
            handle: state.handle.clone(),
            copy: state.copy.clone(),
            styled: StyledText::new(body.clone()),
            text: body.clone(),
            order: reading_order(&node.path),
        };
        // The run reports nothing to accessibility; it reads as the plain
        // element would.
        let labelled = div()
            .id(ElementId::Name(format!("{}:text", node.key).into()))
            .role(role)
            .aria_label(body)
            .child(run);
        self.container(base.child(labelled), node, window, cx)
    }
}

/// A styled text run in the window's text selection. Unlike the kit's
/// `SelectableText`, a truncated run still selects: the run it reports is
/// the text as laid out, ellipsis included, and copying maps what is
/// selected back onto the full text.
struct SelectableRun {
    handle: TextSelectionHandle,
    copy: Rc<RefCell<String>>,
    /// Where it comes in a copy that spans several runs.
    order: u64,
    text: SharedString,
    styled: StyledText,
}

impl IntoElement for SelectableRun {
    type Element = Self;
    fn into_element(self) -> Self {
        self
    }
}

impl Element for SelectableRun {
    type RequestLayoutState = ();
    type PrepaintState = ();

    fn id(&self) -> Option<ElementId> {
        None
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, ()) {
        self.styled.request_layout(id, inspector_id, window, cx)
    }

    fn prepaint(
        &mut self,
        id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) {
        self.styled
            .prepaint(id, inspector_id, bounds, &mut (), window, cx);
        let hitbox = window.insert_hitbox(bounds, HitboxBehavior::Normal);
        let registration = TextSelectionRegistration::new(hitbox, bounds)
            .with_document_order(self.order)
            .with_text_bounds(vec![bounds])
            .with_rendered_element(&self.handle, window, cx);
        self.handle.register(registration, window, cx);
    }

    fn paint(
        &mut self,
        id: Option<&GlobalElementId>,
        inspector_id: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut (),
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) {
        let layout = self.styled.layout().clone();
        // Selection only projects onto a run whose text is exactly what was
        // laid out, so a truncated run reports its shown text.
        let shown: SharedString = match layout.text() {
            laid if laid == *self.text => self.text.clone(),
            laid => laid.into(),
        };
        let projection = self.handle.update_runs(
            &[TextSelectionRun::new(shown.clone(), layout.clone(), bounds)],
            cx,
        );
        let range = projection.ranges().first().cloned().flatten();
        let copy = range
            .clone()
            .map(|range| copy_text(&self.text, &shown, range))
            .unwrap_or_default();
        if *self.copy.borrow() != copy {
            *self.copy.borrow_mut() = copy;
            // As the kit's run does: what a copy takes changed.
            window.refresh();
        }
        if let Some(range) = range {
            let color = gpui_kit::base::Theme::global(cx).tokens.colors.selection;
            paint_selection(&layout, range, color, window);
        }
        self.styled
            .paint(id, inspector_id, bounds, &mut (), &mut (), window, cx);
    }
}

/// A run's place in a copy that spans several: its element's position in
/// the tree (`r.0.2.15`), as a number that sorts the way the positions do.
///
/// Each index is written as its bit length in unary (ones, then a zero) and
/// its bits below the leading one. Shorter numbers then sort first, and an
/// element sorts before everything after it in the tree. A path too deep to
/// fit shares its number with its neighbours, which only ties their order.
/// Segments that are not indices (a hover card's `content`) count as 0.
fn reading_order(path: &str) -> u64 {
    let mut order: u128 = 0;
    let mut used = 0u32;
    for segment in path.split('.').skip(1) {
        // From 2, so every code starts with a one: a child then sorts
        // after its parent rather than level with it.
        let n = segment.parse::<u64>().unwrap_or(0) as u128 + 2;
        let bits = 128 - n.leading_zeros();
        // `bits - 1` ones, a zero, then the bits under the leading one.
        let ones = (1u128 << (bits - 1)) - 1;
        let low = n & ((1u128 << (bits - 1)) - 1);
        let code = (ones << bits) | low;
        let width = 2 * bits - 1;
        if used + width > 64 {
            break;
        }
        order = (order << width) | code;
        used += width;
    }
    (order << (64 - used)) as u64
}

/// What selecting `range` of the laid-out `shown` text copies from `full`:
/// the same characters, and the hidden text too once the ellipsis that
/// stands for it is selected.
fn copy_text(full: &str, shown: &str, range: Range<usize>) -> String {
    if shown == full {
        return full[range].to_owned();
    }
    if let Some(kept) = shown
        .strip_suffix(ELLIPSIS)
        .filter(|kept| full.starts_with(kept))
    {
        let end = if range.end > kept.len() {
            full.len()
        } else {
            range.end
        };
        return full[range.start.min(kept.len())..end].to_owned();
    }
    if let Some(kept) = shown
        .strip_prefix(ELLIPSIS)
        .filter(|kept| full.ends_with(kept))
    {
        let hidden = full.len() - kept.len();
        let shift = |i: usize| i.saturating_sub(ELLIPSIS.len()) + hidden;
        let start = if range.start < ELLIPSIS.len() {
            0
        } else {
            shift(range.start)
        };
        return full[start..shift(range.end).max(start)].to_owned();
    }
    // Some other layout: the whole text, rather than the wrong part of it.
    full.to_owned()
}

/// Paints the highlight behind `range` of a laid-out run.
fn paint_selection(layout: &TextLayout, range: Range<usize>, color: Hsla, window: &mut Window) {
    let (Some(start), Some(end)) = (
        layout.position_for_index(range.start),
        layout.position_for_index(range.end),
    ) else {
        return;
    };
    let line = layout.line_height();
    let edges = layout.bounds();
    let mut quads = Vec::with_capacity(3);
    if start.y == end.y {
        quads.push(Bounds::from_corners(start, point(end.x, end.y + line)));
    } else {
        quads.push(Bounds::from_corners(
            start,
            point(edges.right(), start.y + line),
        ));
        if end.y > start.y + line {
            quads.push(Bounds::from_corners(
                point(edges.left(), start.y + line),
                point(edges.right(), end.y),
            ));
        }
        quads.push(Bounds::from_corners(
            point(edges.left(), end.y),
            point(end.x, end.y + line),
        ));
    }
    for bounds in quads {
        window.paint_quad(fill(bounds, color));
    }
}

#[cfg(test)]
mod tests {
    use super::{copy_text, reading_order};

    #[test]
    fn reading_order_follows_the_tree() {
        let paths = [
            "r",
            "r.0",
            "r.0.0",
            "r.0.1",
            "r.0.6",
            "r.0.7",
            "r.0.7.3",
            "r.0.200",
            "r.1",
            "r.1.0.0.0.0",
            "r.2",
            "r.15",
            "r.15.4000",
            "r.16",
        ];
        for pair in paths.windows(2) {
            assert!(
                reading_order(pair[0]) < reading_order(pair[1]),
                "{} should come before {}",
                pair[0],
                pair[1]
            );
        }
    }

    #[test]
    fn a_truncated_selection_copies_what_the_ellipsis_hides() {
        let full = "deploy/production-eu-west";
        let shown = "deploy/produc…";
        let kept = "deploy/produc".len();
        // Inside the shown text: exactly what is highlighted.
        assert_eq!(copy_text(full, shown, 0..6), "deploy");
        // Reaching the ellipsis takes the rest of the text.
        assert_eq!(copy_text(full, shown, 0..shown.len()), full);
        assert_eq!(copy_text(full, shown, 7..shown.len()), "production-eu-west");
        // Only the ellipsis: the hidden part.
        assert_eq!(copy_text(full, shown, kept..shown.len()), "tion-eu-west");
        // Untruncated text copies as is.
        assert_eq!(copy_text(full, full, 7..17), "production");
    }

    #[test]
    fn a_start_truncated_selection_copies_what_the_ellipsis_hides() {
        let full = "~/Code/view/src/main.rs";
        let shown = "…src/main.rs";
        assert_eq!(copy_text(full, shown, 0..shown.len()), full);
        let end = shown.len();
        assert_eq!(copy_text(full, shown, end - 7..end), "main.rs");
    }
}
