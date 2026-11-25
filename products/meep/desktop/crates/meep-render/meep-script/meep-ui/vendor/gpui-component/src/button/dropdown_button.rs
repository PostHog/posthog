use gpui::Corners;
use gpui::{
    Anchor, App, Context, Edges, ElementId, InteractiveElement as _, IntoElement, ParentElement,
    RenderOnce, SharedString, StyleRefinement, Styled, Window, div, prelude::FluentBuilder,
};
use rust_i18n::t;

use crate::{
    Disableable, Selectable, Sizable, Size, StyledExt as _,
    menu::{DropdownMenu, PopupMenu},
};

use super::{Button, ButtonVariant, ButtonVariants};

/// Group name shared by both halves, so hovering one can style the other.
const HALVES_GROUP: &str = "dropdown-button";

/// A split button: an action button with an attached menu trigger.
///
/// The two halves stay visually joined. A `ghost` split is transparent at
/// rest; hovering either half surfaces the whole control with the hovered half
/// emphasized, and it stays surfaced while the menu is open, so the pair reads
/// as one control rather than two buttons.
///
#[derive(IntoElement)]
pub struct DropdownButton {
    id: ElementId,
    style: StyleRefinement,
    button: Option<Button>,
    menu:
        Option<Box<dyn Fn(PopupMenu, &mut Window, &mut Context<PopupMenu>) -> PopupMenu + 'static>>,
    selected: bool,
    disabled: bool,
    menu_accessibility_label: Option<SharedString>,
    // The button props, applied to both halves. Unset means the inner
    // [`Button`] keeps whatever it was given.
    outline: bool,
    variant: Option<ButtonVariant>,
    size: Option<Size>,
    anchor: Anchor,
}

impl DropdownButton {
    /// Create a new DropdownButton.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            button: None,
            menu: None,
            selected: false,
            disabled: false,
            menu_accessibility_label: None,
            outline: false,
            variant: None,
            size: None,
            anchor: Anchor::TopRight,
        }
    }

    fn effective_variant(&self) -> ButtonVariant {
        self.variant
            .or_else(|| self.button.as_ref().map(Button::variant))
            .unwrap_or_default()
    }

    fn effective_size(&self) -> Size {
        self.size
            .or_else(|| self.button.as_ref().map(Button::button_size))
            .unwrap_or_default()
    }

    /// Set the left button of the dropdown button.
    ///
    /// The button keeps its own label, icon, tooltip and click handler. A
    /// variant or size set on the [`DropdownButton`] applies to both halves and
    /// overrides the one set here. When either outer value is unset, this
    /// button's value becomes the shared value for both halves.
    pub fn button(mut self, button: Button) -> Self {
        self.button = Some(button);
        self
    }

    /// Set the dropdown menu of the button.
    pub fn dropdown_menu(
        mut self,
        menu: impl Fn(PopupMenu, &mut Window, &mut Context<PopupMenu>) -> PopupMenu + 'static,
    ) -> Self {
        self.menu = Some(Box::new(menu));
        self
    }

    /// Set the dropdown menu of the button with anchor corner.
    pub fn dropdown_menu_with_anchor(
        mut self,
        anchor: impl Into<Anchor>,
        menu: impl Fn(PopupMenu, &mut Window, &mut Context<PopupMenu>) -> PopupMenu + 'static,
    ) -> Self {
        self.menu = Some(Box::new(menu));
        self.anchor = anchor.into();
        self
    }

    /// Set the name a screen reader announces for the menu trigger. Defaults
    /// to the localized "More options".
    ///
    /// The trigger shows only a caret, so it has no visible label to read.
    /// The inner [`Button`] names the action half.
    pub fn menu_accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.menu_accessibility_label = Some(label.into());
        self
    }

    /// Set the button to outline style.
    ///
    /// See also: [`Button::outline`]
    pub fn outline(mut self) -> Self {
        self.outline = true;
        self
    }
}

impl Disableable for DropdownButton {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl Styled for DropdownButton {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl Sizable for DropdownButton {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl ButtonVariants for DropdownButton {
    fn with_variant(mut self, variant: ButtonVariant) -> Self {
        self.variant = Some(variant);
        self
    }
}

impl Selectable for DropdownButton {
    fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    fn is_selected(&self) -> bool {
        self.selected
    }
}

impl RenderOnce for DropdownButton {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        debug_assert!(
            self.button.is_some() || self.menu.is_some(),
            "a DropdownButton needs a `button`, a `dropdown_menu`, or both"
        );

