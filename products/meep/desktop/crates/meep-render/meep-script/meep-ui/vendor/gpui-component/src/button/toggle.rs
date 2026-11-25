use std::{cell::Cell, rc::Rc, time::Duration};

use gpui::{
    AnyElement, App, Axis, Corners, Edges, ElementId, InteractiveElement, IntoElement,
    ParentElement, RenderOnce, SharedString, StatefulInteractiveElement, StyleRefinement, Styled,
    Window, prelude::FluentBuilder as _, relative,
};
use gpui_base::{Toggle as BaseToggle, ToggleGroup as BaseToggleGroup};
use smallvec::{SmallVec, smallvec};

use crate::{ActiveTheme, Disableable, Icon, Sizable, Size, StyledExt, tooltip::ComponentTooltip};

#[derive(Default, Copy, Debug, Clone, PartialEq, Eq, Hash)]
pub enum ToggleVariant {
    #[default]
    Ghost,
    Outline,
}

pub trait ToggleVariants: Sized {
    /// Set the variant of the toggle.
    fn with_variant(self, variant: ToggleVariant) -> Self;
    /// Set the variant to ghost.
    fn ghost(self) -> Self {
        self.with_variant(ToggleVariant::Ghost)
    }
    /// Set the variant to outline.
    fn outline(self) -> Self {
        self.with_variant(ToggleVariant::Outline)
    }
}

#[derive(IntoElement)]
pub struct Toggle {
    id: ElementId,
    style: StyleRefinement,
    checked: bool,
    size: Size,
    variant: ToggleVariant,
    disabled: bool,
    border_corners: Corners<bool>,
    border_edges: Edges<bool>,
    children: SmallVec<[AnyElement; 1]>,
    on_click: Option<Box<dyn Fn(&bool, &mut Window, &mut App) + 'static>>,
    tooltip: ComponentTooltip,
}

impl Toggle {
    /// Create a new Toggle element.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            checked: false,
            size: Size::default(),
            variant: ToggleVariant::default(),
            disabled: false,
            border_corners: Corners {
                top_left: true,
                top_right: true,
                bottom_left: true,
                bottom_right: true,
            },
            border_edges: Edges::all(true),
            children: smallvec![],
            on_click: None,
            tooltip: ComponentTooltip::default(),
        }
    }

    /// Set tooltip text for the toggle.
    pub fn tooltip(mut self, tooltip: impl Into<SharedString>) -> Self {
        self.tooltip.text = Some((tooltip.into(), None));
        self
    }

    /// Overrides how long the pointer must rest before the tooltip shows.
    ///
    /// Defaults to [`gpui_base::TooltipDefaults::show_delay`].
    pub fn tooltip_show_delay(mut self, delay: Duration) -> Self {
        self.tooltip.show_delay = Some(delay);
        self
    }

    /// Add a label to the toggle.
    pub fn label(mut self, label: impl Into<SharedString>) -> Self {
        let label: SharedString = label.into();
        self.children.push(label.into_any_element());
        self
    }

    /// Add icon to the toggle.
    pub fn icon(mut self, icon: impl Into<Icon>) -> Self {
        let icon: Icon = icon.into();
        self.children.push(icon.into());
        self
    }

    /// Set the checked state of the toggle, default: false
    pub fn checked(mut self, checked: bool) -> Self {
        self.checked = checked;
        self
    }

    /// Set the callback to be called when the toggle is clicked.
    ///
    /// The `&bool` parameter represents the new checked state of the toggle.
    pub fn on_click(mut self, handler: impl Fn(&bool, &mut Window, &mut App) + 'static) -> Self {
        self.on_click = Some(Box::new(handler));
        self
    }

    pub(crate) fn border_corners(mut self, corners: impl Into<Corners<bool>>) -> Self {
        self.border_corners = corners.into();
        self
    }

    pub(crate) fn border_edges(mut self, edges: impl Into<Edges<bool>>) -> Self {
        self.border_edges = edges.into();
        self
    }
}

impl ToggleVariants for Toggle {
    fn with_variant(mut self, variant: ToggleVariant) -> Self {
        self.variant = variant;
        self
    }
}

impl ParentElement for Toggle {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Disableable for Toggle {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl Sizable for Toggle {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for Toggle {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Toggle {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let checked = self.checked;
        let disabled = self.disabled;
        let hoverable = !disabled && !checked;
        let rounding = cx.theme().radius;
        let pressed_background = cx.theme().tokens.accent;
        let pressed_foreground = cx.theme().accent_foreground;
        let instance_style = self.style.clone();

