use gpui_base::TestSupportExt as _;
use std::{rc::Rc, time::Duration};

use gpui::{
    Animation, AnimationExt as _, AnyElement, App, ClickEvent, DefiniteLength, DismissEvent, Edges,
    EventEmitter, FocusHandle, InteractiveElement as _, IntoElement, ParentElement, Pixels,
    RenderOnce, StyleRefinement, Styled, Window, div, prelude::FluentBuilder as _, px,
};
use gpui_base::{ElementExt as _, Sheet as BaseSheet, TextSelectionScopeId, actions::Cancel};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::{
    ActiveTheme, IconName, Placement, Sizable, StyledExt as _, WindowExt as _,
    button::{Button, ButtonVariants as _},
    dialog::overlay_color,
    h_flex,
    scroll::ScrollableElement as _,
    title_bar::TITLE_BAR_HEIGHT,
    v_flex,
};

pub(crate) fn init(_: &mut App) {}

/// The settings for sheets.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
#[non_exhaustive]
pub struct SheetSettings {
    /// The margin top for the sheet, default is [`TITLE_BAR_HEIGHT`].
    pub margin_top: Pixels,
}

impl Default for SheetSettings {
    fn default() -> Self {
        Self {
            margin_top: TITLE_BAR_HEIGHT,
        }
    }
}

/// Sheet component that slides in from the side of the window.
#[derive(IntoElement)]
pub struct Sheet {
    pub(crate) focus_handle: FocusHandle,
    pub(crate) placement: Placement,
    pub(crate) size: DefiniteLength,
    pub(crate) selection_scope: TextSelectionScopeId,
    resizable: bool,
    on_close: Rc<dyn Fn(&ClickEvent, &mut Window, &mut App) + 'static>,
    title: Option<AnyElement>,
    footer: Option<AnyElement>,
    style: StyleRefinement,
    children: Vec<AnyElement>,
    overlay: bool,
    overlay_closable: bool,
}

impl Sheet {
    /// Creates a new Sheet.
    pub fn new(_: &mut Window, cx: &mut App) -> Self {
        Self {
            focus_handle: cx.focus_handle(),
            placement: Placement::Right,
            size: DefiniteLength::Absolute(px(350.).into()),
            selection_scope: TextSelectionScopeId::default(),
            resizable: true,
            title: None,
            footer: None,
            style: StyleRefinement::default(),
            children: Vec::new(),
            overlay: true,
            overlay_closable: true,
            on_close: Rc::new(|_, _, _| {}),
        }
    }

    /// Sets the title of the sheet.
    pub fn title(mut self, title: impl IntoElement) -> Self {
        self.title = Some(title.into_any_element());
        self
    }

    /// Set the footer of the sheet.
    pub fn footer(mut self, footer: impl IntoElement) -> Self {
        self.footer = Some(footer.into_any_element());
        self
    }

    /// Sets the size of the sheet, default is 350px.
    pub fn size(mut self, size: impl Into<DefiniteLength>) -> Self {
        self.size = size.into();
        self
    }

    /// Sets whether the sheet is resizable, default is `true`.
    pub fn resizable(mut self, resizable: bool) -> Self {
        self.resizable = resizable;
        self
    }

    /// Set whether the sheet should have an overlay, default is `true`.
    pub fn overlay(mut self, overlay: bool) -> Self {
        self.overlay = overlay;
        self
    }

    /// Set whether the sheet should be closable by clicking the overlay, default is `true`.
    pub fn overlay_closable(mut self, overlay_closable: bool) -> Self {
        self.overlay_closable = overlay_closable;
        self
    }

    /// Listen to the close event of the sheet.
    pub fn on_close(
        mut self,
        on_close: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_close = Rc::new(on_close);
        self
    }
}

