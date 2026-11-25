use std::{rc::Rc, time::Duration};

use crate::{
    ActiveTheme, Disableable, IconName, RoleOverride, Selectable, Sizable, Size, icon::IconNamed,
    text::Text, tooltip::ComponentTooltip, v_flex,
};
use crate::{StyleSized as _, StyledExt as _, ThemeStyled as _};
use gpui::{
    AnyElement, App, ElementId, InteractiveElement, IntoElement, MouseButton, ParentElement,
    RenderOnce, SharedString, StatefulInteractiveElement, StyleRefinement, Styled, Window, div,
    prelude::FluentBuilder as _, px, relative, rems, svg,
};
use gpui_base::{CheckboxIndicator, spring};

/// A Checkbox element.
#[derive(IntoElement)]
pub struct Checkbox {
    id: ElementId,
    base: gpui_base::Checkbox,
    style: StyleRefinement,
    // `Text` is legacy presentation state. During render it is composed into
    // the Base Checkbox child seam together with application children.
    label: Option<Text>,
    accessibility_label: Option<SharedString>,
    children: Vec<AnyElement>,
    checked: bool,
    disabled: bool,
    size: Size,
    tab_stop: bool,
    tab_index: isize,
    on_click: Option<Rc<dyn Fn(&bool, &mut Window, &mut App) + 'static>>,
    tooltip: ComponentTooltip,
    role: RoleOverride,
    focus_ring_enabled: bool,
}

impl Checkbox {
    /// Create a new Checkbox with the given id.
    pub fn new(id: impl Into<ElementId>) -> Self {
        let id = id.into();
        Self {
            id: id.clone(),
            base: gpui_base::Checkbox::new(id),
            style: StyleRefinement::default(),
            label: None,
            accessibility_label: None,
            children: Vec::new(),
            checked: false,
            disabled: false,
            size: Size::default(),
            on_click: None,
            tab_stop: true,
            tab_index: 0,
            tooltip: ComponentTooltip::default(),
            role: RoleOverride::default(),
            focus_ring_enabled: true,
        }
    }

    pub fn role(mut self, role: impl Into<RoleOverride>) -> Self {
        self.role = role.into();
        self
    }

    /// Set tooltip text for the checkbox.
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

    /// Set the label for the checkbox.
    pub fn label(mut self, label: impl Into<Text>) -> Self {
        self.label = Some(label.into());
        self
    }

    /// Set the name a screen reader announces, overriding the visible label.
    ///
    /// This does not change the label drawn on screen. A checkbox without a
    /// [`label`](Self::label) or text children has no accessible name, so set this
    /// whenever the checkbox is drawn without visible text.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Set the checked state for the checkbox.
    pub fn checked(mut self, checked: bool) -> Self {
        self.checked = checked;
        self
    }

    /// Alias for [`Self::on_change`]. The last callback registered with either name wins.
    pub fn on_click(self, handler: impl Fn(&bool, &mut Window, &mut App) + 'static) -> Self {
        self.on_change(handler)
    }

    /// Handle a requested checked value from pointer or keyboard activation.
    ///
    /// This is a controlled value: the owner must write the requested value and
    /// call `cx.notify()` to render it. Disabled controls do not call the handler.
    /// This and [`Self::on_click`] share one callback; chaining them replaces
    /// the previous handler instead of calling both.
    pub fn on_change(mut self, handler: impl Fn(&bool, &mut Window, &mut App) + 'static) -> Self {
        self.on_click = Some(Rc::new(handler));
        self
    }

    /// Set the tab stop for the checkbox, default is true.
    pub fn tab_stop(mut self, tab_stop: bool) -> Self {
        self.tab_stop = tab_stop;
        self
    }

    /// Set the tab index for the checkbox, default is 0.
    pub fn tab_index(mut self, tab_index: isize) -> Self {
        self.tab_index = tab_index;
        self
    }
}

impl InteractiveElement for Checkbox {
    fn interactivity(&mut self) -> &mut gpui::Interactivity {
        self.base.interactivity()
    }
}
impl StatefulInteractiveElement for Checkbox {}

impl Styled for Checkbox {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl Disableable for Checkbox {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl crate::FocusableExt for Checkbox {
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_ring_enabled = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_ring_enabled
    }
}

impl Selectable for Checkbox {
    fn selected(self, selected: bool) -> Self {
        self.checked(selected)
    }

