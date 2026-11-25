//! The clip a script view paints under, which absolute sheets and dialogs
//! keep: the view's root builds them (`tree::Node::view_layer`), and as
//! layers they paint after everything else, outside their parents' clips.
use super::*;

/// The rectangle and rounded corners that clip the view where it paints.
#[derive(Clone, Copy)]
pub(super) struct ViewClip {
    mask: Bounds<Pixels>,
    corners: Option<(Bounds<Pixels>, Corners<Pixels>)>,
}

/// Records where the view paints: its own bounds, inside the pane's border,
/// and the pane's rounded corners brought in to them. Layers paint later,
/// outside the pane, and reapply it.
pub(super) fn clip_probe(shared: Rc<Shared>) -> impl IntoElement {
    canvas(
        |_, _, _| {},
        move |view, _, window, _| {
            let scale = window.scale_factor();
            let unscale = |v: ScaledPixels| px(v.0 / scale);
            let mask = window.content_mask().bounds.intersect(&view);
            let clip = window.corner_clip();
            let outer = Bounds::new(
                point(unscale(clip.bounds.origin.x), unscale(clip.bounds.origin.y)),
                size(
                    unscale(clip.bounds.size.width),
                    unscale(clip.bounds.size.height),
                ),
            );
            // An inner edge follows an outer radius less the inset, as in CSS.
            let inner = |radius: ScaledPixels, dx: Pixels, dy: Pixels| {
                (unscale(radius) - dx.max(dy)).max(Pixels::ZERO)
            };
            let r = clip.corner_radii;
            let (left, top) = (view.left() - outer.left(), view.top() - outer.top());
            let (right, bottom) = (outer.right() - view.right(), outer.bottom() - view.bottom());
            let radii = Corners {
                top_left: inner(r.top_left, left, top),
                top_right: inner(r.top_right, right, top),
                bottom_right: inner(r.bottom_right, right, bottom),
                bottom_left: inner(r.bottom_left, left, bottom),
            };
            let rounded = [
                radii.top_left,
                radii.top_right,
                radii.bottom_right,
                radii.bottom_left,
            ]
            .iter()
            .any(|r| *r > Pixels::ZERO);
            shared.clip.set(Some(ViewClip {
                mask,
                corners: rounded.then_some((view, radii)),
            }));
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
        let corners = self.shared.clip.get().and_then(|c| c.corners);
        let mask = self.mask();
        let child = &mut self.child;
        window.with_content_mask(mask, |window| match corners {
            Some((bounds, radii)) => {
                window.with_corner_clip(bounds, radii, |window| child.paint(window, cx))
            }
            None => child.paint(window, cx),
        });
    }
}
