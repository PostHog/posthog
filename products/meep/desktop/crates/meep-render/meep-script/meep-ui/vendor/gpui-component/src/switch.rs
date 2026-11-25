use crate::{
    ActiveTheme, Disableable, FocusableExt, Side, Sizable, Size, StyleSized as _, StyledExt,
    ThemeStyled as _, text::Text, tooltip::ComponentTooltip,
};
use gpui::{
    App, Background, ElementId, Hsla, InteractiveElement, IntoElement, ParentElement as _,
    RenderOnce, SharedString, StyleRefinement, Styled, Window, div, prelude::FluentBuilder as _,
    px,
};
use gpui_base::{Switch as BaseSwitch, SwitchThumb, SwitchTrack, spring};
use std::{rc::Rc, time::Duration};

/// A Switch element that can be toggled on or off.
#[derive(IntoElement)]
pub struct Switch {
    id: ElementId,
    style: StyleRefinement,
    checked: bool,
    disabled: bool,
    label: Option<Text>,
    /// The announced name, when the visible label is not it.
    accessibility_label: Option<SharedString>,
    label_side: Side,
    on_click: Option<Rc<dyn Fn(&bool, &mut Window, &mut App)>>,
    size: Size,
    color: Option<Hsla>,
    tooltip: ComponentTooltip,
    tab_stop: bool,
    tab_index: isize,
    focus_ring_enabled: bool,
}

impl Switch {
    /// Create a new Switch element.
    pub fn new(id: impl Into<ElementId>) -> Self {
        let id: ElementId = id.into();
        Self {
            id: id.clone(),
            style: StyleRefinement::default(),
            checked: false,
            disabled: false,
            label: None,
            accessibility_label: None,
            on_click: None,
            label_side: Side::Right,
            size: Size::Medium,
            color: None,
            tooltip: ComponentTooltip::default(),
            tab_stop: true,
            tab_index: 0,
            focus_ring_enabled: true,
        }
    }

    /// Set the checked state of the switch.
    pub fn checked(mut self, checked: bool) -> Self {
        self.checked = checked;
        self
    }

    /// Set the label of the switch.
    pub fn label(mut self, label: impl Into<Text>) -> Self {
        self.label = Some(label.into());
        self
    }

    /// Set the name a screen reader announces, when the visible label is not
    /// it.
    ///
    /// A switch's name comes from its [`label`](Self::label) by default.
    /// Setting this replaces the announced name without changing what is
    /// displayed. A switch without a label has no accessible name, so set this
    /// whenever the switch is drawn without visible text.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Alias for [`Self::on_change`]. The last callback registered with either name wins.
    pub fn on_click<F>(self, handler: F) -> Self
    where
        F: Fn(&bool, &mut Window, &mut App) + 'static,
    {
        self.on_change(handler)
    }

    /// Handle a requested checked value from pointer or keyboard activation.
    ///
    /// This is a controlled value: the owner must write the requested value and
    /// call `cx.notify()` to render it. Disabled controls do not call the handler.
    /// This and [`Self::on_click`] share one callback; chaining them replaces
    /// the previous handler instead of calling both.
    pub fn on_change<F>(mut self, handler: F) -> Self
    where
        F: Fn(&bool, &mut Window, &mut App) + 'static,
    {
        self.on_click = Some(Rc::new(handler));
        self
    }

    /// Set the background color of the switch when checked.
    /// Defaults to `cx.theme().primary`.
    pub fn color(mut self, color: impl Into<Hsla>) -> Self {
        self.color = Some(color.into());
        self
    }

    /// Set tooltip text for the switch.
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

    /// Set whether the switch participates in keyboard focus traversal,
    /// default is true.
    pub fn tab_stop(mut self, tab_stop: bool) -> Self {
        self.tab_stop = tab_stop;
        self
    }

    /// Set the focus traversal index within a GPUI tab group, default is 0.
    pub fn tab_index(mut self, tab_index: isize) -> Self {
        self.tab_index = tab_index;
        self
    }
}

impl Styled for Switch {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl Sizable for Switch {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Disableable for Switch {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl FocusableExt for Switch {
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_ring_enabled = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_ring_enabled
    }
}

impl RenderOnce for Switch {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let checked = self.checked;
        let on_click = self.on_click.clone();
        let accessibility_label = self
            .accessibility_label
            .clone()
            .or_else(|| self.label.as_ref().map(|label| label.get_text(cx)));
        let focus_handle = window
            .use_keyed_state(self.id.clone(), cx, |_, cx| cx.focus_handle())
            .read(cx)
            .clone();
        let is_focused = focus_handle.is_focused(window);

