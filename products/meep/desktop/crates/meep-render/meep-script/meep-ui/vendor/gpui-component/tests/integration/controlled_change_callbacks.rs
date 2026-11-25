#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

use std::{cell::RefCell, rc::Rc};

use gpui::{
    App, Context, IntoElement, KeyDownEvent, KeyUpEvent, Keystroke, Modifiers, Render, Styled,
    TestAppContext, Window, div, prelude::*, px,
};
use gpui_component::{
    Disableable,
    checkbox::Checkbox,
    radio::{Radio, RadioGroup},
    switch::Switch,
};

#[derive(Clone, Copy, Debug)]
enum Control {
    Checkbox,
    Switch,
    Radio,
    RadioGroup,
}

#[derive(Clone, Copy, Debug)]
enum Callback {
    Click,
    Change,
    ClickThenChange,
    ChangeThenClick,
}

struct Harness {
    control: Control,
    callback: Callback,
    disabled: bool,
    requests: Rc<RefCell<Vec<String>>>,
}

impl Render for Harness {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        macro_rules! bind {
            ($control:expr, $value:ty) => {{
                let requests = self.requests.clone();
                let record = move |value: &$value, _: &mut Window, _: &mut App| {
                    requests.borrow_mut().push(format!("{value:?}"));
                };
                let replaced = |_: &$value, _: &mut Window, _: &mut App| {
                    panic!("an earlier callback must be replaced");
                };
                let control = $control;
                match self.callback {
                    Callback::Click => control.on_click(record),
                    Callback::Change => control.on_change(record),
                    Callback::ClickThenChange => control.on_click(replaced).on_change(record),
                    Callback::ChangeThenClick => control.on_change(replaced).on_click(record),
                }
                .into_any_element()
            }};
        }
        let control = match self.control {
            Control::Checkbox => bind!(
                Checkbox::new("control")
                    .checked(false)
                    .disabled(self.disabled)
                    .label("Choice"),
                bool
            ),
            Control::Switch => bind!(
                Switch::new("control")
                    .checked(false)
                    .disabled(self.disabled)
                    .label("Choice"),
                bool
            ),
            Control::Radio => bind!(
                Radio::new("control")
                    .checked(false)
                    .disabled(self.disabled)
                    .label("Choice"),
                bool
            ),
            Control::RadioGroup => bind!(
                RadioGroup::new("control")
                    .selected_index(None)
                    .child(Radio::new("choice").label("Choice"))
                    .disabled(self.disabled),
                usize
            ),
        };
        div().id("parent").tab_group().w(px(200.)).child(
            div()
                .debug_selector(|| "control-target".into())
                .child(control),
        )
    }
}

#[gpui::test]
fn controlled_change_callbacks_preserve_activation_and_replace_aliases(cx: &mut TestAppContext) {
    cx.update(gpui_component::init);
    for control in [
        Control::Checkbox,
        Control::Switch,
        Control::Radio,
        Control::RadioGroup,
    ] {
        for callback in [
            Callback::Click,
            Callback::Change,
            Callback::ClickThenChange,
            Callback::ChangeThenClick,
        ] {
            for disabled in [false, true] {
                let requests = Rc::new(RefCell::new(Vec::new()));
                let (_, visual) = cx.add_window_view({
                    let requests = requests.clone();
                    move |_, _| Harness {
                        control,
                        callback,
                        disabled,
                        requests,
                    }
                });
                visual.update(|window, cx| window.draw(cx).clear(cx));
                let target = visual.debug_bounds("control-target").unwrap();
                // Click inside the leading control, not the full-width wrapper.
                visual.simulate_click(
                    gpui::point(target.left() + px(8.), target.center().y),
                    Modifiers::default(),
                );
                visual.update(|window, cx| {
                    window.blur(cx);
                    window.focus_next(cx);
                });
                for key in ["enter", "space"] {
                    let keystroke = Keystroke::parse(key).unwrap();
                    visual.simulate_event(KeyDownEvent {
                        keystroke: keystroke.clone(),
                        is_held: false,
                        prefer_character_input: false,
                    });
                    visual.simulate_event(KeyUpEvent { keystroke });
                }
                let expected = match control {
                    Control::RadioGroup => "0",
                    _ => "true",
                };
                assert_eq!(
                    *requests.borrow(),
                    if disabled {
                        vec![]
                    } else {
                        vec![expected.to_owned(); 3]
                    },
                    "{control:?}, {callback:?}, disabled={disabled}"
                );
            }
        }
    }
}

#[gpui::test]
fn owner_applies_requested_value_before_the_next_activation(cx: &mut TestAppContext) {
    struct Owner {
        checked: bool,
        requests: Vec<bool>,
    }

    impl Render for Owner {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            div().id("owner").tab_group().child(
                Checkbox::new("owned-checkbox")
                    .checked(self.checked)
                    .label("Choice")
                    .on_change(cx.listener(|this, checked, _, cx| {
                        this.checked = *checked;
                        this.requests.push(*checked);
                        cx.notify();
                    })),
            )
        }
    }

    cx.update(gpui_component::init);
    let (owner, visual) = cx.add_window_view(|_, _| Owner {
        checked: false,
        requests: vec![],
    });
    visual.update(|window, cx| window.draw(cx).clear(cx));
    visual.simulate_click(gpui::point(px(8.), px(8.)), Modifiers::default());
    visual.update(|window, cx| {
        window.draw(cx).clear(cx);
        window.focus_next(cx);
    });
    let keystroke = Keystroke::parse("space").unwrap();
    visual.simulate_event(KeyDownEvent {
        keystroke: keystroke.clone(),
        is_held: false,
        prefer_character_input: false,
    });
    visual.simulate_event(KeyUpEvent { keystroke });
    visual.update(|_, cx| {
        assert_eq!(owner.read(cx).requests, [true, false]);
        assert!(!owner.read(cx).checked);
    });
}
