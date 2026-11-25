use std::rc::Rc;

use gpui::{
    App, ClickEvent, ElementId, InteractiveElement as _, IntoElement, ParentElement, RenderOnce,
    Role, SharedString, StatefulInteractiveElement, StyleRefinement, Styled, Window, div,
    prelude::FluentBuilder as _,
};

use crate::{ActiveTheme, Icon, IconName, StyledExt, h_flex};

/// A breadcrumb navigation element.
#[derive(IntoElement)]
pub struct Breadcrumb {
    style: StyleRefinement,
    items: Vec<BreadcrumbItem>,
}

/// Item for the [`Breadcrumb`].
#[derive(IntoElement)]
pub struct BreadcrumbItem {
    id: ElementId,
    style: StyleRefinement,
    label: SharedString,
    on_click: Option<Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>>,
    disabled: bool,
    is_last: bool,
}

impl BreadcrumbItem {
    /// Create a new BreadcrumbItem with the given id and label.
    pub fn new(label: impl Into<SharedString>) -> Self {
        Self {
            id: ElementId::Integer(0),
            style: StyleRefinement::default(),
            label: label.into(),
            on_click: None,
            disabled: false,
            is_last: false,
        }
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn on_click(
        mut self,
        on_click: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Rc::new(on_click));
        self
    }

    fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = id.into();
        self
    }

    /// For internal use only.
    fn is_last(mut self, is_last: bool) -> Self {
        self.is_last = is_last;
        self
    }
}

impl Styled for BreadcrumbItem {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl From<&'static str> for BreadcrumbItem {
    fn from(value: &'static str) -> Self {
        Self::new(value)
    }
}

impl From<String> for BreadcrumbItem {
    fn from(value: String) -> Self {
        Self::new(value)
    }
}

impl From<SharedString> for BreadcrumbItem {
    fn from(value: SharedString) -> Self {
        Self::new(value)
    }
}

impl RenderOnce for BreadcrumbItem {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        div()
            .id(self.id)
            .role(if self.on_click.is_some() && !self.disabled {
                Role::Link
            } else {
                Role::ListItem
            })
            .child(self.label)
            .text_color(cx.theme().muted_foreground)
            .when(self.is_last, |this| this.text_color(cx.theme().foreground))
            .when(self.disabled, |this| {
                this.text_color(cx.theme().muted_foreground)
            })
            .refine_style(&self.style)
            .when(!self.disabled, |this| {
                this.when_some(self.on_click, |this, on_click| {
                    this.cursor_pointer().on_click(move |event, window, cx| {
                        on_click(event, window, cx);
                    })
                })
            })
    }
}

impl Breadcrumb {
    /// Create a new breadcrumb.
    pub fn new() -> Self {
        Self {
            items: Vec::new(),
            style: StyleRefinement::default(),
        }
    }

    /// Add an [`BreadcrumbItem`] to the breadcrumb.
    pub fn child(mut self, item: impl Into<BreadcrumbItem>) -> Self {
        self.items.push(item.into());
        self
    }

    /// Add multiple [`BreadcrumbItem`] items to the breadcrumb.
    pub fn children(mut self, items: impl IntoIterator<Item = impl Into<BreadcrumbItem>>) -> Self {
        self.items.extend(items.into_iter().map(Into::into));
        self
    }
}

#[derive(IntoElement)]
struct BreadcrumbSeparator;
impl RenderOnce for BreadcrumbSeparator {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        Icon::new(IconName::ChevronRight)
            .text_color(cx.theme().muted_foreground)
            .size_3p5()
            .into_any_element()
    }
}

impl Styled for Breadcrumb {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Breadcrumb {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let items_count = self.items.len();

        let mut children = vec![];
        for (ix, item) in self.items.into_iter().enumerate() {
            let is_last = ix == items_count - 1;

            let item = item.id(ix);
            children.push(item.is_last(is_last).into_any_element());
            if !is_last {
                children.push(BreadcrumbSeparator.into_any_element());
            }
        }

        h_flex()
            .gap_1p5()
            .text_sm()
            .text_color(cx.theme().muted_foreground)
            .refine_style(&self.style)
            .children(children)
    }
}
