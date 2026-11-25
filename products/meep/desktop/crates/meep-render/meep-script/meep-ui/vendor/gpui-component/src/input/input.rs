use std::rc::Rc;

use gpui::prelude::FluentBuilder as _;
use gpui::{
    AnyElement, App, DefiniteLength, Edges, ElementId, Entity, Global, Hsla,
    InteractiveElement as _, IntoElement, MouseButton, ParentElement as _, Rems, RenderOnce, Role,
    SharedString, StyleRefinement, Styled, TextAlign, TouchPhase, Window, div, px, relative,
};

use crate::button::{Button, ButtonRounded, ButtonVariants as _};
use crate::input::clear_button;
use crate::native_menu::NativeMenu;
use crate::spinner::Spinner;
use crate::touch_selection::{EditMenuItem, TouchSelectionOverlay};
use crate::{ActiveTheme, Colorize, v_flex};
use crate::{IconName, Size};
use crate::{RoleOverride, Selectable, StyledExt, h_flex};
use crate::{Sizable, StyleSized};
use gpui_base::InputBase as BaseInput;
use rust_i18n::t;

use super::state::{TextInputState, sync_focused_input_registry};
use super::{InputContentType, InputState, sync_native_content_type};
use crate::ThemeStyled as _;

/// Set when the platform draws the touch selection UI of a focused input.
#[derive(Default)]
struct NativeTouchSelection(bool);
impl Global for NativeTouchSelection {}

/// Let the platform draw the touch selection UI of a focused [`Input`]: the
/// selection handles and the edit menu a long press leaves behind.
///
/// Use it on a host that already shows its own text UI over the window, such
/// as Android's floating toolbar and drag handles. The long press still
/// selects a word; the platform follows that selection and drives it back
/// through the window's input handler. Selections in plain text, outside an
/// input, keep the handles and menu drawn here.
pub fn set_native_touch_selection(enabled: bool, cx: &mut App) {
    cx.set_global(NativeTouchSelection(enabled));
    cx.refresh_windows();
}

fn is_native_touch_selection(cx: &App) -> bool {
    cx.try_global::<NativeTouchSelection>()
        .is_some_and(|native| native.0)
}

fn accessibility_role(
    is_multi_line: bool,
    content_type: Option<InputContentType>,
    role: RoleOverride,
) -> Option<Role> {
    role.resolve(|| {
        if is_multi_line {
            return Role::MultilineTextInput;
        }

        match content_type {
            None => Role::TextInput,
            Some(InputContentType::TelephoneNumber) => Role::PhoneNumberInput,
            Some(InputContentType::EmailAddress) => Role::EmailInput,
            Some(InputContentType::Url) => Role::UrlInput,
            Some(InputContentType::Password | InputContentType::NewPassword) => Role::PasswordInput,
            Some(InputContentType::DateTime) => Role::DateTimeInput,
            Some(InputContentType::Birthdate) => Role::DateInput,
            Some(
                InputContentType::Name
                | InputContentType::NamePrefix
                | InputContentType::GivenName
                | InputContentType::MiddleName
                | InputContentType::FamilyName
                | InputContentType::NameSuffix
                | InputContentType::Nickname
                | InputContentType::JobTitle
                | InputContentType::OrganizationName
                | InputContentType::Location
                | InputContentType::FullStreetAddress
                | InputContentType::StreetAddressLine1
                | InputContentType::StreetAddressLine2
                | InputContentType::AddressCity
                | InputContentType::AddressState
                | InputContentType::AddressCityAndState
                | InputContentType::Sublocality
                | InputContentType::CountryName
                | InputContentType::PostalCode
                | InputContentType::CreditCardNumber
                | InputContentType::CreditCardName
                | InputContentType::CreditCardGivenName
                | InputContentType::CreditCardMiddleName
                | InputContentType::CreditCardFamilyName
                | InputContentType::CreditCardSecurityCode
                | InputContentType::CreditCardExpiration
                | InputContentType::CreditCardExpirationMonth
                | InputContentType::CreditCardExpirationYear
                | InputContentType::CreditCardType
                | InputContentType::Username
                | InputContentType::OneTimeCode
                | InputContentType::ShipmentTrackingNumber
                | InputContentType::FlightNumber
                | InputContentType::BirthdateDay
                | InputContentType::BirthdateMonth
                | InputContentType::BirthdateYear
                | InputContentType::CellularEid
                | InputContentType::CellularImei,
            ) => Role::TextInput,
        }
    })
}

fn exposes_accessibility_value(content_type: Option<InputContentType>) -> bool {
    !matches!(
        content_type,
        Some(InputContentType::Password | InputContentType::NewPassword)
    )
}

/// Returns `(background, foreground)` colors for input-like components.
pub(crate) fn input_style(disabled: bool, cx: &App) -> (Hsla, Hsla) {
    if disabled {
        (
            cx.theme().input.mix_oklab(cx.theme().transparent, 0.8),
            cx.theme().muted_foreground,
        )
    } else {
        (cx.theme().input_background(), cx.theme().foreground)
    }
}

/// A text input element bind to an [`InputState`].
#[derive(IntoElement)]
pub struct Input {
    token_renderer: Option<gpui_base::input::InlineTokenRenderer>,
    token_click_listener: Option<gpui_base::input::InlineTokenClickListener>,
    token_hover_listener: Option<gpui_base::input::InlineTokenHoverListener>,
    id: Option<ElementId>,
    state: TextInputState,
    style: StyleRefinement,
    size: Size,
    prefix: Option<AnyElement>,
    suffix: Option<AnyElement>,
    height: Option<DefiniteLength>,
    appearance: bool,
    cleanable: bool,
    mask_toggle: bool,
    disabled: bool,
    readonly: bool,
    bordered: bool,
    focus_bordered: bool,
    tab_index: isize,
    selected: bool,
    content_type: Option<InputContentType>,
    role: RoleOverride,
    accessibility_id: Option<SharedString>,
    aria_label: Option<SharedString>,

