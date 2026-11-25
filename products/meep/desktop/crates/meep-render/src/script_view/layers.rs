//! The clip a script view paints under, which absolute sheets and dialogs
//! keep: the view's root builds them (`tree::Node::view_layer`), and as
//! layers they paint after everything else, outside their parents' clips.
use super::*;

/// The rectangle and rounded corners that clip the view where it paints.
#[derive(Clone, Copy)]
pub(super) struct ViewClip {
    mask: Bounds<Pixels>,
}

/// Records where the view paints: its own bounds, inside the pane's border,
/// and the pane's rounded corners brought in to them. Layers paint later,
/// outside the pane, and reapply it.
pub(super) fn clip_probe(shared: Rc<Shared>) -> impl IntoElement {
    canvas(
        |_, _, _| {},
        move |view, _, window, _| {
            let mask = window.content_mask().bounds.intersect(&view);
            shared.clip.set(Some(ViewClip { mask }));
        },
    )
    .absolute()
    .inset_0()
}

/// A layer, clipped like the rest of the view. `deferred` paints it after
/// every ancestor, when neither the pane's bounds nor its rounded corners are
/// in force any more, so a full-bleed scrim or sheet would square the pane's
/// corners and could spill over its edge.
pub(super) struct ViewClipped {
    pub(super) child: AnyElement,
    pub(super) shared: Rc<Shared>,
}

impl ViewClipped {
    pub(super) fn mask(&self) -> Option<ContentMask<Pixels>> {
        self.shared
            .clip
            .get()
            .map(|c| ContentMask { bounds: c.mask })
    }
}

impl IntoElement for ViewClipped {
    type Element = Self;
    fn into_element(self) -> Self {
        self
    }
}

impl Element for ViewClipped {
    type RequestLayoutState = ();
    type PrepaintState = ();
    fn id(&self) -> Option<ElementId> {
        None
    }
    fn source_location(&self) -> Option<&'static core::panic::Location<'static>> {
        None
    }
    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, ()) {
        (self.child.request_layout(window, cx), ())
    }
    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) {
        // Hitboxes outside the view must not catch clicks either.
        let mask = self.mask();
        let child = &mut self.child;
        window.with_content_mask(mask, |window| child.prepaint(window, cx));
    }
    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        _: Bounds<Pixels>,
        _: &mut (),
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) {
        let mask = self.mask();
        window.with_content_mask(mask, |window| self.child.paint(window, cx));
    }
}
