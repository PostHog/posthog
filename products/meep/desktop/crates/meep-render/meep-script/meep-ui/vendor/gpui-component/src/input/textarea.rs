use std::rc::Rc;

use gpui::{
    App, DefiniteLength, Entity, IntoElement, RenderOnce, SharedString, StyleRefinement, Styled,
    Window, prelude::FluentBuilder as _,
};

use super::{Input, TextareaState};
use crate::native_menu::NativeMenu;
use crate::{RoleOverride, Sizable, Size, StyledExt as _};

/// A styled ordinary multi-line text field.
#[derive(IntoElement)]
pub struct Textarea {
    token_renderer: Option<gpui_base::input::InlineTokenRenderer>,
    token_click_listener: Option<gpui_base::input::InlineTokenClickListener>,
    token_hover_listener: Option<gpui_base::input::InlineTokenHoverListener>,
    state: Entity<TextareaState>,
    style: StyleRefinement,
    size: Size,
    height: Option<DefiniteLength>,
    appearance: bool,
    bordered: bool,
    disabled: bool,
    readonly: bool,
    tab_index: isize,
    role: RoleOverride,
    accessibility_id: Option<SharedString>,
    aria_label: Option<SharedString>,

    /// An optional context menu builder to allow a custom context menu.
    ///
    /// If set, this overrides the built-in context menu.
    context_menu_builder: Option<Rc<dyn Fn(NativeMenu, &mut Window, &mut App) -> NativeMenu>>,

    paste_handler: Option<Rc<dyn Fn(&gpui::ClipboardItem, &mut Window, &mut App) -> bool>>,
}

