use crate::{
    ActiveTheme, ElementExt, Placement,
    dialog::{ANIMATION_DURATION, Dialog, DialogMotion},
    input::AnyInputState,
    native_menu::FallbackMenuOverlay,
    notification::{Notification, NotificationList},
    sheet::Sheet,
    tooltip::render_tooltip,
    touch_selection::WindowTouchSelectionOverlay,
    window_border,
};
use gpui::{
    App, AppContext, Bounds, Context, DefiniteLength, DispatchPhase, ElementId, Entity,
    FocusHandle, GlobalElementId, InteractiveElement, IntoElement, MouseMoveEvent,
    ParentElement as _, Pixels, Render, RenderOnce, Styled, WeakFocusHandle, Window, canvas, div,
    prelude::FluentBuilder as _,
};
use gpui_base::{TextSelection, TextSelectionScopeId, motion::Presence};
use std::{any::TypeId, cell::Cell, rc::Rc};

pub(crate) fn init(cx: &mut App) {
    gpui_base::Root::register_plugin::<WindowState>(cx, WindowState::new);
}

/// Component-owned window state and presentation; Base owns the actual root.
pub(crate) struct WindowState {
    pub(crate) active_sheet: Option<ActiveSheet>,
    pub(crate) active_dialogs: Vec<ActiveDialog>,
    pub(super) focused_input: Option<AnyInputState>,
    pub notification: Entity<NotificationList>,
    pub(crate) tooltip_overlay: Entity<gpui_base::TooltipOverlay>,
    tooltip_hovered_trigger: Option<GlobalElementId>,
    tooltip_trigger_lifetime: std::rc::Weak<()>,
    /// Bounds of the tooltip trigger last pressed, whose tooltip stays
    /// dismissed until the pointer moves outside them.
    tooltip_pressed_trigger: Option<Bounds<Pixels>>,
    pub(crate) native_menu_overlay: Entity<FallbackMenuOverlay>,
    touch_selection_overlay: Entity<WindowTouchSelectionOverlay>,
    sheet_size: Option<DefiniteLength>,
    pending_focus_restore: Option<WeakFocusHandle>,
    /// Source of stable dialog identities, including their rendered subtrees.
    next_dialog_id: usize,
}

#[derive(Clone)]
pub(crate) struct ActiveSheet {
    focus_handle: FocusHandle,
    /// The previous focused handle before opening the Sheet.
    previous_focused_handle: Option<WeakFocusHandle>,
    placement: Placement,
    selection_scope: TextSelectionScopeId,
    builder: Rc<dyn Fn(Sheet, &mut Window, &mut App) -> Sheet + 'static>,
}

#[derive(Clone)]
pub(crate) struct ActiveDialog {
    /// Stable for the dialog's lifetime, independently of its stack position.
    id: usize,
    focus_handle: FocusHandle,
    /// The previous focused handle before opening the Dialog.
    previous_focused_handle: Option<WeakFocusHandle>,
    selection_scope: TextSelectionScopeId,
    builder: Rc<dyn Fn(Dialog, &mut Window, &mut App) -> Dialog + 'static>,
    /// Whether closing plays an exit transition, refreshed on every render.
    ///
    /// `DialogEntrance::None`, reduced motion, and a zero theme duration all
    /// close in a single frame.
    exit_enabled: Rc<Cell<bool>>,
    /// Retained after closing until its exit transition finishes.
    pub(crate) closing: bool,
}

impl ActiveDialog {
    pub(crate) fn new(
        id: usize,
        focus_handle: FocusHandle,
        previous_focused_handle: Option<WeakFocusHandle>,
        selection_scope: TextSelectionScopeId,
        builder: impl Fn(Dialog, &mut Window, &mut App) -> Dialog + 'static,
    ) -> Self {
        Self {
            id,
            focus_handle,
            previous_focused_handle,
            selection_scope,
            builder: Rc::new(builder),
            exit_enabled: Rc::new(Cell::new(false)),
            closing: false,
        }
    }

    #[cfg(test)]
    pub(crate) fn focus_handle(&self) -> &FocusHandle {
        &self.focus_handle
    }
}

/// Keys one dialog's shared entrance and exit transition.
fn dialog_presence_id(id: usize) -> ElementId {
    ElementId::NamedInteger("dialog-presence".into(), id as u64)
}