        BaseToggle::new(self.id)
            .pressed(checked)
            .disabled(disabled)
            .when_some(
                self.tooltip.text.as_ref().map(|(text, _)| text.clone()),
                |this, label| this.accessibility_label(label),
            )
            .when_some(self.on_click, |this, on_click| {
                this.on_change(move |next, _, window, cx| on_click(&next, window, cx))
            })
            .flex()
            .flex_row()
            .line_height(relative(1.25))
            .items_center()
            .justify_center()
            .map(|this| match self.size {
                Size::XSmall => this.min_w_5().h_5().px_0p5().text_xs(),
                Size::Small => this.min_w_6().h_6().px_1().text_sm(),
                Size::Large => this.min_w_9().h_9().px_3().text_base(),
                _ => this.min_w_8().h_8().px_2().text_sm(),
            })
            .when(self.border_corners.top_left, |this| {
                this.rounded_tl(rounding)
            })
            .when(self.border_corners.top_right, |this| {
                this.rounded_tr(rounding)
            })
            .when(self.border_corners.bottom_left, |this| {
                this.rounded_bl(rounding)
            })
            .when(self.border_corners.bottom_right, |this| {
                this.rounded_br(rounding)
            })
            .when(self.variant == ToggleVariant::Outline, |this| {
                this.when(self.border_edges.left, |this| this.border_l_1())
                    .when(self.border_edges.right, |this| this.border_r_1())
                    .when(self.border_edges.top, |this| this.border_t_1())
                    .when(self.border_edges.bottom, |this| this.border_b_1())
                    .border_color(cx.theme().border)
                    .bg(cx.theme().tokens.background)
            })
            .when(hoverable, |this| {
                this.hover(|this| {
                    this.bg(cx.theme().tokens.accent)
                        .text_color(cx.theme().accent_foreground)
                })
            })
            .styles(|styles| {
                styles.pressed(|style| {
                    style
                        .bg(pressed_background)
                        .text_color(pressed_foreground)
                        .refine_style(&instance_style)
                })
            })
            .refine_style(&self.style)
            .children(self.children)
            .map(|this| self.tooltip.apply(this))
    }
}

/// A group of toggles.
#[derive(IntoElement)]
pub struct ToggleGroup {
    id: ElementId,
    style: StyleRefinement,
    size: Size,
    variant: ToggleVariant,
    disabled: bool,
    segmented: bool,
    items: Vec<Toggle>,
    on_click: Option<Rc<dyn Fn(&Vec<bool>, &mut Window, &mut App) + 'static>>,
}

impl ToggleGroup {
    /// Create a new ToggleGroup element.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            size: Size::default(),
            variant: ToggleVariant::default(),
            disabled: false,
            segmented: false,
            items: Vec::new(),
            on_click: None,
        }
    }

    /// Add a child [`Toggle`] to the group.
    pub fn child(mut self, toggle: impl Into<Toggle>) -> Self {
        self.items.push(toggle.into());
        self
    }

    /// Add multiple [`Toggle`]s to the group.
    pub fn children(mut self, children: impl IntoIterator<Item = impl Into<Toggle>>) -> Self {
        self.items.extend(children.into_iter().map(Into::into));
        self
    }

    /// Set the callback to be called when the toggle group changes.
    ///
    /// The `&Vec<bool>` parameter represents the new check state of each [`Toggle`] in the group.
    pub fn on_click(
        mut self,
        on_click: impl Fn(&Vec<bool>, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Rc::new(on_click));
        self
    }

    /// Render the group as a connected segmented control.
    ///
    /// This keeps the existing multi-toggle behavior, but removes the default
    /// gap and joins adjacent item borders into a single segmented outline.
    pub fn segmented(mut self) -> Self {
        self.segmented = true;
        self
    }
}

impl Sizable for ToggleGroup {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl ToggleVariants for ToggleGroup {
    fn with_variant(mut self, variant: ToggleVariant) -> Self {
        self.variant = variant;
        self
    }
}

impl Disableable for ToggleGroup {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl Styled for ToggleGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for ToggleGroup {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let disabled = self.disabled;
        let items_len = self.items.len();
        let checks = self
            .items
            .iter()
            .map(|item| item.checked)
            .collect::<Vec<bool>>();
        let clicked_index = Rc::new(Cell::new(None));

