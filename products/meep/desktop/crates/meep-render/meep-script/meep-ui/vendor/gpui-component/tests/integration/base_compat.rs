#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

use gpui::{
    Axis, Div, InteractiveElement as _, Length, ParentElement as _, Pixels, Stateful,
    StatefulInteractiveElement as _, Styled as _, blue, green, prelude::FluentBuilder as _, px,
    red,
};
use gpui_component::{
    AxisExt as _, FocusTrapElement, InteractiveElementExt, LengthExt as _, Placement, Side,
    animation,
};

#[test]
fn legacy_foundation_exports_remain_available() {
    assert!(Axis::Horizontal.is_horizontal());
    assert!(Axis::Vertical.is_vertical());
    assert_eq!(Placement::Top.axis(), Axis::Vertical);
    assert!(Side::Left.is_left());

    let length = Length::Definite(px(12.).into());
    let pixels: Option<Pixels> = length.to_pixels(px(16.).into(), px(16.));
    assert_eq!(pixels, Some(px(12.)));

    assert_eq!(animation::ease_in_cubic(0.5), 0.125);

    fn requires_interaction_extensions<T: FocusTrapElement + InteractiveElementExt>() {}
    requires_interaction_extensions::<Stateful<Div>>();
}

#[test]
fn focus_ring_api_exposes_component_state_without_visual_options() {
    use gpui_component::FocusableExt as _;

    let button = gpui_component::button::Button::new("focus-ring-state").focus_ring(false);
    assert!(!button.is_focus_ring_enabled());
}

#[test]
fn base_crate_exports_the_same_foundation_types() {
    let legacy = gpui_component::Edges::all(1_u8);
    let base: gpui_base::Edges<u8> = legacy;

    assert_eq!(base.top, 1);
    assert_eq!(base.right, 1);
    assert_eq!(base.bottom, 1);
    assert_eq!(base.left, 1);
}

#[test]
fn motion_core_types_are_available_from_the_base_facade() {
    let timing = gpui_base::Timing::new(std::time::Duration::from_millis(100))
        .ease(gpui_base::Easing::Linear);
    assert_eq!(
        timing
            .sample(std::time::Duration::from_millis(50))
            .directed_progress,
        0.5
    );
}

#[test]
fn base_avatar_uses_application_owned_image_and_fallback_slots() {
    let _ = gpui_base::Avatar::new()
        .image(gpui_base::AvatarImage::new(gpui::ImageSource::from(
            "avatar.png",
        )))
        .fallback(gpui_base::AvatarFallback::new().child("JL"));
}

#[test]
fn base_sheet_accepts_application_owned_overlay_and_surface() {
    fn build(cx: &mut gpui::App) {
        let _ = gpui_base::Sheet::new(cx)
            .overlay(gpui::div())
            .surface(gpui::div())
            .overlay_closable(false)
            .on_close(|_, _, _| {});
    }

    let _ = build;
}

#[test]
fn base_dialog_owns_modal_actions_and_alert_defaults() {
    fn dialog(cx: &mut gpui::App) {
        let handle = gpui_base::DialogHandle::new(true);
        let _ = gpui_base::Dialog::new(cx)
            .handle(handle.clone())
            .on_open_change(|_, _, _, _| {})
            .backdrop(gpui_base::DialogBackdrop::new())
            .popup(gpui_base::DialogPopup::new())
            .on_ok(|_, _, _| true)
            .on_cancel(|_, _, _| true)
            .on_close(|_, _, _| {});
        let _ = gpui_base::AlertDialog::new(cx)
            .handle(handle)
            .backdrop(gpui_base::AlertDialogBackdrop::new())
            .popup(gpui_base::AlertDialogPopup::new());
    }

    let _ = dialog;
    let _ = gpui_base::DialogTitle::new().child("Title");
    let _ = gpui_base::DialogDescription::new().child("Description");
    let _ = gpui_base::DialogClose::new().child(gpui::div());
    let _ = gpui_base::AlertDialogTrigger::new(gpui::div());
    let _ = gpui_base::AlertDialogTitle::new().child("Title");
    let _ = gpui_base::AlertDialogDescription::new().child("Description");
    let _ = gpui_base::AlertDialogAction::new().child(gpui::div());
    let _ = gpui_base::AlertDialogCancel::new().child(gpui::div());
    let _: gpui_base::actions::Cancel = gpui_component::dialog::Cancel;
    let _: gpui_base::actions::Confirm = gpui_component::dialog::Confirm { secondary: false };
}