impl WindowState {
    fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        Self {
            active_sheet: None,
            active_dialogs: Vec::new(),
            focused_input: None,
            notification: cx.new(|cx| NotificationList::new(window, cx)),
            tooltip_overlay: cx
                .new(|_| gpui_base::TooltipOverlay::new().render_with(render_tooltip)),
            tooltip_hovered_trigger: None,
            tooltip_trigger_lifetime: std::rc::Weak::new(),
            tooltip_pressed_trigger: None,
            native_menu_overlay: cx.new(|_| FallbackMenuOverlay::new()),
            touch_selection_overlay: cx.new(|cx| WindowTouchSelectionOverlay::new(window, cx)),
            sheet_size: None,
            pending_focus_restore: None,
            next_dialog_id: 0,
        }
    }

    fn entity(window: &Window, cx: &App) -> Option<Entity<Self>> {
        window.root::<gpui_base::Root>()??.read(cx).plugin::<Self>()
    }

    fn allocate_text_selection_scope(&mut self) -> TextSelectionScopeId {
        TextSelectionScopeId::new()
    }

    pub(crate) fn active_text_selection_scope(&self) -> TextSelectionScopeId {
        self.active_dialogs
            .iter()
            .rev()
            .find(|dialog| !dialog.closing)
            .map(|dialog| dialog.selection_scope)
            .or_else(|| {
                self.active_sheet
                    .as_ref()
                    .map(|sheet| sheet.selection_scope)
            })
            .unwrap_or_default()
    }

    pub fn update<F, R>(window: &mut Window, cx: &mut App, f: F) -> R
    where
        F: FnOnce(&mut Self, &mut Window, &mut Context<Self>) -> R,
    {
        let root = Self::entity(window, cx).expect(ROOT_MISSING);

        root.update(cx, |root, cx| f(root, window, cx))
    }

    pub(crate) fn try_read<'a>(window: &Window, cx: &'a App) -> Option<&'a Self> {
        Self::entity(window, cx).map(|root| root.read(cx))
    }

    pub(crate) fn try_update<F, R>(window: &mut Window, cx: &mut App, f: F) -> Option<R>
    where
        F: FnOnce(&mut Self, &mut Window, &mut Context<Self>) -> R,
    {
        let root = Self::entity(window, cx)?;
        Some(root.update(cx, |root, cx| f(root, window, cx)))
    }

    pub fn read<'a>(window: &'a Window, cx: &'a App) -> &'a Self {
        Self::entity(window, cx).expect(ROOT_MISSING).read(cx)
    }

    fn notification_layer(
        root: &Entity<WindowState>,
        window: &Window,
        cx: &App,
    ) -> Option<impl IntoElement + use<>> {
        let active_sheet_placement = root.read(cx).active_sheet.clone().map(|d| d.placement);

        let sheet_size = root.read(cx).sheet_size;
        let (mt, mr, mb, ml) = match active_sheet_placement {
            Some(Placement::Top) => (sheet_size, None, None, None),
            Some(Placement::Right) => (None, sheet_size, None, None),
            Some(Placement::Bottom) => (None, None, sheet_size, None),
            Some(Placement::Left) => (None, None, None, sheet_size),
            _ => (None, None, None, None),
        };

        // Keep toasts out from under the system bars and the on-screen keyboard.
        let safe_insets = window_border::window_safe_insets(window);

        Some(
            div()
                .absolute()
                .top(safe_insets.top)
                .right(safe_insets.right)
                .bottom(safe_insets.bottom)
                .left(safe_insets.left)
                .child(
                    div()
                        .absolute()
                        .inset_0()
                        .when_some(mt, |this, offset| this.mt(offset))
                        .when_some(mr, |this, offset| this.mr(offset))
                        .when_some(mb, |this, offset| this.mb(offset))
                        .when_some(ml, |this, offset| this.ml(offset))
                        .child(root.read(cx).notification.clone()),
                ),
        )
    }

    fn sheet_layer(
        root: Entity<WindowState>,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<impl IntoElement + use<>> {
        if let Some(active_sheet) = root.read(cx).active_sheet.clone() {
            let mut sheet = Sheet::new(window, cx);
            sheet = (active_sheet.builder)(sheet, window, cx);
            sheet.focus_handle = active_sheet.focus_handle.clone();
            sheet.placement = active_sheet.placement;
            sheet.selection_scope = active_sheet.selection_scope;

            let size = sheet.size;

            return Some(
                div()
                    .relative()
                    .child(sheet)
                    .on_prepaint(move |_, _, cx| root.update(cx, |r, _| r.sheet_size = Some(size))),
            );
        }

        None
    }

    fn dialog_layer(
        root: &Entity<WindowState>,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<impl IntoElement + use<>> {
        let active_dialogs = root.read(cx).active_dialogs.clone();

        if active_dialogs.is_empty() {
            return None;
        }

        let mut rendered: Vec<(usize, Dialog)> = Vec::with_capacity(active_dialogs.len());

        for (index, active_dialog) in active_dialogs.iter().enumerate() {
            let mut dialog = Dialog::new(cx);

            dialog = (active_dialog.builder)(dialog, window, cx);

            // Give the dialog the focus handle, because `dialog` is a temporary value, is not possible to
            // keep the focus handle in the dialog.
            //
            // So we keep the focus handle in the `active_dialog`, this is owned by the `WindowState`.
            dialog.focus_handle = active_dialog.focus_handle.clone();
            dialog.selection_scope = active_dialog.selection_scope;

            dialog.layer_ix = index;
            dialog.id = active_dialog.id;

            // Refreshed every frame so closing decides in one step whether an
            // exit transition has to play at all.
            let exit_duration = dialog.exit_duration(cx);
            active_dialog.exit_enabled.set(!exit_duration.is_zero());

            let sample =
                Presence::new(dialog_presence_id(active_dialog.id), !active_dialog.closing)
                    .transition(dialog.motion_transition(cx))
                    .sample(window, cx);
            if active_dialog.closing && !sample.should_render() {
                Self::schedule_dialog_removal(root, active_dialog.id, window, cx);
                continue;
            }
            dialog.motion = Some(DialogMotion {
                visibility: sample.progress,
                closing: active_dialog.closing,
            });

            rendered.push((index, dialog));
        }

        if rendered.is_empty() {
            return None;
        }

        // The overlay belongs to the newest dialog still open. With none left,
        // the newest closing dialog keeps the dim through its exit so the
        // backdrop fades with the surface instead of switching off at once.
        // A closing dialog below an open overlay never paints its own backdrop:
        // the constant dim beneath it hands over without a flash.
        let overlay_slot = rendered
            .iter()
            .enumerate()
            .filter(|(_, (index, dialog))| !active_dialogs[*index].closing && dialog.has_overlay())
            .map(|(slot, _)| slot)
            .next_back()
            .or_else(|| {
                rendered
                    .iter()
                    .rposition(|(_, dialog)| dialog.has_overlay())
            });
        if let Some(slot) = overlay_slot {
            rendered[slot].1.props.overlay_visible = true;
        }

        let closing_scopes: Vec<_> = active_dialogs
            .iter()
            .filter(|dialog| dialog.closing)
            .map(|dialog| dialog.focus_handle.clone())
            .collect();

        // Named so a test can assert the layer actually reached the screen. A
        // dialog that opens into a root which never renders this layer looks
        // exactly like one that does not open.
        Some(
            div()
                .debug_selector(|| "dialog-layer".to_string())
                .children(
                    rendered
                        .into_iter()
                        .map(|(_, dialog)| div().id(("dialog-instance", dialog.id)).child(dialog)),
                )
                .when(!closing_scopes.is_empty(), |layer| {
                    layer.on_prepaint(move |_, window, cx| {
                        // Skip every exiting scope, including when close-all
                        // leaves several old tab groups mounted at once.
                        let mut visited = Vec::new();
                        while closing_scopes
                            .iter()
                            .any(|scope| scope.contains_focused(window, cx))
                        {
                            let current = window.focused(cx);
                            if visited.contains(&current) {
                                window.blur(cx);
                                break;
                            }
                            visited.push(current);
                            if window.modifiers().shift {
                                window.focus_prev(cx);
                            } else {
                                window.focus_next(cx);
                            }
                        }
                    })
                }),
        )
    }

    /// Unmounts a dialog once its exit transition has finished.
    ///
    /// The removal is deferred because the layer runs while the window state
    /// that owns the dialog is rendering, and removing it mid-render would
    /// update an entity that is still on the stack.
    fn schedule_dialog_removal(
        root: &Entity<WindowState>,
        dialog_id: usize,
        window: &mut Window,
        cx: &mut App,
    ) {
        let root = root.clone();
        window.defer(cx, move |_, cx| {
            root.update(cx, |state, cx| {
                let before = state.active_dialogs.len();
                state
                    .active_dialogs
                    .retain(|dialog| !(dialog.closing && dialog.id == dialog_id));
                if state.active_dialogs.len() != before {
                    cx.notify();
                }
            });
        });
    }

    pub fn open_dialog<F>(
        &mut self,
        build: F,
        window: &mut Window,
        cx: &mut Context<'_, WindowState>,
    ) where
        F: Fn(Dialog, &mut Window, &mut App) -> Dialog + 'static,
    {
        let mut previous_focused_handle = window.focused(cx).map(|h| h.downgrade());

        // Use pending focus restore if available to maintain correct focus chain
        // when a new dialog is opened immediately after closing another dialog.
        if let Some(pending_handle) = self.pending_focus_restore.take() {
            previous_focused_handle = Some(pending_handle);
        }

        let focus_handle = cx.focus_handle();
        focus_handle.focus(window, cx);

        let id = self.next_dialog_id;
        self.next_dialog_id += 1;
        let selection_scope = self.allocate_text_selection_scope();
        self.active_dialogs.push(ActiveDialog::new(
            id,
            focus_handle,
            previous_focused_handle,
            selection_scope,
            build,
        ));
        // Opening a modal confines selection to it; drop any background
        // selection so it cannot linger (or be copied) under the modal.
        gpui_base::TextSelection::clear(window, cx);
        cx.notify();
    }

    /// Closes the newest dialog that is not already closing.
    ///
    /// A dialog with an exit transition stays in `active_dialogs`, marked
    /// `closing`, until [`WindowState::dialog_layer`] unmounts it once the
    /// transition ends. Without one, it is removed as before.
    fn close_dialog_internal(&mut self, window: &mut Window, cx: &mut App) -> Option<FocusHandle> {
        self.focused_input = None;

        let ix = self
            .active_dialogs
            .iter()
            .rposition(|dialog| !dialog.closing)?;
        let previous_focused_handle = self.active_dialogs[ix]
            .previous_focused_handle
            .clone()
            .and_then(|handle| handle.upgrade());

        if self.active_dialogs[ix].exit_enabled.get() {
            Self::begin_dialog_exit(&mut self.active_dialogs[ix], window, cx);
        } else {
            self.active_dialogs.remove(ix);
        }

        previous_focused_handle
    }

    fn begin_dialog_exit(dialog: &mut ActiveDialog, window: &mut Window, cx: &mut App) {
        if dialog.closing {
            return;
        }
        dialog.closing = true;
        // Do not leave the input handler active during deferred focus restoration.
        if dialog.focus_handle.contains_focused(window, cx) {
            window.blur(cx);
        }
    }

    pub fn close_dialog(&mut self, window: &mut Window, cx: &mut Context<'_, WindowState>) {
        if let Some(handle) = self.close_dialog_internal(window, cx) {
            window.focus(&handle, cx);
        }
        gpui_base::TextSelection::clear(window, cx);
        cx.notify();
    }

    pub(crate) fn defer_close_dialog(
        &mut self,
        window: &mut Window,
        cx: &mut Context<'_, WindowState>,
    ) {
        if let Some(handle) = self.close_dialog_internal(window, cx) {
            // The dialog left behind for its exit transition must not look
            // like a newly opened dialog later, so compare what stays open.
            let open_dialogs = self
                .active_dialogs
                .iter()
                .filter(|dialog| !dialog.closing)
                .count();

            // Save for new dialogs opened during animation to maintain focus chain
            self.pending_focus_restore = Some(handle.downgrade());

            cx.spawn_in(window, async move |this, cx| {
                cx.background_executor().timer(*ANIMATION_DURATION).await;
                let _ = this.update_in(cx, |this, window, cx| {
                    let current_open_dialogs = this
                        .active_dialogs
                        .iter()
                        .filter(|dialog| !dialog.closing)
                        .count();
                    // Only restore focus if no new dialogs were opened during animation
                    if current_open_dialogs == open_dialogs {
                        window.focus(&handle, cx);
                    }
                    this.pending_focus_restore = None;
                });
            })
            .detach();
        }
        gpui_base::TextSelection::clear(window, cx);
        cx.notify();
    }

    pub fn close_all_dialogs(&mut self, window: &mut Window, cx: &mut Context<'_, WindowState>) {
        self.focused_input = None;
        let previous_focused_handle = self
            .active_dialogs
            .first()
            .and_then(|d| d.previous_focused_handle.clone());

        // Dialogs with an exit transition leave by animating; the rest go now.
        self.active_dialogs
            .retain(|dialog| dialog.closing || dialog.exit_enabled.get());
        for dialog in &mut self.active_dialogs {
            Self::begin_dialog_exit(dialog, window, cx);
        }

        if let Some(handle) = previous_focused_handle.and_then(|h| h.upgrade()) {
            window.focus(&handle, cx);
        }
        gpui_base::TextSelection::clear(window, cx);
        cx.notify();
    }

    pub fn open_sheet_at<F>(
        &mut self,
        placement: Placement,
        build: F,
        window: &mut Window,
        cx: &mut Context<'_, WindowState>,
    ) where
        F: Fn(Sheet, &mut Window, &mut App) -> Sheet + 'static,
    {
        let previous_focused_handle = self
            .active_sheet
            .take()
            .and_then(|s| s.previous_focused_handle)
            .or_else(|| window.focused(cx).map(|h| h.downgrade()));

        let focus_handle = cx.focus_handle();
        focus_handle.focus(window, cx);
        let selection_scope = self.allocate_text_selection_scope();
        self.active_sheet = Some(ActiveSheet {
            focus_handle,
            previous_focused_handle,
            placement,
            selection_scope,
            builder: Rc::new(build),
        });
        // Opening a modal confines selection to it; drop any background
        // selection so it cannot linger (or be copied) under the modal.
        gpui_base::TextSelection::clear(window, cx);
        cx.notify();
    }

    pub fn close_sheet(&mut self, window: &mut Window, cx: &mut Context<'_, WindowState>) {
        self.focused_input = None;
        if let Some(previous_handle) = self
            .active_sheet
            .as_ref()
            .and_then(|s| s.previous_focused_handle.as_ref())
            .and_then(|h| h.upgrade())
        {
            window.focus(&previous_handle, cx);
        }
        self.active_sheet = None;
        gpui_base::TextSelection::clear(window, cx);
        cx.notify();
    }

    pub fn push_notification(
        &mut self,
        note: impl Into<Notification>,
        window: &mut Window,
        cx: &mut Context<'_, WindowState>,
    ) {
        self.notification
            .update(cx, |view, cx| view.push(note, window, cx));
        cx.notify();
    }

    /// Removes all notifications whose id matches `T`, including ones registered with
    /// either [`Notification::id`] or [`Notification::id1`] (any key).
    pub fn remove_notification<T: Sized + 'static>(
        &mut self,
        window: &mut Window,
        cx: &mut Context<'_, WindowState>,
    ) {
        self.notification.update(cx, |view, cx| {
            view.close_by_type(TypeId::of::<T>(), window, cx);
        });
        cx.notify();
    }

    /// Removes the notification matching the given type and element id (paired with [`Notification::id1`]).
    pub fn remove_notification1<T: Sized + 'static>(
        &mut self,
        key: impl Into<ElementId>,
        window: &mut Window,
        cx: &mut Context<'_, WindowState>,
    ) {
        let key = key.into();
        self.notification.update(cx, |view, cx| {
            view.close((TypeId::of::<T>(), key), window, cx);
        });
        cx.notify();
    }

    pub fn clear_notifications(&mut self, window: &mut Window, cx: &mut Context<'_, WindowState>) {
        self.notification
            .update(cx, |view, cx| view.clear(window, cx));
        cx.notify();
    }

    /// Get the tooltip overlay entity for this window.
    pub(crate) fn tooltip_overlay(
        window: &Window,
        cx: &App,
    ) -> Option<Entity<gpui_base::TooltipOverlay>> {
        let root = Self::entity(window, cx)?;
        Some(root.read(cx).tooltip_overlay.clone())
    }

    /// Only the current trigger may request a hide. Hover listeners run in
    /// reverse paint order, so a new trigger can enter before the old one leaves.
    pub(crate) fn tooltip_overlay_for_trigger(
        trigger: &GlobalElementId,
        lifetime: std::rc::Weak<()>,
        hovered: bool,
        window: &Window,
        cx: &mut App,
    ) -> Option<Entity<gpui_base::TooltipOverlay>> {
        Self::entity(window, cx)?.update(cx, |state, _| {
            if hovered {
                state.tooltip_hovered_trigger = Some(trigger.clone());
                state.tooltip_trigger_lifetime = lifetime;
            } else if state.tooltip_hovered_trigger.as_ref() == Some(trigger) {
                state.tooltip_hovered_trigger = None;
                state.tooltip_trigger_lifetime = std::rc::Weak::new();
            } else {
                return None;
            }
            Some(state.tooltip_overlay.clone())
        })
    }

    fn dismiss_removed_tooltip(&self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(trigger) = self.tooltip_hovered_trigger.clone() else {
            return;
        };
        let state = cx.weak_entity();
        // Defer until GPUI has retained this frame's element states and dropped
        // absent ones. A reused cached subtree keeps its trigger alive.
        window.defer(cx, move |_, cx| {
            _ = state.update(cx, |state, cx| {
                if state.tooltip_hovered_trigger.as_ref() != Some(&trigger)
                    || state.tooltip_trigger_lifetime.upgrade().is_some()
                {
                    return;
                }
                state.tooltip_hovered_trigger = None;
                state.tooltip_trigger_lifetime = std::rc::Weak::new();
                state
                    .tooltip_overlay
                    .update(cx, |overlay, cx| overlay.hide(cx));
            });
        });
    }

    /// Keeps the tooltip of the trigger at `bounds` dismissed until the
    /// pointer moves outside them.
    pub(crate) fn press_tooltip_trigger(bounds: Bounds<Pixels>, window: &mut Window, cx: &mut App) {
        Self::try_update(window, cx, |state, _, cx| {
            state.tooltip_pressed_trigger = Some(bounds);
            cx.notify();
        });
    }

    pub(crate) fn is_tooltip_trigger_pressed(
        bounds: Bounds<Pixels>,
        window: &Window,
        cx: &App,
    ) -> bool {
        Self::try_read(window, cx)
            .is_some_and(|state| state.tooltip_pressed_trigger == Some(bounds))
    }

    /// Ends the press on the first pointer move outside the trigger. It is
    /// window-level because a removed or moved trigger never reports a
    /// hover-leave.
    fn tooltip_press_listener(&self, cx: &Context<Self>) -> Option<impl IntoElement + use<>> {
        let bounds = self.tooltip_pressed_trigger?;
        let state = cx.entity().downgrade();
        Some(canvas(
            |_, _, _| {},
            move |_, _, window, _| {
                window.on_mouse_event(move |event: &MouseMoveEvent, phase, _, cx| {
                    if phase != DispatchPhase::Capture || bounds.contains(&event.position) {
                        return;
                    }
                    _ = state.update(cx, |state, cx| {
                        if state.tooltip_pressed_trigger == Some(bounds) {
                            state.tooltip_pressed_trigger = None;
                            cx.notify();
                        }
                    });
                });
            },
        ))
    }

    /// Get the fallback native-menu overlay entity for this window.
    pub(crate) fn native_menu_overlay(
        window: &Window,
        cx: &App,
    ) -> Option<Entity<FallbackMenuOverlay>> {
        let root = Self::entity(window, cx)?;
        Some(root.read(cx).native_menu_overlay.clone())
    }
}