        let checked_bg = self
            .color
            .map(Background::from)
            .unwrap_or(cx.theme().tokens.primary.into());
        let unchecked_bg: Background = cx.theme().tokens.switch.into();
        // GPUI's element opacity multiplies each primitive's alpha instead of
        // compositing the subtree as one group, so fading the whole control
        // would let the track show through the thumb. Fading the track alone
        // lands on the pixels a grouped fade would: the thumb is `background`.
        let disabled_bg = if checked { checked_bg } else { unchecked_bg }.opacity(0.5);
        let toggle_bg: Background = cx.theme().tokens.switch_thumb.into();
        let disabled_label_color = cx.theme().muted_foreground;

        let (bg_width, bg_height) = match self.size {
            Size::XSmall | Size::Small => (px(28.), px(16.)),
            Size::Large => (px(44.), px(24.)),
            _ => (px(36.), px(20.)),
        };
        let bar_width = match self.size {
            Size::XSmall | Size::Small => px(12.),
            Size::Large => px(20.),
            _ => px(16.),
        };
        let inset = px(2.);
        let radius = if cx.theme().radius >= px(4.) {
            bg_height
        } else {
            cx.theme().radius
        };

        // The thumb's position is geometry, not a semantic state style: a
        // `checked` style setting `left` outranks the instance style by the
        // documented precedence, which left the travel visible in one direction
        // only. The spring owns it end to end and reverses from wherever the
        // thumb is when the switch is toggled again mid-travel.
        let thumb_x = spring(
            (self.id.clone(), "thumb"),
            if checked {
                bg_width - bar_width - inset * 2
            } else {
                px(0.)
            },
            cx.theme().motion_tokens().spring_move,
            window,
            cx,
        );

        div().refine_style(&self.style).child(
            BaseSwitch::new(self.id.clone())
                .checked(checked)
                .disabled(self.disabled)
                .styles(|styles| {
                    styles.disabled(|style| {
                        style.text_color(disabled_label_color).cursor_not_allowed()
                    })
                })
                .when_some(accessibility_label, |this, label| {
                    this.accessibility_label(label)
                })
                .when_some(on_click, |this, on_click| {
                    this.on_change(move |next, _, window, cx| on_click(&next, window, cx))
                })
                .tab_stop(self.tab_stop)
                .tab_index(self.tab_index)
                .track_focus(&focus_handle)
                .h_flex()
                .gap_2()
                .items_start()
                .when(self.label_side.is_left(), |this| this.flex_row_reverse())
                .child(
                    // Switch Bar
                    SwitchTrack::new((self.id.clone(), "track"))
                        .checked(checked)
                        .disabled(self.disabled)
                        .when(cfg!(test), |this| {
                            this.debug_selector(|| "switch-bar".into())
                        })
                        .w(bg_width)
                        .h(bg_height)
                        .flex_shrink_0()
                        .rounded(radius)
                        .flex()
                        .items_center()
                        // The thumb inset is a 1px border plus 1px padding,
                        // not a 2px border: the focus ring tints the border
                        // solid, and that 1px line is what keeps the ring
                        // visible on an unchecked track. Its 50% halo alone
                        // lands within a few values of `switch.background`
                        // in both default modes.
                        .border_1()
                        .border_color(cx.theme().transparent)
                        .p(inset - px(1.))
                        .when(!checked, |this| this.bg(unchecked_bg))
                        .styles(|styles| {
                            styles
                                .checked(|style| style.bg(checked_bg))
                                .disabled(|style| style.bg(disabled_bg))
                        })
                        // The ring hugs the track, not the row, so the label
                        // stays outside it.
                        .when(is_focused && self.focus_ring_enabled, |this| {
                            this.focus_ring_style(window, cx)
                        })
                        .map(|this| self.tooltip.apply(this))
                        .child(
                            // Switch Toggle
                            SwitchThumb::new(checked)
                                .rounded(radius)
                                .size(bar_width)
                                .left(thumb_x)
                                .bg(toggle_bg),
                        ),
                )
                .when_some(self.label, |this, label| {
                    this.child(
                        div()
                            .when(cfg!(test), |this| {
                                this.debug_selector(|| "switch-label".into())
                            })
                            .min_w_0()
                            .line_height(bg_height)
                            .child(label)
                            .map(|this| match self.size {
                                Size::Size(_) => this.input_text_size(Size::Medium),
                                size => this.input_text_size(size),
                            }),
                    )
                }),
        )
    }
}

#[cfg(test)]
mod tests {
    use std::{cell::Cell, rc::Rc};

