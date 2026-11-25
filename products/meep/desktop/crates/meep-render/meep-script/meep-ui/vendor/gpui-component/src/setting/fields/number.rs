use std::rc::Rc;

use gpui::{
    AnyElement, App, AppContext as _, Entity, IntoElement, SharedString, StyleRefinement, Styled,
    Subscription, Window, prelude::FluentBuilder as _,
};

use crate::{
    AxisExt, Disableable, Sizable, StyledExt,
    input::{InputEvent, InputState, NumberInput},
    setting::{
        AnySettingField, RenderOptions,
        fields::{SettingFieldRender, get_value, set_value},
    },
};

#[derive(Clone, Debug)]
pub struct NumberFieldOptions {
    /// The minimum value for the number input, default is `f64::MIN`.
    pub min: f64,
    /// The maximum value for the number input, default is `f64::MAX`.
    pub max: f64,
    /// The step value for the number input, default is `1.0`.
    pub step: f64,
}

impl Default for NumberFieldOptions {
    fn default() -> Self {
        Self {
            min: f64::MIN,
            max: f64::MAX,
            step: 1.0,
        }
    }
}

pub(crate) struct NumberField {
    options: NumberFieldOptions,
    /// The setting's title, the input's accessible name.
    title: SharedString,
}

impl NumberField {
    pub(crate) fn new(options: Option<&NumberFieldOptions>, title: SharedString) -> Self {
        Self {
            options: options.cloned().unwrap_or_default(),
            title,
        }
    }
}

struct State {
    input: Entity<InputState>,
    initial_value: f64,
    _subscriptions: Vec<Subscription>,
}

impl SettingFieldRender for NumberField {
    fn render(
        &self,
        field: Rc<dyn AnySettingField>,
        options: &RenderOptions,
        style: &StyleRefinement,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let value = get_value::<f64>(&field, cx);
        let set_value = set_value::<f64>(&field, cx);
        let num_options = self.options.clone();

        let state_entity = window.use_keyed_state(
            SharedString::from(format!(
                "number-state-{}-{}-{}",
                options.page_ix(),
                options.group_ix(),
                options.item_ix()
            )),
            cx,
            |window, cx| {
                // Configure stepping and bounds on the engine itself: `+`/`-`
                // and Up/Down step by `step` with precision handling, and
                // out-of-range text is tolerated while typing and clamped on
                // blur. Re-implementing either on `Change` breaks both.
                let input = cx.new(|cx| {
                    InputState::new(window, cx)
                        .default_value(value.to_string())
                        .step(num_options.step)
                        .min(num_options.min)
                        .max(num_options.max)
                });
                let _subscriptions = vec![cx.subscribe_in(&input, window, {
                    move |state: &mut State, input, event: &InputEvent, _window, cx| match event {
                        InputEvent::Change => {
                            input.update(cx, |input, cx| {
                                let text = input.value();
                                if text == state.initial_value.to_string() {
                                    return;
                                }

                                // Unparsable intermediates ("-", "", "1.") are
                                // left alone so the next keystroke can complete
                                // them. Out-of-range text stays too (the engine
                                // clamps it on blur), but the setting only ever
                                // receives a value inside `min..=max`.
                                if let Ok(parsed) = text.parse::<f64>() {
                                    let clamped = parsed.clamp(num_options.min, num_options.max);
                                    set_value(clamped, cx);
                                    state.initial_value = clamped;
                                }
                            });
                        }
                        _ => {}
                    }
                })];

                State {
                    input,
                    initial_value: value,
                    _subscriptions,
                }
            },
        );

        // Sync engine config and displayed value when options or the
        // underlying setting changed externally.
        let sync_options = self.options.clone();
        state_entity.update(cx, |state, cx| {
            state.input.update(cx, |input, cx| {
                input.set_step(Some(sync_options.step.into()), window, cx);
                input.set_min(Some(sync_options.min), window, cx);
                input.set_max(Some(sync_options.max), window, cx);
            });
            if state.initial_value != value {
                state.initial_value = value;
                state.input.update(cx, |input, cx| {
                    input.set_value(SharedString::from(value.to_string()), window, cx);
                });
            }
        });

        let state = state_entity.read(cx);

        NumberInput::new(&state.input)
            .accessibility_label(self.title.clone())
            .disabled(options.is_disabled())
            .with_size(options.size())
            .map(|this| {
                if options.layout().is_horizontal() {
                    this.w_32()
                } else {
                    this.w_full()
                }
            })
            .refine_style(style)
            .into_any_element()
    }
}