    fn is_selected(&self) -> bool {
        self.checked
    }
}

impl ParentElement for Checkbox {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Sizable for Checkbox {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

pub(crate) fn checkbox_check_icon(
    id: ElementId,
    size: Size,
    checked: bool,
    disabled: bool,
    window: &mut Window,
    cx: &mut App,
) -> impl IntoElement {
    // The mark keeps its path while the spring is still fading it out. Guarding
    // the path on `checked` alone unmounted the glyph the moment the box was
    // cleared, so only the fade-in was ever visible.
    let opacity = spring(
        (id, "mark"),
        if checked { 1. } else { 0. },
        cx.theme().motion_tokens().spring_control,
        window,
        cx,
    );
    let color = if disabled {
        cx.theme().primary_foreground.opacity(0.5)
    } else {
        cx.theme().primary_foreground
    };

    svg()
        .absolute()
        .top_px()
        .left_px()
        .map(|this| match size {
            Size::XSmall => this.size_2(),
            Size::Small => this.size_2p5(),
            Size::Medium => this.size_3(),
            Size::Large => this.size_3p5(),
            _ => this.size_3(),
        })
        .text_color(color)
        .when(opacity > 0., |this| {
            this.path(crate::resolve_icon_path(IconName::Check.path(), cx))
                .opacity(opacity)
        })
}

impl RenderOnce for Checkbox {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let checked = self.checked;
        let has_content = self.label.is_some() || !self.children.is_empty();
        let indicator_size = rems(match self.size {
            Size::XSmall => 0.75,
            Size::Small => 0.875,
            Size::Large => 1.125,
            _ => 1.,
        });

        let base = self.base;
        let children = self.children;
        let accessibility_label = self
            .accessibility_label
            .or_else(|| self.label.as_ref().map(|label| label.get_text(cx)));
        let on_click = self.on_click.clone();
        let focus_handle = window
            .use_keyed_state(self.id.clone(), cx, |_, cx| cx.focus_handle())
            .read(cx)
            .clone();
        let is_focused = focus_handle.is_focused(window);

        let unchecked_border = cx.theme().input;
        let checked_color = cx.theme().primary;
        let disabled_indicator_color = if checked {
            checked_color.opacity(0.5)
        } else {
            unchecked_border.opacity(0.5)
        };
        let radius = cx.theme().radius.min(px(4.));
        let disabled_text_color = cx.theme().muted_foreground;
        let instance_style = self.style.clone();
        base.role(self.role)
            .checked(checked)
            .disabled(self.disabled)
            .styles(|styles| {
                styles.disabled(|style| {
                    style
                        .text_color(disabled_text_color)
                        .refine_style(&instance_style)
                })
            })
            .tab_stop(self.tab_stop)
            .tab_index(self.tab_index)
            .track_focus(&focus_handle)
            .when_some(accessibility_label, |this, label| {
                this.accessibility_label(label)
            })
            .when_some(on_click, |this, on_click| {
                this.on_change(move |_, _, window, cx| {
                    window.prevent_default();
                    on_click(&!checked, window, cx);
                })
            })
            .h_flex()
            .gap_2()
            .items_start()
            .line_height(relative(1.))
            .text_color(cx.theme().foreground)
            .map(|this| match self.size {
                Size::Size(_) => this,
                size => this.input_text_size(size),
            })
            .rounded(cx.theme().radius * 0.5)
            .when(is_focused && self.focus_ring_enabled, |this| {
                this.focus_ring_style(window, cx)
            })
            .refine_style(&self.style)
            .child(
                CheckboxIndicator::new()
                    .checked(checked)
                    .disabled(self.disabled)
                    .relative()
                    .size(indicator_size)
                    // Center on the first 1.25em line, including when the label wraps.
                    .when(has_content, |this| this.mt(indicator_size * 0.125))
                    .flex_shrink_0()
                    .border_1()
                    .rounded(radius)
                    .when(!checked, |this| {
                        this.bg(cx.theme().input_background())
                            .when(!self.disabled, |this| this.border_color(unchecked_border))
                    })
                    .styles(|styles| {
                        styles
                            .checked(|style| {
                                style
                                    .border_color(checked_color)
                                    .bg(cx.theme().tokens.primary)
                            })
                            .disabled(|style| {
                                style
                                    .border_color(disabled_indicator_color)
                                    .when(checked, |style| style.bg(disabled_indicator_color))
                            })
                    })
                    .child(checkbox_check_icon(
                        self.id,
                        self.size,
                        checked,
                        self.disabled,
                        window,
                        cx,
                    )),
            )
            .when(self.label.is_some() || !children.is_empty(), |this| {
                this.child(
                    v_flex()
                        .flex_1()
                        .overflow_hidden()
                        .line_height(relative(1.25))
                        .gap_1()
                        .map(|this| {
                            if let Some(label) = self.label {
                                this.child(
                                    div()
                                        .size_full()
                                        .text_color(cx.theme().foreground)
                                        .when(self.disabled, |this| {
                                            this.text_color(cx.theme().muted_foreground)
                                        })
                                        .child(label),
                                )
                            } else {
                                this
                            }
                        })
                        .children(children),
                )
            })
            .on_mouse_down(MouseButton::Left, |_, window, _| {
                // Preserve the legacy Checkbox behavior: pointer presses do
                // not move focus, including while disabled.
                window.prevent_default();
            })
            .map(|this| self.tooltip.apply(this))
    }
}

#[cfg(test)]
mod tests {
    use std::{cell::Cell, rc::Rc};

