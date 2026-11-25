#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

use gpui::{
    InteractiveElement as _, ParentElement as _, StatefulInteractiveElement as _, Styled as _,
    blue, green, px, red,
};
use gpui_component::{
    Disableable as _, Selectable as _, Sizable as _, Size,
    checkbox::Checkbox,
    radio::{Radio, RadioGroup},
    switch::Switch,
};

#[test]
fn legacy_checkbox_builder_and_traits_remain_available() {
    let checkbox = Checkbox::new("legacy-checkbox")
        .label("Remember me")
        .tooltip("Stored on this device")
        .checked(true)
        .selected(false)
        .disabled(false)
        .with_size(Size::Small)
        .tab_index(2)
        .tab_stop(true)
        .on_click(|next, _, _| {
            let _: &bool = next;
        })
        .child("application child")
        .bg(red())
        .hover(|style| style.bg(green()))
        .active(|style| style.bg(blue()))
        .focus_visible(|style| style.border_1());

    assert!(!checkbox.is_selected());
}

#[test]
fn legacy_radio_and_radio_group_paths_remain_available() {
    let first = Radio::new("legacy-radio-a")
        .label("Alpha")
        .tooltip("Choose alpha")
        .checked(true)
        .disabled(false)
        .with_size(px(18.))
        .tab_index(0)
        .tab_stop(true)
        .on_click(|next, _, _| {
            let _: &bool = next;
        })
        .child("application child")
        .bg(red())
        .hover(|style| style.bg(green()))
        .active(|style| style.bg(blue()))
        .focus_visible(|style| style.border_1());

    let second = Radio::new("legacy-radio-b").label("Beta");
    let _vertical = RadioGroup::vertical("legacy-radio-group")
        .selected_index(Some(0))
        .disabled(false)
        .on_click(|index, _, _| {
            let _: &usize = index;
        })
        .child(first)
        .child(second)
        .bg(red());

    let _horizontal = RadioGroup::horizontal("legacy-radio-group-horizontal")
        .children([Radio::new("one"), Radio::new("two")]);
}

#[test]
fn legacy_switch_builder_and_trait_methods_remain_available() {
    let _switch = Switch::new("legacy-switch")
        .label("Airplane mode")
        .tooltip("Disable wireless radios")
        .checked(true)
        .disabled(false)
        .with_size(Size::Large)
        .color(green())
        .on_click(|next, _, _| {
            let _: &bool = next;
        })
        .bg(red());
}

#[test]
fn base_controls_do_not_replace_legacy_module_paths() {
    fn legacy_checkbox(_: Checkbox) {}
    fn legacy_switch(_: Switch) {}
    fn base_checkbox(_: gpui_base::Checkbox) {}
    fn base_switch(_: gpui_base::Switch) {}

    legacy_checkbox(Checkbox::new("legacy"));
    legacy_switch(Switch::new("legacy"));
    base_checkbox(gpui_base::Checkbox::new("base"));
    base_switch(gpui_base::Switch::new("base"));
}
