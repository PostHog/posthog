use crate::{StateStyle, StyledExt as _, TestSupportExt as _};
use gpui::{
    AnyElement, App, Div, ElementId, InteractiveElement, Interactivity, IntoElement, ParentElement,
    Refineable as _, RenderOnce, Role, SharedString, StatefulInteractiveElement, StyleRefinement,
    Styled, Window, div, prelude::FluentBuilder as _,
};

/// What the input can offer to its context menu, at the moment it is opened.
///
/// Built by the input and read by the menu, the fields are private and reached
/// through the methods below, so that a new capability can be added without
/// breaking the menu builders.
///
/// ```
/// use gpui_base::input::InputContextMenuCapabilities;
///
/// let capabilities = InputContextMenuCapabilities::new()
///     .code_editor(true)
///     .selection(true);
///
/// assert!(capabilities.is_editable());
/// assert!(capabilities.has_selection());
/// ```
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct InputContextMenuCapabilities {
    disabled: bool,
    readonly: bool,
    code_editor: bool,
    selection: bool,
    masked: bool,
    go_to_definition: bool,
    code_actions: bool,
}

impl InputContextMenuCapabilities {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn readonly(mut self, readonly: bool) -> Self {
        self.readonly = readonly;
        self
    }

    pub fn code_editor(mut self, code_editor: bool) -> Self {
        self.code_editor = code_editor;
        self
    }

    /// Set whether the input has a non-empty selection.
    pub fn selection(mut self, selection: bool) -> Self {
        self.selection = selection;
        self
    }

    /// Set whether the input renders its value masked.
    pub fn masked(mut self, masked: bool) -> Self {
        self.masked = masked;
        self
    }

    pub fn go_to_definition(mut self, go_to_definition: bool) -> Self {
        self.go_to_definition = go_to_definition;
        self
    }

    pub fn code_actions(mut self, code_actions: bool) -> Self {
        self.code_actions = code_actions;
        self
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn is_readonly(&self) -> bool {
        self.readonly
    }

    /// Returns true if the user is allowed to change the text.
    ///
    /// The items that write to the input (Cut, Paste, Code Actions) belong to
    /// this, the reading ones (Copy, Go to Definition) do not.
    pub fn is_editable(&self) -> bool {
        !self.disabled && !self.readonly
    }

    pub fn is_code_editor(&self) -> bool {
        self.code_editor
    }

    pub fn has_selection(&self) -> bool {
        self.selection
    }

    pub fn is_masked(&self) -> bool {
        self.masked
    }

    /// Returns true if the user is allowed to copy the text out.
    ///
    /// A masked input keeps its value out of the clipboard, so Copy and Cut
    /// are both unavailable while the value is hidden.
    pub fn is_copyable(&self) -> bool {
        self.selection && !self.masked
    }

    pub fn has_definition(&self) -> bool {
        self.go_to_definition
    }

    pub fn has_code_actions(&self) -> bool {
        self.code_actions
    }
}

/// The foundational input frame.
///
/// It intentionally owns only input semantics, interaction forwarding, and
/// normal children. Applications remain responsible for all presentation.
#[derive(IntoElement)]
pub struct InputBase {
    base: crate::ObservedElement<gpui::Stateful<Div>>,
    style: StyleRefinement,
    semantic_styles: InputStyles,
    children: Vec<AnyElement>,
    focused: bool,
    disabled: bool,
    role: crate::RoleOverride,
}

impl InputBase {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id).test_support(),
            style: StyleRefinement::default(),
            semantic_styles: InputStyles::default(),
            children: Vec::new(),
            focused: false,
            disabled: false,
            role: crate::RoleOverride::Implicit,
        }
    }
    pub fn role(mut self, role: impl Into<crate::RoleOverride>) -> Self {
        self.role = role.into();
        self
    }

    pub fn focused(mut self, focused: bool) -> Self {
        self.focused = focused;
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Exposes an editor's native semantics through this frame's component ID.
    ///
    /// `editor` must identify the input, textarea or editor state rendered below
    /// this frame, without intervening element IDs. Anonymous layout wrappers
    /// are allowed. ID queries retain the frame's path, bounds and visibility.
    /// Role, label, value, checked/indeterminate, selected, expanded, disabled
    /// and focus facts come from the editor's existing native node and observed
    /// focus scope, not independently focusable addon controls. Native snapshot
    /// enumeration is unchanged, so role/label queries do not duplicate editors.
    ///
    /// This only declares an observation relationship with `test-support`; it
    /// never adds a native accessibility node or registers a focus handle. The
    /// relationship follows the frame's GPUI element-state lifetime.
    pub fn semantic_owner(self, editor: gpui::EntityId) -> Self {
        #[cfg(feature = "test-support")]
        {
            Self {
                base: self.base.semantic_owner([
                    ElementId::View(editor),
                    super::state::EDITOR_ELEMENT_ID.into(),
                ]),
                ..self
            }
        }
        #[cfg(not(feature = "test-support"))]
        {
            let _ = editor;
            self
        }
    }

    pub fn styles(mut self, build: impl FnOnce(InputStyles) -> InputStyles) -> Self {
        self.semantic_styles = build(self.semantic_styles);
        self
    }

    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.base = self.base.aria_label(label.into());
        self
    }

    fn resolved_style(&self) -> StyleRefinement {
        crate::state_style::resolve_style(
            &self.style,
            [
                self.focused.then_some(&self.semantic_styles.focused),
                self.disabled.then_some(&self.semantic_styles.disabled),
            ]
            .into_iter()
            .flatten(),
        )
    }
}

#[derive(Default)]
pub struct InputStyles {
    focused: StyleRefinement,
    disabled: StyleRefinement,
}

impl InputStyles {
    pub fn focused(mut self, build: impl FnOnce(StateStyle) -> StateStyle) -> Self {
        self.focused
            .refine(&build(StateStyle::default()).into_refinement());
        self
    }

    pub fn disabled(mut self, build: impl FnOnce(StateStyle) -> StateStyle) -> Self {
        self.disabled
            .refine(&build(StateStyle::default()).into_refinement());
        self
    }
}

impl Styled for InputBase {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for InputBase {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for InputBase {
    fn track_focus(mut self, focus: &gpui::FocusHandle) -> Self {
        self.base = self.base.track_focus(focus);
        self
    }

    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for InputBase {}

impl RenderOnce for InputBase {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let style = self.resolved_style();
        self.base
            .when_some(self.role.resolve(|| Role::TextInput), |this, role| {
                this.role(role)
            })
            .children(self.children)
            .refine_style(&style)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frame_accepts_application_owned_content_and_style() {
        let _ = InputBase::new("input")
            .focused(true)
            .disabled(false)
            .styles(|styles| {
                styles
                    .focused(|style| style.border_1())
                    .disabled(|style| style.opacity(0.5))
            })
            .child("value")
            .opacity(0.8);
    }

    #[test]
    fn semantic_state_styles_override_the_normal_style() {
        let focused = InputBase::new("focused")
            .focused(true)
            .border_color(gpui::red())
            .styles(|styles| styles.focused(|style| style.border_color(gpui::blue())));
        assert_eq!(focused.resolved_style().border_color, Some(gpui::blue()));

        let disabled = InputBase::new("disabled")
            .focused(true)
            .disabled(true)
            .opacity(1.)
            .styles(|styles| {
                styles
                    .focused(|style| style.opacity(0.8))
                    .disabled(|style| style.opacity(0.5))
            });
        assert_eq!(disabled.resolved_style().opacity, Some(0.5));
    }
}
