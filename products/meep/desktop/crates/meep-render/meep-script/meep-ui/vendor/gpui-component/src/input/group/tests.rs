use super::*;
use crate::input::{InputState, TextareaState};
use gpui::{AppContext as _, TestAppContext};

#[test]
fn validation_takes_precedence_over_focus_and_remains_visible_when_disabled() {
    for mode in [crate::ThemeMode::Light, crate::ThemeMode::Dark] {
        let theme = crate::Theme {
            mode,
            ..Default::default()
        };
        let focused = GroupAppearance::new(&theme, true, false, false);
        assert_eq!(focused.border, theme.ring);
        assert_eq!(focused.ring, Some(theme.ring.opacity(0.5)));

        let disabled = GroupAppearance::new(&theme, true, true, false);
        assert_eq!(disabled.border, theme.input);
        assert_eq!(disabled.ring, None);

        for focused in [false, true] {
            for disabled in [false, true] {
                let invalid = GroupAppearance::new(&theme, focused, disabled, true);
                assert_eq!(invalid.border, theme.danger);
                assert_eq!(
                    invalid.ring,
                    Some(
                        theme
                            .danger
                            .opacity(if theme.is_dark() { 0.4 } else { 0.2 })
                    )
                );
            }
        }
    }
}

#[gpui::test]
fn test_input_group_builder(cx: &mut TestAppContext) {
    cx.update(crate::init);
    cx.add_window(|window, cx| {
        let input = cx.new(|cx| InputState::new(window, cx));
        let textarea = cx.new(|cx| TextareaState::new(window, cx));
        let group = InputGroup::new("group")
            .input(InputGroupInput::new(&input).aria_label("Replaced input"))
            .input(
                InputGroupTextarea::new(&textarea)
                    .aria_label("Message")
                    .readonly(true),
            )
            .disabled(true)
            .invalid(true)
            .small()
            .addon(
                InputGroupAddon::new("footer")
                    .align(InputGroupAddonAlignment::BlockEnd)
                    .child(InputGroupText::new().child("Help"))
                    .child(InputGroupButton::new("send").primary().label("Send")),
            );
        assert_eq!(
            group.control.as_ref().unwrap().state().entity_id(),
            textarea.entity_id()
        );
        assert!(group.disabled && group.invalid);
        assert_eq!(group.size, Size::Small);
        assert_eq!(group.addons[0].children.len(), 2);
        assert_eq!(
            group.addons[0].alignment,
            InputGroupAddonAlignment::BlockEnd
        );

        let button = InputGroupButton::new("icon")
            .icon(crate::IconName::Copy)
            .small();
        assert_eq!(button.size, Size::Small);
        assert!(button.button.is_icon_only());
        assert!(matches!(button.button.variant(), ButtonVariant::Ghost));
        gpui::Empty
    });
}

#[cfg(feature = "test-support")]
mod interaction {
    use super::*;
    use crate::{Root, WindowExt as _};
    use gpui::{
        ClipboardEntry, ClipboardItem, Context, Entity, EntityInputHandler as _, FocusHandle,
        InputEvent as _, LongPressEvent, Modifiers, Render, TouchPhase, VisualTestContext, point,
        px,
    };
    use gpui_base::test_support::{ElementSnapshot, find};
    use std::rc::Rc;

    struct Probe {
        input: Entity<InputState>,
        textarea: Entity<TextareaState>,
        other: FocusHandle,
        multiline: bool,
        disabled: bool,
        readonly: bool,
        invalid: bool,
        clicks: usize,
        control_style: StyleRefinement,
        width: gpui::DefiniteLength,
        paste_handler: Option<Rc<dyn Fn(&ClipboardItem, &mut Window, &mut App) -> bool>>,
    }

