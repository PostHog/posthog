use std::{cell::RefCell, collections::HashSet, rc::Rc, sync::Arc};

use gpui::{
    AnyElement, App, ElementId, InteractiveElement as _, IntoElement, ParentElement, RenderOnce,
    SharedString, StatefulInteractiveElement as _, StyleRefinement, Styled, Window, div,
    percentage, prelude::FluentBuilder as _, rems,
};

use crate::{ActiveTheme as _, Icon, IconName, Sizable, Size, StyledExt as _, h_flex};
use gpui_base::{
    Accordion as BaseAccordion, AccordionHeader as BaseAccordionHeader,
    AccordionItem as BaseAccordionItem, AccordionPanel as BaseAccordionPanel, AccordionTrigger,
    MotionReveal, spring,
};

/// Accordion element.
#[derive(IntoElement)]
pub struct Accordion {
    id: ElementId,
    style: StyleRefinement,
    multiple: bool,
    size: Size,
    bordered: bool,
    disabled: bool,
    children: Vec<AccordionItem>,
    on_toggle_click: Option<Rc<dyn Fn(&[usize], &mut Window, &mut App)>>,
}

impl Accordion {
    /// Create a new Accordion with the given ID.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            multiple: false,
            size: Size::default(),
            bordered: true,
            children: Vec::new(),
            disabled: false,
            on_toggle_click: None,
        }
    }

    /// Set whether multiple accordion items can be opened simultaneously, default: false
    pub fn multiple(mut self, multiple: bool) -> Self {
        self.multiple = multiple;
        self
    }

    /// Set whether the accordion items have borders, default: true
    pub fn bordered(mut self, bordered: bool) -> Self {
        self.bordered = bordered;
        self
    }

    /// Set whether the accordion is disabled, default: false
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Adds an AccordionItem to the Accordion.
    pub fn item<F>(mut self, child: F) -> Self
    where
        F: FnOnce(AccordionItem) -> AccordionItem,
    {
        let item = child(AccordionItem::new());
        self.children.push(item);
        self
    }

    /// Sets the on_toggle_click callback for the AccordionGroup.
    ///
    /// The first argument `Vec<usize>` is the indices of the open accordions.
    pub fn on_toggle_click(
        mut self,
        on_toggle_click: impl Fn(&[usize], &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_toggle_click = Some(Rc::new(on_toggle_click));
        self
    }
}

impl Sizable for Accordion {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for Accordion {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Accordion {
    fn render(self, _window: &mut Window, cx: &mut App) -> impl IntoElement {
        let open_indices = Rc::new(RefCell::new(HashSet::new()));
        let multiple = self.multiple;
        let last_ix = self.children.len().saturating_sub(1);

        BaseAccordion::new(self.id)
            .v_flex()
            .size_full()
            // The bordered accordion is a single rounded card, the items are
            // joined by their separators.
            .when(self.bordered, |this| {
                this.border_1()
                    .border_color(cx.theme().border)
                    .rounded(cx.theme().radius_lg)
                    .overflow_hidden()
            })
            .refine_style(&self.style)
            .children(
                self.children
                    .into_iter()
                    .enumerate()
                    .map(|(ix, accordion)| {
                        if accordion.open {
                            open_indices.borrow_mut().insert(ix);
                        }
                        let disabled = self.disabled || accordion.disabled;

                        accordion
                            .index(ix)
                            .last(ix == last_ix)
                            .with_size(self.size)
                            .disabled(disabled)
                            .on_toggle_click({
                                let open_indices = open_indices.clone();
                                move |open, _, _| {
                                    let mut open_indices = open_indices.borrow_mut();
                                    if *open {
                                        if !multiple {
                                            open_indices.clear();
                                        }
                                        open_indices.insert(ix);
                                    } else {
                                        open_indices.remove(&ix);
                                    }
                                }
                            })
                    }),
            )
            .when_some(
                self.on_toggle_click.filter(|_| !self.disabled),
                |this, on_toggle| {
                    this.on_click(move |_, window, cx| {
                        let open_indices =
                            open_indices.borrow().iter().copied().collect::<Vec<_>>();
                        on_toggle(&open_indices, window, cx)
                    })
                },
            )
    }
}

/// An Accordion is a vertically stacked list of items, each of which can be expanded to reveal the content associated with it.
#[derive(IntoElement)]
pub struct AccordionItem {
    index: usize,
    last: bool,
    style: StyleRefinement,
    hover_style: Option<StyleRefinement>,
    title_style: StyleRefinement,
    content_style: StyleRefinement,
    icon: Option<Icon>,
    title: AnyElement,
    children: Vec<AnyElement>,
    open: bool,
    size: Size,
    disabled: bool,
    on_toggle_click: Option<Arc<dyn Fn(&bool, &mut Window, &mut App)>>,
}

impl AccordionItem {
    /// Create a new AccordionItem.
    pub fn new() -> Self {
        Self {
            index: 0,
            last: false,
            style: StyleRefinement::default(),
            hover_style: None,
            title_style: StyleRefinement::default(),
            content_style: StyleRefinement::default(),
            icon: None,
            title: SharedString::default().into_any_element(),
            children: Vec::new(),
            open: false,
            disabled: false,
            on_toggle_click: None,
            size: Size::default(),
        }
    }