    /// An optional context menu builder to allow a custom context menu on the input.
    ///
    /// If set, this overrides the built-in context menu.
    context_menu_builder: Option<Rc<dyn Fn(NativeMenu, &mut Window, &mut App) -> NativeMenu>>,

    /// An optional paste handler. If set, it is invoked with the clipboard item
    /// before the default text insertion. Return `true` if handled.
    paste_handler: Option<Rc<dyn Fn(&gpui::ClipboardItem, &mut Window, &mut App) -> bool>>,
}

impl Sizable for Input {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Selectable for Input {
    fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    fn is_selected(&self) -> bool {
        self.selected
    }
}

impl crate::FocusableExt for Input {
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_bordered = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_bordered
    }
}

impl Input {
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

    /// Sets the GPUI identity of the input frame. By default it uses the state entity ID.
    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = Some(id.into());
        self
    }

    /// Create a new [`Input`] element bind to the [`InputState`].
    pub fn new(state: &Entity<InputState>) -> Self {
        Self::with_state(state.clone().into())
    }

    /// Builds an input renderer around a state of any kind.
    ///
    /// `Textarea` and `Editor` render through this. Application code uses
    /// [`Input::new`], [`super::Textarea`], or [`super::Editor`].
    pub(crate) fn from_state(state: impl Into<TextInputState>) -> Self {
        Self::with_state(state.into())
    }

    fn with_state(state: TextInputState) -> Self {
        Self {
            id: None,
            state,
            size: Size::default(),
            style: StyleRefinement::default(),
            prefix: None,
            suffix: None,
            height: None,
            appearance: true,
            cleanable: false,
            mask_toggle: false,
            disabled: false,
            readonly: false,
            bordered: true,
            focus_bordered: true,
            tab_index: 0,
            selected: false,
            content_type: None,
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

    /// Set the developer-assigned identifier exposed to accessibility clients.
    /// The state this input renders; a compound control reads focus and
    /// presentation from it.
    pub(crate) fn state(&self) -> &TextInputState {
        &self.state
    }

    pub(crate) fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn accessibility_id(mut self, id: impl Into<SharedString>) -> Self {
        self.accessibility_id = Some(id.into());
        self
    }

    pub fn aria_label(mut self, label: impl Into<SharedString>) -> Self {
        self.aria_label = Some(label.into());
        self
    }

    pub fn prefix(mut self, prefix: impl IntoElement) -> Self {
        self.prefix = Some(prefix.into_any_element());
        self
    }

    pub fn suffix(mut self, suffix: impl IntoElement) -> Self {
        self.suffix = Some(suffix.into_any_element());
        self
    }

    /// Set full height of the input (Multi-line only).
    pub fn h_full(mut self) -> Self {
        self.height = Some(relative(1.));
        self
    }

    /// Set height of the input (Multi-line only).
    pub fn h(mut self, height: impl Into<DefiniteLength>) -> Self {
        self.height = Some(height.into());
        self
    }

    /// Set the appearance of the input field, if false the input field will no border, background.
    pub fn appearance(mut self, appearance: bool) -> Self {
        self.appearance = appearance;
        self
    }

    /// Set the bordered for the input, default: true
    pub fn bordered(mut self, bordered: bool) -> Self {
        self.bordered = bordered;
        self
    }

    /// Set focus border for the input, default is true.
    pub fn focus_bordered(mut self, bordered: bool) -> Self {
        self.focus_bordered = bordered;
        self
    }

    /// Set whether to show the clear button when the input field is not empty, default is false.
    pub fn cleanable(mut self, cleanable: bool) -> Self {
        self.cleanable = cleanable;
        self
    }

    /// Set to enable toggle button for password mask state.
    pub fn mask_toggle(mut self) -> Self {
        self.mask_toggle = true;
        self
    }

    /// Set the semantic content type for password managers and autofill.
    ///
    /// This is a component-level semantic hint. It does not change the text
    /// value or masked rendering state.
    pub fn content_type(mut self, content_type: InputContentType) -> Self {
        self.content_type = Some(content_type);
        self
    }

    /// Override the accessible role for the input.
    ///
    /// If unset, the role is inferred from multi-line mode and content type.
    pub fn role(mut self, role: impl Into<RoleOverride>) -> Self {
        self.role = role.into();
        self
    }

    /// Set to disable the input field.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Set the input field to read-only, default is `false`.
    ///
    /// Unlike [`Self::disabled`], a read-only input keeps the normal appearance
    /// and still can be focused, selected and copied, it only rejects the changes
    /// made by the user.
    pub fn readonly(mut self, readonly: bool) -> Self {
        self.readonly = readonly;
        self
    }

    /// Set the tab index for the input, default is 0.
    pub fn tab_index(mut self, index: isize) -> Self {
        self.tab_index = index;
        self
    }

    /// Sets a custom context menu builder for the input, shown as a native OS menu.
    ///
    /// If set, this overrides the built-in right-click context menu. It shows
    /// only while the state's context menu is enabled, which is the default.
    pub fn context_menu(
        mut self,
        f: impl Fn(NativeMenu, &mut Window, &mut App) -> NativeMenu + 'static,
    ) -> Self {
        self.context_menu_builder = Some(Rc::new(f));
        self
    }

    /// Intercept paste payloads (images, files) before the default text insertion.
    ///
    /// The handler receives the clipboard item and returns whether it took the
    /// paste: `true` stops the `input::Paste` action so the input inserts
    /// nothing, `false` lets it reach the engine, which inserts
    /// `clipboard.text()` as today. Text stays in the `Rope`; images and
    /// copied files (`ClipboardEntry::Image`, `ClipboardEntry::ExternalPaths`)
    /// belong in app-owned state beside the input (e.g. `Attachment`s), never
    /// inside it.
    ///
    /// Known limit: on web `read_from_clipboard()` is `None`, so the handler
    /// is skipped there and the input inserts the plain text itself (a
    /// keyboard paste arrives through the platform input handler, a menu
    /// paste through the asynchronous clipboard read); image paste there
    /// needs `read_from_clipboard_async` and permission, out of scope here.
    pub fn on_paste(
        mut self,
        handler: impl Fn(&gpui::ClipboardItem, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.paste_handler = Some(Rc::new(handler));
        self
    }

    /// The handles and the edit menu of the selection a long press made, unless
    /// the platform draws them; see [`set_native_touch_selection`].
    ///
    /// The menu offers what the native context menu would: Cut, Copy, Paste
    /// and Select All, leaving out what cannot apply right now rather than
    /// disabling it. Cut, Copy and Paste go through the input's actions, so a
    /// custom key binding or an open completion menu sees them the same way.
    fn render_touch_selection(
        state: &TextInputState,
        window: &Window,
        cx: &App,
    ) -> Vec<AnyElement> {
        if is_native_touch_selection(cx) || state.touch_selection(cx).is_none() {
            return Vec::new();
        }
        let capabilities = state.context_menu_capabilities(cx);
        let editable = capabilities.is_editable();
        let copyable = capabilities.is_copyable();
        // Offered whenever the text can change, without peeking at the
        // clipboard: on iOS every read of it shows the system's paste banner,
        // and an empty clipboard pastes nothing.
        let pasteable = editable;
        let selectable = state.text(cx).len() > 0 && !state.is_all_selected(cx);
        let focus_handle = state.presentation(cx).focus_handle().clone();

        let dispatch = {
            let focus_handle = focus_handle.clone();
            move |action: &dyn gpui::Action, window: &mut Window, cx: &mut App| {
                focus_handle.dispatch_action(action, window, cx);
            }
        };
        let mut items = Vec::with_capacity(4);
        if editable && copyable {
            let dispatch = dispatch.clone();
            items.push(EditMenuItem::new(t!("Input.Cut"), move |window, cx| {
                dispatch(&gpui_base::input::Cut, window, cx);
            }));
        }
        if copyable {
            let dispatch = dispatch.clone();
            let state = state.clone();
            items.push(EditMenuItem::new(t!("Input.Copy"), move |window, cx| {
                dispatch(&gpui_base::input::Copy, window, cx);
                state.close_edit_menu(cx);
            }));
        }
        if pasteable {
            let dispatch = dispatch.clone();
            items.push(EditMenuItem::new(t!("Input.Paste"), move |window, cx| {
                dispatch(&gpui_base::input::Paste, window, cx);
            }));
        }
        if selectable {
            let state = state.clone();
            items.push(EditMenuItem::new(
                t!("Input.Select All"),
                move |window, cx| state.select_all_from_edit_menu(window, cx),
            ));
        }

        let drag_state = state.clone();
        let source_state = state.clone();
        TouchSelectionOverlay::new(
            ("input-touch-selection", state.entity_id()),
            move |_, cx| source_state.touch_selection(cx),
        )
        .handles(move |edge, phase, position, _, cx| match phase {
            TouchPhase::Started => drag_state.begin_edge_drag(edge, position, cx),
            TouchPhase::Moved => drag_state.update_edge_drag(position, cx),
            TouchPhase::Ended | TouchPhase::Cancelled => drag_state.end_edge_drag(cx),
        })
        .items(items)
        .into_elements(window, cx)
    }

    fn render_toggle_mask_button(state: &TextInputState, cx: &App) -> impl IntoElement {
        let masked = state.presentation(cx).is_masked();
        Button::new("toggle-mask")
            .icon(if masked {
                IconName::Eye
            } else {
                IconName::EyeOff
            })
            .accessibility_label(if masked {
                t!("Input.Show Password")
            } else {
                t!("Input.Hide Password")
            })
            .xsmall()
            .text()
            .tab_stop(false)
            .on_click({
                let state = state.clone();
                move |_, window, cx| state.toggle_masked(window, cx)
            })
    }

    /// This method must after the refine_style.
    fn render_editor(
        input_state: TextInputState,
        search_panel: Option<AnyElement>,
        _: &Window,
    ) -> impl IntoElement {
        v_flex().size_full().children(search_panel).child(
            div()
                .relative()
                .flex_1()
                .child(input_state.into_any_element()),
        )
    }
}

impl Styled for Input {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Input {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        const LINE_HEIGHT: Rems = Rems(1.25);
        let text_align = self.style.text.text_align.unwrap_or(TextAlign::Left);
        let state = self.state.clone();
        state.install_token_presentation(
            Some(self.token_renderer.unwrap_or_else(|| {
                Rc::new(|token, _, _| super::InputToken::new(token).into_any_element())
            })),
            self.token_click_listener,
            matches!(
                self.content_type,
                Some(InputContentType::Password | InputContentType::NewPassword)
            ),
            cx,
        );
        state.install_token_hover_presentation(self.token_hover_listener, cx);
        // Which kind of input this registers as follows from the state itself.
        sync_focused_input_registry(&state, window, cx);

        state.ensure_highlighter_factory(crate::highlighter::input_highlighter_factory(), cx);
        state.set_editor_style(
            gpui_base::input::InputEditorStyle {
                foreground: cx.theme().foreground,
                muted_foreground: cx.theme().muted_foreground,
                background: cx.theme().editor_background(),
                border: cx.theme().border,
                selection: cx.theme().selection,
                caret: cx.theme().caret,
                diagnostics: gpui_base::input::DiagnosticColors {
                    error: cx.theme().highlight_theme.style.status.error(cx),
                    warning: cx.theme().highlight_theme.style.status.warning(cx),
                    info: cx.theme().highlight_theme.style.status.info(cx),
                    hint: cx.theme().highlight_theme.style.status.hint(cx),
                },
                highlight_styles: cx.theme().highlight_theme.clone(),
                editor_invisible: cx.theme().highlight_theme.style.editor_invisible,
                editor_active_line: cx.theme().highlight_theme.style.editor_active_line,
                editor_gutter_background: cx.theme().highlight_theme.style.editor_gutter_background,
                fold_icon_renderer: Some(Rc::new(|ix, is_folded| {
                    Button::new(("fold-icon", ix))
                        .ghost()
                        .icon(if is_folded {
                            IconName::ChevronRight
                        } else {
                            IconName::ChevronDown
                        })
                        .xsmall()
                        .rounded(ButtonRounded::Small)
                        .size(px(14.))
                        .selected(is_folded)
                        .into_any_element()
                })),
            },
            cx,
        );
        state.set_editor_paddings(
            if state.presentation(cx).is_multi_line() {
                Edges {
                    top: self.size.input_py(),
                    right: self.size.input_px(),
                    bottom: self.size.input_py(),
                    left: if state.presentation(cx).is_code_editor() {
                        self.size.input_px().min(px(6.))
                    } else {
                        self.size.input_px()
                    },
                }
            } else {
                Edges::default()
            },
            cx,
        );
        state.set_disabled(self.disabled, cx);
        state.set_readonly(self.readonly, cx);
        state.set_text_align(text_align, cx);
        let custom = self.context_menu_builder.clone();
        state.on_context_menu(
            Rc::new(move |_, capabilities, position, window, cx| {
                let menu = if let Some(custom) = custom.as_ref() {
                    custom(NativeMenu::new(), window, cx)
                } else {
                    let enabled = !capabilities.is_disabled();
                    // A read-only input can still navigate the code, it only
                    // rejects the items that would change the text.
                    let editable = enabled && !capabilities.is_readonly();
                    let mut menu = NativeMenu::new();
                    if capabilities.is_code_editor() {
                        menu = menu
                            .menu_with_disabled(
                                t!("Input.Go to Definition"),
                                !(enabled && capabilities.has_definition()),
                                Box::new(gpui_base::input::GoToDefinition),
                            )
                            .menu_with_disabled(
                                t!("Input.Show Code Actions"),
                                !(editable && capabilities.has_code_actions()),
                                Box::new(gpui_base::input::ToggleCodeActions),
                            )
                            .separator();
                    }
                    menu.menu_with_disabled(
                        t!("Input.Cut"),
                        !(editable && capabilities.is_copyable()),
                        Box::new(gpui_base::input::Cut),
                    )
                    .menu_with_disabled(
                        t!("Input.Copy"),
                        !capabilities.is_copyable(),
                        Box::new(gpui_base::input::Copy),
                    )
                    // Offered whenever the text can change, without peeking
                    // at the clipboard: the synchronous read is always empty
                    // on the web, and an empty clipboard pastes nothing.
                    .menu_with_disabled(
                        t!("Input.Paste"),
                        !editable,
                        Box::new(gpui_base::input::Paste),
                    )
                    .separator()
                    .menu(
                        t!("Input.Select All"),
                        Box::new(gpui_base::input::SelectAll),
                    )
                };
                menu.show(position, window, cx);
            }),
            cx,
        );
        // The engine ignores `Paste` on a read-only or disabled input; the hook
        // must not see a paste the input itself would refuse.
        let paste_handler = self
            .paste_handler
            .clone()
            .filter(|_| state.presentation(cx).is_editable());
        let mut overlays = state.render_overlays(window, cx);
        overlays
            .floating
            .extend(Self::render_touch_selection(&state, window, cx));

        let presentation = state.presentation(cx);
        let content_type = self.content_type;
        let disabled = self.disabled;
        let is_multi_line = presentation.is_multi_line();
        // Without a content type, a masked input is a password field to screen
        // readers, so they announce it as one.
        let accessibility_role = accessibility_role(
            is_multi_line,
            content_type.or(presentation
                .is_masked()
                .then_some(InputContentType::Password)),
            self.role,
        );
        let input_focused =
            presentation.focus_handle().is_focused(window) && !presentation.is_disabled();
        if input_focused {
            sync_native_content_type(window, content_type, presentation.is_editable());
        }
        let frame_focus_handle = window
            .use_keyed_state(("input-frame-focus", state.entity_id()), cx, |_, cx| {
                cx.focus_handle()
            })
            .read(cx)
            .clone();
        let focused = !presentation.is_disabled()
            && (state.has_selection_focus(window, cx)
                || frame_focus_handle.contains_focused(window, cx));

        let gap_x = match self.size {
            Size::Small => px(4.),
            Size::Large => px(8.),
            _ => px(6.),
        };

        let (bg, _) = input_style(presentation.is_disabled(), cx);
        let bg = if presentation.is_code_editor() {
            cx.theme().editor_background()
        } else {
            bg
        };
        let bg = if presentation.is_disabled() {
            bg.opacity(0.5)
        } else {
            bg
        };
        let prefix = self.prefix;
        let suffix = self.suffix;
        let show_clear_button = self.cleanable
            && presentation.is_editable()
            && !presentation.is_loading()
            && state.text(cx).len() > 0
            && !presentation.is_multi_line();
        let has_suffix =
            suffix.is_some() || presentation.is_loading() || self.mask_toggle || show_clear_button;

        let placeholder = Some(presentation.placeholder().clone()).filter(|p| !p.is_empty());

        // Don't use a mask-derived placeholder ("(___)___-___") as an aria_label fallback.
        let placeholder_is_mask = presentation.mask_placeholder() == placeholder.as_deref();

        let aria_label = match self.aria_label {
            Some(label) => Some(label),
            None if placeholder_is_mask => None,
            None => placeholder.clone(),
        };
        state.set_accessibility(
            gpui_base::input::InputAccessibility::new(accessibility_role)
                .with_label(aria_label)
                .with_placeholder(placeholder)
                .with_accessibility_id(self.accessibility_id)
                .with_value_exposed(exposes_accessibility_value(content_type)),
            cx,
        );
        let id = self
            .id
            .unwrap_or_else(|| ("input", state.entity_id()).into());
        BaseInput::new(id)
            .semantic_owner(state.entity_id())
            .focused(focused)
            .disabled(disabled)
            .track_focus(&frame_focus_handle)
            .on_mouse_down(MouseButton::Right, {
                let state = state.clone();
                move |_, window, cx| {
                    // The text element has already taken focus. Publish its state
                    // before an outer ContextMenu resolves the selection owner;
                    // render-time registration still names the previous input.
                    sync_focused_input_registry(&state, window, cx);
                }
            })
            .when(disabled, |this| {
                this.capture_any_mouse_down(|_, _, cx| cx.stop_propagation())
            })
            .styles(|styles| {
                styles.focused(|style| {
                    style.when(
                        self.appearance && self.bordered && self.focus_bordered,
                        |style| style.border_1().border_color(cx.theme().ring),
                    )
                })
            })
            // The editor owns text semantics. The frame still scopes addon
            // controls, custom IDs and focus styling without registering the
            // editor's FocusHandle a second time.
            .role(RoleOverride::Presentational)
            .flex()
            .size_full()
            .line_height(LINE_HEIGHT)
            .when(!is_multi_line, |this| {
                this.input_px(self.size).input_py(self.size)
            })
            .input_h(self.size)
            .input_text_size(self.size)
            .items_center()
            .when(presentation.is_multi_line(), |this| {
                this.h_auto()
                    .when_some(self.height, |this, height| this.h(height))
            })
            .when(self.appearance, |this| {
                this.bg(bg)
                    .rounded(cx.theme().radius)
                    .when(self.bordered, |this| {
                        this.border_1().border_color(cx.theme().input)
                    })
            })
            .items_center()
            .gap(gap_x)
            .refine_style(&self.style)
            .when(
                focused && self.appearance && self.bordered && self.focus_bordered,
                |this| this.focus_ring_style(window, cx),
            )
            .children(prefix.map(|p| {
                div()
                    .when(presentation.is_disabled(), |this| this.opacity(0.5))
                    .child(p)
            }))
            .when(presentation.is_multi_line(), |this| {
                this.child(Self::render_editor(state.clone(), overlays.search, window))
            })
            .when(!presentation.is_multi_line(), |this| {
                this.child(state.clone().into_any_element())
            })
            .when(has_suffix, |this| {
                this.pr(self.size.input_px()).child(
                    h_flex()
                        .id("suffix")
                        .gap(gap_x)
                        .items_center()
                        .cursor_default()
                        .when(presentation.is_disabled(), |this| this.opacity(0.5))
                        .when(presentation.is_loading(), |this| {
                            this.child(Spinner::new().color(cx.theme().muted_foreground))
                        })
                        .when(self.mask_toggle, |this| {
                            this.child(Self::render_toggle_mask_button(&state, cx))
                        })
                        .when(show_clear_button, |this| {
                            this.child(clear_button(cx).on_click({
                                let state = state.clone();
                                move |_, window, cx| {
                                    state.clean(window, cx);
                                    state.focus(window, cx);
                                }
                            }))
                        })
                        .children(suffix),
                )
            })
            .relative()
            .children(overlays.floating)
            .when_some(paste_handler, |this, handler| {
                this.capture_action(move |_: &gpui_base::input::Paste, window, cx| {
                    if let Some(clipboard) = cx.read_from_clipboard() {
                        if handler(&clipboard, window, cx) {
                            cx.stop_propagation();
                        }
                    }
                })
            })
            .render(window, cx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ElementExt as _;
    use crate::input::AnyInputState;

    #[test]
    fn content_types_map_to_accessibility_roles() {
        let cases = [
            (None, Role::TextInput),
            (Some(InputContentType::Name), Role::TextInput),
            (Some(InputContentType::NamePrefix), Role::TextInput),
            (Some(InputContentType::GivenName), Role::TextInput),
            (Some(InputContentType::MiddleName), Role::TextInput),
            (Some(InputContentType::FamilyName), Role::TextInput),
            (Some(InputContentType::NameSuffix), Role::TextInput),
            (Some(InputContentType::Nickname), Role::TextInput),
            (Some(InputContentType::JobTitle), Role::TextInput),
            (Some(InputContentType::OrganizationName), Role::TextInput),
            (Some(InputContentType::Location), Role::TextInput),
            (Some(InputContentType::FullStreetAddress), Role::TextInput),
            (Some(InputContentType::StreetAddressLine1), Role::TextInput),
            (Some(InputContentType::StreetAddressLine2), Role::TextInput),
            (Some(InputContentType::AddressCity), Role::TextInput),
            (Some(InputContentType::AddressState), Role::TextInput),
            (Some(InputContentType::AddressCityAndState), Role::TextInput),
            (Some(InputContentType::Sublocality), Role::TextInput),
            (Some(InputContentType::CountryName), Role::TextInput),
            (Some(InputContentType::PostalCode), Role::TextInput),
            (
                Some(InputContentType::TelephoneNumber),
                Role::PhoneNumberInput,
            ),
            (Some(InputContentType::EmailAddress), Role::EmailInput),
            (Some(InputContentType::Url), Role::UrlInput),
            (Some(InputContentType::CreditCardNumber), Role::TextInput),
            (Some(InputContentType::CreditCardName), Role::TextInput),
            (Some(InputContentType::CreditCardGivenName), Role::TextInput),
            (
                Some(InputContentType::CreditCardMiddleName),
                Role::TextInput,
            ),
            (
                Some(InputContentType::CreditCardFamilyName),
                Role::TextInput,
            ),
            (
                Some(InputContentType::CreditCardSecurityCode),
                Role::TextInput,
            ),
            (
                Some(InputContentType::CreditCardExpiration),
                Role::TextInput,
            ),
            (
                Some(InputContentType::CreditCardExpirationMonth),
                Role::TextInput,
            ),
            (
                Some(InputContentType::CreditCardExpirationYear),
                Role::TextInput,
            ),
            (Some(InputContentType::CreditCardType), Role::TextInput),
            (Some(InputContentType::Username), Role::TextInput),
            (Some(InputContentType::Password), Role::PasswordInput),
            (Some(InputContentType::NewPassword), Role::PasswordInput),
            (Some(InputContentType::OneTimeCode), Role::TextInput),
            (
                Some(InputContentType::ShipmentTrackingNumber),
                Role::TextInput,
            ),
            (Some(InputContentType::FlightNumber), Role::TextInput),
            (Some(InputContentType::DateTime), Role::DateTimeInput),
            (Some(InputContentType::Birthdate), Role::DateInput),
            (Some(InputContentType::BirthdateDay), Role::TextInput),
            (Some(InputContentType::BirthdateMonth), Role::TextInput),
            (Some(InputContentType::BirthdateYear), Role::TextInput),
            (Some(InputContentType::CellularEid), Role::TextInput),
            (Some(InputContentType::CellularImei), Role::TextInput),
        ];

        for (content_type, role) in cases {
            assert_eq!(
                accessibility_role(false, content_type, RoleOverride::Implicit),
                Some(role)
            );
        }
    }

    #[test]
    fn multiline_inputs_keep_multiline_accessibility_role() {
        assert_eq!(
            accessibility_role(
                true,
                Some(InputContentType::Password),
                RoleOverride::Implicit
            ),
            Some(Role::MultilineTextInput)
        );
    }

    #[test]
    fn explicit_accessibility_role_overrides_defaults() {
        assert_eq!(
            accessibility_role(
                false,
                Some(InputContentType::Password),
                Role::TextInput.into()
            ),
            Some(Role::TextInput)
        );
        assert_eq!(
            accessibility_role(
                true,
                Some(InputContentType::Password),
                Role::TextInput.into()
            ),
            Some(Role::TextInput)
        );
    }

    #[test]
    fn presentational_role_emits_no_accessibility_node() {
        assert_eq!(
            accessibility_role(
                false,
                Some(InputContentType::Password),
                RoleOverride::Presentational
            ),
            None
        );
        assert_eq!(
            accessibility_role(true, None, RoleOverride::Presentational),
            None
        );
    }

    #[test]
    fn role_option_converts_to_the_matching_override() {
        assert_eq!(
            RoleOverride::from(Some(Role::Button)),
            RoleOverride::Role(Role::Button)
        );
        assert_eq!(RoleOverride::from(None), RoleOverride::Presentational);
    }

    #[gpui::test]
    fn test_on_paste_builder(cx: &mut gpui::TestAppContext) {
        use gpui::{AppContext as _, Render};

        struct Probe;
        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
                div()
            }
        }

        cx.update(crate::init);
        let _ = cx.add_window_view(|window, cx| {
            let state = cx.new(|cx| InputState::new(window, cx));

            assert!(Input::new(&state).paste_handler.is_none());
            let input = Input::new(&state).on_paste(|_, _, _| true);
            assert!(input.paste_handler.is_some());
            Probe
        });
    }

    #[gpui::test]
    fn test_on_token_hover_builder(cx: &mut gpui::TestAppContext) {
        use gpui::{AppContext as _, Render};

        struct Probe;
        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
                div()
            }
        }

        cx.update(crate::init);
        let _ = cx.add_window_view(|window, cx| {
            let state = cx.new(|cx| InputState::new(window, cx));

            assert!(Input::new(&state).token_hover_listener.is_none());
            let input = Input::new(&state).on_token_hover(|_, _, _| {});
            assert!(input.token_hover_listener.is_some());
            Probe
        });
    }

    #[gpui::test]
    fn editable_input_offers_accessibility_write_action(cx: &mut gpui::TestAppContext) {
        use gpui::{AccessibleAction, AppContext as _, Element as _, IntoElement as _, Render};
        use std::cell::RefCell;

        type EmittedState = Option<(Option<String>, bool)>;

        struct InputA11yProbe {
            state: Entity<InputState>,
            emitted: Rc<RefCell<EmittedState>>,
            disabled: bool,
            readonly: bool,
        }

        impl Render for InputA11yProbe {
            fn render(
                &mut self,
                _window: &mut Window,
                _cx: &mut gpui::Context<Self>,
            ) -> impl IntoElement {
                let state = self.state.clone();
                let emitted = self.emitted.clone();
                div()
                    .child(
                        Input::new(&state)
                            .disabled(self.disabled)
                            .readonly(self.readonly),
                    )
                    .on_prepaint(move |_, window, cx| {
                        state.update(cx, |state, cx| {
                            let input = state.render(window, cx).into_element();
                            let mut node = gpui::accesskit::Node::new(Role::Unknown);
                            input.write_a11y_info(&mut node);
                            *emitted.borrow_mut() = Some((
                                node.value().map(ToOwned::to_owned),
                                node.supports_action(AccessibleAction::SetValue),
                            ));
                        });
                    })
            }
        }

        cx.update(crate::init);
        let emitted = Rc::new(RefCell::new(None));
        let captured = emitted.clone();
        let (probe, cx) = cx.add_window_view(move |window, cx| InputA11yProbe {
            state: cx.new(|cx| InputState::new(window, cx).default_value("initial")),
            emitted,
            disabled: false,
            readonly: false,
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        // Normal builds leave the value lazy without an accessibility client;
        // test-support reads that same production value path eagerly.
        let expected_value = cfg!(feature = "test-support").then(|| "initial".to_owned());
        assert_eq!(*captured.borrow(), Some((expected_value.clone(), true)));

        let state = probe.read_with(cx, |probe, _| probe.state.clone());
        for disabled in [false, true] {
            probe.update(cx, |probe, cx| {
                probe.disabled = disabled;
                probe.readonly = !disabled;
                cx.notify();
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            assert_eq!(*captured.borrow(), Some((expected_value.clone(), false)));
        }
        probe.update(cx, |probe, cx| {
            probe.disabled = false;
            probe.readonly = false;
            cx.notify();
        });
        cx.update(|window, cx| {
            state.update(cx, |state, cx| state.set_masked(true, window, cx));
            window.draw(cx).clear(cx);
        });
        assert_eq!(state.read_with(cx, |state, _| state.value()), "initial");
        assert_eq!(*captured.borrow(), Some((None, true)));
    }

    #[gpui::test]
    fn input_emits_accessibility_id(cx: &mut gpui::TestAppContext) {
        use gpui::{AppContext as _, Element as _, IntoElement as _, Render};
        use std::cell::RefCell;

        type EmittedIds = Vec<Option<String>>;

        struct InputA11yProbe {
            states: [Entity<InputState>; 2],
            emitted: Rc<RefCell<EmittedIds>>,
        }

        impl Render for InputA11yProbe {
            fn render(
                &mut self,
                _window: &mut Window,
                _cx: &mut gpui::Context<Self>,
            ) -> impl IntoElement {
                let states = self.states.clone();
                let emitted = self.emitted.clone();
                div()
                    .child(Input::new(&states[0]))
                    .child(Input::new(&states[1]).accessibility_id("search.query"))
                    .on_prepaint(move |_, window, cx| {
                        *emitted.borrow_mut() = states
                            .iter()
                            .map(|state| {
                                state.update(cx, |state, cx| {
                                    let input = state.render(window, cx).into_element();
                                    let mut node = gpui::accesskit::Node::new(Role::Unknown);
                                    input.write_a11y_info(&mut node);
                                    node.author_id().map(ToOwned::to_owned)
                                })
                            })
                            .collect();
                    })
            }
        }

        cx.update(crate::init);
        let emitted = Rc::new(RefCell::new(Vec::new()));
        let captured = emitted.clone();
        let (_, cx) = cx.add_window_view(move |window, cx| InputA11yProbe {
            states: std::array::from_fn(|_| cx.new(|cx| InputState::new(window, cx))),
            emitted,
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });

        assert_eq!(*captured.borrow(), vec![None, Some("search.query".into())]);
    }

    #[test]
    fn password_content_types_keep_accessibility_values_private() {
        assert!(exposes_accessibility_value(None));
        assert!(!exposes_accessibility_value(Some(
            InputContentType::Password
        )));
        assert!(!exposes_accessibility_value(Some(
            InputContentType::NewPassword
        )));
    }

    #[gpui::test]
    fn focused_input_registry_tracks_focus_and_blur(cx: &mut gpui::TestAppContext) {
        use crate::{Root, WindowExt as _};
        use gpui::{AppContext as _, Render};

        struct Probe {
            input: Entity<InputState>,
            textarea: Entity<crate::input::TextareaState>,
            editor: Entity<crate::input::EditorState>,
            otp: Entity<gpui_base::OtpState>,
            other: gpui::FocusHandle,
        }
        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
                div()
                    .child(div().track_focus(&self.other))
                    .child(Input::new(&self.input))
                    .child(crate::input::Textarea::new(&self.textarea))
                    .child(crate::input::Editor::new(&self.editor))
                    .child(crate::input::OtpInput::new(&self.otp))
            }
        }

        cx.update(crate::init);
        let mut input = None;
        let mut textarea = None;
        let mut editor = None;
        let mut other_focus = None;
        let mut otp = None;
        let window = cx.update(|cx| {
            cx.open_window(Default::default(), |window, cx| {
                let state = cx.new(|cx| InputState::new(window, cx));
                let textarea_state = cx.new(|cx| crate::input::TextareaState::new(window, cx));
                let editor_state =
                    cx.new(|cx| crate::input::EditorState::new(window, cx).language("rust"));
                let otp_state = cx.new(|cx| gpui_base::OtpState::new(6, window, cx));
                input = Some(state.clone());
                textarea = Some(textarea_state.clone());
                editor = Some(editor_state.clone());
                otp = Some(otp_state.clone());
                let other = cx.focus_handle();
                other_focus = Some(other.clone());
                let probe = cx.new(|_| Probe {
                    input: state,
                    textarea: textarea_state,
                    editor: editor_state,
                    otp: otp_state,
                    other,
                });
                cx.new(|cx| Root::new(probe, window, cx))
            })
            .unwrap()
        });
        let input = input.unwrap();
        let textarea = textarea.unwrap();
        let editor = editor.unwrap();
        let otp = otp.unwrap();
        let other_focus = other_focus.unwrap();
        let mut cx = gpui::VisualTestContext::from_window(window.into(), cx);

        // Focusing each kind of input registers it, and blurring clears it.
        let cases: Vec<AnyInputState> = vec![
            input.clone().into(),
            textarea.clone().into(),
            editor.clone().into(),
            otp.clone().into(),
        ];
        for expected in cases {
            cx.update(|window, cx| {
                let _ = window.draw(cx);
            });
            cx.update(|window, cx| expected.focus_handle(cx).focus(window, cx));
            cx.run_until_parked();
            cx.update(|window, cx| {
                let _ = window.draw(cx);
            });
            assert_eq!(
                cx.update(|window, cx| window.focused_input(cx)),
                Some(expected)
            );

            cx.update(|window, cx| other_focus.clone().focus(window, cx));
            cx.run_until_parked();
            cx.update(|window, cx| {
                let _ = window.draw(cx);
            });
            assert_eq!(cx.update(|window, cx| window.focused_input(cx)), None);
        }
    }

    #[gpui::test]
    fn focused_input_registry_ignores_input_removed_while_focused(cx: &mut gpui::TestAppContext) {
        use crate::{Root, WindowExt as _};
        use gpui::{AppContext as _, Render};

        struct Probe {
            input: Entity<InputState>,
            show_input: bool,
            other: gpui::FocusHandle,
        }
        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
                let base = div().child(div().track_focus(&self.other));
                if self.show_input {
                    base.child(Input::new(&self.input))
                } else {
                    base
                }
            }
        }

        cx.update(crate::init);
        let mut input = None;
        let mut other_focus = None;
        let mut probe_entity = None;
        let window = cx.update(|cx| {
            cx.open_window(Default::default(), |window, cx| {
                let state = cx.new(|cx| InputState::new(window, cx));
                input = Some(state.clone());
                let other = cx.focus_handle();
                other_focus = Some(other.clone());
                let probe = cx.new(|_| Probe {
                    input: state,
                    show_input: true,
                    other,
                });
                probe_entity = Some(probe.clone());
                cx.new(|cx| Root::new(probe, window, cx))
            })
            .unwrap()
        });
        let input: AnyInputState = input.unwrap().into();
        let other_focus = other_focus.unwrap();
        let probe = probe_entity.unwrap();
        let mut cx = gpui::VisualTestContext::from_window(window.into(), cx);

        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        cx.update(|window, cx| input.focus_handle(cx).focus(window, cx));
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        assert_eq!(
            cx.update(|window, cx| window.focused_input(cx)),
            Some(input.clone())
        );

        // Remove the input from the tree while it holds focus and move focus
        // elsewhere in the same update (e.g. closing a sidebar containing the
        // input) — the input never re-renders to unregister itself.
        cx.update(|window, cx| {
            probe.update(cx, |probe, cx| {
                probe.show_input = false;
                cx.notify();
            });
            other_focus.focus(window, cx);
        });
        cx.run_until_parked();
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        assert!(!cx.update(|window, cx| window.has_focused_input(cx)));
        assert_eq!(cx.update(|window, cx| window.focused_input(cx)), None);
    }

    #[gpui::test]
    fn native_touch_selection_leaves_the_handles_and_menu_to_the_platform(
        cx: &mut gpui::TestAppContext,
    ) {
        use gpui::{AppContext as _, LongPressEvent, Render, point};

        struct Probe(Entity<InputState>);
        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
                div().w(px(300.)).child(Input::new(&self.0))
            }
        }

        cx.update(crate::init);
        let (probe, cx) = cx.add_window_view(|window, cx| {
            Probe(cx.new(|cx| InputState::new(window, cx).default_value("quick select value")))
        });
        cx.update(|window, cx| {
            let _ = window.draw(cx);
        });
        let position = point(px(40.), px(16.));
        for phase in [TouchPhase::Started, TouchPhase::Ended] {
            cx.simulate_event(LongPressEvent {
                phase,
                start_position: position,
                position,
            });
        }
        let state = TextInputState::from(probe.read_with(cx, |probe, _| probe.0.clone()));
        let overlay = |cx: &mut gpui::VisualTestContext| {
            cx.update(|window, cx| Input::render_touch_selection(&state, window, cx).len())
        };
        assert!(cx.update(|_, cx| state.touch_selection(cx).is_some()));
        assert!(overlay(cx) > 0);

        cx.update(|_, cx| set_native_touch_selection(true, cx));
        assert!(cx.update(|_, cx| state.touch_selection(cx).is_some()));
        assert_eq!(overlay(cx), 0);

        cx.update(|_, cx| set_native_touch_selection(false, cx));
        assert!(overlay(cx) > 0);
    }
}
