use std::rc::Rc;

use gpui::{
    AnyElement, App, AppContext as _, Entity, IntoElement, SharedString, StyleRefinement, Styled,
    Window, prelude::FluentBuilder as _,
};

use crate::{
    AxisExt as _, Sizable, StyledExt,
    input::{Input, InputEvent, InputState},
    setting::{
        AnySettingField, RenderOptions,
        fields::{SettingFieldRender, get_value, set_value},
    },
};

pub(crate) struct StringField<T> {
    /// The setting's title, the input's accessible name.
    title: SharedString,
    _marker: std::marker::PhantomData<T>,
}

impl<T> StringField<T> {
    pub(crate) fn new(title: SharedString) -> Self {
        Self {
            title,
            _marker: std::marker::PhantomData,
        }
    }
}

struct State {
    input: Entity<InputState>,
    _subscription: gpui::Subscription,
}

impl<T> SettingFieldRender for StringField<T>
where
    T: Into<SharedString> + From<SharedString> + Clone + 'static,
{
    fn render(
        &self,
        field: Rc<dyn AnySettingField>,
        options: &RenderOptions,
        style: &StyleRefinement,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let value = get_value::<T>(&field, cx);
        let value: SharedString = value.into();
        let set_value = set_value::<T>(&field, cx);

        let state_entity = window.use_keyed_state(
            SharedString::from(format!(
                "string-state-{}-{}-{}",
                options.page_ix(),
                options.group_ix(),
                options.item_ix()
            )),
            cx,
            {
                let value = value.clone();
                |window, cx| {
                    let input = cx.new(|cx| InputState::new(window, cx).default_value(value));
                    let _subscription = cx.subscribe(&input, {
                        move |_, input, event: &InputEvent, cx| match event {
                            InputEvent::Change => {
                                let value = input.read(cx).value();
                                set_value(value.into(), cx);
                            }
                            _ => {}
                        }
                    });

                    State {
                        input,
                        _subscription,
                    }
                }
            },
        );

        // Sync the displayed value when the underlying setting changed externally
        state_entity.update(cx, |state, cx| {
            if state.input.read(cx).value() != value {
                state.input.update(cx, |input, cx| {
                    input.set_value(value.clone(), window, cx);
                });
            }
        });

        let state = state_entity.read(cx);

        Input::new(&state.input)
            .aria_label(self.title.clone())
            .disabled(options.is_disabled())
            .with_size(options.size())
            .map(|this| {
                if options.layout().is_horizontal() {
                    this.w_64()
                } else {
                    this.w_full()
                }
            })
            .refine_style(style)
            .into_any_element()
    }
}
