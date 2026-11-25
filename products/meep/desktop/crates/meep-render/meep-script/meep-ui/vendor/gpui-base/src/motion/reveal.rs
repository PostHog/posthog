use gpui::{
    AnyElement, App, AvailableSpace, Bounds, ContentMask, Element, ElementId, GlobalElementId,
    InspectorElementId, IntoElement, LayoutId, Pixels, Style, Window, px, relative, size,
};

/// A measured, clipped vertical reveal driven by normalized progress.
pub struct MotionReveal {
    id: ElementId,
    progress: f32,
    child: AnyElement,
}

#[derive(Clone, Copy, Default)]
struct RevealState {
    height: Option<Pixels>,
}

impl MotionReveal {
    pub fn new(id: impl Into<ElementId>, progress: f32, child: AnyElement) -> Self {
        Self {
            id: id.into(),
            progress: progress.clamp(0.0, 1.0),
            child,
        }
    }
}

impl IntoElement for MotionReveal {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for MotionReveal {
    type RequestLayoutState = ();
    type PrepaintState = ();

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        global_id: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        let height = window.with_element_state(
            global_id.expect("MotionReveal must have an id"),
            |state: Option<RevealState>, _| {
                let state = state.unwrap_or_default();
                (state.height, state)
            },
        );
        let mut style = Style::default();
        style.size.width = relative(1.0).into();
        match height {
            None if self.progress > 0.0 => {}
            None => style.size.height = px(0.0).into(),
            Some(height) => style.size.height = (height * self.progress).into(),
        }
        (window.request_layout(style, None, cx), ())
    }

    fn prepaint(
        &mut self,
        global_id: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let measured = self.child.layout_as_root(
            size(
                AvailableSpace::Definite(bounds.size.width),
                AvailableSpace::MinContent,
            ),
            window,
            cx,
        );
        let changed = window.with_element_state(
            global_id.expect("MotionReveal must have an id"),
            |state: Option<RevealState>, _| {
                let mut state = state.unwrap_or_default();
                let changed = state.height != Some(measured.height);
                state.height = Some(measured.height);
                (changed, state)
            },
        );
        if changed {
            window.request_animation_frame();
        }
        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            self.child.prepaint_at(bounds.origin, window, cx);
        });
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut Self::RequestLayoutState,
        _: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            self.child.paint(window, cx);
        });
    }
}