    use gpui::{
        Context, KeyDownEvent, KeyUpEvent, Keystroke, Modifiers, Render, TestAppContext,
        VisualTestContext, point,
    };

    use super::*;

    #[test]
    fn an_explicit_accessibility_label_replaces_the_visible_one() {
        let plain = Checkbox::new("remember").label("Remember me");
        assert_eq!(plain.accessibility_label, None);

        let named = Checkbox::new("remember")
            .label("Remember me")
            .accessibility_label("Remember this account");
        assert_eq!(
            named.accessibility_label.as_deref(),
            Some("Remember this account"),
            "an explicit name must win over the visible label"
        );
        assert!(
            matches!(named.label.as_ref(), Some(Text::String(label)) if label.as_ref() == "Remember me"),
            "and must not change what is drawn"
        );
    }

    struct CheckboxHarness {
        disabled: bool,
        clicks: Rc<Cell<usize>>,
        parent_clicks: Rc<Cell<usize>>,
    }

    impl Render for CheckboxHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let clicks = self.clicks.clone();
            let parent_clicks = self.parent_clicks.clone();
            div()
                .id("checkbox-parent")
                .tab_group()
                .size(px(100.))
                .on_click(move |_, _, _| parent_clicks.set(parent_clicks.get() + 1))
                .child(
                    Checkbox::new("checkbox")
                        .disabled(self.disabled)
                        .size_full()
                        .on_click(move |checked, _, _| {
                            assert!(*checked);
                            clicks.set(clicks.get() + 1);
                        }),
                )
        }
    }

    fn harness(
        cx: &mut TestAppContext,
        disabled: bool,
    ) -> (&mut VisualTestContext, Rc<Cell<usize>>, Rc<Cell<usize>>) {
        cx.update(crate::init);
        let clicks = Rc::new(Cell::new(0));
        let parent_clicks = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let clicks = clicks.clone();
            let parent_clicks = parent_clicks.clone();
            move |_, _| CheckboxHarness {
                disabled,
                clicks,
                parent_clicks,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, clicks, parent_clicks)
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
    fn facade_pointer_activation_fires_once_without_moving_focus(cx: &mut TestAppContext) {
        let (cx, clicks, _) = harness(cx, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        assert_eq!(clicks.get(), 1);
        cx.update(|window, cx| assert!(window.focused(cx).is_none()));
    }

    #[gpui::test]
    fn facade_supports_tab_enter_and_space(cx: &mut TestAppContext) {
        let (cx, clicks, _) = harness(cx, false);
        cx.update(|window, cx| window.focus_next(cx));
        cx.update(|window, cx| assert!(window.focused(cx).is_some()));

        activate_key(cx, "enter");
        activate_key(cx, "space");

        assert_eq!(clicks.get(), 2);
    }

    #[gpui::test]
    fn facade_disabled_is_inert_and_pointer_activation_bubbles(cx: &mut TestAppContext) {
        let (cx, clicks, parent_clicks) = harness(cx, true);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        assert_eq!(clicks.get(), 0);
        assert_eq!(parent_clicks.get(), 1);
        cx.update(|window, cx| assert!(window.focused(cx).is_none()));
    }

    #[gpui::test]
    fn facade_prepaints_label_and_custom_content_through_the_base_slot(cx: &mut TestAppContext) {
        struct ContentHarness;

        impl Render for ContentHarness {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                Checkbox::new("content-checkbox")
                    .label("Remember me")
                    .child(
                        div()
                            .debug_selector(|| "checkbox-custom-content".into())
                            .child("Additional detail"),
                    )
            }
        }

        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| ContentHarness);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let bounds = cx
            .debug_bounds("checkbox-custom-content")
            .expect("custom content must prepaint through the Base child seam");
        assert!(bounds.size.width > px(0.));
        assert!(bounds.size.height > px(0.));
    }

    #[gpui::test]
    fn the_check_mark_asks_the_icon_resolver_for_its_path(cx: &mut TestAppContext) {
        struct CheckedHarness;

        impl Render for CheckedHarness {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                Checkbox::new("checked").checked(true)
            }
        }

        let asked = Rc::new(std::cell::RefCell::new(Vec::<String>::new()));
        cx.update(|cx| {
            crate::init(cx);
            cx.set_reduce_motion(true);
            let asked = asked.clone();
            crate::set_icon_resolver(cx, move |path, _| {
                asked.borrow_mut().push(path.to_string());
                None
            });
        });
        let (_, cx) = cx.add_window_view(|_, _| CheckedHarness);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert!(
            asked.borrow().contains(&IconName::Check.path().to_string()),
            "the check mark must be drawn from the resolved path"
        );
    }
}