    /// Set the icon for the accordion item.
    pub fn icon(mut self, icon: impl Into<Icon>) -> Self {
        self.icon = Some(icon.into());
        self
    }

    /// Set the title for the accordion item.
    pub fn title(mut self, title: impl IntoElement) -> Self {
        self.title = title.into_any_element();
        self
    }

    pub fn open(mut self, open: bool) -> Self {
        self.open = open;
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Set extra style for the title row.
    pub fn title_style(mut self, style: StyleRefinement) -> Self {
        self.title_style = style;
        self
    }

    /// Set the style of the title row while the mouse is over it.
    ///
    /// There is no hover style by default. The title row is the part that
    /// toggles the item, so the hover feedback belongs there, not on the
    /// whole item.
    pub fn hover(mut self, f: impl FnOnce(StyleRefinement) -> StyleRefinement) -> Self {
        self.hover_style = Some(f(StyleRefinement::default()));
        self
    }

    /// Set extra style for the content below the title.
    pub fn content_style(mut self, style: StyleRefinement) -> Self {
        self.content_style = style;
        self
    }

    fn index(mut self, index: usize) -> Self {
        self.index = index;
        self
    }

    fn last(mut self, last: bool) -> Self {
        self.last = last;
        self
    }

    fn on_toggle_click(
        mut self,
        on_toggle_click: impl Fn(&bool, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_toggle_click = Some(Arc::new(on_toggle_click));
        self
    }
}

impl ParentElement for AccordionItem {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Sizable for AccordionItem {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for AccordionItem {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for AccordionItem {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let text_size = match self.size {
            Size::XSmall => rems(0.75),
            Size::Large => rems(1.0),
            _ => rems(0.875),
        };
        let progress = spring(
            (self.index, "accordion-panel"),
            if self.open { 1. } else { 0. },
            cx.theme().motion_tokens().spring_control,
            window,
            cx,
        );
        let trigger = AccordionTrigger::new(("trigger", self.index))
            .open(self.open)
            .disabled(self.disabled)
            .h_flex()
            .justify_between()
            .gap_3()
            .font_medium()
            .map(|this| match self.size {
                Size::XSmall => this.py_1().px_1p5(),
                Size::Small => this.py_1p5().px_2(),
                Size::Large => this.py_3().px_4(),
                _ => this.py_2().px_3(),
            })
            .when(self.open, |this| this.text_color(cx.theme().foreground))
            .refine_style(&self.title_style)
            .child(
                h_flex()
                    .flex_1()
                    .min_w_0()
                    .items_center()
                    .map(|this| match self.size {
                        Size::XSmall | Size::Small => this.gap_1(),
                        _ => this.gap_2(),
                    })
                    .when_some(self.icon, |this, icon| {
                        this.child(icon.with_size(self.size))
                    })
                    .child(self.title),
            )
            .when(!self.disabled, |this| {
                this.when_some(self.hover_style, |this, hover_style| {
                    this.hover(move |this| this.refine_style(&hover_style))
                })
                .child(
                    Icon::new(IconName::ChevronDown)
                        .xsmall()
                        .flex_none()
                        .text_color(cx.theme().muted_foreground)
                        .rotate(percentage(if self.open { 0.5 } else { 0. })),
                )
                .when_some(self.on_toggle_click, |this, on_toggle_click| {
                    this.on_change(move |open, _, window, cx| {
                        on_toggle_click(&open, window, cx);
                    })
                })
            });

        div().flex_1().child(
            BaseAccordionItem::new()
                .open(self.open)
                .disabled(self.disabled)
                .header(
                    BaseAccordionHeader::new(trigger)
                        .id(("header", self.index))
                        .w_full(),
                )
                .panel(
                    BaseAccordionPanel::new()
                        .id(("panel", self.index))
                        .open(self.open)
                        // Mounted while the reveal moves; a settled closed panel
                        // unmounts, so its content costs no layout or paint. A
                        // settled spring returns exactly 0, and `!=` keeps a
                        // bouncy theme spring mounted while it dips below 0.
                        // Reduced motion reopens straight to full progress, which
                        // needs the reveal's height from a mounted frame.
                        .keep_mounted(progress != 0. || cx.reduce_motion())
                        .w_full()
                        .child(MotionReveal::new(
                            ("content", self.index),
                            progress,
                            div()
                                .map(|this| match self.size {
                                    Size::XSmall => this.pb_1().px_1p5(),
                                    Size::Small => this.pb_1p5().px_2(),
                                    Size::Large => this.pb_3().px_4(),
                                    _ => this.pb_2().px_3(),
                                })
                                .refine_style(&self.content_style)
                                .children(self.children)
                                .into_any_element(),
                        )),
                )
                .v_flex()
                .w_full()
                .bg(cx.theme().tokens.accordion)
                .overflow_hidden()
                .when(!self.last, |this| {
                    this.border_b_1().border_color(cx.theme().border)
                })
                .text_size(text_size)
                .refine_style(&self.style),
        )
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use gpui::{Context, Render, TestAppContext, div, px};

    use super::*;

    struct Harness;

    impl Render for Harness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Accordion::new("accordion-layout")
                .w(px(240.))
                .h(px(100.))
                .item(|item| {
                    item.open(true)
                        .title(div().debug_selector(|| "first-title".into()).child("First"))
                        .child(div().debug_selector(|| "first-content".into()).h(px(60.)))
                })
                .item(|item| {
                    item.title(
                        div()
                            .debug_selector(|| "second-title".into())
                            .child("Second"),
                    )
                })
        }
    }

    #[gpui::test]
    fn expanded_panel_keeps_content_between_its_header_and_the_next_item(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let (_, cx) = cx.add_window_view(|_, _| Harness);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let first = cx.debug_bounds("first-title").unwrap();
        let content = cx.debug_bounds("first-content").unwrap();
        let second = cx.debug_bounds("second-title").unwrap();
        assert!(first.origin.y < content.origin.y);
        assert!(content.origin.y + content.size.height <= second.origin.y);
    }

    struct Toggle(bool);

    impl Render for Toggle {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Accordion::new("accordion-toggle")
                .w(px(240.))
                .item(|item| {
                    item.open(self.0)
                        .title("Item")
                        .child(div().debug_selector(|| "toggle-content".into()).h(px(60.)))
                })
                .item(|item| item.title("Next"))
        }
    }

    fn content_height(cx: &mut gpui::VisualTestContext) -> Option<gpui::Pixels> {
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.debug_bounds("toggle-content")
            .map(|bounds| bounds.size.height)
    }

    #[gpui::test]
    fn settled_closed_panel_unmounts_its_content(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let (view, cx) = cx.add_window_view(|_, _| Toggle(false));
        assert_eq!(content_height(cx), None);

        view.update(cx, |view, cx| {
            view.0 = true;
            cx.notify();
        });
        assert_eq!(content_height(cx), Some(px(60.)));
        for _ in 0..100 {
            cx.executor().advance_clock(Duration::from_millis(16));
            assert_eq!(content_height(cx), Some(px(60.)));
        }

        // The closing reveal keeps the content until the spring settles.
        view.update(cx, |view, cx| {
            view.0 = false;
            cx.notify();
        });
        let mut closing_frames = 0;
        while content_height(cx).is_some() {
            closing_frames += 1;
            assert!(closing_frames < 100, "closed content stayed mounted");
            cx.executor().advance_clock(Duration::from_millis(16));
        }
        assert!(
            closing_frames > 1,
            "content unmounted before the reveal ran"
        );
    }
}
