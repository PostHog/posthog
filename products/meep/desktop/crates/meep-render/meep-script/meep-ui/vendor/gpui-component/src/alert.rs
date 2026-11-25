use std::rc::Rc;

use gpui::{
    App, ClickEvent, ElementId, Empty, Hsla, InteractiveElement, IntoElement, ParentElement as _,
    RenderOnce, Role, SharedString, StatefulInteractiveElement, StyleRefinement, Styled, Window,
    div, prelude::FluentBuilder as _, px, rems, transparent_white,
};

use crate::{
    ActiveTheme as _, Colorize, Icon, IconName, Sizable, Size, StyledExt, h_flex,
    text::{Text, TextViewStyle},
};

/// The variant of the [`Alert`].
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub enum AlertVariant {
    #[default]
    Default,
    Info,
    Success,
    Warning,
    Error,
}

impl AlertVariant {
    fn fg(&self, cx: &App) -> Hsla {
        match self {
            Self::Default => cx.theme().foreground,
            Self::Info => cx.theme().info,
            Self::Success => cx.theme().success,
            Self::Warning => cx.theme().warning,
            Self::Error => cx.theme().danger,
        }
    }

    fn bg(&self, cx: &App) -> Hsla {
        match self {
            Self::Default => cx.theme().background,
            Self::Info => cx.theme().info.mix_oklab(transparent_white(), 0.04),
            Self::Success => cx.theme().success.mix_oklab(transparent_white(), 0.04),
            Self::Warning => cx.theme().warning.mix_oklab(transparent_white(), 0.04),
            Self::Error => cx.theme().danger.mix_oklab(transparent_white(), 0.04),
        }
    }

    fn border_color(&self, cx: &App) -> Hsla {
        match self {
            Self::Default => cx.theme().border,
            Self::Info => cx.theme().info.mix_oklab(transparent_white(), 0.3),
            Self::Success => cx.theme().success.mix_oklab(transparent_white(), 0.3),
            Self::Warning => cx.theme().warning.mix_oklab(transparent_white(), 0.3),
            Self::Error => cx.theme().danger.mix_oklab(transparent_white(), 0.3),
        }
    }
}

/// Alert used to display a message to the user.
#[derive(IntoElement)]
pub struct Alert {
    id: ElementId,
    style: StyleRefinement,
    variant: AlertVariant,
    icon: Icon,
    title: Option<SharedString>,
    message: Text,
    size: Size,
    banner: bool,
    on_close: Option<Rc<dyn Fn(&ClickEvent, &mut Window, &mut App) + 'static>>,
    visible: bool,
}

impl Alert {
    /// Create a new alert with the given message.
    pub fn new(id: impl Into<ElementId>, message: impl Into<Text>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            variant: AlertVariant::default(),
            icon: Icon::new(IconName::Info),
            title: None,
            message: message.into(),
            size: Size::default(),
            banner: false,
            visible: true,
            on_close: None,
        }
    }

    /// Create a new info [`AlertVariant::Info`] with the given message.
    pub fn info(id: impl Into<ElementId>, message: impl Into<Text>) -> Self {
        Self::new(id, message)
            .with_variant(AlertVariant::Info)
            .icon(IconName::Info)
    }

    /// Create a new [`AlertVariant::Success`] alert with the given message.
    pub fn success(id: impl Into<ElementId>, message: impl Into<Text>) -> Self {
        Self::new(id, message)
            .with_variant(AlertVariant::Success)
            .icon(IconName::CircleCheck)
    }

    /// Create a new [`AlertVariant::Warning`] alert with the given message.
    pub fn warning(id: impl Into<ElementId>, message: impl Into<Text>) -> Self {
        Self::new(id, message)
            .with_variant(AlertVariant::Warning)
            .icon(IconName::TriangleAlert)
    }

    /// Create a new [`AlertVariant::Error`] alert with the given message.
    pub fn error(id: impl Into<ElementId>, message: impl Into<Text>) -> Self {
        Self::new(id, message)
            .with_variant(AlertVariant::Error)
            .icon(IconName::CircleX)
    }

    /// Sets the [`AlertVariant`] of the alert.
    pub fn with_variant(mut self, variant: AlertVariant) -> Self {
        self.variant = variant;
        self
    }

    /// Set the icon for the alert.
    pub fn icon(mut self, icon: impl Into<Icon>) -> Self {
        self.icon = icon.into();
        self
    }

    /// Set the title for the alert.
    pub fn title(mut self, title: impl Into<SharedString>) -> Self {
        self.title = Some(title.into());
        self
    }

    /// Set alert as banner style.
    ///
    /// The `banner` style will make the alert take the full width of the container and not border and radius.
    /// This mode will not display `title`.
    pub fn banner(mut self) -> Self {
        self.banner = true;
        self
    }

    /// Set the visibility of the alert.
    pub fn visible(mut self, visible: bool) -> Self {
        self.visible = visible;
        self
    }

    /// Set alert as closable, true will show Close icon.
    pub fn on_close(
        mut self,
        on_close: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_close = Some(Rc::new(on_close));
        self
    }
}

impl Sizable for Alert {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for Alert {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Alert {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        if !self.visible {
            return Empty.into_any_element();
        }

        let (radius, padding_x, padding_y, gap) = match self.size {
            Size::XSmall => (cx.theme().radius, px(12.), px(6.), px(6.)),
            Size::Small => (cx.theme().radius, px(12.), px(8.), px(6.)),
            Size::Large => (cx.theme().radius_lg, px(20.), px(14.), px(12.)),
            _ => (cx.theme().radius, px(16.), px(10.), px(12.)),
        };

        let bg = self.variant.bg(cx);
        let fg = self.variant.fg(cx);
        let border_color = self.variant.border_color(cx);

        h_flex()
            .id(self.id)
            .role(Role::Alert)
            .w_full()
            .text_color(fg)
            .bg(bg)
            .px(padding_x)
            .py(padding_y)
            .gap(gap)
            .justify_between()
            .text_sm()
            .border_1()
            .border_color(border_color)
            .when(!self.banner, |this| this.rounded(radius).items_start())
            .refine_style(&self.style)
            .child(
                div()
                    .flex()
                    .flex_1()
                    .when(self.banner, |this| this.items_center())
                    .overflow_hidden()
                    .gap(gap)
                    .child(
                        div()
                            .when(!self.banner, |this| this.mt(px(5.)))
                            .child(self.icon),
                    )
                    .child(
                        div()
                            .flex_1()
                            .overflow_hidden()
                            .gap_3()
                            .when(!self.banner, |this| {
                                this.when_some(self.title, |this, title| {
                                    this.child(
                                        div().w_full().truncate().font_semibold().child(title),
                                    )
                                })
                            })
                            .child(
                                self.message
                                    .style(TextViewStyle::default().paragraph_gap(rems(0.2))),
                            ),
                    ),
            )
            .when_some(self.on_close, |this, on_close| {
                this.child(
                    div()
                        .id("close")
                        .p_0p5()
                        .rounded(cx.theme().radius)
                        .hover(|this| this.bg(bg.opacity(0.8)))
                        .active(|this| this.bg(bg.opacity(0.9)))
                        .on_click(move |ev, window, cx| {
                            on_close(ev, window, cx);
                        })
                        .child(
                            Icon::new(IconName::Close)
                                .with_size(self.size.max(Size::Medium))
                                .flex_shrink_0(),
                        ),
                )
            })
            .into_any_element()
    }
}
