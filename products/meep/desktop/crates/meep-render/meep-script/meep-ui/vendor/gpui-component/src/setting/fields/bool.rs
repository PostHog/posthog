use std::rc::Rc;

use crate::{
    Disableable, Sizable, StyledExt,
    checkbox::Checkbox,
    setting::{
        AnySettingField, RenderOptions,
        fields::{SettingFieldRender, get_value, set_value},
    },
    switch::Switch,
};
use gpui::{
    AnyElement, App, IntoElement, ParentElement as _, SharedString, StyleRefinement, Window, div,
};

pub(crate) struct BoolField {
    use_switch: bool,
    /// The setting's title. The control has no visible text of its own, so this is its
    /// accessible name.
    title: SharedString,
}

impl BoolField {
    pub(crate) fn new(use_switch: bool, title: SharedString) -> Self {
        Self { use_switch, title }
    }
}

impl SettingFieldRender for BoolField {
    fn render(
        &self,
        field: Rc<dyn AnySettingField>,
        options: &RenderOptions,
        style: &StyleRefinement,
        _: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let checked = get_value::<bool>(&field, cx);
        let set_value = set_value::<bool>(&field, cx);

        div()
            .refine_style(style)
            .child(if self.use_switch {
                Switch::new("check")
                    .accessibility_label(self.title.clone())
                    .checked(checked)
                    .disabled(options.is_disabled())
                    .with_size(options.size())
                    .on_click(move |checked: &bool, _, cx: &mut App| {
                        set_value(*checked, cx);
                    })
                    .into_any_element()
            } else {
                Checkbox::new("check")
                    .accessibility_label(self.title.clone())
                    .checked(checked)
                    .disabled(options.is_disabled())
                    .with_size(options.size())
                    .on_click(move |checked: &bool, _, cx: &mut App| {
                        set_value(*checked, cx);
                    })
                    .into_any_element()
            })
            .into_any_element()
    }
}