#[test]
fn base_button_accepts_application_owned_state_styles() {
    let _button = gpui_base::Button::new("save")
        .accessibility_label("Save")
        .disabled(false)
        .on_click(|_, _, _| {})
        .child("Save")
        .bg(red())
        .hover(|style| style.bg(green()))
        .active(|style| style.bg(blue()))
        .focus_visible(|style| style.border_1());
}

#[test]
fn base_controls_expose_typed_semantic_style_contexts() {
    let _ = gpui_base::Button::new("button")
        .styles(|styles| styles.disabled(|style| style.opacity(0.5)));
    let _ = gpui_base::Checkbox::new("checkbox").styles(|styles| {
        styles
            .checked(|style| style.bg(green()))
            .indeterminate(|style| style.bg(blue()))
            .disabled(|style| style.when(true, |style| style.opacity(0.5)))
    });
    let _ =
        gpui_base::Radio::new("radio").styles(|styles| styles.checked(|style| style.bg(green())));
    let _ =
        gpui_base::Switch::new("switch").styles(|styles| styles.checked(|style| style.bg(green())));
    let _ =
        gpui_base::Toggle::new("toggle").styles(|styles| styles.pressed(|style| style.bg(green())));
    let _ =
        gpui_base::Link::new("link").styles(|styles| styles.disabled(|style| style.opacity(0.5)));
    let _ = gpui_base::Tab::new("tab").styles(|styles| {
        styles
            .selected(|style| style.bg(green()))
            .disabled(|style| style.opacity(0.5))
    });
    let _ = gpui_base::Tabs::new("tabs").child(
        gpui_base::Tab::new("first")
            .selected(true)
            .on_click(|_, _, _| {}),
    );
}

#[test]
fn base_collapsible_uses_normal_child_and_content_slots() {
    let _ = gpui_base::Collapsible::new()
        .open(true)
        .child("Trigger")
        .content("Content");
    let _ = gpui_component::collapsible::Collapsible::new()
        .open(true)
        .child("Trigger")
        .content("Content");
}

#[test]
fn base_accordion_uses_normal_parts_and_children() {
    let trigger = gpui_base::AccordionTrigger::new("trigger")
        .open(true)
        .disabled(false)
        .child("Title");
    let header = gpui_base::AccordionHeader::new(trigger).level(3);
    let panel = gpui_base::AccordionPanel::new().open(true).child("Content");
    let item = gpui_base::AccordionItem::new()
        .open(true)
        .header(header)
        .panel(panel);
    let _ = gpui_base::Accordion::new("accordion").child(item);
}

#[test]
fn legacy_behavior_traits_are_the_base_traits() {
    fn selectable<T: gpui_base::Selectable>(value: T) -> T {
        value
    }
    fn disableable<T: gpui_base::Disableable>(value: T) -> T {
        value
    }

    let _ = selectable(gpui_component::button::Button::new("selectable"));
    let _ = disableable(gpui_component::button::Button::new("disableable"));
}

#[test]
fn legacy_measure_type_is_the_base_type() {
    fn accepts_base(_: gpui_base::Measure) {}
    accepts_base(gpui_component::Measure::new("compat"));
}

#[test]
fn base_progress_accepts_application_owned_indicator_content() {
    let _ = gpui_base::Progress::new("progress")
        .value(42.)
        .child(gpui_base::ProgressTrack::new())
        .child(gpui_base::ProgressIndicator::new().child(gpui::div()));
}