    use gpui::{
        Context, KeyDownEvent, KeyUpEvent, Keystroke, Modifiers, Render,
        StatefulInteractiveElement as _, TestAppContext, VisualTestContext, point,
    };

    use super::*;

    #[test]
    fn an_explicit_accessibility_label_replaces_the_visible_one() {
        let plain = Switch::new("wifi").label("Wi-Fi");
        assert_eq!(plain.accessibility_label, None);
        assert!(matches!(
            &plain.label,
            Some(Text::String(label)) if label.as_ref() == "Wi-Fi"
        ));

        let named = Switch::new("wifi")
            .label("Wi-Fi")
            .accessibility_label("Toggle Wi-Fi");
        assert_eq!(
            named.accessibility_label.as_deref(),
            Some("Toggle Wi-Fi"),
            "an explicit name must win over the visible label"
        );
        assert!(
            matches!(
                &named.label,
                Some(Text::String(label)) if label.as_ref() == "Wi-Fi"
            ),
            "and must not change what is drawn"
        );
    }

    struct SwitchHarness {
        disabled: bool,
        toggles: Rc<Cell<usize>>,
        parent_clicks: Rc<Cell<usize>>,
    }

    impl Render for SwitchHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let toggles = self.toggles.clone();
            let parent_clicks = self.parent_clicks.clone();
            div()
                .id("switch-parent")
                .tab_group()
                .size(px(100.))
                .on_click(move |_, _, _| parent_clicks.set(parent_clicks.get() + 1))
                .child(Switch::new("switch").disabled(self.disabled).on_click(
                    move |checked, _, _| {
                        assert!(*checked);
                        toggles.set(toggles.get() + 1);
                    },
                ))
        }
    }

    fn harness(
        cx: &mut TestAppContext,
        disabled: bool,
    ) -> (&mut VisualTestContext, Rc<Cell<usize>>, Rc<Cell<usize>>) {
        cx.update(crate::init);
        let toggles = Rc::new(Cell::new(0));
        let parent_clicks = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let toggles = toggles.clone();
            let parent_clicks = parent_clicks.clone();
            move |_, _| SwitchHarness {
                disabled,
                toggles,
                parent_clicks,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, toggles, parent_clicks)
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
        let (cx, toggles, _) = harness(cx, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        assert_eq!(toggles.get(), 1);
        cx.update(|window, cx| assert!(window.focused(cx).is_some()));
    }

    #[gpui::test]
    fn canonical_switch_supports_tab_enter_and_space(cx: &mut TestAppContext) {
        let (cx, toggles, _) = harness(cx, false);
        cx.update(|window, cx| window.focus_next(cx));
        cx.update(|window, cx| assert!(window.focused(cx).is_some()));

        activate_key(cx, "enter");
        activate_key(cx, "space");

        assert_eq!(toggles.get(), 2);
    }

    #[gpui::test]
    fn canonical_disabled_switch_is_inert_and_blocks_parent(cx: &mut TestAppContext) {
        let (cx, toggles, parent_clicks) = harness(cx, true);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        assert_eq!(toggles.get(), 0);
        assert_eq!(parent_clicks.get(), 0);
        cx.update(|window, cx| assert!(window.focused(cx).is_none()));
    }

    struct FocusRingHarness {
        disabled: bool,
        focus_ring: bool,
    }

    impl Render for FocusRingHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().id("switch-parent").tab_group().size(px(100.)).child(
                Switch::new("switch")
                    .label("Airplane mode")
                    .disabled(self.disabled)
                    .focus_ring(self.focus_ring),
            )
        }
    }

    fn focus_ring_harness(
        cx: &mut TestAppContext,
        disabled: bool,
        focus_ring: bool,
    ) -> &mut VisualTestContext {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(move |_, _| FocusRingHarness {
            disabled,
            focus_ring,
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx
    }

    #[gpui::test]
    fn focus_ring_hugs_the_track_when_the_switch_is_focused(cx: &mut TestAppContext) {
        let cx = focus_ring_harness(cx, false, true);
        assert!(
            cx.debug_bounds("focus-ring").is_none(),
            "an unfocused switch draws no ring"
        );

        cx.update(|window, cx| window.focus_next(cx));
        cx.update(|window, cx| {
            assert!(window.focused(cx).is_some());
            window.draw(cx).clear(cx);
        });

        let ring = cx
            .debug_bounds("focus-ring")
            .expect("a focused switch must draw its focus ring");
        let bar = cx.debug_bounds("switch-bar").unwrap();
        let label = cx.debug_bounds("switch-label").unwrap();
        assert!(ring.contains(&bar.origin), "the ring surrounds the track");
        assert!(
            ring.right() < label.origin.x,
            "the ring hugs the track and leaves the label outside"
        );
    }

    #[gpui::test]
    fn focus_ring_can_be_turned_off(cx: &mut TestAppContext) {
        let cx = focus_ring_harness(cx, false, false);
        cx.update(|window, cx| window.focus_next(cx));
        cx.update(|window, cx| {
            assert!(window.focused(cx).is_some());
            window.draw(cx).clear(cx);
        });

        assert!(
            cx.debug_bounds("focus-ring").is_none(),
            "`focus_ring(false)` must not draw a ring"
        );
    }

    #[gpui::test]
    fn disabled_switch_takes_no_focus_and_draws_no_ring(cx: &mut TestAppContext) {
        let cx = focus_ring_harness(cx, true, true);
        cx.update(|window, cx| window.focus_next(cx));
        cx.update(|window, cx| {
            assert!(window.focused(cx).is_none());
            window.draw(cx).clear(cx);
        });

        assert!(cx.debug_bounds("focus-ring").is_none());
    }

    #[gpui::test]
    fn long_labels_preserve_track_size_in_narrow_containers(cx: &mut TestAppContext) {
        struct NarrowSwitch {
            size: Size,
            checked: bool,
            disabled: bool,
        }

        impl Render for NarrowSwitch {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .w(px(160.))
                    .debug_selector(|| "narrow-switch".into())
                    .child(
                        Switch::new("switch")
                            .with_size(self.size)
                            .checked(self.checked)
                            .disabled(self.disabled)
                            .label("Automatically transcribe downloaded episodes"),
                    )
            }
        }

        cx.update(crate::init);
        for (size, width, height) in [
            (Size::Small, 28., 16.),
            (Size::Medium, 36., 20.),
            (Size::Large, 44., 24.),
        ] {
            for checked in [false, true] {
                for disabled in [false, true] {
                    let (_, cx) = cx.add_window_view(move |_, _| NarrowSwitch {
                        size,
                        checked,
                        disabled,
                    });
                    cx.update(|window, cx| window.draw(cx).clear(cx));

                    let container = cx.debug_bounds("narrow-switch").unwrap();
                    let track = cx.debug_bounds("switch-bar").unwrap();
                    let label = cx.debug_bounds("switch-label").unwrap();
                    assert_eq!(track.size.width, px(width), "the track must not shrink");
                    assert_eq!(track.size.height, px(height));
                    assert!(label.origin.x >= track.right());
                    assert!(label.right() <= container.right());
                    assert!(label.size.height > track.size.height, "the label must wrap");
                }
            }
        }
    }

    #[gpui::test]
    fn label_prepaints_with_the_base_switch_content(cx: &mut TestAppContext) {
        struct LabelHarness;

        impl Render for LabelHarness {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div()
                    .debug_selector(|| "labeled-switch".into())
                    .child(Switch::new("switch").label("Airplane mode"))
            }
        }

        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| LabelHarness);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let bounds = cx
            .debug_bounds("labeled-switch")
            .expect("the complete labeled Switch must participate in prepaint");
        assert!(bounds.size.width > px(36.));
        let bar = cx
            .debug_bounds("switch-bar")
            .expect("the Switch bar must participate in prepaint");
        let label = cx
            .debug_bounds("switch-label")
            .expect("the Switch label must participate in prepaint");
        assert_eq!(bar.origin.y, label.origin.y);
    }
}
