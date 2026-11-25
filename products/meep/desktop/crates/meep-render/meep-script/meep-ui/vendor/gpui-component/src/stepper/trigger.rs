use gpui::{
    AnyElement, App, Axis, ClickEvent, InteractiveElement as _, IntoElement, ParentElement, Pixels,
    RenderOnce, StatefulInteractiveElement as _, StyleRefinement, Styled, Window, div,
    prelude::FluentBuilder as _, px,
};
use gpui_base::TestSupportExt as _;

use crate::{ActiveTheme as _, AxisExt, Icon, Size, StyleSized, StyledExt as _, ThemeStyled as _};

/// The trigger part of a stepper item.
#[derive(IntoElement)]
pub(super) struct StepperTrigger {
    step: usize,
    checked_step: usize,
    style: StyleRefinement,
    icon: Option<Icon>,
    icon_size: Pixels,
    children: Vec<AnyElement>,
    layout: Axis,
    disabled: bool,
    text_center: bool,
    size: Size,
    on_click: Box<dyn Fn(&ClickEvent, &mut Window, &mut App) + 'static>,
}

impl StepperTrigger {
    pub(super) fn new() -> Self {
        Self {
            step: 0,
            checked_step: 0,
            icon: None,
            icon_size: px(24.),
            layout: Axis::Horizontal,
            disabled: false,
            size: Size::default(),
            children: Vec::new(),
            text_center: false,
            style: StyleRefinement::default(),
            on_click: Box::new(|_, _, _| {}),
        }
    }

    pub(super) fn step(mut self, ix: usize) -> Self {
        self.step = ix;
        self
    }

    pub(super) fn checked_step(mut self, checked_step: usize) -> Self {
        self.checked_step = checked_step;
        self
    }

    pub(super) fn layout(mut self, layout: Axis) -> Self {
        self.layout = layout;
        self
    }

    pub(super) fn icon(mut self, icon: Option<impl Into<Icon>>) -> Self {
        self.icon = icon.map(|i| i.into());
        self
    }

    pub(super) fn icon_size(mut self, size: Pixels) -> Self {
        self.icon_size = size;
        self
    }

    pub(super) fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub(super) fn with_size(mut self, size: Size) -> Self {
        self.size = size;
        self
    }

    pub(super) fn text_center(mut self, center: bool) -> Self {
        self.text_center = center;
        self
    }

    pub(super) fn on_click<F>(mut self, f: F) -> Self
    where
        F: Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    {
        self.on_click = Box::new(f);
        self
    }
}

impl Styled for StepperTrigger {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for StepperTrigger {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for StepperTrigger {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let is_checked = self.step <= self.checked_step;

        div()
            .id(("trigger", self.step))
            .test_support()
            .when(self.layout.is_horizontal(), |this| this.v_flex().gap_1())
            .when(self.layout.is_vertical(), |this| this.h_flex().gap_2())
            .items_start()
            .when(self.text_center, |this| this.items_center())
            .input_text_size(self.size.smaller())
            .refine_style(&self.style)
            .child(
                div()
                    .id("indicator")
                    .size(self.icon_size)
                    .overflow_hidden()
                    .flex()
                    .rounded_full_style(cx)
                    .items_center()
                    .justify_center()
                    .bg(cx.theme().tokens.secondary)
                    .when(!self.disabled && !is_checked, |this| {
                        this.hover(|this| this.bg(cx.theme().tokens.secondary_hover))
                            .active(|this| this.bg(cx.theme().tokens.secondary_active))
                    })
                    .text_color(cx.theme().secondary_foreground)
                    .when(is_checked, |this| {
                        this.bg(cx.theme().tokens.primary)
                            .text_color(cx.theme().primary_foreground)
                    })
                    .when(self.size != Size::XSmall, |this| {
                        this.map(|this| {
                            this.child(if let Some(icon) = self.icon {
                                icon.into_any_element()
                            } else {
                                div().child(format!("{}", self.step + 1)).into_any_element()
                            })
                        })
                    }),
            )
            .children(self.children)
            .when(!self.disabled, |this| {
                this.on_click(move |event, window, cx| {
                    (self.on_click)(event, window, cx);
                })
            })
    }
}