        BaseToggleGroup::new(self.id)
            .axis(Axis::Horizontal)
            .child(
                crate::h_flex()
                    .items_center()
                    .when(!self.segmented, |this| this.gap_2())
                    .refine_style(&self.style)
                    .children(self.items.into_iter().enumerate().map({
                        {
                            let clicked_index = clicked_index.clone();
                            move |(ix, item)| {
                                let item = if !self.segmented || items_len == 1 {
                                    item
                                } else if ix == 0 {
                                    item.border_corners(Corners {
                                        top_left: true,
                                        top_right: false,
                                        bottom_left: true,
                                        bottom_right: false,
                                    })
                                    .border_edges(Edges {
                                        left: true,
                                        top: true,
                                        right: true,
                                        bottom: true,
                                    })
                                } else if ix == items_len - 1 {
                                    item.border_corners(Corners {
                                        top_left: false,
                                        top_right: true,
                                        bottom_left: false,
                                        bottom_right: true,
                                    })
                                    .border_edges(Edges {
                                        left: false,
                                        top: true,
                                        right: true,
                                        bottom: true,
                                    })
                                } else {
                                    item.border_corners(Corners {
                                        top_left: false,
                                        top_right: false,
                                        bottom_left: false,
                                        bottom_right: false,
                                    })
                                    .border_edges(Edges {
                                        left: false,
                                        top: true,
                                        right: true,
                                        bottom: true,
                                    })
                                };

                                let effective_disabled = disabled || item.disabled;
                                let clicked_index = clicked_index.clone();
                                item.disabled(effective_disabled)
                                    .with_size(self.size)
                                    .with_variant(self.variant)
                                    .on_click(move |_, _, cx| {
                                        clicked_index.set(Some(ix));
                                        cx.propagate();
                                    })
                            }
                        }
                    })),
            )
            .when_some(
                (!disabled).then_some(self.on_click).flatten(),
                |this, on_click| {
                    this.on_click(move |_, window, cx| {
                        let Some(ix) = clicked_index.take() else {
                            return;
                        };
                        let mut next = checks.clone();
                        next[ix] = !next[ix];
                        on_click(&next, window, cx);
                    })
                },
            )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{IconName, h_flex};
    use gpui::{
        Context, KeyDownEvent, KeyUpEvent, Keystroke, Modifiers, Render,
        StatefulInteractiveElement, TestAppContext, VisualTestContext, point, px,
    };
    use std::cell::{Cell, RefCell};

    struct ToggleHarness {
        disabled: bool,
        changes: Rc<RefCell<Vec<bool>>>,
        parent_clicks: Rc<Cell<usize>>,
    }

    impl Render for ToggleHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let changes = self.changes.clone();
            let parent_clicks = self.parent_clicks.clone();
            h_flex()
                .id("toggle-parent")
                .tab_group()
                .size(px(100.))
                .on_click(move |_, _, _| parent_clicks.set(parent_clicks.get() + 1))
                .child(
                    Toggle::new("toggle")
                        .label("Bold")
                        .disabled(self.disabled)
                        .size_full()
                        .on_click(move |next, _, _| changes.borrow_mut().push(*next)),
                )
        }
    }

    fn harness(
        cx: &mut TestAppContext,
        disabled: bool,
    ) -> (
        &mut VisualTestContext,
        Rc<RefCell<Vec<bool>>>,
        Rc<Cell<usize>>,
    ) {
        cx.update(crate::init);
        let changes = Rc::new(RefCell::new(Vec::new()));
        let parent_clicks = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let changes = changes.clone();
            let parent_clicks = parent_clicks.clone();
            move |_, _| ToggleHarness {
                disabled,
                changes,
                parent_clicks,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, changes, parent_clicks)
    }

    fn activate_key(cx: &mut VisualTestContext, key: &str) {
        let keystroke =
            cx.update(|_, cx| Keystroke::parse_with_os(key, cx.platform_info().os).unwrap());
        cx.simulate_event(KeyDownEvent {
            keystroke: keystroke.clone(),
            is_held: false,
            prefer_character_input: false,
        });
        cx.simulate_event(KeyUpEvent { keystroke });
    }