        let variant = self.effective_variant();
        let size = self.effective_size();
        let selected = self.selected || self.button.as_ref().is_some_and(Selectable::is_selected);
        // Only a ghost split has no surface at rest, so only it needs hovering
        // one half to reveal the other, and the action half to stay revealed
        // while the menu holds the trigger pressed.
        let is_ghost = variant.is_ghost();
        let menu_open = window.use_keyed_state(self.id.clone(), cx, |_, _| false);
        let is_menu_open = *menu_open.read(cx);

        div()
            .id(self.id)
            .when(is_ghost, |this| this.group(HALVES_GROUP))
            .h_flex()
            .refine_style(&self.style)
            .when_some(self.button, |this, button| {
                let disabled = self.disabled || button.is_disabled();
                this.child(
                    button
                        .border_corners(Corners {
                            top_left: true,
                            top_right: false,
                            bottom_left: true,
                            bottom_right: false,
                        })
                        .border_edges(Edges::all(true))
                        .selected(selected)
                        .disabled(disabled)
                        .when(self.outline, |this| this.outline())
                        .with_size(size)
                        .with_variant(variant)
                        .when(is_ghost, |this| {
                            this.hover_group(HALVES_GROUP)
                                .hover_group_held(is_menu_open)
                        }),
                )
            })
            .when_some(self.menu, |this, menu| {
                this.child(
                    Button::new("popup")
                        .dropdown_caret(true)
                        .accessibility_label(
                            self.menu_accessibility_label
                                .unwrap_or_else(|| t!("DropdownButton.more_options").into()),
                        )
                        .border_corners(Corners {
                            top_left: false,
                            top_right: true,
                            bottom_left: false,
                            bottom_right: true,
                        })
                        .border_edges(Edges {
                            left: false,
                            top: true,
                            right: true,
                            bottom: true,
                        })
                        .selected(selected)
                        .disabled(self.disabled)
                        .when(self.outline, |this| this.outline())
                        .with_size(size)
                        .with_variant(variant)
                        .when(is_ghost, |this| this.hover_group(HALVES_GROUP))
                        .dropdown_menu_with_anchor(self.anchor, menu)
                        .on_open_change(move |open, _, cx| {
                            menu_open.update(cx, |state, cx| {
                                *state = *open;
                                cx.notify();
                            })
                        }),
                )
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[gpui::test]
    fn test_dropdown_button_builder(_cx: &mut gpui::TestAppContext) {
        let button = Button::new("inner").label("Action");
        let dropdown = DropdownButton::new("complex-dropdown")
            .button(button)
            .primary()
            .outline()
            .large()
            .disabled(false)
            .selected(false)
            .dropdown_menu_with_anchor(Anchor::BottomLeft, |menu, _, _| menu);

        assert!(dropdown.button.is_some());
        assert_eq!(dropdown.variant, Some(ButtonVariant::Primary));
        assert!(dropdown.outline);
        assert_eq!(dropdown.size, Some(Size::Large));
        assert!(!dropdown.disabled);
        assert!(!dropdown.selected);
        assert!(dropdown.menu.is_some());
        assert_eq!(dropdown.anchor, Anchor::BottomLeft);
    }

    /// An unset variant or size leaves the inner button's own to survive, so a
    /// caller can style the halves from either level.
    #[gpui::test]
    fn inner_button_keeps_its_own_variant_and_size(_cx: &mut gpui::TestAppContext) {
        let dropdown = DropdownButton::new("dropdown")
            .button(Button::new("inner").label("Action").danger().small())
            .dropdown_menu(|menu, _, _| menu);

        assert_eq!(dropdown.variant, None);
        assert_eq!(dropdown.size, None);
    }

    #[gpui::test]
    fn inner_ghost_becomes_the_split_variant(_cx: &mut gpui::TestAppContext) {
        let dropdown = DropdownButton::new("dropdown")
            .button(Button::new("inner").label("Action").ghost())
            .dropdown_menu(|menu, _, _| menu);

        assert_eq!(dropdown.effective_variant(), ButtonVariant::Ghost);
    }

    #[gpui::test]
    fn inner_size_becomes_the_split_size(_cx: &mut gpui::TestAppContext) {
        let dropdown = DropdownButton::new("dropdown")
            .button(Button::new("inner").label("Action").small())
            .dropdown_menu(|menu, _, _| menu);

        assert_eq!(dropdown.effective_size(), Size::Small);
    }
}
