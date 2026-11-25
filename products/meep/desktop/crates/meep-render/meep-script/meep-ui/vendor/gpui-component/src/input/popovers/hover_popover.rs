use std::{ops::Range, rc::Rc};

use gpui::{
    AnyElement, App, AppContext as _, AvailableSpace, Bounds, Element, ElementId, Entity,
    InteractiveElement, IntoElement, MouseDownEvent, MouseMoveEvent, ParentElement as _, Pixels,
    Render, StatefulInteractiveElement as _, StyleRefinement, Styled, Window, deferred, div, point,
    px,
};

use crate::{
    StyledExt, ThemeStyled as _,
    input::{EditorState, popovers::render_markdown},
};

pub struct HoverPopover {
    editor: Entity<EditorState>,
    /// The symbol range byte of the hover trigger.
    pub(crate) symbol_range: Range<usize>,
    pub(crate) hover: Rc<lsp_types::Hover>,
}

impl HoverPopover {
    pub fn new(
        editor: Entity<EditorState>,
        symbol_range: Range<usize>,
        hover: &lsp_types::Hover,
        cx: &mut App,
    ) -> Entity<Self> {
        let hover = Rc::new(hover.clone());

        cx.new(|_| Self {
            editor,
            symbol_range,
            hover,
        })
    }
}

impl Render for HoverPopover {
    fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
        let contents = match self.hover.contents.clone() {
            lsp_types::HoverContents::Scalar(scalar) => match scalar {
                lsp_types::MarkedString::String(s) => s,
                lsp_types::MarkedString::LanguageString(ls) => ls.value,
            },
            lsp_types::HoverContents::Array(arr) => arr
                .into_iter()
                .map(|item| match item {
                    lsp_types::MarkedString::String(s) => s,
                    lsp_types::MarkedString::LanguageString(ls) => ls.value,
                })
                .collect::<Vec<_>>()
                .join("\n\n"),
            lsp_types::HoverContents::Markup(markup) => markup.value,
        };

        Popover::new(
            "hover-popover",
            self.editor.clone(),
            self.symbol_range.clone(),
            move |window, cx| render_markdown("message", contents.clone(), window, cx),
        )
        .into_any_element()
    }
}

pub(crate) struct Popover {
    id: ElementId,
    style: StyleRefinement,
    editor: Entity<EditorState>,
    range: Range<usize>,
    width_limit: Range<Pixels>,
    content_builder: Box<dyn Fn(&mut Window, &mut App) -> AnyElement>,
}

impl Styled for Popover {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Popover {
    pub fn new<F, E>(
        id: impl Into<ElementId>,
        editor: Entity<EditorState>,
        range: Range<usize>,
        f: F,
    ) -> Self
    where
        F: Fn(&mut Window, &mut App) -> E + 'static,
        E: IntoElement,
    {
        Self {
            id: id.into(),
            editor,
            range,
            style: StyleRefinement::default(),
            width_limit: px(200.)..px(500.),
            content_builder: Box::new(move |window, cx| (f)(window, cx).into_any_element()),
        }
    }

    /// Get the bounds of the range in the editor, if it is visible.
    fn trigger_bounds(&self, cx: &App) -> Option<Bounds<Pixels>> {
        let editor = self.editor.read(cx);
        editor.range_to_bounds(&self.range)
    }
}

impl IntoElement for Popover {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

pub(crate) struct PopoverLayoutState {
    bounds: Bounds<Pixels>,
    element: Option<AnyElement>,
}

impl Element for Popover {
    type RequestLayoutState = PopoverLayoutState;
    type PrepaintState = ();

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (gpui::LayoutId, Self::RequestLayoutState) {
        let trigger_bounds = match self.trigger_bounds(cx) {
            Some(bounds) => bounds,
            None => {
                return (
                    div().into_any_element().request_layout(window, cx),
                    PopoverLayoutState {
                        bounds: Bounds::default(),
                        element: None,
                    },
                );
            }
        };

        let max_width = self
            .width_limit
            .end
            .min(window.bounds().size.width - SNAP_TO_EDGE * 2)
            .max(px(200.));
        let max_height = (window.bounds().size.height - SNAP_TO_EDGE * 2).min(px(320.));

        let mut popover = deferred(
            div()
                .id("hover-popover-content")
                .flex_none()
                .occlude()
                .p_1()
                .text_xs()
                .popover_style(cx)
                .shadow_md()
                .max_w(max_width)
                .max_h(max_height)
                .overflow_y_scroll()
                .refine_style(&self.style)
                .child((self.content_builder)(window, cx)),
        )
        .with_priority(gpui_base::POPUP_PRIORITY)
        .into_any_element();

        let popover_size = popover.layout_as_root(AvailableSpace::min_size(), window, cx);
        const SNAP_TO_EDGE: Pixels = px(8.);
        let top_space = trigger_bounds.top() - SNAP_TO_EDGE;
        let right_space = window.bounds().size.width - trigger_bounds.left() - SNAP_TO_EDGE;

        let mut pos = point(
            trigger_bounds.left(),
            trigger_bounds.top() - popover_size.height,
        );
        if popover_size.height > top_space {
            pos.y = trigger_bounds.bottom();
        }
        if popover_size.width > right_space {
            pos.x = trigger_bounds.right() - popover_size.width;
        }

        let mut empty = div().into_any_element();
        let layout_id = empty.request_layout(window, cx);
        (
            layout_id,
            PopoverLayoutState {
                bounds: Bounds {
                    origin: pos,
                    size: popover_size,
                },
                element: Some(popover),
            },
        )
    }

    fn prepaint(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: Bounds<Pixels>,
        request_layout: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let bounds = request_layout.bounds;
        let Some(popover) = request_layout.element.as_mut() else {
            return;
        };

        window.with_absolute_element_offset(bounds.origin, |window| {
            popover.prepaint(window, cx);
        })
    }

    fn paint(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: Bounds<Pixels>,
        request_layout: &mut Self::RequestLayoutState,
        _: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        let bounds = request_layout.bounds;
        let Some(popover) = request_layout.element.as_mut() else {
            return;
        };

        popover.paint(window, cx);

        let editor = self.editor.clone();
        // Mouse down out to hide.
        window.on_mouse_event(move |event: &MouseDownEvent, _, _, cx| {
            if !bounds.contains(&event.position) {
                let _ = editor.update(cx, |editor, cx| {
                    editor.clear_hover_state(cx);
                });
            }
        });

        // Mouse out of trigger + popover bounds
        let editor = self.editor.clone();
        let trigger_bounds = self.trigger_bounds(cx).unwrap_or(bounds);
        let keep_open_region = trigger_bounds.union(&bounds);
        window.on_mouse_event(move |event: &MouseMoveEvent, _, _, cx| {
            if !keep_open_region.contains(&event.position) {
                let _ = editor.update(cx, |editor, cx| {
                    editor.clear_hover_state(cx);
                });
            }
        })
    }
}
