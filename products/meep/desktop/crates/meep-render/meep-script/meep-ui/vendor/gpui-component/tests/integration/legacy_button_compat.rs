#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

use gpui::{Axis, InteractiveElement as _, ParentElement as _, Styled as _, blue, green, px, red};
use gpui_component::{
    Disableable as _, Icon, IconName, Selectable as _, Sizable as _, Size,
    button::{
        Button, ButtonCustomVariant, ButtonGroup, ButtonRounded, ButtonVariant,
        ButtonVariants as _, DropdownButton, Toggle, ToggleGroup, ToggleVariant,
        ToggleVariants as _,
    },
    input::Enter,
};

#[test]
fn legacy_button_path_and_builder_surface_remain_available() {
    let button = Button::new("legacy-button")
        .label("Save")
        .icon(IconName::Check)
        .tooltip("Save changes")
        .tooltip_with_action(
            "Save changes",
            &Enter {
                secondary: false,
                shift: false,
            },
            Some("Button"),
        )
        .accessibility_id("settings.save")
        .primary()
        .with_variant(ButtonVariant::Secondary)
        .outline()
        .rounded(ButtonRounded::Large)
        .rounded(px(6.))
        .compact()
        .loading(false)
        .loading_icon(Icon::new(IconName::LoaderCircle))
        .dropdown_caret(true)
        .toggled(false)
        .disabled(false)
        .selected(true)
        .with_size(Size::Small)
        .tab_index(3)
        .tab_stop(true)
        .on_hover(|hovered, _, _| {
            let _: &bool = hovered;
        })
        .on_click(|event, _, _| {
            let _: &gpui::ClickEvent = event;
        })
        .child("application child")
        .bg(red())
        .hover(|style| style.bg(green()));

    assert!(button.is_selected());
}

#[test]
fn legacy_button_variants_and_rounding_types_remain_public() {
    let variants = [
        ButtonVariant::Default,
        ButtonVariant::Primary,
        ButtonVariant::Secondary,
        ButtonVariant::Danger,
        ButtonVariant::Info,
        ButtonVariant::Success,
        ButtonVariant::Warning,
        ButtonVariant::Ghost,
        ButtonVariant::Link,
        ButtonVariant::Text,
    ];
    assert!(variants[7].is_ghost());
    assert!(variants[8].is_link());
    assert!(variants[9].is_text());

    let _rounding = [
        ButtonRounded::None,
        ButtonRounded::Small,
        ButtonRounded::Medium,
        ButtonRounded::Large,
        ButtonRounded::Size(px(8.)),
    ];

    let _custom_constructor: fn(&gpui::App) -> ButtonCustomVariant = ButtonCustomVariant::new;
    let _custom_builders = (
        ButtonCustomVariant::color,
        ButtonCustomVariant::foreground,
        ButtonCustomVariant::hover,
        ButtonCustomVariant::active,
        ButtonCustomVariant::shadow,
    );

    let _variant_helpers = Button::new("variant-helpers")
        .primary()
        .secondary()
        .danger()
        .warning()
        .success()
        .info()
        .ghost()
        .link()
        .text();
}

#[test]
fn legacy_button_group_and_dropdown_paths_remain_available() {
    let _group = ButtonGroup::new("legacy-button-group")
        .children([
            Button::new("one").label("One"),
            Button::new("two").label("Two"),
        ])
        .child(Button::new("three").label("Three"))
        .multiple(true)
        .layout(Axis::Horizontal)
        .compact()
        .outline()
        .danger()
        .disabled(false)
        .with_size(Size::Medium)
        .on_click(|indices, _, _| {
            let _: &Vec<usize> = indices;
        })
        .bg(red());

    let dropdown = DropdownButton::new("legacy-dropdown-button")
        .button(Button::new("dropdown-primary").label("Export"))
        .dropdown_menu(|menu, _, _| menu)
        .dropdown_menu_with_anchor(gpui::Anchor::BottomLeft, |menu, _, _| menu)
        .outline()
        .success()
        .disabled(false)
        .selected(true)
        .with_size(Size::Large)
        .bg(blue());
    assert!(dropdown.is_selected());
}

#[test]
fn legacy_toggle_types_under_button_module_remain_available() {
    let toggle = Toggle::new("legacy-toggle")
        .label("Bold")
        .icon(IconName::Check)
        .tooltip("Toggle bold")
        .checked(true)
        .with_variant(ToggleVariant::Outline)
        .ghost()
        .outline()
        .disabled(false)
        .with_size(Size::Small)
        .on_click(|checked, _, _| {
            let _: &bool = checked;
        })
        .child("application child")
        .bg(red());

    let _group = ToggleGroup::new("legacy-toggle-group")
        .child(toggle)
        .children([Toggle::new("left"), Toggle::new("right")])
        .segmented()
        .disabled(false)
        .with_size(Size::Medium)
        .on_click(|indices, _, _| {
            let _: &Vec<bool> = indices;
        })
        .bg(green());
}

#[test]
fn base_button_does_not_replace_legacy_button_module_path() {
    fn legacy(_: Button) {}
    fn base(_: gpui_base::Button) {}

    legacy(Button::new("legacy"));
    base(gpui_base::Button::new("base"));
}