#[test]
fn base_table_and_toast_accept_application_owned_composition() {
    let row = gpui_base::TableRow::new("row", 1)
        .child(gpui_base::TableHead::new("head", 1).child("Name"))
        .child(gpui_base::TableCell::new("cell", 1).child("Ada"));
    let _ = gpui_base::Table::new("table")
        .child(gpui_base::TableHeader::new("header").child(row))
        .child(gpui_base::TableBody::new("body"))
        .child(gpui_base::TableCaption::new("caption").child("People"));

    let _ = gpui_base::ToastStack::new("toasts", gpui_base::ToastStackState::default())
        .child(gpui_base::Toast::new("toast").child("Saved"));
}

#[test]
fn legacy_tree_models_are_base_types() {
    fn accepts_base(_: gpui_base::TreeItem) {}
    accepts_base(gpui_component::tree::TreeItem::new("id", "Label"));
}

#[test]
fn base_combobox_accepts_application_owned_content() {
    fn build(trigger: gpui::FocusHandle, content: gpui::FocusHandle) {
        let _ = gpui_base::Combobox::new("language")
            .open(true)
            .disabled(false)
            .focus_handle(&trigger)
            .content_focus_handle(&content)
            .on_open_change(|_, _, _| {})
            .on_confirm(|_, _| {})
            .child(gpui::div());
    }

    let _ = build;
}

#[test]
fn base_input_frames_accept_application_owned_content() {
    let _ = gpui_base::InputBase::new("input").child(gpui::div());
    fn build_number(state: &gpui::Entity<gpui_base::input::InputState>) {
        let _ = gpui_base::NumberInput::new(state)
            .on_step(|_, _, _| {})
            .decrement_button(|button| button.child("-"))
            .increment_button(|button| button.child("+"))
            .input(gpui::div())
            .child(gpui::div());
    }
    let _ = build_number;
    let _ = gpui_base::NumberInputText::new().child(gpui::div());

    let _: gpui_base::StepAction = gpui_component::input::StepAction::Increment;
}

#[test]
fn base_input_accepts_application_owned_highlighters() {
    struct CustomHighlighter;

    impl gpui_base::input::InputHighlighter for CustomHighlighter {
        fn language(&self) -> gpui::SharedString {
            "custom".into()
        }

        fn update(
            &mut self,
            _: Option<gpui_base::input::InputEdit>,
            _: &gpui_base::input::Rope,
            _: bool,
            _: &mut gpui::Window,
            _: &mut gpui::Context<gpui_base::input::EditorState>,
        ) {
        }

        fn styles(
            &self,
            _: &std::ops::Range<usize>,
            _: &dyn gpui_base::input::HighlightStyleResolver,
        ) -> Vec<(std::ops::Range<usize>, gpui::HighlightStyle)> {
            Vec::new()
        }

        fn fold_ranges(&self, _: &gpui_base::input::Rope) -> Vec<gpui_base::input::FoldRange> {
            Vec::new()
        }
    }

    let factory: gpui_base::input::InputHighlighterFactory =
        std::rc::Rc::new(|_| Some(Box::new(CustomHighlighter)));
    let _ = factory;
}

#[test]
fn legacy_list_settings_are_the_base_type() {
    fn accepts_base(_: gpui_base::ListSettings) {}
    accepts_base(gpui_component::list::ListSettings::default());
}

#[test]
fn legacy_global_state_is_the_base_type() {
    fn accepts_base(_: &gpui_base::GlobalState) {}
    fn through_legacy(state: &gpui_component::GlobalState) {
        accepts_base(state);
    }

    let _ = through_legacy;
}

#[test]
fn legacy_popover_state_is_the_base_type() {
    fn accepts_base(_: &gpui_base::PopoverState) {}
    fn through_legacy(state: &gpui_component::popover::PopoverState) {
        accepts_base(state);
    }

    let _ = through_legacy;
}