    #[gpui::test]
    fn canonical_pointer_activation_fires_once_and_focuses(cx: &mut TestAppContext) {
        let (cx, changes, _) = harness(cx, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(changes.borrow().as_slice(), &[true]);
        cx.update(|window, cx| assert!(window.focused(cx).is_some()));
    }

    #[gpui::test]
    fn canonical_toggle_supports_tab_enter_and_space(cx: &mut TestAppContext) {
        let (cx, changes, _) = harness(cx, false);
        cx.update(|window, cx| window.focus_next(cx));
        cx.update(|window, cx| assert!(window.focused(cx).is_some()));
        activate_key(cx, "enter");
        activate_key(cx, "space");
        assert_eq!(changes.borrow().as_slice(), &[true, true]);
    }

    #[gpui::test]
    fn canonical_disabled_toggle_is_inert_and_blocks_parent(cx: &mut TestAppContext) {
        let (cx, changes, parent_clicks) = harness(cx, true);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert!(changes.borrow().is_empty());
        assert_eq!(parent_clicks.get(), 0);
    }

    struct ToggleGroupHarness {
        install_group_callback: bool,
        child_clicks: Rc<Cell<usize>>,
        group_changes: Rc<RefCell<Vec<Vec<bool>>>>,
    }

    impl Render for ToggleGroupHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let child_clicks = self.child_clicks.clone();
            let mut group = ToggleGroup::new("toggle-group")
                .w(px(120.))
                .child(
                    Toggle::new("one")
                        .label("One")
                        .checked(true)
                        .on_click(move |_, _, _| child_clicks.set(child_clicks.get() + 1)),
                )
                .child(Toggle::new("two").label("Two"));
            if self.install_group_callback {
                let changes = self.group_changes.clone();
                group = group.on_click(move |next, _, _| changes.borrow_mut().push(next.clone()));
            }
            group
        }
    }

    fn toggle_group_harness(
        cx: &mut TestAppContext,
        install_group_callback: bool,
    ) -> (
        &mut VisualTestContext,
        Rc<Cell<usize>>,
        Rc<RefCell<Vec<Vec<bool>>>>,
    ) {
        cx.update(crate::init);
        let child_clicks = Rc::new(Cell::new(0));
        let group_changes = Rc::new(RefCell::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let child_clicks = child_clicks.clone();
            let group_changes = group_changes.clone();
            move |_, _| ToggleGroupHarness {
                install_group_callback,
                child_clicks,
                group_changes,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, child_clicks, group_changes)
    }

    #[gpui::test]
    fn legacy_toggle_group_overrides_child_callback_even_without_group_callback(
        cx: &mut TestAppContext,
    ) {
        let (cx, child_clicks, changes) = toggle_group_harness(cx, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(child_clicks.get(), 0);
        assert!(changes.borrow().is_empty());
    }

    #[gpui::test]
    fn legacy_toggle_group_pointer_flips_only_the_clicked_rendered_value(cx: &mut TestAppContext) {
        let (cx, child_clicks, changes) = toggle_group_harness(cx, true);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(child_clicks.get(), 0);
        assert_eq!(changes.borrow().as_slice(), &[vec![false, false]]);
    }

    #[gpui::test]
    fn legacy_toggle_group_keyboard_click_does_not_reach_the_group_callback(
        cx: &mut TestAppContext,
    ) {
        let (cx, child_clicks, changes) = toggle_group_harness(cx, true);
        cx.update(|window, cx| window.focus_next(cx));
        activate_key(cx, "enter");
        assert_eq!(child_clicks.get(), 0);
        assert!(changes.borrow().is_empty());
    }

    #[test]
    fn instance_style_remains_the_final_visual_override() {
        let toggle = Toggle::new("styled").checked(true).opacity(0.37);
        assert_eq!(toggle.style.opacity, Some(0.37));
    }

    #[gpui::test]
    fn test_toggle_builder(_cx: &mut gpui::TestAppContext) {
        let toggle = Toggle::new("complex-toggle")
            .label("Enable Feature")
            .icon(IconName::Check)
            .checked(true)
            .outline()
            .large()
            .disabled(false)
            .on_click(|_, _, _| {});

        assert_eq!(toggle.children.len(), 2); // label + icon
        assert!(toggle.checked);
        assert_eq!(toggle.variant, ToggleVariant::Outline);
        assert_eq!(toggle.size, Size::Large);
        assert!(!toggle.disabled);
        assert!(toggle.on_click.is_some());
    }

    #[gpui::test]
    fn test_toggle_group_builder(_cx: &mut gpui::TestAppContext) {
        let group = ToggleGroup::new("complex-group")
            .child(Toggle::new("toggle1").label("Option 1"))
            .child(Toggle::new("toggle2").label("Option 2").checked(true))
            .child(Toggle::new("toggle3").label("Option 3"))
            .outline()
            .large()
            .segmented()
            .disabled(false)
            .on_click(|_, _, _| {});

        assert_eq!(group.items.len(), 3);
        assert_eq!(group.variant, ToggleVariant::Outline);
        assert_eq!(group.size, Size::Large);
        assert!(group.segmented);
        assert!(!group.disabled);
        assert!(group.on_click.is_some());
    }
}