impl gpui_base::RootPlugin for WindowState {
    fn prepare(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.dismiss_removed_tooltip(window, cx);
        window.set_rem_size(cx.theme().font_size);
        TextSelection::activate_scope(self.active_text_selection_scope(), window, cx);
    }

    fn style(&self, surface: &mut gpui::Stateful<gpui::Div>, _window: &mut Window, cx: &mut App) {
        use gpui::Refineable as _;
        surface.style().refine(
            &gpui::StyleRefinement::default()
                .font_family(cx.theme().font_family.clone())
                .bg(cx.theme().tokens.background)
                .text_color(cx.theme().foreground),
        );
    }

    fn decorate(
        &self,
        surface: gpui::AnyElement,
        _root: &gpui_base::Root,
        _window: &mut Window,
        _cx: &mut App,
    ) -> impl IntoElement {
        window_border().child(surface)
    }
}

impl Render for WindowState {
    fn render(&mut self, _window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .absolute()
            .inset_0()
            .child(WindowStateLayers { root: cx.entity() })
            .child(self.touch_selection_overlay.clone())
            .child(self.tooltip_overlay.clone())
            .children(self.tooltip_press_listener(cx))
            .child(self.native_menu_overlay.clone())
    }
}

const ROOT_MISSING: &str =
    "component window state is missing; call gpui_component::init before gpui_kit::open_window";

/// Window-level layers, always mounted once after the application content.
/// Child view caching does not affect their ownership or rendering.
#[derive(IntoElement)]
struct WindowStateLayers {
    root: Entity<WindowState>,
}

impl RenderOnce for WindowStateLayers {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let root = self.root;
        div()
            .absolute()
            .inset_0()
            .debug_selector(|| "root-layers".to_string())
            .children(WindowState::sheet_layer(root.clone(), window, cx))
            .children(WindowState::dialog_layer(&root, window, cx))
            .children(WindowState::notification_layer(&root, window, cx))
    }
}