#[test]
fn legacy_hover_card_state_is_the_base_type() {
    fn accepts_base(_: &gpui_base::HoverCardState) {}
    fn through_legacy(state: &gpui_component::hover_card::HoverCardState) {
        accepts_base(state);
    }

    let _ = through_legacy;
}

#[test]
fn base_tooltip_positioner_uses_normal_children() {
    let _ = gpui_base::Tooltip::new("tooltip-popup")
        .child("Tooltip")
        .child("⌘K");
    let _ = gpui_base::TooltipPositioner::new(gpui::Bounds::default())
        .placement(gpui_component::Placement::Right)
        .child("Tooltip");
}

#[test]
fn transition_ids_accept_strings_and_named_channels() {
    let _: gpui_base::TransitionId = "opacity".into();
    let _: gpui_base::TransitionId = ("checkbox", "fill").into();

    fn requires_interpolation<T: gpui_base::Interpolate>() {}
    requires_interpolation::<f32>();
}

#[test]
fn legacy_styled_and_sizing_exports_remain_available() {
    use gpui_component::Sizable as _;

    let _: gpui_component::Size = gpui_component::Size::Medium;
    let _ = gpui_component::StyledExt::font_medium(gpui::div());
    let _ = gpui_component::h_flex();
    let _ = gpui_component::v_flex();
    let _ = gpui_component::box_shadow(0., 0., 0., 0., gpui::hsla(0., 0., 0., 0.));

    struct SizedValue;
    impl gpui_component::Sizable for SizedValue {
        fn with_size(self, _: impl Into<gpui_component::Size>) -> Self {
            self
        }
    }
    let _ = SizedValue.small();
}

#[test]
fn element_ext_is_available_from_base_and_the_legacy_root() {
    use gpui_component::ElementExt as _;

    fn requires_base<T: gpui_base::ElementExt>() {}
    fn requires_legacy<T: gpui_component::ElementExt>() {}
    requires_base::<gpui::Div>();
    requires_legacy::<gpui::Div>();

    let _ = gpui::div().on_prepaint(|_, _, _| {});
}

#[test]
fn legacy_history_path_reexports_the_base_type() {
    let _: gpui_component::history::History<u8> = gpui_base::History::new();
    let _: gpui_component::history::UndoHistory<u8> = gpui_base::UndoHistory::new();
}

#[test]
fn legacy_auto_scroll_path_reexports_the_base_type() {
    fn through_legacy_path(scroll: gpui_base::AutoScroll) -> gpui_component::scroll::AutoScroll {
        scroll
    }

    let _ = through_legacy_path(gpui_base::AutoScroll::default());
}

#[test]
fn root_resizable_paths_reexport_base_types() {
    fn state_through_facade(state: gpui_base::ResizableState) -> gpui_component::ResizableState {
        state
    }

    fn group_through_facade(
        group: gpui_base::ResizablePanelGroup,
    ) -> gpui_component::ResizablePanelGroup {
        group
    }

    fn panel_through_facade(panel: gpui_base::ResizablePanel) -> gpui_component::ResizablePanel {
        panel
    }

    let _ = state_through_facade(gpui_base::ResizableState::default());
    let _ = group_through_facade(gpui_base::ResizablePanelGroup::new("group"));
    let _ = panel_through_facade(gpui_base::resizable_panel());
    let _ = gpui_component::h_resizable("horizontal");
    let _ = gpui_component::v_resizable("vertical");
}

#[test]
fn legacy_resizable_module_paths_remain_available() {
    fn panel_through_legacy(
        panel: gpui_base::ResizablePanel,
    ) -> gpui_component::resizable::ResizablePanel {
        panel
    }

    let _ = panel_through_legacy(gpui_base::resizable_panel());
    let _ = gpui_component::resizable::h_resizable("horizontal");
    let _ = gpui_component::resizable::v_resizable("vertical");
}