    impl Render for Probe {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            div().p_4().child(div().track_focus(&self.other)).child(
                InputGroup::new("group")
                    .w(self.width)
                    .disabled(self.disabled)
                    .readonly(self.readonly)
                    .invalid(self.invalid)
                    .map(|group| {
                        if self.multiline {
                            group.input(
                                InputGroupTextarea::new(&self.textarea)
                                    .aria_label("Message")
                                    .when_some(self.paste_handler.clone(), |input, handler| {
                                        input.on_paste(move |item, window, cx| {
                                            handler(item, window, cx)
                                        })
                                    })
                                    .refine_style(&self.control_style),
                            )
                        } else {
                            group.input(
                                InputGroupInput::new(&self.input)
                                    .aria_label("Address")
                                    .when_some(self.paste_handler.clone(), |input, handler| {
                                        input.on_paste(move |item, window, cx| {
                                            handler(item, window, cx)
                                        })
                                    })
                                    .refine_style(&self.control_style),
                            )
                        }
                    })
                    // Deliberately supply parts in reverse visual order.
                    .addon(
                        InputGroupAddon::new("end")
                            .align(InputGroupAddonAlignment::InlineEnd)
                            .child(InputGroupButton::new("action").label("Run").on_click(
                                cx.listener(|this, _, window, cx| {
                                    this.clicks += 1;
                                    this.other.focus(window, cx);
                                    cx.notify();
                                }),
                            )),
                    )
                    .addon(
                        InputGroupAddon::new("start")
                            .child(InputGroupText::new().child("https://")),
                    )
                    .when(self.multiline, |group| {
                        group
                            .addon(
                                InputGroupAddon::new("footer")
                                    .align(InputGroupAddonAlignment::BlockEnd)
                                    .child("Footer"),
                            )
                            .addon(
                                InputGroupAddon::new("header")
                                    .align(InputGroupAddonAlignment::BlockStart)
                                    .child("Header"),
                            )
                    }),
            )
        }
    }

    fn mount(cx: &mut TestAppContext, multiline: bool) -> (Entity<Probe>, VisualTestContext) {
        cx.update(crate::init);
        let captured = Rc::new(std::cell::RefCell::new(None));
        let capture = captured.clone();
        let window = cx.add_window(move |window, cx| {
            let probe = cx.new(|cx| Probe {
                input: cx.new(|cx| InputState::new(window, cx)),
                textarea: cx.new(|cx| TextareaState::new(window, cx).auto_grow(1, 6)),
                other: cx.focus_handle(),
                multiline,
                disabled: false,
                readonly: false,
                invalid: false,
                clicks: 0,
                control_style: StyleRefinement::default(),
                width: rems(20.).into(),
                paste_handler: None,
            });
            *capture.borrow_mut() = Some(probe.clone());
            Root::new(probe, window, cx)
        });
        let probe = captured.borrow().clone().unwrap();
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        draw(&mut cx);
        (probe, cx)
    }

    fn draw(cx: &mut VisualTestContext) {
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
    }

    fn snapshot(cx: &mut VisualTestContext, id: impl Into<ElementId>) -> ElementSnapshot {
        let id = id.into();
        cx.update(|window, _| find(window, &[], &id).unwrap_or_else(|| panic!("missing {id:?}")))
    }

    fn click(cx: &mut VisualTestContext, id: &'static str) {
        let bounds = snapshot(cx, id).bounds();
        cx.simulate_click(bounds.center(), Modifiers::default());
        draw(cx);
    }

    #[gpui::test]
    fn paste_hooks_receive_payloads_and_respect_editability(cx: &mut TestAppContext) {
        for multiline in [false, true] {
            let (probe, mut cx) = mount(cx, multiline);
            let state: crate::input::state::TextInputState = probe.read_with(&cx, |probe, _| {
                if multiline {
                    probe.textarea.clone().into()
                } else {
                    probe.input.clone().into()
                }
            });
            let received = Rc::new(std::cell::RefCell::new(Vec::new()));
            probe.update(&mut cx, |probe, cx| {
                let received = received.clone();
                probe.paste_handler = Some(Rc::new(move |item, _, _| {
                    received.borrow_mut().push(item.clone());
                    item.entries().iter().any(|entry| {
                        matches!(
                            entry,
                            ClipboardEntry::Image(_) | ClipboardEntry::ExternalPaths(_)
                        )
                    })
                }));
                cx.notify();
            });
            draw(&mut cx);
            cx.update(|window, cx| state.focus(window, cx));
            draw(&mut cx);
            let payloads = [
                ClipboardItem {
                    entries: vec![
                        ClipboardEntry::Image(gpui::Image::empty()),
                        ClipboardEntry::String(gpui::ClipboardString::new("image caption".into())),
                    ],
                },
                ClipboardItem {
                    entries: vec![ClipboardEntry::ExternalPaths(gpui::ExternalPaths(
                        vec!["attachment.png".into()].into(),
                    ))],
                },
                ClipboardItem::new_string("text".into()),
            ];
            for (ix, payload) in payloads.iter().enumerate() {
                cx.update(|window, cx| {
                    cx.write_to_clipboard(payload.clone());
                    window.dispatch_action(Box::new(crate::input::Paste), cx);
                });
                draw(&mut cx);
                assert_eq!(&*received.borrow(), &payloads[..=ix]);
                assert_eq!(
                    cx.update(|_, cx| state.text(cx).to_string()),
                    if ix < 2 { "" } else { "text" }
                );
            }
            for (disabled, readonly) in [(true, false), (false, true)] {
                probe.update(&mut cx, |probe, cx| {
                    probe.disabled = disabled;
                    probe.readonly = readonly;
                    cx.notify();
                });
                draw(&mut cx);
                cx.update(|window, cx| window.dispatch_action(Box::new(crate::input::Paste), cx));
                draw(&mut cx);
                assert_eq!(received.borrow().len(), 3);
                assert_eq!(cx.update(|_, cx| state.text(cx).to_string()), "text");
            }
            probe.update(&mut cx, |probe, cx| {
                probe.readonly = false;
                probe.paste_handler = None;
                cx.notify();
            });
            draw(&mut cx);
            cx.update(|window, cx| window.dispatch_action(Box::new(crate::input::Paste), cx));
            draw(&mut cx);
            assert_eq!(received.borrow().len(), 3);
            assert_eq!(cx.update(|_, cx| state.text(cx).to_string()), "texttext");
        }
    }

    #[gpui::test]
    fn long_press_shows_edit_menu_and_copy_keeps_the_text(cx: &mut TestAppContext) {
        for multiline in [false, true] {
            let (probe, mut cx) = mount(cx, multiline);
            cx.update(|window, cx| {
                if multiline {
                    let state = probe.read(cx).textarea.clone();
                    state.update(cx, |state, cx| {
                        state.set_value("quick select value", window, cx)
                    });
                } else {
                    let state = probe.read(cx).input.clone();
                    state.update(cx, |state, cx| {
                        state.set_value("quick select value", window, cx)
                    });
                }
            });
            draw(&mut cx);
            let bounds = probe
                .read_with(&cx, |probe, cx| {
                    if multiline {
                        probe.textarea.read(cx).range_to_bounds(&(0..1))
                    } else {
                        probe.input.read(cx).range_to_bounds(&(0..1))
                    }
                })
                .unwrap();
            let position = bounds.center();
            for phase in [TouchPhase::Started, TouchPhase::Ended] {
                cx.update(|window, cx| {
                    window.dispatch_event(
                        LongPressEvent {
                            phase,
                            start_position: position,
                            position,
                        }
                        .to_platform_input(),
                        cx,
                    );
                });
                draw(&mut cx);
            }
            for command in ["Cut", "Copy", "Paste", "Select All"] {
                assert!(snapshot(&mut cx, command).visible());
            }
            click(&mut cx, "Copy");
            assert_eq!(
                cx.update(|_, cx| cx.read_from_clipboard().and_then(|item| item.text())),
                Some("quick".into())
            );
            assert!(cx.update(|window, _| find(window, &[], &"Copy".into()).is_none()));
            assert_eq!(
                probe.read_with(&cx, |probe, cx| {
                    if multiline {
                        probe.textarea.read(cx).value()
                    } else {
                        probe.input.read(cx).value()
                    }
                }),
                "quick select value"
            );
        }
    }

    #[gpui::test]
    fn editor_overrides_preserve_caret_selection_and_ime_geometry(cx: &mut TestAppContext) {
        let (probe, mut cx) = mount(cx, false);
        let state = probe.read_with(&cx, |probe, _| probe.input.clone());
        click(&mut cx, "start");
        cx.simulate_input("Ada 中文");
        probe.update(&mut cx, |probe, cx| {
            probe.control_style = StyleRefinement::default().px(px(24.)).py_0().text_lg();
            cx.notify();
        });
        draw(&mut cx);
        let frame = snapshot(&mut cx, ("input", state.entity_id())).bounds();
        let text = state.read_with(&cx, |state, _| state.text_bounds().unwrap());
        assert!((text.left() - frame.left() - px(24.)).abs() <= px(1.));
        cx.simulate_click(
            point(text.left() + px(0.5), text.center().y),
            Modifiers::default(),
        );
        draw(&mut cx);
        assert_eq!(state.read_with(&cx, |state, _| state.cursor()), 0);
        let range = state.read_with(&cx, |state, _| state.range_to_bounds(&(4..7)).unwrap());
        let ime = cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state.bounds_for_range(4..5, text, window, cx).unwrap()
            })
        });
        assert_eq!(
            range, ime,
            "UTF-16 IME bounds must match the actual glyph bounds"
        );
        state.update(&mut cx, |state, cx| state.set_selected_range(4..7, cx));
        cx.simulate_input("文");
        draw(&mut cx);
        assert_eq!(state.read_with(&cx, |state, _| state.value()), "Ada 文文");
    }

    #[gpui::test]
    fn textarea_keeps_scrolling_native_between_block_addons(cx: &mut TestAppContext) {
        let (probe, mut cx) = mount(cx, true);
        let state = probe.read_with(&cx, |probe, _| probe.textarea.clone());
        click(&mut cx, "header");
        cx.simulate_input("One\nTwo\nThree\nFour\nFive\nSix\nSeven\nEight");
        draw(&mut cx);
        assert!(state.read_with(&cx, |state, _| state.scroll_offset().y < px(0.)));
        let (caret, viewport) = state.read_with(&cx, |state, _| {
            // cursor_layout keeps y in content coordinates; the native painter
            // applies the vertical scroll offset when painting the caret.
            let mut caret = state.cursor_layout().unwrap().0;
            caret.origin.y += state.scroll_offset().y;
            (caret, state.input_bounds())
        });
        assert!(
            caret.top() >= viewport.top() - px(1.) && caret.bottom() <= viewport.bottom() + px(1.),
            "caret {caret:?}, viewport {viewport:?}"
        );
        cx.update(|window, cx| {
            window.dispatch_action(Box::new(crate::input::SelectAll), cx);
            window.dispatch_action(Box::new(crate::input::Copy), cx);
        });
        assert_eq!(
            cx.update(|_, cx| cx.read_from_clipboard().and_then(|item| item.text())),
            Some("One\nTwo\nThree\nFour\nFive\nSix\nSeven\nEight".into())
        );
    }

    #[gpui::test]
    fn addon_focus_editing_and_button_actions_use_the_retained_state(cx: &mut TestAppContext) {
        let (probe, mut cx) = mount(cx, false);
        let state = probe.read_with(&cx, |probe, _| probe.input.clone());
        click(&mut cx, "start");
        cx.simulate_input("Ada 中文");
        draw(&mut cx);
        assert_eq!(state.read_with(&cx, |state, _| state.value()), "Ada 中文");
        let control = snapshot(&mut cx, ("input", state.entity_id()));
        assert_eq!(control.role(), Some(Role::TextInput));
        assert_eq!(control.label(), Some("Address"));
        assert_eq!(control.value(), Some("Ada 中文"));
        assert_eq!(control.focused(), Some(true));
        assert_eq!(snapshot(&mut cx, "group").role(), Some(Role::Group));
        assert_eq!(
            cx.update(|window, cx| window.focused_input(cx)),
            Some(state.clone().into())
        );

        click(&mut cx, "action");
        assert_eq!(probe.read_with(&cx, |probe, _| probe.clicks), 1);
        assert!(cx.update(|window, cx| probe.read(cx).other.is_focused(window)));
        assert_eq!(state.read_with(&cx, |state, _| state.value()), "Ada 中文");

        let before = snapshot(&mut cx, "start").bounds();
        let after = snapshot(&mut cx, "end").bounds();
        assert!(before.right() <= control.bounds().left());
        assert!(control.bounds().right() <= after.left());
    }

    #[gpui::test]
    fn disabled_blocks_actions_and_edits_but_readonly_keeps_copy_and_actions(
        cx: &mut TestAppContext,
    ) {
        let (probe, mut cx) = mount(cx, false);
        let state = probe.read_with(&cx, |probe, _| probe.input.clone());
        click(&mut cx, "start");
        cx.simulate_input("Retained value");
        probe.update(&mut cx, |probe, cx| {
            probe.disabled = true;
            cx.notify();
        });
        draw(&mut cx);
        click(&mut cx, "action");
        click(&mut cx, "start");
        cx.simulate_input("blocked");
        draw(&mut cx);
        assert_eq!(probe.read_with(&cx, |probe, _| probe.clicks), 0);
        assert_eq!(
            state.read_with(&cx, |state, _| state.value()),
            "Retained value"
        );
        assert!(state.read_with(&cx, |state, _| state.presentation().is_disabled()));

        probe.update(&mut cx, |probe, cx| {
            probe.disabled = false;
            probe.readonly = true;
            cx.notify();
        });
        draw(&mut cx);
        click(&mut cx, "start");
        cx.simulate_input("blocked");
        cx.update(|window, cx| {
            window.dispatch_action(Box::new(crate::input::SelectAll), cx);
            window.dispatch_action(Box::new(crate::input::Copy), cx);
        });
        draw(&mut cx);
        assert_eq!(
            state.read_with(&cx, |state, _| state.value()),
            "Retained value"
        );
        assert_eq!(
            cx.update(|_, cx| cx.read_from_clipboard().and_then(|item| item.text())),
            Some("Retained value".into())
        );
        click(&mut cx, "action");
        assert_eq!(probe.read_with(&cx, |probe, _| probe.clicks), 1);

        probe.update(&mut cx, |probe, cx| {
            probe.readonly = false;
            probe.invalid = true;
            cx.notify();
        });
        draw(&mut cx);
        click(&mut cx, "start");
        cx.simulate_input("Editable error");
        draw(&mut cx);
        assert_eq!(
            state.read_with(&cx, |state, _| state.value()),
            "Editable error"
        );
    }

    #[gpui::test]
    fn textarea_grows_between_block_addons_and_retains_native_focus(cx: &mut TestAppContext) {
        let (probe, mut cx) = mount(cx, true);
        let state = probe.read_with(&cx, |probe, _| probe.textarea.clone());
        let initial_footer = snapshot(&mut cx, "footer").bounds();
        click(&mut cx, "header");
        cx.simulate_input("One\nTwo\nThree\nFour\nFive");
        draw(&mut cx);
        let control = snapshot(&mut cx, ("input", state.entity_id()));
        let header = snapshot(&mut cx, "header").bounds();
        let footer = snapshot(&mut cx, "footer").bounds();
        assert_eq!(control.role(), Some(Role::MultilineTextInput));
        assert_eq!(control.focused(), Some(true));
        assert!(header.bottom() <= control.bounds().top());
        assert!(control.bounds().bottom() <= footer.top());
        assert!(
            footer.top() > initial_footer.top(),
            "textarea must grow before its toolbar"
        );
        assert_eq!(
            state.read_with(&cx, |state, _| state.value()),
            "One\nTwo\nThree\nFour\nFive"
        );

        // A narrow viewport must still give the editor usable space between addons.
        cx.update(|window, cx| {
            window.set_rem_size(px(20.));
            window.draw(cx).clear(cx);
        });
        let bounds = snapshot(&mut cx, ("input", state.entity_id())).bounds();
        assert!(bounds.size.width > px(0.));
        assert!(bounds.bottom() <= snapshot(&mut cx, "footer").bounds().top());
    }

    struct PopupProbe {
        input: Entity<InputState>,
        changes: Rc<std::cell::RefCell<Vec<(&'static str, bool)>>>,
        clicks: Rc<std::cell::Cell<usize>>,
    }

    impl Render for PopupProbe {
        fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            use crate::{
                menu::{DropdownMenu as _, PopupMenuItem},
                popover::Popover,
            };
            let menu_changes = self.changes.clone();
            let popover_changes = self.changes.clone();
            let enabled_clicks = self.clicks.clone();
            let disabled_clicks = self.clicks.clone();
            v_flex()
                .p_4()
                .child(
                    InputGroup::new("popup-group")
                        .w_96()
                        .input(InputGroupInput::new(&self.input))
                        .addon(
                            InputGroupAddon::new("popup-actions")
                                .align(InputGroupAddonAlignment::BlockEnd)
                                .child(InputGroupButton::new("first").label("First").on_click(
                                    move |_, _, _| enabled_clicks.set(enabled_clicks.get() + 1),
                                ))
                                .child(div().id("between").test_support().child("then"))
                                .children([
                                    InputGroupButton::new("last")
                                        .label("Last")
                                        .into_any_element(),
                                    InputGroupButton::new("menu-trigger")
                                        .label("Menu")
                                        .dropdown_menu(|menu, _, _| {
                                            menu.item(PopupMenuItem::new("Action"))
                                        })
                                        .on_open_change(move |open, _, _| {
                                            menu_changes.borrow_mut().push(("menu", *open));
                                        })
                                        .into_any_element(),
                                    Popover::new("group-popover")
                                        .trigger(
                                            InputGroupButton::new("popover-trigger")
                                                .label("Details"),
                                        )
                                        .child("Details content")
                                        .on_open_change(move |open, _, _| {
                                            popover_changes.borrow_mut().push(("popover", *open));
                                        })
                                        .into_any_element(),
                                ]),
                        ),
                )
                .child(
                    // Exercise inherited disabled state without the group's capture
                    // handlers: the native button itself must reject activation.
                    InputGroupAddon::new("disabled-addon")
                        .child(
                            InputGroupButton::new("disabled-action")
                                .label("Disabled")
                                .on_click(move |_, _, _| {
                                    disabled_clicks.set(disabled_clicks.get() + 1)
                                }),
                        )
                        .render_in_group(
                            GroupPresentation {
                                disabled: true,
                                ..Default::default()
                            },
                            window,
                            cx,
                        ),
                )
        }
    }

    #[gpui::test]
    fn ordered_children_and_native_button_popup_composition(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let changes = Rc::new(std::cell::RefCell::new(Vec::new()));
        let clicks = Rc::new(std::cell::Cell::new(0));
        let window = cx.add_window({
            let changes = changes.clone();
            let clicks = clicks.clone();
            move |window, cx| {
                let probe = cx.new(|cx| PopupProbe {
                    input: cx.new(|cx| InputState::new(window, cx)),
                    changes,
                    clicks,
                });
                Root::new(probe, window, cx)
            }
        });
        let mut cx = VisualTestContext::from_window(window.into(), cx);
        draw(&mut cx);
        let first = snapshot(&mut cx, "first").bounds();
        let between = snapshot(&mut cx, "between").bounds();
        let last = snapshot(&mut cx, "last").bounds();
        assert!(first.right() <= between.left() && between.right() <= last.left());
        click(&mut cx, "first");
        assert_eq!(clicks.get(), 1);
        click(&mut cx, "disabled-action");
        assert_eq!(clicks.get(), 1);

        click(&mut cx, "menu-trigger");
        assert_eq!(&*changes.borrow(), &[("menu", true)]);
        cx.simulate_keystrokes("escape");
        draw(&mut cx);
        assert_eq!(&*changes.borrow(), &[("menu", true), ("menu", false)]);

        click(&mut cx, "popover-trigger");
        assert_eq!(changes.borrow().last(), Some(&("popover", true)));
        cx.simulate_keystrokes("escape");
        draw(&mut cx);
        assert_eq!(changes.borrow().last(), Some(&("popover", false)));
    }
}