impl Textarea {
    /// The element each atomic inline token renders as, in place of the default
    /// [`InputToken`](super::InputToken); editing and history stay
    /// with the input.
    pub fn token<R: IntoElement>(
        mut self,
        render: impl Fn(&super::InlineTokenContext, &mut Window, &mut App) -> R + 'static,
    ) -> Self {
        self.token_renderer = Some(Rc::new(move |token, window, cx| {
            render(token, window, cx).into_any_element()
        }));
        self
    }
    /// Open a reference after a completed, unconsumed token click.
    pub fn on_token_click(
        mut self,
        listener: impl Fn(&super::InlineTokenClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.token_click_listener = Some(Rc::new(listener));
        self
    }
    /// Report pointer presence over a token so the application can show a
    /// tooltip or run custom logic. Hover never selects or edits.
    pub fn on_token_hover(
        mut self,
        listener: impl Fn(&super::InlineTokenHoverEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.token_hover_listener = Some(Rc::new(listener));
        self
    }

    pub fn new(state: &Entity<TextareaState>) -> Self {
        Self {
            state: state.clone(),
            style: StyleRefinement::default(),
            size: Size::default(),
            height: None,
            appearance: true,
            bordered: true,
            disabled: false,
            readonly: false,
            tab_index: 0,
            role: RoleOverride::default(),
            accessibility_id: None,
            aria_label: None,
            context_menu_builder: None,
            paste_handler: None,
            token_renderer: None,
            token_click_listener: None,
            token_hover_listener: None,
        }
    }

    pub fn h(mut self, height: impl Into<DefiniteLength>) -> Self {
        self.height = Some(height.into());
        self
    }

    pub fn appearance(mut self, appearance: bool) -> Self {
        self.appearance = appearance;
        self
    }

    pub fn bordered(mut self, bordered: bool) -> Self {
        self.bordered = bordered;
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Set the textarea to read-only, default is `false`.
    ///
    /// Unlike [`Self::disabled`], a read-only textarea keeps the normal appearance
    /// and still can be focused, selected and copied, it only rejects the changes
    /// made by the user.
    pub fn readonly(mut self, readonly: bool) -> Self {
        self.readonly = readonly;
        self
    }

    pub fn tab_index(mut self, index: isize) -> Self {
        self.tab_index = index;
        self
    }

    pub fn role(mut self, role: impl Into<RoleOverride>) -> Self {
        self.role = role.into();
        self
    }

    /// Set the developer-assigned accessibility identifier.
    pub fn accessibility_id(mut self, id: impl Into<SharedString>) -> Self {
        self.accessibility_id = Some(id.into());
        self
    }

    pub fn aria_label(mut self, label: impl Into<SharedString>) -> Self {
        self.aria_label = Some(label.into());
        self
    }

    /// Replace the built-in context menu shown on right-click.
    ///
    /// The closure receives an empty menu and returns the one to show, so it
    /// decides entirely what appears — the default items are not added. It
    /// shows only while the state's context menu is enabled, which is the
    /// default.
    pub fn context_menu(
        mut self,
        f: impl Fn(NativeMenu, &mut Window, &mut App) -> NativeMenu + 'static,
    ) -> Self {
        self.context_menu_builder = Some(Rc::new(f));
        self
    }

    /// Intercept paste payloads (images, files) before the default text insertion.
    ///
    /// `true` consumes the paste so nothing is inserted, `false` falls through
    /// to `clipboard.text()`. Copied files arrive as `ExternalPaths` through
    /// the same hook. On web the clipboard reads `None`; image paste needs
    /// async clipboard access and is out of scope.
    pub fn on_paste(
        mut self,
        handler: impl Fn(&gpui::ClipboardItem, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.paste_handler = Some(Rc::new(handler));
        self
    }
}

impl Sizable for Textarea {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for Textarea {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Textarea {
    /// The [`Input`] this textarea renders, for a compound control that frames
    /// it.
    pub(crate) fn into_input(self) -> Input {
        Input::from_state(self.state.clone())
            .when_some(self.token_renderer, |this, render| {
                this.token(move |token, window, cx| render(token, window, cx))
            })
            .when_some(self.token_click_listener, |this, listener| {
                this.on_token_click(move |event, window, cx| listener(event, window, cx))
            })
            .when_some(self.token_hover_listener, |this, listener| {
                this.on_token_hover(move |event, window, cx| listener(event, window, cx))
            })
            .appearance(self.appearance)
            .bordered(self.bordered)
            .disabled(self.disabled)
            .readonly(self.readonly)
            .tab_index(self.tab_index)
            .role(self.role)
            .with_size(self.size)
            .when_some(self.height, |this, height| this.h(height))
            .when_some(self.accessibility_id, |this, id| this.accessibility_id(id))
            .when_some(self.aria_label, |this, label| this.aria_label(label))
            .when_some(self.context_menu_builder, |this, build| {
                this.context_menu(move |menu, window, cx| build(menu, window, cx))
            })
            .when_some(self.paste_handler, |this, handler| {
                this.on_paste(move |item, window, cx| handler(item, window, cx))
            })
            .refine_style(&self.style)
    }
}

impl RenderOnce for Textarea {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.into_input()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[gpui::test]
    fn test_on_paste_builder(cx: &mut gpui::TestAppContext) {
        use gpui::{AppContext as _, Render};

        struct Probe;
        impl Render for Probe {
            fn render(
                &mut self,
                _: &mut Window,
                _: &mut gpui::Context<Self>,
            ) -> impl gpui::IntoElement {
                gpui::div()
            }
        }

        cx.update(crate::init);
        let _ = cx.add_window_view(|window, cx| {
            let state = cx.new(|cx| TextareaState::new(window, cx));
            assert!(Textarea::new(&state).paste_handler.is_none());
            let textarea = Textarea::new(&state).on_paste(|_, _, _| true);
            assert!(textarea.paste_handler.is_some());
            Probe
        });
    }

    #[gpui::test]
    fn test_on_token_hover_builder(cx: &mut gpui::TestAppContext) {
        use gpui::{AppContext as _, Render};

        struct Probe;
        impl Render for Probe {
            fn render(
                &mut self,
                _: &mut Window,
                _: &mut gpui::Context<Self>,
            ) -> impl gpui::IntoElement {
                gpui::div()
            }
        }

        cx.update(crate::init);
        let _ = cx.add_window_view(|window, cx| {
            let state = cx.new(|cx| TextareaState::new(window, cx));
            assert!(Textarea::new(&state).token_hover_listener.is_none());
            let textarea = Textarea::new(&state).on_token_hover(|_, _, _| {});
            assert!(textarea.token_hover_listener.is_some());
            Probe
        });
    }
}