impl EventEmitter<DismissEvent> for Sheet {}
impl ParentElement for Sheet {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}
impl Styled for Sheet {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Sheet {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let placement = self.placement;
        let selection_scope = self.selection_scope;
        let frame_insets = crate::window_border::window_content_insets(window);
        let safe_insets = crate::window_border::window_safe_insets(window);
        let frame_insets = Edges {
            top: frame_insets.top.max(safe_insets.top),
            right: frame_insets.right.max(safe_insets.right),
            bottom: frame_insets.bottom.max(safe_insets.bottom),
            left: frame_insets.left.max(safe_insets.left),
        };
        let size = window.viewport_size()
            - gpui::size(
                frame_insets.left + frame_insets.right,
                frame_insets.top + frame_insets.bottom,
            );
        let top = cx.theme().sheet.margin_top;
        let base_size = window.text_style().font_size;
        let rem_size = window.rem_size();
        let mut paddings = Edges::all(px(16.));
        if let Some(pl) = self.style.padding.left {
            paddings.left = pl.to_pixels(base_size, rem_size);
        }
        if let Some(pr) = self.style.padding.right {
            paddings.right = pr.to_pixels(base_size, rem_size);
        }
        if let Some(pt) = self.style.padding.top {
            paddings.top = pt.to_pixels(base_size, rem_size);
        }
        if let Some(pb) = self.style.padding.bottom {
            paddings.bottom = pb.to_pixels(base_size, rem_size);
        }

        let overlay = div()
            .occlude()
            .w(size.width)
            .h(size.height)
            .bg(overlay_color(self.overlay, cx));

        let surface = v_flex()
            .id("sheet-content")
            .test_support()
            .absolute()
            .occlude()
            .bg(cx.theme().tokens.background)
            .border_color(cx.theme().border)
            .shadow_xl()
            .refine_style(&self.style)
            .map(|this| {
                // Set the size of the sheet.
                if placement.is_horizontal() {
                    this.w(self.size)
                } else {
                    this.h(self.size)
                }
            })
            .map(|this| match self.placement {
                Placement::Top => this.top(top).left_0().right_0().border_b_1(),
                Placement::Right => this.top(top).right_0().bottom_0().border_l_1(),
                Placement::Bottom => this.bottom_0().left_0().right_0().border_t_1(),
                Placement::Left => this.top(top).left_0().bottom_0().border_r_1(),
            })
            .child(
                // TitleBar
                h_flex()
                    .justify_between()
                    .pl_4()
                    .pr_3()
                    .py_2()
                    .w_full()
                    .font_semibold()
                    .child(self.title.unwrap_or(div().into_any_element()))
                    .child(
                        Button::new("close")
                            .small()
                            .ghost()
                            .icon(IconName::Close)
                            .accessibility_label("Close")
                            .on_click(|_, window, cx| {
                                window.dispatch_action(Box::new(Cancel), cx);
                            }),
                    ),
            )
            .child(
                div().flex_1().overflow_hidden().child(
                    // Body
                    v_flex()
                        .size_full()
                        .overflow_y_scrollbar()
                        .pl(paddings.left)
                        .pr(paddings.right)
                        .children(self.children),
                ),
            )
            .when_some(self.footer, |this, footer| {
                // Footer
                this.child(
                    h_flex()
                        .justify_between()
                        .px_4()
                        .py_3()
                        .w_full()
                        .child(footer),
                )
            })
            .with_animation(
                "slide",
                Animation::new(Duration::from_secs_f64(0.15)),
                move |this, delta| {
                    let y = px(-100.) + delta * px(100.);
                    this.map(|this| match placement {
                        Placement::Top => this.top(top + y),
                        Placement::Right => this.right(y),
                        Placement::Bottom => this.bottom(y),
                        Placement::Left => this.left(y),
                    })
                },
            );
        let surface = surface.text_selection_scope(selection_scope);

        BaseSheet::new(cx)
            .top(frame_insets.top)
            .left(frame_insets.left)
            .w(size.width)
            .h(size.height)
            .focus_handle(self.focus_handle)
            .overlay_interactive(self.overlay)
            .overlay_closable(self.overlay && self.overlay_closable)
            .request_close(|window, cx| window.close_sheet(cx))
            .on_close(move |event, window, cx| (self.on_close)(event, window, cx))
            .overlay(overlay)
            .surface(surface)
    }
}
